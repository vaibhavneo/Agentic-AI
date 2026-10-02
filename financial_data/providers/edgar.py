"""
FIL provider — SEC EDGAR / XBRL companyfacts.

WHY THIS IS THE PRIMARY FUNDAMENTALS SOURCE
-------------------------------------------
Most retail fundamentals APIs serve the CURRENT view of history: ask for 2019
revenue and you get today's restated figure. Backtesting on that is look-ahead
— you are trading on a number nobody had in 2019.

EDGAR's companyfacts is structurally different. Every fact carries `filed`,
the date the document reached the SEC, and restatements arrive as ADDITIONAL
entries rather than overwrites. History is append-only, so "what did the world
know on date D?" is answerable exactly: keep entries with filed <= D, then take
the latest survivor per period. That is the whole point-in-time fix, and it is
free.

Endpoints (no key, no auth):
  company_tickers.json                      ticker -> CIK
  data.sec.gov/api/xbrl/companyfacts/CIK... every fact ever filed
  data.sec.gov/submissions/CIK...           filing index

SEC requires a descriptive User-Agent with contact info and asks for <10 req/s.
Both are honored below; being a bad citizen here would get the whole repo
blocked from a public good.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import cache
from ..schemas import make_datum, make_source

BASE_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
BASE_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"

_MIN_INTERVAL = 1.0 / 8      # stay under SEC's 10 req/s guidance
_last_call = [0.0]


class NotConfiguredError(RuntimeError):
    """SEC_USER_AGENT is absent or non-compliant.

    Kept distinct from ProviderError on purpose: "you have not configured this"
    and "SEC is unreachable" demand opposite responses from a caller, and a test
    that lumps them together will happily skip past a config bug forever —
    which is precisely how this was nearly missed.
    """


def _load_user_agent() -> str:
    """SEC's fair-access policy REQUIRES a User-Agent naming a real contact
    ("Company Name admin@example.com"). Anything else — including a browser
    string — gets a hard 403, verified empirically 2026-07-16.

    Read from the environment, falling back to stock_agent/.env (the same
    convention web/app.py uses for DEEPSEEK_API_KEY). Deliberately NOT defaulted
    to a hardcoded address: an email in a committed file is both a privacy leak
    and a lie about who is making the requests.
    """
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        env_file = Path(__file__).resolve().parents[2] / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line.startswith("SEC_USER_AGENT="):
                    ua = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not ua:
        raise NotConfiguredError(
            "SEC_USER_AGENT is not set. SEC requires a User-Agent identifying a real "
            "contact, e.g. 'Your Name you@example.com'. Add to stock_agent/.env:\n"
            "    SEC_USER_AGENT=Your Name you@example.com\n"
            "See https://www.sec.gov/os/webmaster-faq#developers")
    if "@" not in ua:
        raise NotConfiguredError(
            f"SEC_USER_AGENT={ua!r} has no contact email; SEC will reject it with 403. "
            "Use the form 'Your Name you@example.com'.")
    return ua

# The ~20 core concepts. Each maps to an ORDERED list of us-gaap tags because
# companies legitimately tag the same economic quantity differently (and change
# tags between years). First tag that yields data wins; the tag actually used is
# recorded in the datum's source.ref, so a reader can always see which one.
CONCEPT_MAP: Dict[str, List[str]] = {
    # "Revenues" is TOTAL revenue by definition; contract revenue can be a
    # subset (Caterpillar's excludes its finance arm, Progressive's is a
    # sliver of premiums). Checked against the printed 10-Ks: with contract
    # revenue first, CAT's and PGR's revenue did not appear in their filings.
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax",
                # Banks: total net revenue. Equal to "Revenues" wherever a bank
                # tags both (JPM FY2025: 182,447 in each); JPM stopped tagging
                # "Revenues" in its 2026 10-Qs.
                "RevenuesNetOfInterestExpense", "SalesRevenueGoodsNet", "SalesRevenueServicesNet"],
    "cost_of_revenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfServices"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "eps_basic": ["EarningsPerShareBasic"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "equity": ["StockholdersEquity",
               "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "shares_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "shares_outstanding": ["CommonStockSharesOutstanding", "CommonStockSharesIssued"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities",
                            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt",
                       # Coca-Cola moved to this tag in 2024
                       "LongTermDebtAndCapitalLeaseObligations"],
    "inventory": ["InventoryNet"],
    "rd_expense": ["ResearchAndDevelopmentExpense"],
    "sga_expense": ["SellingGeneralAndAdministrativeExpense"],
    "interest_expense": ["InterestExpense", "InterestExpenseDebt"],
    "income_tax": ["IncomeTaxExpenseBenefit"],
}

# The original 21 concepts are what a caller gets when it names none — every
# existing caller (the live pillar, the xsection features) keeps exactly the
# data volume it was built against. The statement engine asks for the full set
# explicitly.
CORE_CONCEPTS: List[str] = list(CONCEPT_MAP)

# Line items the financial-statement engine (stock_analysis/) adds. Same rule:
# ordered tags, first tag that covers a period wins for that period.
CONCEPT_MAP.update({
    "operating_expenses": ["OperatingExpenses", "CostsAndExpenses"],
    "pretax_income": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
                      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic"],
    "net_income_continuing": ["IncomeLossFromContinuingOperations"],
    "shares_basic": ["WeightedAverageNumberOfSharesOutstandingBasic"],
    "depreciation_amortization": ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
                                  "DepreciationAndAmortization", "Depreciation"],
    "stock_comp": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
    "impairment": ["GoodwillImpairmentLoss", "AssetImpairmentCharges",
                   "ImpairmentOfLongLivedAssetsHeldForUse", "GoodwillAndIntangibleAssetImpairment"],
    "restructuring": ["RestructuringCharges", "RestructuringSettlementAndImpairmentProvisions"],
    "gain_on_sale": ["GainLossOnSaleOfPropertyPlantEquipment", "GainLossOnDispositionOfAssets1",
                     "GainLossOnDispositionOfAssets", "DisposalGroupNotDiscontinuedOperationGainLossOnDisposal"],
    "nonoperating_income": ["NonoperatingIncomeExpense", "OtherNonoperatingIncomeExpense"],
    "income_taxes_paid": ["IncomeTaxesPaidNet", "IncomeTaxesPaid"],
    "interest_paid": ["InterestPaidNet", "InterestPaid"],
    "investing_cash_flow": ["NetCashProvidedByUsedInInvestingActivities",
                            "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations"],
    "financing_cash_flow": ["NetCashProvidedByUsedInFinancingActivities",
                            "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations"],
    "capitalized_software": ["PaymentsToDevelopSoftware", "PaymentsForSoftware"],
    "acquisitions": ["PaymentsToAcquireBusinessesNetOfCashAcquired"],
    "buybacks": ["PaymentsForRepurchaseOfCommonStock"],
    "dividends_paid": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
    "debt_issued": ["ProceedsFromIssuanceOfLongTermDebt", "ProceedsFromIssuanceOfDebt"],
    "debt_repaid": ["RepaymentsOfLongTermDebt", "RepaymentsOfDebt"],
    "short_term_investments": ["ShortTermInvestments", "MarketableSecuritiesCurrent",
                               "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
    "receivables": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
    "current_assets": ["AssetsCurrent"],
    "ppe_net": ["PropertyPlantAndEquipmentNet",
                "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization"],
    "goodwill": ["Goodwill"],
    "intangibles": ["IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet"],
    "accounts_payable": ["AccountsPayableCurrent", "AccountsPayableAndAccruedLiabilitiesCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "deferred_revenue": ["ContractWithCustomerLiabilityCurrent", "DeferredRevenueCurrent"],
    "short_term_debt": ["LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings",
                        "LongTermDebtAndCapitalLeaseObligationsCurrent"],
    "retained_earnings": ["RetainedEarningsAccumulatedDeficit"],
    "operating_lease_liabilities": ["OperatingLeaseLiability"],
})

# Foreign private issuers filing 20-F under IFRS tag in the ifrs-full
# namespace — the same economic quantity under a different name. Without this
# map TSM, ASML or SAP read as "no fundamentals" though they file every year.
IFRS_CONCEPT_MAP: Dict[str, List[str]] = {
    "revenue": ["Revenue", "RevenueFromContractsWithCustomers"],
    "cost_of_revenue": ["CostOfSales"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["ProfitLossFromOperatingActivities"],
    "pretax_income": ["ProfitLossBeforeTax"],
    "income_tax": ["IncomeTaxExpenseContinuingOperations"],
    "net_income": ["ProfitLossAttributableToOwnersOfParent", "ProfitLoss"],
    "eps_basic": ["BasicEarningsLossPerShare"],
    "eps_diluted": ["DilutedEarningsLossPerShare"],
    "shares_basic": ["WeightedAverageShares"],
    "shares_diluted": ["AdjustedWeightedAverageShares"],
    "rd_expense": ["ResearchAndDevelopmentExpense"],
    "sga_expense": ["SellingGeneralAndAdministrativeExpense"],
    "interest_expense": ["InterestExpense", "FinanceCosts"],
    "depreciation_amortization": ["DepreciationAndAmortisationExpense",
                                  "DepreciationAmortisationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss",
                                  "AdjustmentsForDepreciationAndAmortisationExpense"],
    "stock_comp": ["AdjustmentsForSharebasedPayments", "ExpenseFromSharebasedPaymentTransactionsWithEmployees"],
    "impairment": ["ImpairmentLossRecognisedInProfitOrLoss", "ImpairmentLossRecognisedInProfitOrLossGoodwill"],
    "operating_cash_flow": ["CashFlowsFromUsedInOperatingActivities"],
    "investing_cash_flow": ["CashFlowsFromUsedInInvestingActivities"],
    "financing_cash_flow": ["CashFlowsFromUsedInFinancingActivities"],
    "capex": ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
              "PurchaseOfPropertyPlantAndEquipment"],
    "acquisitions": ["CashFlowsUsedInObtainingControlOfSubsidiariesOrOtherBusinessesClassifiedAsInvestingActivities"],
    "buybacks": ["PaymentsToAcquireOrRedeemEntitysShares"],
    "dividends_paid": ["DividendsPaidClassifiedAsFinancingActivities", "DividendsPaid"],
    "income_taxes_paid": ["IncomeTaxesPaidRefundClassifiedAsOperatingActivities"],
    "interest_paid": ["InterestPaidClassifiedAsOperatingActivities", "InterestPaidClassifiedAsFinancingActivities"],
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "equity": ["EquityAttributableToOwnersOfParent", "Equity"],
    "current_assets": ["CurrentAssets"],
    "current_liabilities": ["CurrentLiabilities"],
    "cash": ["CashAndCashEquivalents"],
    "short_term_investments": ["CurrentFinancialAssetsAtFairValueThroughProfitOrLoss", "OtherCurrentFinancialAssets"],
    "receivables": ["TradeAndOtherCurrentReceivables", "CurrentTradeReceivables"],
    "inventory": ["Inventories"],
    "ppe_net": ["PropertyPlantAndEquipment"],
    "goodwill": ["Goodwill"],
    "intangibles": ["IntangibleAssetsOtherThanGoodwill"],
    "accounts_payable": ["TradeAndOtherCurrentPayables", "TradeAndOtherCurrentPayablesToTradeSuppliers"],
    "short_term_debt": ["ShorttermBorrowings", "CurrentPortionOfLongtermBorrowings", "CurrentBorrowings"],
    "long_term_debt": ["LongtermBorrowings", "NoncurrentPortionOfLongtermBorrowings", "NoncurrentBorrowings",
                       "BondsIssued"],
    "retained_earnings": ["RetainedEarnings"],
}

# Cover-page facts (dei). The share count on the cover is the most recent one a
# company states, as of a date shortly before filing — what market cap needs.
DEI_CONCEPT_MAP: Dict[str, List[str]] = {
    "shares_outstanding_cover": ["EntityCommonStockSharesOutstanding"],
    "public_float": ["EntityPublicFloat"],
}

NAMESPACE_MAPS = (("us-gaap", CONCEPT_MAP), ("ifrs-full", IFRS_CONCEPT_MAP), ("dei", DEI_CONCEPT_MAP))
ALL_CONCEPTS: List[str] = sorted({c for _, m in NAMESPACE_MAPS for c in m})

KINDS = ("fundamentals_pit", "filings")


class ProviderError(RuntimeError):
    """Network/parse failure. Raised, never swallowed into an empty result —
    "SEC is down" and "this company reports nothing" must stay distinguishable."""


def _throttle() -> None:
    delta = time.time() - _last_call[0]
    if delta < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - delta)
    _last_call[0] = time.time()


def _fetch_json(url: str, timeout: int = 20) -> Any:
    _throttle()
    req = urllib.request.Request(url, headers={
        "User-Agent": _load_user_agent(),
        "Accept-Encoding": "gzip, deflate",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                import gzip
                raw = gzip.decompress(raw)
            return json.loads(raw.decode())
    except urllib.error.HTTPError as e:
        if e.code == 403:
            # Near-always the User-Agent, not a real block. Say so, because a
            # generic "HTTP 403" sent me chasing the network for ten minutes.
            raise NotConfiguredError(
                f"EDGAR returned 403 for {url}. This is almost always a non-compliant "
                f"User-Agent — SEC requires 'Your Name you@example.com' in SEC_USER_AGENT.") from e
        raise ProviderError(f"EDGAR HTTP {e.code} for {url}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ProviderError(f"EDGAR unreachable: {e}") from e
    except json.JSONDecodeError as e:
        raise ProviderError(f"EDGAR returned non-JSON for {url}") from e


def resolve_cik(symbol: str, max_age_sec: int = 86400 * 7) -> Optional[int]:
    """Ticker -> CIK. Cached for a week; the mapping changes rarely."""
    payload = cache.get("sec-edgar", "_meta", "ticker_map", max_age_sec=max_age_sec)
    if payload is None:
        payload = _fetch_json(TICKER_MAP_URL)
        cache.put("sec-edgar", "_meta", "ticker_map", payload)
    sym = symbol.upper().strip()
    for row in payload.values():
        if str(row.get("ticker", "")).upper() == sym:
            return int(row["cik_str"])
    return None


# A ticker that moves to a new registrant (a holding-company reorganization)
# keeps its history under the old CIK. Each entry is a documented succession,
# never inferred: XOM — ExxonMobil Holdings Corp (2115436) succeeded Exxon
# Mobil Corp (34088) as the XOM registrant by 8-K12B on 2026-07-01, so the
# new CIK alone holds one quarter of history.
PREDECESSOR_CIKS: Dict[int, List[int]] = {2115436: [34088]}


def _companyfacts(cik: int, max_age_sec: int = 86400) -> Dict[str, Any]:
    key = f"CIK{cik:010d}"
    payload = cache.get("sec-edgar", "companyfacts", key, max_age_sec=max_age_sec)
    if payload is None:
        payload = _fetch_json(BASE_FACTS.format(cik=cik))
        cache.put("sec-edgar", "companyfacts", key, payload)
    return payload


# Filings whose XBRL is a financial statement. Proxy statements (DEF 14A) now
# tag company net income in their pay-versus-performance tables; letting one
# "cover" a period hid the 10-K's own figure behind it (Caterpillar FY2025).
_STATEMENT_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "10-KT", "10-KT/A",
                    "20-F", "20-F/A", "40-F", "40-F/A"}


def parse_companyfacts(payload: Dict[str, Any], symbol: str,
                       concepts: Optional[List[str]] = None,
                       reliability: float = 1.0, all_tags: bool = False) -> List[Dict[str, Any]]:
    """Turn a raw companyfacts payload into Datums.

    Pure function — no network. That is deliberate: it lets the point-in-time
    and restatement logic be tested exhaustively against fixtures, offline and
    deterministically, which is the only way this guarantee stays trustworthy.

    Every filed entry becomes its own Datum, INCLUDING superseded restatements.
    We do not resolve them here; the gateway resolves them relative to a caller's
    `as_of`. Discarding them at parse time would destroy the very history that
    makes point-in-time possible.

    all_tags=True emits every tag's entries with its priority (`tag_rank`) and
    skips nothing. The choice of tag per period must then be made by the caller
    AFTER the point-in-time cut — choosing here, on the full history, lets a
    tag from a filing made after `as_of` claim a period and hide the tag that
    was actually on file at the time (Kraft Heinz FY2017 revenue vanished that way).
    """
    wanted = list(concepts) if concepts else list(CORE_CONCEPTS)
    all_facts = payload.get("facts") or {}
    out: List[Dict[str, Any]] = []

    for concept in wanted:
        # Tags are tried in priority order, and a lower-priority tag only fills
        # the PERIODS a higher one left empty. Companies change tags between
        # years (SalesRevenueNet until 2017, RevenueFromContractWithCustomer
        # after); "first tag with any data wins" kept only the new tag and
        # silently cut a decade of revenue history to five years.
        covered: set = set()
        rank = 0
        for namespace, cmap in NAMESPACE_MAPS:
            facts = all_facts.get(namespace) or {}
            for tag in cmap.get(concept, []):
                rank += 1
                node = facts.get(tag)
                if not node:
                    continue
                tag_periods: set = set()
                for unit_name, entries in (node.get("units") or {}).items():
                    for e in entries:
                        filed, val = e.get("filed"), e.get("val")
                        if filed is None or val is None:
                            continue     # cannot place it in time -> unusable, skip
                        period = (e.get("start"), e.get("end"), unit_name)
                        if period in covered and not all_tags:
                            continue
                        if e.get("form") in _STATEMENT_FORMS:
                            tag_periods.add(period)
                        try:
                            out.append(make_datum(
                                kind="fundamentals_pit",
                                value=val,
                                available_at=filed,          # THE anti-look-ahead field
                                source=make_source(
                                    provider="sec-edgar",
                                    document=e.get("accn"),   # accession number: hand-checkable
                                    ref=f"{namespace}:{tag}",
                                    url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                                        f"&CIK={payload.get('cik')}&type={e.get('form','')}",
                                ),
                                symbol=symbol,
                                concept=concept,
                                unit=unit_name,
                                period_start=e.get("start"),
                                period_end=e.get("end"),
                                confidence=reliability,
                                status="actual",             # EDGAR is as-reported by definition
                                extra={"form": e.get("form"), "fy": e.get("fy"), "fp": e.get("fp"),
                                       "frame": e.get("frame"), "tag_rank": rank},
                            ))
                        except Exception:
                            # One malformed entry must not sink the whole company's
                            # history; it is simply absent, and absence is visible
                            # because the caller sees fewer datums, never a fake one.
                            continue
                covered |= tag_periods
    return out


# ── Filings: the index, the company profile, and the documents themselves ──

ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
SUBMISSIONS_PAGE = "https://data.sec.gov/submissions/{name}"
# Forms worth paging back through history for. Insider Form 4s dominate a large
# filer's "recent" list (JPM's 1,000 most recent filings span barely a year), so
# without paging, a five-year 10-K history quietly ends after one.
CORE_FORMS = ("10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A",
              "8-K", "8-K/A", "6-K", "NT 10-K", "NT 10-Q", "NT 20-F")


def _fetch_text(url: str, timeout: int = 30) -> str:
    _throttle()
    req = urllib.request.Request(url, headers={
        "User-Agent": _load_user_agent(), "Accept-Encoding": "gzip, deflate"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                import gzip
                raw = gzip.decompress(raw)
            return raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise NotConfiguredError(f"EDGAR returned 403 for {url} — check SEC_USER_AGENT") from e
        raise ProviderError(f"EDGAR HTTP {e.code} for {url}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ProviderError(f"EDGAR unreachable: {e}") from e


def _submissions(cik: int, max_age_sec: int = 86400) -> Dict[str, Any]:
    key = f"CIK{cik:010d}"
    payload = cache.get("sec-edgar", "submissions", key, max_age_sec=max_age_sec)
    if payload is None:
        payload = _fetch_json(BASE_SUBMISSIONS.format(cik=cik))
        cache.put("sec-edgar", "submissions", key, payload)
    return payload


def _submissions_page(name: str) -> Dict[str, Any]:
    # Older pages never change once written — cache them for a month.
    payload = cache.get("sec-edgar", "submissions", name, max_age_sec=86400 * 30)
    if payload is None:
        payload = _fetch_json(SUBMISSIONS_PAGE.format(name=name))
        cache.put("sec-edgar", "submissions", name, payload)
    return payload


def _rows(block: Dict[str, Any]) -> List[Dict[str, Any]]:
    keys = list(block.keys())
    n = len(block.get("accessionNumber") or [])
    return [{k: (block[k][i] if i < len(block[k]) else None) for k in keys} for i in range(n)]


def filing_rows(cik: int, since: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every filing on record, newest first, paging back until `since`
    (default: ten years) is covered for the core forms."""
    sub = _submissions(cik)
    rows = _rows((sub.get("filings") or {}).get("recent") or {})
    since = since or f"{int(time.strftime('%Y')) - 10}-01-01"
    for page in (sub.get("filings") or {}).get("files") or []:
        if (page.get("filingTo") or "9999") < since:
            break
        try:
            rows.extend(_rows(_submissions_page(page["name"])))
        except ProviderError:
            break      # older history unavailable — what we have is still correct
    rows.sort(key=lambda r: (r.get("filingDate") or ""), reverse=True)
    return rows


def company_profile(cik: int) -> Dict[str, Any]:
    sub = _submissions(cik)
    return {
        "cik": cik, "name": sub.get("name"), "sic": sub.get("sic"),
        "sic_description": sub.get("sicDescription"), "category": sub.get("category"),
        "fiscal_year_end": sub.get("fiscalYearEnd"), "state_of_incorporation": sub.get("stateOfIncorporation"),
        "tickers": sub.get("tickers"), "exchanges": sub.get("exchanges"),
        "entity_type": sub.get("entityType"),
        "former_names": [f.get("name") for f in (sub.get("formerNames") or [])],
    }


def html_to_text(html: str) -> str:
    """Filing HTML → readable text with paragraph breaks kept, because section
    detection ("Item 1A. Risk Factors") reads line starts. Inline-XBRL headers
    hold thousands of hidden facts and are dropped before anything else."""
    import html as _html
    import re
    t = re.sub(r"(?is)<ix:header>.*?</ix:header>", " ", html)
    t = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", t)
    t = re.sub(r"(?is)<div[^>]*display:\s*none[^>]*>.*?</div>", " ", t)
    t = re.sub(r"(?i)<br\s*/?>", "\n", t)
    t = re.sub(r"(?i)</(p|div|tr|li|h[1-6]|table)>", "\n", t)
    t = re.sub(r"(?i)</t[dh]>", " | ", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = _html.unescape(t).replace("\xa0", " ")
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r" *\n[ \n]*", "\n", t)
    return t.strip()


def filing_document(cik: int, accession: str, document: str) -> str:
    """The text of one filed document. Filed documents never change, so the
    cache never expires."""
    key = f"{accession}_{document}"
    cached = cache.get("sec-edgar", "documents", key)
    if cached is not None:
        return cached
    url = ARCHIVE_URL.format(cik=cik, acc=accession.replace("-", ""), doc=document)
    raw = _fetch_text(url, timeout=60)
    text = html_to_text(raw) if document.lower().endswith((".htm", ".html")) else raw
    cache.put("sec-edgar", "documents", key, text)
    return text


def filing_documents(cik: int, accession: str) -> List[Dict[str, Any]]:
    """The documents inside one filing (primary document, exhibits) from the
    filing's index page: [{seq, description, document, type, size}]."""
    import re
    key = f"{accession}_index"
    cached = cache.get("sec-edgar", "documents", key)
    if cached is not None:
        return cached
    url = (f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/"
           f"{accession}-index.htm")
    html = _fetch_text(url)
    docs = []
    for row in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", html):
        cells = re.findall(r"(?is)<td[^>]*>(.*?)</td>", row)
        if len(cells) < 4:
            continue
        link = re.search(r'href="([^"]+)"', cells[2])
        if not link:
            continue
        name = link.group(1).split("/")[-1]
        clean = [re.sub(r"(?s)<[^>]+>", "", c).strip() for c in cells]
        docs.append({"seq": clean[0], "description": clean[1], "document": name,
                     "type": clean[3], "size": clean[4] if len(clean) > 4 else None})
    cache.put("sec-edgar", "documents", key, docs)
    return docs


def _filings_fetch(symbols: List[str], concepts: Optional[List[str]], reliability: float,
                   **kwargs: Any) -> Dict[str, Any]:
    """kind="filings". concepts selects what:
      ["filing"]           the filing index (default) — one Datum per filing,
                           value = form type, available_at = acceptance time
      ["company_profile"]  SIC industry, fiscal year end, filer category
      ["document"]         one document's text; needs accession= and document=
      ["filing_documents"] the documents inside one filing; needs accession=
    """
    what = (concepts or ["filing"])[0]
    data: List[Dict[str, Any]] = []
    unavailable: List[Dict[str, Any]] = []
    for sym in symbols:
        try:
            cik = kwargs.get("cik") or resolve_cik(sym)
        except ProviderError as e:
            unavailable.append({"symbol": sym, "reason": f"cik_lookup_failed: {e}"})
            continue
        if cik is None:
            unavailable.append({"symbol": sym, "reason": "no_sec_cik (not an SEC filer)"})
            continue
        try:
            if what == "company_profile":
                prof = company_profile(cik)
                rows = filing_rows(cik)
                first = rows[-1]["filingDate"] if rows else "1994-01-01"
                data.append(make_datum(
                    kind="filings", value=prof.get("sic") or "unknown", available_at=first,
                    source=make_source("sec-edgar", document=f"CIK{cik:010d}", ref="submissions:profile",
                                       url=BASE_SUBMISSIONS.format(cik=cik)),
                    symbol=sym, concept="company_profile", confidence=reliability,
                    extra={**prof, "note": "current classification, not point-in-time"}))
            elif what == "document":
                acc, doc = kwargs.get("accession"), kwargs.get("document")
                if not acc or not doc:
                    raise ProviderError("document requires accession= and document=")
                text = filing_document(cik, acc, doc)
                data.append(make_datum(
                    kind="filings", value=text, available_at=kwargs.get("filed") or "1994-01-01",
                    source=make_source("sec-edgar", document=acc, ref=f"document:{doc}",
                                       url=ARCHIVE_URL.format(cik=cik, acc=acc.replace("-", ""), doc=doc)),
                    symbol=sym, concept="document", unit="text", confidence=reliability,
                    extra={"cik": cik, "document": doc, "chars": len(text)}))
            elif what == "filing_documents":
                acc = kwargs.get("accession")
                docs = filing_documents(cik, acc) if acc else []
                if not docs:
                    raise ProviderError(f"no document list for {acc}")
                data.append(make_datum(
                    kind="filings", value=len(docs), available_at=kwargs.get("filed") or "1994-01-01",
                    source=make_source("sec-edgar", document=acc, ref="filing:index"),
                    symbol=sym, concept="filing_documents", confidence=reliability,
                    extra={"documents": docs, "cik": cik}))
            else:
                forms = set(kwargs.get("forms") or CORE_FORMS)
                rows = [dict(r, _cik=cik) for r in filing_rows(cik, since=kwargs.get("since"))]
                for pred in PREDECESSOR_CIKS.get(cik, []):
                    rows.extend(dict(r, _cik=pred) for r in filing_rows(pred, since=kwargs.get("since")))
                for r in rows:
                    rcik = r["_cik"]
                    if r.get("form") not in forms:
                        continue
                    acc = r.get("accessionNumber")
                    accepted = (r.get("acceptanceDateTime") or "").replace(".000Z", "").replace("Z", "")
                    data.append(make_datum(
                        kind="filings", value=r.get("form"),
                        available_at=accepted or r.get("filingDate"),
                        source=make_source("sec-edgar", document=acc, ref=f"filing:{r.get('form')}",
                                           url=ARCHIVE_URL.format(cik=rcik, acc=(acc or "").replace("-", ""),
                                                                  doc=r.get("primaryDocument") or "")),
                        symbol=sym, concept="filing", period_end=r.get("reportDate") or None,
                        confidence=reliability,
                        extra={"cik": rcik, "filing_date": r.get("filingDate"),
                               "primary_document": r.get("primaryDocument"),
                               "description": r.get("primaryDocDescription"),
                               "items": r.get("items"), "size": r.get("size"),
                               "is_xbrl": bool(r.get("isXBRL")), "file_number": r.get("fileNumber")}))
        except ProviderError as e:
            unavailable.append({"symbol": sym, "reason": str(e)})
    return {"data": data, "unavailable": unavailable, "warnings": []}


def fetch(kind: str, symbols: List[str], start: Optional[str] = None,
          end: Optional[str] = None, as_of: Optional[str] = None,
          concepts: Optional[List[str]] = None, reliability: float = 1.0,
          **kwargs: Any) -> Dict[str, Any]:
    """Gateway entrypoint. Returns {data, unavailable, warnings}.

    Note it does NOT apply `as_of` filtering — that is the gateway's job, in one
    place, for every provider. A provider that filtered on its own could quietly
    disagree with the gateway's guarantee.
    """
    if kind not in KINDS:
        raise ProviderError(f"sec-edgar does not serve kind {kind!r}")
    if kind == "filings":
        return _filings_fetch(symbols, concepts, reliability, **kwargs)

    data: List[Dict[str, Any]] = []
    unavailable: List[Dict[str, Any]] = []
    warnings: List[str] = []

    for sym in symbols:
        try:
            cik = resolve_cik(sym)
        except ProviderError as e:
            unavailable.append({"symbol": sym, "reason": f"cik_lookup_failed: {e}"})
            continue
        if cik is None:
            # Honest: not "no data", but "this ticker is not an SEC filer" —
            # true for ADRs, most ETFs, crypto, and foreign issuers.
            unavailable.append({"symbol": sym, "reason": "no_sec_cik (not a US SEC filer?)"})
            continue
        try:
            payload = _companyfacts(cik)
        except ProviderError as e:
            unavailable.append({"symbol": sym, "reason": str(e)})
            continue

        all_tags = bool(kwargs.get("all_tags"))
        datums = parse_companyfacts(payload, sym, concepts=concepts, reliability=reliability, all_tags=all_tags)
        for pred in PREDECESSOR_CIKS.get(cik, []):
            try:
                older = parse_companyfacts(_companyfacts(pred), sym, concepts=concepts, reliability=reliability,
                                           all_tags=all_tags)
            except ProviderError as e:
                warnings.append(f"{sym}: predecessor registrant CIK {pred} unavailable: {e}")
                continue
            for d in older:
                d.setdefault("extra", {})["registrant_cik"] = pred
            datums.extend(older)
            warnings.append(f"{sym}: history includes predecessor registrant CIK {pred}")
        if not datums:
            unavailable.append({"symbol": sym, "reason": "no_matching_xbrl_concepts"})
            continue
        data.extend(datums)

    return {"data": data, "unavailable": unavailable, "warnings": warnings}

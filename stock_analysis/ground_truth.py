"""
Phase 0 — the fixed test set and the check against the filings themselves.

TEST_SET is frozen BEFORE the quality-of-earnings scoring exists, for the same
reason the desk's routing corpus was: a check graded on cases chosen after
seeing its output can only confirm itself. Each case carries what kind of
company it is (some ratios do not apply to banks, insurers or REITs) and, for
the accounting-event cases, the date BEFORE the event came to light — the
analysis runs as of that date, on what had been filed by then.

`check_against_filing` is the independent cross-check of the statement engine:
it takes the latest fiscal-year figures the engine produced from XBRL, opens
the annual report's actual document, and looks for each number as printed
(in millions or thousands, the way filings print them). XBRL and the printed
document are produced separately by the filer; a number that appears in both
is a number the engine read correctly.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

TEST_SET: List[Dict[str, Any]] = [
    # ── US domestic filers (10-K / 10-Q, US GAAP) ──
    {"ticker": "AAPL", "kind": "domestic", "note": "52/53-week fiscal year ending late September"},
    {"ticker": "MSFT", "kind": "domestic", "note": "fiscal year ends June 30"},
    {"ticker": "NVDA", "kind": "domestic", "note": "fiscal year ends late January; 10-for-1 split in 2024"},
    {"ticker": "AMZN", "kind": "domestic"},
    {"ticker": "GOOGL", "kind": "domestic"},
    {"ticker": "KO", "kind": "domestic"},
    {"ticker": "XOM", "kind": "domestic", "note": "capital-intensive; commodity cycle"},
    {"ticker": "CAT", "kind": "domestic", "note": "has a captive finance arm"},
    {"ticker": "COST", "kind": "domestic", "note": "thin margins, negative working capital"},
    {"ticker": "TSLA", "kind": "domestic"},
    # ── Financials: standard industrial ratios do not apply ──
    {"ticker": "JPM", "kind": "bank"},
    {"ticker": "BAC", "kind": "bank"},
    {"ticker": "PGR", "kind": "insurer"},
    {"ticker": "O", "kind": "reit"},
    {"ticker": "PLD", "kind": "reit"},
    # ── Foreign private issuers ──
    {"ticker": "TSM", "kind": "foreign", "note": "20-F, IFRS, reports in TWD"},
    {"ticker": "ASML", "kind": "foreign", "note": "20-F, IFRS, reports in EUR"},
    {"ticker": "SAP", "kind": "foreign", "note": "20-F, IFRS, reports in EUR"},
    {"ticker": "BABA", "kind": "foreign", "note": "20-F, US GAAP, reports in CNY"},
    {"ticker": "TM", "kind": "foreign", "note": "20-F, reports in JPY"},
    # ── Accounting-event cases: analysed as of BEFORE the event was public ──
    {"ticker": "SMCI", "kind": "event", "as_of": "2024-08-26",
     "event": "2024-08: short report alleging accounting manipulation; 10-K filed late (NT 10-K 2024-08-29); "
              "auditor EY resigned 2024-10-30"},
    {"ticker": "KHC", "kind": "event", "as_of": "2019-02-20",
     "event": "2019-02-21: $15.4B impairment, SEC subpoena over procurement accounting, later restatement"},
    {"ticker": "UAA", "kind": "event", "as_of": "2017-01-30",
     "event": "SEC found Under Armour pulled forward ~$408M of sales in 2015-2016 to meet targets"},
    {"ticker": "MDXG", "kind": "event", "as_of": "2018-02-15",
     "event": "2018: channel-stuffing allegations, audit committee investigation, restatement of 2012-2016"},
    {"ticker": "BHC", "kind": "event", "as_of": "2015-10-15",
     "event": "2015-10: Philidor specialty-pharmacy revelations (Valeant); revenue recognition restated"},
]

CHECK_CONCEPTS = ["revenue", "net_income", "operating_income", "assets", "equity", "cash",
                  "operating_cash_flow", "capex", "long_term_debt", "eps_diluted"]


def _candidates(concept: str, value: float) -> List[str]:
    """How the number could be printed in the document."""
    if concept.startswith("eps"):
        return [f"{abs(value):.2f}"]
    out = []
    for scale in (1e6, 1e3, 1.0):
        v = abs(value) / scale
        if v < 1:
            continue
        out.append(f"{round(v):,}")
        if scale in (1e6, 1e3):
            out.append(f"{v:,.1f}")     # TSMC prints NT$ millions to one decimal
    return out


def _appears(text: str, token: str) -> bool:
    return re.search(r"(?<![\d.,])" + re.escape(token) + r"(?![\d,]|\.\d)", text) is not None


def check_against_filing(symbol: str, statements: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Look for each latest-fiscal-year figure in the annual report document."""
    from financial_data import gateway as gw
    from stock_analysis.statements import build_statements

    st = statements or build_statements(symbol)
    if not st.get("available") or not st.get("annual"):
        return {"symbol": symbol, "status": "UNAVAILABLE", "reason": st.get("reason")}
    fy = st["annual"][0]
    results, docs = [], {}
    filings = {d["source"]["document"]: d for d in
               gw.get("filings", symbol, concepts=["filing"])["data"]}
    for concept in CHECK_CONCEPTS:
        cell = fy["values"].get(concept)
        if cell is None:
            results.append({"concept": concept, "status": "NOT_REPORTED"})
            continue
        acc = cell.get("accession")
        f = filings.get(acc)
        if f is None:
            results.append({"concept": concept, "status": "NO_DOCUMENT", "accession": acc})
            continue
        if acc not in docs:
            doc = gw.get("filings", symbol, concepts=["document"], accession=acc,
                         document=f["extra"]["primary_document"], filed=f["available_at"],
                         cik=f["extra"]["cik"])
            docs[acc] = doc["data"][0]["value"] if doc["data"] else ""
            # Some companies print their statements in an exhibit (Progressive's
            # EX-13 annual report), not the 10-K wrapper.
            try:
                idx = gw.get("filings", symbol, concepts=["filing_documents"], accession=acc,
                             cik=f["extra"]["cik"])["data"]
                exhibits = [d for d in (idx[0]["extra"]["documents"] if idx else [])
                            if re.match(r"EX-(13|99)", d.get("type") or "")
                            and d["document"].lower().endswith((".htm", ".html"))]
                for ex in exhibits[:4]:
                    t = gw.get("filings", symbol, concepts=["document"], accession=acc,
                               document=ex["document"], filed=f["available_at"], cik=f["extra"]["cik"])
                    docs[acc] += "\n" + (t["data"][0]["value"] if t["data"] else "")
            except Exception:
                pass
        cands = _candidates(concept, cell["value"])
        hit = next((c for c in cands if _appears(docs[acc], c)), None)
        results.append({"concept": concept, "value": cell["value"], "accession": acc,
                        "form": f["value"], "status": "FOUND" if hit else "NOT_FOUND_IN_PRIMARY_DOCUMENT",
                        "printed_as": hit, "looked_for": cands})
    found = sum(r["status"] == "FOUND" for r in results)
    checkable = sum(r["status"] in ("FOUND", "NOT_FOUND_IN_PRIMARY_DOCUMENT") for r in results)
    return {"symbol": symbol, "fiscal_year": fy["label"], "fiscal_year_end": fy["end"],
            "found": found, "checkable": checkable, "results": results,
            "status": ("PASS" if checkable and found == checkable else
                       "PARTIAL" if found else "NOT_IN_PRIMARY_DOCUMENT")}

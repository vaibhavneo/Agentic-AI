"""
Survivorship audit — what does testing on TODAY's companies hide?

Every evaluation in backtest/ replays history on tickers that still trade, so
a company that went bankrupt, was acquired or was taken private after 2017
is invisible to it. This audit measures that blind spot from SEC data alone
(free, no price vendor):

  universe   the largest US filers by calendar-2017 revenue (XBRL frames),
             kept only if they had public equity holders — a proxy statement
             (DEF 14A) filed in 2017-18 — which drops debt-only subsidiaries.
             Addressed by CIK, so delisted registrants are reachable.
  grade      the earnings-quality grade (stock_analysis/quality.py) on what
             had been filed by GRADE_DATE — the FY2017 10-K era.
  outcome    still filing periodic reports today; REORGANIZED (it stopped,
             but a former name of it is a company that files and trades today
             in the same SIC code — a holding-company or redomicile
             reorganization, e.g. Disney 2019, Cigna 2018, Bunge 2023: the
             shareholders never left); or stopped, classified by its own
             filings: BANKRUPTCY (8-K Item 1.03), ACQUIRED (merger proxy,
             tender-offer response or 425 under its CIK), or OTHER. A company
             whose last report predates GRADE_DATE was already gone and is
             left out.

The question it answers: did the companies a quality screen would have
avoided (D/F) disappear in bankruptcy more often than the ones it would have
kept? If so, a survivors-only test UNDERSTATES the screen; if acquisitions
(usually at a premium) cluster in one grade, they bias it the other way.
Forward RETURNS of the non-survivors need delisted prices (TIINGO_API_KEY);
this audit does not invent them.

Run: python3 -m backtest.survivorship_audit [top_n]
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.fundamentals_v2_eval import UNIVERSE as EVAL_UNIVERSE, _visible  # noqa: E402

REVENUE_TAGS = ("Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax")
PERIOD = "CY2017"
GRADE_DATE = "2018-04-30"
PERIODIC = {"10-K", "10-Q", "20-F", "40-F", "10-KT", "10-QT"}
MERGER_FORMS = {"DEFM14A", "PREM14A", "DEFM14C", "PREM14C", "SC 14D9", "425", "SC TO-T"}
STALE_DAYS = 455                      # no periodic report for 15 months = stopped


def universe(top_n: int) -> List[Dict[str, Any]]:
    from financial_data.providers.edgar import frame
    rev: Dict[int, float] = {}
    for tag in REVENUE_TAGS:
        for cik, v in frame("us-gaap", tag, "USD", PERIOD).items():
            rev[cik] = max(rev.get(cik, 0.0), v)
    return [{"cik": c, "revenue_2017": rev[c]} for c in sorted(rev, key=lambda c: -rev[c])[:top_n]]


def classify(rows: List[Dict[str, Any]], today: date) -> Dict[str, Any]:
    """Outcome from a registrant's filing rows (SEC submissions format). Pure."""
    periodic = sorted(r["filingDate"] for r in rows if r.get("form") in PERIODIC)
    last = periodic[-1] if periodic else None
    had_proxy = any(r.get("form") == "DEF 14A" and "2017-01-01" <= (r.get("filingDate") or "") <= "2018-12-31"
                    for r in rows)
    after = [r for r in rows if (r.get("filingDate") or "") >= "2018-01-01"]
    bankrupt = next((r["filingDate"] for r in after
                     if (r.get("form") or "").startswith("8-K") and "1.03" in (r.get("items") or "")), None)
    merger = next((r["filingDate"] for r in after if r.get("form") in MERGER_FORMS), None)
    stopped = last is None or (today - date.fromisoformat(last)).days > STALE_DAYS
    if not stopped:
        outcome = "STILL_FILING"
    elif bankrupt:
        outcome = "BANKRUPTCY"
    elif merger:
        outcome = "ACQUIRED"
    else:
        outcome = "OTHER_STOPPED"
    return {"outcome": outcome, "last_periodic": last, "had_public_equity": had_proxy,
            "bankruptcy_8k": bankrupt, "merger_filing": merger}


_NAME_STOP = {"inc", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "sa", "se", "nv", "ag",
              "llc", "lp", "holdings", "holding", "group", "the", "new", "de", "of", "and", "a", "pte"}


def name_tokens(name: str) -> frozenset:
    """'WALT DISNEY CO/' -> {'walt', 'disney'}. Pure."""
    base = (name or "").split("/")[0].lower().replace("&", " and ")
    return frozenset(t for t in re.findall(r"[a-z0-9]+", base) if t not in _NAME_STOP)


# The only words a successor's name may add: 'Bunge Ltd' -> 'Bunge Global SA'
# is the same company; 'WestRock' -> 'Smurfit Westrock' is an acquirer.
_GENERIC_EXTRA = {"global", "international", "worldwide"}


def successor_candidates(names: List[str], titles: Dict[int, str], own_cik: int) -> List[int]:
    """Registrants named like one of `names`, adding at most a generic word.
    Pure; the caller confirms the industry before believing it."""
    out = []
    for n in names:
        tk = name_tokens(n)
        if not tk:
            continue
        for cik, title in titles.items():
            tt = name_tokens(title)
            if cik != own_cik and tk <= tt and (tt - tk) <= _GENERIC_EXTRA:
                out.append(cik)
    return list(dict.fromkeys(out))


def grade_at(cik: int, sic: Optional[str], day: str) -> Dict[str, Any]:
    from stock_analysis.company import industry_kind
    from stock_analysis.quality import assess
    from stock_analysis.statements import build_from_facts, load_facts
    sym = f"CIK{cik:010d}"
    facts = load_facts(sym)["facts"]
    st = build_from_facts(sym, _visible(facts, day), as_of=day)
    if not st.get("available"):
        return {"grade": None, "why": st.get("reason") or "no statements by then"}
    q = assess(st, industry_kind(sic))
    return {"grade": q.get("grade"), "quality_score": q.get("score")}


def audit(top_n: int = 300, today: Optional[date] = None, log=print) -> Dict[str, Any]:
    from financial_data import cache
    from financial_data.providers.edgar import cik_ticker_map, filing_rows, _submissions
    today = today or date.today()
    tickers = cik_ticker_map()
    eval_ciks = {c for c, t in tickers.items() if t in set(EVAL_UNIVERSE)}
    titles: Dict[int, str] = {}
    for r in (cache.get("sec-edgar", "_meta", "ticker_map") or {}).values():
        titles.setdefault(int(r["cik_str"]), r.get("title") or "")
    out = []
    for n, u in enumerate(universe(top_n), 1):
        t0 = time.time()
        cik = u["cik"]
        try:
            sub = _submissions(cik, max_age_sec=7 * 86400)
            rows = filing_rows(cik, since="2017-01-01", max_age_sec=7 * 86400)
            row = {**u, "name": sub.get("name"), "ticker_now": tickers.get(cik), "in_eval_universe": cik in eval_ciks,
                   **classify(rows, today)}
            row["sic"] = sub.get("sic")
            row["names"] = [sub.get("name") or ""] + [f["name"] for f in sub.get("formerNames") or []
                                                      if (f.get("to") or "") >= "2017"]
            if row["last_periodic"] and row["last_periodic"] < GRADE_DATE:
                row["outcome"] = "GONE_BEFORE_START"
            if row["had_public_equity"] and row["outcome"] != "GONE_BEFORE_START":
                row.update(grade_at(cik, sub.get("sic"), GRADE_DATE))
        except Exception as e:
            row = {**u, "error": f"{type(e).__name__}: {e}"}
        out.append(row)
        if n % 25 == 0:
            log(f"  [{n}/{top_n}] {row.get('name')} {row.get('outcome')} {row.get('grade')} ({time.time() - t0:.0f}s)")
    resolve_successors(out, titles, tickers, lambda c: _submissions(c, max_age_sec=7 * 86400).get("sic"))
    return summarize(out)


def resolve_successors(rows: List[Dict[str, Any]], titles: Dict[int, str], tickers: Dict[int, str],
                       sic_of) -> None:
    """A stopped registrant whose name lives on in the SAME industry is the
    same company: DUPLICATE when the successor is itself a row here (counted
    once, there), REORGANIZED when the successor trades today."""
    in_universe = {r["cik"]: r.get("name") or "" for r in rows if not r.get("error")}
    by_cik = {r["cik"]: r for r in rows}
    for r in rows:
        if r.get("error") or r.get("outcome") in ("STILL_FILING", "GONE_BEFORE_START"):
            continue
        for pool, outcome in ((in_universe, "DUPLICATE"), (titles, "REORGANIZED")):
            hit = next((c for c in successor_candidates(r.get("names") or [], pool, r["cik"])
                        if str(sic_of(c)) == str(r.get("sic"))), None)
            if hit:
                label = pool[hit] + (f" ({tickers[hit]})" if tickers.get(hit) else "")
                r.update(outcome=outcome, successor=label)
                if outcome == "DUPLICATE":
                    # The successor registrant (new Disney, 2019) has no 2017-18 proxy
                    # or 2018 filings of its own; the company's are the predecessor's.
                    sr = by_cik[hit]
                    if r.get("had_public_equity") and not sr.get("had_public_equity"):
                        sr["had_public_equity"] = True
                    if r.get("grade") and not sr.get("grade"):
                        sr.update(grade=r["grade"], quality_score=r.get("quality_score"), grade_from=r.get("name"))
                break


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    eq = [r for r in rows if r.get("had_public_equity") and not r.get("error")
          and r.get("outcome") not in ("GONE_BEFORE_START", "DUPLICATE")]
    graded = [r for r in eq if r.get("grade")]
    outcomes = ("STILL_FILING", "REORGANIZED", "ACQUIRED", "BANKRUPTCY", "OTHER_STOPPED")
    by_grade: Dict[str, Dict[str, Any]] = {}
    for label, grades in (("A/B", "AB"), ("C", "C"), ("D/F", "DF")):
        g = [r for r in graded if r["grade"] in grades]
        by_grade[label] = {"n": len(g), **{o: sum(1 for r in g if r["outcome"] == o) for o in outcomes}}
        for o in outcomes:
            by_grade[label][f"{o}_rate"] = round(by_grade[label][o] / len(g), 3) if g else None
    gone = [r for r in eq if r["outcome"] not in ("STILL_FILING", "REORGANIZED")]
    return {"generated": date.today().isoformat(), "period": PERIOD, "grade_date": GRADE_DATE,
            "n_candidates": len(rows), "n_public_equity": len(eq), "n_graded": len(graded),
            "n_errors": sum(1 for r in rows if r.get("error")),
            "outcomes": {o: sum(1 for r in eq if r["outcome"] == o) for o in outcomes},
            "share_gone": round(len(gone) / len(eq), 3) if eq else None,
            "eval_universe_overlap": sum(1 for r in eq if r.get("in_eval_universe")),
            "gone_before_start": [r.get("name") for r in rows if r.get("outcome") == "GONE_BEFORE_START"],
            "duplicates": [{"name": r.get("name"), "successor": r.get("successor")}
                           for r in rows if r.get("outcome") == "DUPLICATE"],
            "reorganized": [{"name": r.get("name"), "successor": r.get("successor")}
                            for r in eq if r["outcome"] == "REORGANIZED"],
            "grade_counts": {g: sum(1 for r in graded if r["grade"] == g) for g in "ABCDF"},
            "by_grade": by_grade,
            "gone": sorted(({k: r.get(k) for k in ("name", "outcome", "last_periodic", "grade", "revenue_2017",
                                                   "bankruptcy_8k", "merger_filing")} for r in gone),
                           key=lambda r: -(r["revenue_2017"] or 0)),
            "rows": rows}


def write_report(res: Dict[str, Any], path: Path) -> None:
    o, bg = res["outcomes"], res["by_grade"]
    lines = ["# Survivorship audit", "",
             f"Generated {res['generated']} by `backtest/survivorship_audit.py` from SEC data only. Universe: the "
             f"{res['n_candidates']} largest US filers by {res['period']} revenue (XBRL frames), "
             f"{res['n_public_equity']} with public equity (a 2017–18 proxy statement). Earnings-quality grade on "
             f"what had been filed by {res['grade_date']}; {res['n_graded']} could be graded.", "",
             "## Where they are now", "",
             "| outcome | companies |", "|---|---|"]
    lines += [f"| {k.replace('_', ' ').lower()} | {v} |" for k, v in o.items()]
    lines += ["", f"**{res['share_gone']:.0%} of the 2017 large-company universe no longer exists as a listed "
              f"company** (acquired, bankrupt or otherwise gone; reorganizations whose successor still trades "
              f"are not counted). The evaluations in this repo (`FUNDAMENTALS_V2_EVALUATION.md`, "
              f"`EVENT_SIGNALS_EVALUATION.md`) use today's tickers, so none of those companies is in them.", ""]
    if res.get("reorganized"):
        lines += ["Reorganized — the successor still trades, so these are not survivorship losses: " +
                  "; ".join(f"{r['name']} → {r['successor']}" for r in res["reorganized"]) + ".", ""]
    if res.get("duplicates"):
        lines += ["Counted once — an earlier registrant of a company already in the universe: " +
                  "; ".join(f"{r['name']} → {r['successor']}" for r in res["duplicates"]) + ".", ""]
    if res.get("gone_before_start"):
        lines += ["Left out — last report before " + res["grade_date"] + ", so never in the universe being "
                  "graded: " + ", ".join(res["gone_before_start"]) + ".", ""]
    gc = res.get("grade_counts") or {}
    lines += ["## Outcome by the 2018 earnings-quality grade", "",
              "| grade | n | still filing or reorganized | acquired | bankruptcy | other stopped |",
              "|---|---|---|---|---|---|"]
    for g, v in bg.items():
        if not v["n"]:
            continue
        lines.append(f"| {g} | {v['n']} | {v['STILL_FILING_rate'] + v['REORGANIZED_rate']:.1%} | "
                     f"{v['ACQUIRED_rate']:.1%} ({v['ACQUIRED']}) | {v['BANKRUPTCY_rate']:.1%} ({v['BANKRUPTCY']}) | "
                     f"{v['OTHER_STOPPED_rate']:.1%} |")
    hi, lo = bg.get("A/B") or {}, bg.get("D/F") or {}
    if hi.get("n") and lo.get("n"):
        bk_dir = lo["BANKRUPTCY_rate"] > hi["BANKRUPTCY_rate"]
        acq_dir = hi["ACQUIRED_rate"] >= lo["ACQUIRED_rate"]
        lines += ["", "**Direction of the bias.** " + (
            "Bankruptcy was more common in the D/F names and acquisitions (usually at a premium) in the A/B "
            "names — both missing from survivors-only tests, and both in the screen's favour. Those tests are, "
            "if anything, conservative for the quality screen." if bk_dir and acq_dir else
            "The two biases point in different directions here; survivors-only tests may overstate or "
            "understate the screen.") +
            f" With {lo['n']} D/F companies this is a direction, not a measurement."]
    if gc and res["n_graded"]:
        ab = (gc.get("A", 0) + gc.get("B", 0)) / res["n_graded"]
        lines += ["", f"Grades: " + ", ".join(f"{g} {n}" for g, n in gc.items()) + f". **{ab:.0%} of large "
                  "companies grade A or B**, so among large caps the grade separates very little — the same "
                  "picture as the quality component's negative IC in `FUNDAMENTALS_V2_EVALUATION.md`. The grade's "
                  "use is flagging the few outliers, not ranking the many."]
    lines += ["", "## Companies that stopped filing", "",
              "| company | outcome | last 10-K/10-Q | 2018 grade |", "|---|---|---|---|"]
    lines += [f"| {r['name']} | {r['outcome'].replace('_', ' ').lower()} | {r['last_periodic']} | {r['grade'] or '—'} |"
              for r in res["gone"][:60]]
    lines += ["", "## Reading it", "",
              "- A bankruptcy rate that rises as the grade falls means the survivors-only tests UNDERSTATE the "
              "quality screen: the blow-ups it would have avoided are missing from them.",
              "- Acquisitions usually close at a premium. If they cluster in the better grades, survivors-only "
              "tests miss gains the screen would have kept; if in the worse grades, the reverse.",
              "- Counts per grade are small; this is the direction and size of a bias, not a measured edge. "
              "Measuring the edge needs the non-survivors' prices to their last trading day "
              "(TIINGO_API_KEY covers delisted tickers) — until then the survivorship caveat stands on every "
              "evaluation here.",
              "- Outcome classes come from each company's own filings (8-K Item 1.03; merger proxy / tender "
              "response / Rule 425). \"Other stopped\" includes going-private deals without a merger proxy and "
              "deregistrations.", ""]
    path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    res = audit(n)
    (ROOT / "data" / "survivorship_audit.json").write_text(json.dumps(res, indent=1, default=str))
    write_report(res, ROOT / "docs" / "SURVIVORSHIP_AUDIT.md")
    print(json.dumps({k: res[k] for k in ("n_public_equity", "n_graded", "outcomes", "share_gone", "by_grade")},
                     indent=1))

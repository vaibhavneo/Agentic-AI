"""
Statement engine (stock_analysis/statements.py) — offline, from synthetic facts.

Run: python3 tests/test_stock_analysis_statements.py

Each case pins a failure that reached real data while this was being built:
Q4 and year-to-date cash flows never appear in a filing and must be derived;
a 10-Q's trailing-twelve-month cash flow (Amazon) was read as a fiscal year;
a proxy statement's pay-versus-performance net income (Caterpillar) hid the
10-K's; a tag chosen on the FULL history hid the tag actually on file at an
earlier as_of (Kraft Heinz); a 4-for-1 split looked like a 75% restatement.
"""
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))

FAILURES = []


def check(name, cond, detail=""):
    print(f"  {name:62s} {'OK' if cond else 'FAIL'}  {detail}")
    if not cond:
        FAILURES.append(name)
    assert cond, name


def F(concept, value, start, end, filed, form="10-Q", accession=None, unit="USD", tag_rank=1, tag=None):
    return {"concept": concept, "value": float(value), "unit": unit, "start": start, "end": end,
            "filed": filed, "accession": accession or f"ACC-{form}-{filed}", "form": form,
            "tag": tag or f"us-gaap:{concept}", "fy": None, "fp": None, "tag_rank": tag_rank}


def _year(fy_start="2024-01-01", rev=(100, 110, 120, 130), ocf_ytd=(30, 70, 100, 150), filed_year="2024"):
    """One calendar fiscal year the way filings report it: 3-month income
    statements in 10-Qs, YEAR-TO-DATE cash flows, and the full year in the 10-K."""
    y = fy_start[:4]
    q_ends = [f"{y}-03-31", f"{y}-06-30", f"{y}-09-30", f"{y}-12-31"]
    q_starts = [f"{y}-01-01", f"{y}-04-01", f"{y}-07-01", f"{y}-10-01"]
    out = []
    for i in range(3):
        filed = f"{filed_year}-{(i + 1) * 3 + 1:02d}-30"
        out.append(F("revenue", rev[i], q_starts[i], q_ends[i], filed))
        out.append(F("operating_cash_flow", ocf_ytd[i], fy_start, q_ends[i], filed))
        out.append(F("assets", 1000 + i, None, q_ends[i], filed))
        out.append(F("net_income", rev[i] / 10, q_starts[i], q_ends[i], filed))
    k_filed = f"{int(y) + 1}-02-15"
    out.append(F("revenue", sum(rev), fy_start, q_ends[3], k_filed, form="10-K"))
    out.append(F("operating_cash_flow", ocf_ytd[3], fy_start, q_ends[3], k_filed, form="10-K"))
    out.append(F("net_income", sum(rev) / 10, fy_start, q_ends[3], k_filed, form="10-K"))
    out.append(F("assets", 1100, None, q_ends[3], k_filed, form="10-K"))
    return out


def test_quarters_derived_where_filings_only_give_year_to_date():
    print("=== 1. Q4 and year-to-date cash flows ===")
    from stock_analysis.statements import build_from_facts, value
    st = build_from_facts("TEST", _year())
    qs = {q["label"]: q for q in st["quarters"]}
    check("four quarters", len(qs) == 4, str(list(qs)))
    q4 = qs["FY2024 Q4"]
    check("Q4 revenue = full year minus nine months", value(q4, "revenue") == 130)
    check("Q4 revenue is marked derived", q4["values"]["revenue"]["derived"] is True)
    check("Q2 operating cash flow = 6M YTD minus Q1", value(qs["FY2024 Q2"], "operating_cash_flow") == 40)
    check("Q3 operating cash flow = 9M YTD minus 6M YTD", value(qs["FY2024 Q3"], "operating_cash_flow") == 30)
    check("Q4 operating cash flow = FY minus 9M YTD", value(q4, "operating_cash_flow") == 50)
    check("Q1 revenue is reported, not derived", qs["FY2024 Q1"]["values"]["revenue"]["derived"] is False)
    check("balance sheet item read at each quarter end", value(qs["FY2024 Q2"], "assets") == 1001)
    check("annual revenue from the 10-K", value(st["annual"][0], "revenue") == 460)
    check("TTM revenue sums the last four quarters", value(st["ttm"], "revenue") == 460,
          st["ttm"]["basis"])


def test_trailing_twelve_month_10q_figure_is_not_a_fiscal_year():
    print("=== 2. a 10-Q's twelve-month figure is not a fiscal year ===")
    from stock_analysis.statements import build_from_facts
    facts = _year() + [F("operating_cash_flow", 999, "2024-07-01", "2025-06-30", "2025-07-30", form="10-Q")]
    st = build_from_facts("TEST", facts)
    check("only the 10-K's year is a fiscal year", [a["label"] for a in st["annual"]] == ["FY2024"],
          str([a["label"] for a in st["annual"]]))


def test_proxy_statement_facts_do_not_count():
    print("=== 3. proxy-statement (DEF 14A) net income is ignored ===")
    from stock_analysis.statements import build_from_facts, value, STATEMENT_FORMS
    facts = [f for f in _year() + [F("net_income", 1, "2024-01-01", "2024-12-31", "2025-04-01", form="DEF 14A")]
             if f["form"] in STATEMENT_FORMS]
    st = build_from_facts("TEST", facts)
    check("annual net income is the 10-K's", value(st["annual"][0], "net_income") == 46.0)


def test_tag_chosen_after_the_point_in_time_cut():
    print("=== 4. tag priority is resolved among facts on file at as_of ===")
    from stock_analysis.statements import collapse
    later_better_tag = F("revenue", 500, "2024-01-01", "2024-12-31", "2026-02-01", form="10-K", tag_rank=1)
    on_file = F("revenue", 460, "2024-01-01", "2024-12-31", "2025-02-15", form="10-K", tag_rank=3)
    cur, _ = collapse([on_file])                      # as_of 2025-06-01: the later filing is not visible
    check("the only tag on file is used", cur[("revenue", "2024-01-01", "2024-12-31")]["value"] == 460)
    cur, _ = collapse([on_file, later_better_tag])    # today: both visible
    check("with both visible, the higher-priority tag wins",
          cur[("revenue", "2024-01-01", "2024-12-31")]["value"] == 500)


def test_restatement_and_split_are_told_apart():
    print("=== 5. revisions vs stock-split rescaling ===")
    from stock_analysis.statements import collapse
    facts = [
        F("eps_diluted", 12.0, "2019-01-01", "2019-12-31", "2020-02-01", form="10-K", unit="USD/shares"),
        F("eps_diluted", 3.0, "2019-01-01", "2019-12-31", "2021-02-01", form="10-K", unit="USD/shares"),
        F("revenue", 1000, "2019-01-01", "2019-12-31", "2020-02-01", form="10-K"),
        F("revenue", 900, "2019-01-01", "2019-12-31", "2021-02-01", form="10-K"),
        F("net_income", 100, "2019-01-01", "2019-12-31", "2020-02-01", form="10-K"),
        F("net_income", 100.2, "2019-01-01", "2019-12-31", "2021-02-01", form="10-K"),
    ]
    _, rs = collapse(facts)
    kinds = {r["concept"]: r["kind"] for r in rs}
    check("4x EPS change is a split adjustment", kinds.get("eps_diluted") == "SPLIT_ADJUSTMENT", str(kinds))
    check("10% revenue change is a revision", kinds.get("revenue") == "REVISED")
    check("0.2% change is rounding, not a revision", "net_income" not in kinds)


def test_annual_only_filer_says_so():
    print("=== 6. a 20-F filer: annual only, in its own currency ===")
    from stock_analysis.statements import build_from_facts, value
    facts = []
    for y, rev in (("2023", 2000), ("2024", 2500)):
        facts += [F("revenue", rev, f"{y}-01-01", f"{y}-12-31", f"{int(y) + 1}-04-15", form="20-F", unit="TWD",
                    tag="ifrs-full:Revenue"),
                  F("assets", rev * 3, None, f"{y}-12-31", f"{int(y) + 1}-04-15", form="20-F", unit="TWD",
                    tag="ifrs-full:Assets"),
                  F("revenue", rev / 30, f"{y}-01-01", f"{y}-12-31", f"{int(y) + 1}-04-15", form="20-F",
                    unit="USD", tag="ifrs-full:Revenue")]
    st = build_from_facts("FPI", facts)
    check("reporting currency is TWD, not the USD convenience translation", st["filer"]["currency"] == "TWD")
    check("filer type 20-F, IFRS", st["filer"]["form_type"] == "20-F" and st["filer"]["taxonomy"] == "ifrs-full")
    check("annual_only flagged", st["filer"]["annual_only"] is True)
    check("TTM falls back to the latest fiscal year and says so",
          value(st["ttm"], "revenue") == 2500 and "latest fiscal year" in st["ttm"]["basis"])
    check("a warning names the limitation", any("annual figures only" in w for w in st["warnings"]))


def test_no_facts_is_unavailable_not_zero():
    print("=== 7. nothing to read is UNAVAILABLE, never zeros ===")
    from stock_analysis.statements import build_from_facts
    st = build_from_facts("NONE", [])
    check("unavailable with a reason", st["available"] is False and st.get("reason"))


if __name__ == "__main__":
    for fn in [v for k, v in dict(globals()).items() if k.startswith("test_")]:
        fn()
    print(f"\n{'ALL PASSED' if not FAILURES else f'{len(FAILURES)} FAILED'}")

"""
Filing review (stock_analysis/filings.py + narrative.py) — offline.

Run: python3 tests/test_stock_analysis_filings.py

Pins the reading rules found against real filings: the auditor's-report
boilerplate "assessing the risk that a material weakness exists" is not a
finding (it read as one for Super Micro's clean FY2023 10-K); risk-factor
language is hypothetical and never counts; Item 5.02 is context, not a flag;
headings typeset with thin spaces (TSMC) are still headings; and the MD&A
summary is withheld when a quote is not in the filing or a number is invented.
"""
import json
import sys
import types
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


def test_controls_reading():
    print("=== 1. controls: facts vs boilerplate vs hypotheticals ===")
    from stock_analysis.filings import control_findings
    boiler = ("Our audit included obtaining an understanding of internal control over financial reporting, "
              "assessing the risk that a material weakness exists, testing and evaluating the design.")
    check("auditor boilerplate is not a finding", control_findings(boiler) == [])
    hypo = "If we fail to maintain effective controls, a material weakness could be identified in the future."
    check("hypothetical language is not a finding", control_findings(hypo) == [])
    negated = "Management did not identify any material weakness in internal control over financial reporting."
    check("a negated statement is not a finding", control_findings(negated) == [])
    real = ("In reviewing the Company's tax accounting, management identified a material weakness in "
            "internal control over financial reporting related to income taxes.")
    check("an identified weakness is a CONCERN", [f["code"] for f in control_findings(real)] == ["MATERIAL_WEAKNESS"])
    ne = ("Based on this evaluation, our Chief Executive Officer and Chief Financial Officer concluded that "
          "our disclosure controls and procedures were not effective as of June 30, 2026.")
    check("'not effective' conclusion is a CONCERN", control_findings(ne)[0]["code"] == "CONTROLS_NOT_EFFECTIVE")


def test_going_concern_and_customers():
    print("=== 2. going concern and customer concentration ===")
    from stock_analysis.filings import going_concern, customer_concentration
    check("hypothetical going-concern language ignored",
          going_concern("Continued losses could raise substantial doubt about our ability to continue as a going "
                        "concern.") is None)
    gc = going_concern("These conditions raise substantial doubt about the Company's ability to continue as a "
                       "going concern within one year.")
    check("stated doubt is a CONCERN", gc and gc["severity"] == "CONCERN")
    c = customer_concentration("One customer accounted for approximately 32% of our net revenue in fiscal 2026. "
                               "Another distributor accounted for 11% of net sales.")
    check("largest customer share read", c and c[0]["pct"] == 32.0, str([x["pct"] for x in c]))


def test_index_flags():
    print("=== 3. flags from the filing index ===")
    from stock_analysis.filings import index_flags
    rows = [{"form": "NT 10-K", "filed": "2026-08-30", "accession": "A", "url": "u", "items": ""},
            {"form": "8-K", "filed": "2026-05-01", "accession": "B", "url": "u", "items": "4.02,9.01"},
            {"form": "8-K", "filed": "2026-04-01", "accession": "C", "url": "u", "items": "4.01"},
            {"form": "8-K", "filed": "2026-03-01", "accession": "D", "url": "u", "items": "5.02"},
            {"form": "8-K", "filed": "2026-02-01", "accession": "E", "url": "u", "items": "5.02"},
            {"form": "8-K", "filed": "2026-01-15", "accession": "F", "url": "u", "items": "5.02"},
            {"form": "NT 10-Q", "filed": "2019-01-01", "accession": "OLD", "url": "u", "items": ""}]
    flags, events = index_flags(rows, "2026-09-30")
    codes = {f["code"]: f["severity"] for f in flags}
    check("late filing notice → CONCERN", codes.get("LATE_FILING") == "CONCERN")
    check("Item 4.02 non-reliance → CONCERN", codes.get("8K_ITEM_4_02") == "CONCERN")
    check("Item 4.01 auditor change → WATCH", codes.get("8K_ITEM_4_01") == "WATCH")
    check("Item 5.02 x3 is context only", codes.get("MANAGEMENT_CHANGES") == "INFO")
    check("older than three years is not flagged", not any(f["evidence"]["accession"] == "OLD" for f in flags))


def test_sections_with_thin_spaces():
    print("=== 4. section split survives typesetting ===")
    from stock_analysis.filings import split_sections, clean
    toc = "ITEM 1A.\nRisk Factors 12\nITEM 7.\nMD&A 40\n"
    body = ("ITEM 1A. RISK FACTORS\n" + "Risk text. " * 400 + "\nITEM 2. PROPERTIES\nx\n"
            "ITEM 7. MANAGEMENT'S DISCUSSION\n" + "Revenue grew. " * 300 + "\nITEM 8. FINANCIAL\n")
    secs = split_sections(clean(toc + body), "10-K")
    check("risk factors body found, not the TOC line", len(secs["risk_factors"]) > 3000)
    check("MD&A body found", len(secs["mdna"]) > 3000)


def test_risk_factor_diff():
    print("=== 5. risk-factor changes ===")
    from stock_analysis.filings import risk_factor_changes
    prior = "\n".join(["Our business depends on consumer demand for our products and services worldwide.",
                       "We face intense competition in every market in which we operate today."])
    current = "\n".join(["Our business depends on consumer demand for our products and services globally.",
                         "We face intense competition in every market in which we operate today.",
                         "We are subject to an ongoing SEC investigation regarding our revenue recognition."])
    rf = risk_factor_changes(current, prior)
    check("one new heading, reworded one matched", rf["n_added"] == 1, str(rf["added"]))
    check("red-flag terms surface the new heading", rf["added_with_red_flag_terms"][0].startswith("We are subject"))


def test_mdna_summary_held_to_the_filing():
    print("=== 6. MD&A summary: quotes and numbers must be in the filing ===")
    from stock_analysis import narrative
    from financial_data import cache
    mdna = ("Net sales increased 6% to $416.2 billion during 2025 compared to 2024. " * 3
            + "The increase was driven primarily by higher net sales of iPhone and Services. " * 40)

    def client_returning(payload):
        msg = types.SimpleNamespace(content=json.dumps(payload))
        resp = types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])
        return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(
            create=lambda **kw: resp)))
    good = {"bullets": [{"topic": "drivers", "point": "Net sales rose 6% to $416.2 billion.",
                         "quote": "Net sales increased 6% to $416.2 billion during 2025 compared to 2024."}]}
    fake = {"bullets": [{"topic": "drivers", "point": "Net sales rose 9% to $430 billion.",
                         "quote": "Net sales increased 6% to $416.2 billion during 2025 compared to 2024."}]}
    para = {"bullets": [{"topic": "drivers", "point": "Sales rose 6%.",
                         "quote": "Sales went up a lot because of the iPhone."}]}
    for n, (payload, want) in enumerate(((good, "OK"), (fake, "WITHHELD"), (para, "WITHHELD"))):
        f = {"accession": f"TEST-MDNA-{n}-{id(payload)}", "url": "u", "filed": "2025-10-31"}
        r = narrative.summarize_mdna(mdna, f, client=client_returning(payload))
        check(f"summary {n}: {want}", r["status"] == want, str(r.get("validation")))
        cache.path_for("stock-analysis", "mdna", f"mdna_{f['accession']}").unlink(missing_ok=True)


if __name__ == "__main__":
    for fn in [v for k, v in dict(globals()).items() if k.startswith("test_")]:
        fn()
    print(f"\n{'ALL PASSED' if not FAILURES else f'{len(FAILURES)} FAILED'}")

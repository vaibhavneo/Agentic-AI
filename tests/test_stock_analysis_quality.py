"""
Quality of earnings (stock_analysis/quality.py) — offline, hand-computed.

Run: python3 tests/test_stock_analysis_quality.py

Every formula is checked against arithmetic done by hand on small numbers, and
every calibration fix made against real filings is pinned: days-sales measured
on the latest quarter (Exxon's Q2 2026 surge read as receivables stuffing on a
trailing basis), splits are not dilution (Toyota), only a downward full-year
restatement is a concern (Tesla's retrospective accounting change is not), and
a bank is not graded on three tests.
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


def B(end, start=None, label=None, **vals):
    return {"label": label or end, "start": start, "end": end,
            "values": {k: {"value": float(v), "accession": f"ACC-{k}", "filed": end} for k, v in vals.items()}}


def _st(ttm, prior, annual=None, quarters=None, restatements=None, as_of="2025-06-01"):
    return {"available": True, "ttm": dict(ttm, basis="last four quarters"), "ttm_prior": prior,
            "annual": annual or [], "quarters": quarters or [], "restatements": restatements or [],
            "as_of": as_of}


BASE_T = dict(revenue=1000, cost_of_revenue=600, gross_profit=400, sga_expense=100, operating_income=200,
              pretax_income=190, income_tax=40, net_income=150, operating_cash_flow=180, capex=50,
              depreciation_amortization=40, stock_comp=10, receivables=100, inventory=80, current_assets=400,
              current_liabilities=200, ppe_net=300, assets=1000, liabilities=500, equity=500, long_term_debt=200,
              retained_earnings=300, shares_diluted=100)
BASE_P = dict(revenue=900, cost_of_revenue=560, gross_profit=340, sga_expense=95, operating_income=170,
              pretax_income=160, income_tax=35, net_income=120, operating_cash_flow=150, capex=45,
              depreciation_amortization=38, stock_comp=9, receivables=90, inventory=75, current_assets=380,
              current_liabilities=210, ppe_net=290, assets=950, liabilities=500, equity=450, long_term_debt=210,
              retained_earnings=250, shares_diluted=101)


def test_cash_conversion_and_accruals():
    print("=== 1. cash conversion and Sloan accruals ===")
    from stock_analysis import quality as q
    st = _st(B("2025-03-31", **BASE_T), B("2024-03-31", **BASE_P))
    cc = q.cash_conversion(st, "industrial")
    check("OCF/NI = 180/150 = 1.2 → GOOD", cc["value"] == 1.2 and cc["status"] == "GOOD", cc["display"])
    check("inputs carry their filing", cc["inputs"]["net_income_ttm"]["accession"] == "ACC-net_income")
    ac = q.accruals(st, "industrial")
    check("(150-180)/avg(1000,950) = -0.0154 → GOOD", abs(ac["value"] - (-30 / 975)) < 1e-4 and ac["status"] == "GOOD")
    weak = _st(B("2025-03-31", **dict(BASE_T, operating_cash_flow=60)), B("2024-03-31", **BASE_P))
    check("OCF/NI = 0.4 → CONCERN", q.cash_conversion(weak, "industrial")["status"] == "CONCERN")
    check("accruals (150-60)/975 = 9.2% → WATCH", q.accruals(weak, "industrial")["status"] == "WATCH")


def test_beneish_by_hand():
    print("=== 2. Beneish M-score against hand arithmetic ===")
    from stock_analysis import quality as q
    st = _st(B("2025-03-31", **BASE_T), B("2024-03-31", **BASE_P))
    b = q.beneish(st, "industrial")
    dsri = (100 / 1000) / (90 / 900)
    gmi = (340 / 900) / (400 / 1000)
    aqi = (1 - (400 + 300) / 1000) / (1 - (380 + 290) / 950)
    sgi = 1000 / 900
    depi = (38 / (38 + 290)) / (40 / (40 + 300))
    sgai = (100 / 1000) / (95 / 900)
    lvgi = ((200 + 200) / 1000) / ((210 + 210) / 950)
    tata = (150 - 180) / 1000
    m = -4.84 + .920 * dsri + .528 * gmi + .404 * aqi + .892 * sgi + .115 * depi - .172 * sgai + 4.679 * tata - .327 * lvgi
    check("M-score matches hand computation", abs(b["value"] - round(m, 3)) < 1e-3, f"{b['value']} vs {m:.3f}")
    check("status from the Beneish cutoffs", b["status"] == ("CONCERN" if m > -1.78 else "WATCH" if m > -2.22 else "GOOD"))
    check("not applicable to a bank", q.beneish(st, "bank")["status"] == "NOT_APPLICABLE")


def test_piotroski_and_altman():
    print("=== 3. Piotroski and Altman Z'' ===")
    from stock_analysis import quality as q
    st = _st(B("2025-03-31", **BASE_T), B("2024-03-31", **BASE_P))
    p = q.piotroski(st, "industrial")
    expected = sum([150 / 950 > 0, 180 > 0, 150 / 950 > 120 / 950, 180 > 150, (200 / 1000) <= (210 / 950),
                    (400 / 200) > (380 / 210), True, (400 / 1000) > (340 / 900), (1000 / 1000) > (900 / 950)])
    check("F-score counts the nine tests", p["value"] == expected, f"{p['value']} vs {expected}")
    a = q.altman(st, "industrial")
    z = 6.56 * 200 / 1000 + 3.26 * 300 / 1000 + 6.72 * 200 / 1000 + 1.05 * 500 / 500
    check("Z'' = 6.56·WC/TA + 3.26·RE/TA + 6.72·EBIT/TA + 1.05·BE/TL", abs(a["value"] - round(z, 2)) < 1e-6,
          f"{a['value']} vs {z:.2f}")
    check("Altman not applicable to a REIT", q.altman(st, "reit")["status"] == "NOT_APPLICABLE")


def test_days_sales_uses_latest_quarter():
    print("=== 4. receivables measured on the latest quarter vs the same quarter last year ===")
    from stock_analysis import quality as q
    qs = [B("2026-06-30", "2026-04-01", "Q2-26", revenue=116, receivables=60),
          B("2026-03-31", "2026-01-01", "Q1-26", revenue=85, receivables=45),
          B("2025-12-31", "2025-10-01", "Q4-25", revenue=82, receivables=44),
          B("2025-09-30", "2025-07-01", "Q3-25", revenue=85, receivables=45),
          B("2025-06-30", "2025-04-01", "Q2-25", revenue=81, receivables=42)]
    st = _st(B("2026-06-30", revenue=368, receivables=60), B("2025-06-30", revenue=338, receivables=42), quarters=qs)
    r = q.receivables(st, "industrial")
    check("a revenue surge with matching receivables is not stuffing", r["status"] in ("OK", "GOOD"), r["display"])
    stuffed = [dict(qs[0], values=dict(qs[0]["values"], receivables={"value": 100.0}))] + qs[1:]
    st2 = _st(B("2026-06-30", revenue=368, receivables=100), B("2025-06-30", revenue=338, receivables=42),
              quarters=stuffed)
    check("receivables far outgrowing the quarter's sales → CONCERN",
          q.receivables(st2, "industrial")["status"] == "CONCERN", q.receivables(st2, "industrial")["display"])


def test_splits_are_not_dilution():
    print("=== 5. a 5-for-1 split is not dilution ===")
    from stock_analysis import quality as q
    annual = [B("2025-03-31", label="FY2025", shares_diluted=1300), B("2024-03-31", label="FY2024", shares_diluted=1330),
              B("2023-03-31", label="FY2023", shares_diluted=1360), B("2022-03-31", label="FY2022", shares_diluted=278)]
    st = _st(B("2025-03-31", shares_diluted=1300), B("2024-03-31", shares_diluted=1330), annual=annual)
    d = q.dilution(st, "industrial")
    check("buybacks read as shrinking count", d["status"] == "GOOD", d["display"])
    check("the split year is named, not counted", "FY2023" in d["split_years_excluded"], str(d["split_years_excluded"]))


def test_revisions_severity():
    print("=== 6. only a downward full-year restatement is a concern ===")
    from stock_analysis import quality as q

    def rev(concept, start, end, pct, acc):
        return {"kind": "REVISED", "concept": concept, "period_start": start, "period_end": end,
                "change_pct": pct, "revised_filed": "2025-02-01", "revised_accession": acc}
    quarterly = [rev("net_income", "2024-01-01", "2024-03-31", 23.0, "A"), rev("net_income", "2024-04-01",
                                                                           "2024-06-30", -5.3, "B")]
    st = _st(B("2025-03-31", **BASE_T), B("2024-03-31", **BASE_P), restatements=quarterly)
    check("quarterly re-presentations are not a concern", q.revisions(st, "industrial")["status"] in ("OK", "WATCH"))
    down = [rev("revenue", "2023-01-01", "2023-12-31", -8.0, "C")]
    st2 = _st(B("2025-03-31", **BASE_T), B("2024-03-31", **BASE_P), restatements=down)
    check("full-year revenue restated down 8% → CONCERN", q.revisions(st2, "industrial")["status"] == "CONCERN")


def test_grade_only_with_enough_tests():
    print("=== 7. graded only when most of the weight was measured ===")
    from stock_analysis import quality as q
    st = _st(B("2025-03-31", **BASE_T), B("2024-03-31", **BASE_P))
    full = q.assess(st, "industrial")
    check("an industrial company gets a grade", full["grade"] in "ABCDF" and full["coverage"] > 0.9)
    bank = q.assess(st, "bank")
    check("a bank is not graded on three tests", bank["grade"] is None and bank["not_graded_reason"])
    check("the bank's applicable tests are still shown",
          any(t["status"] not in ("NOT_APPLICABLE", "INSUFFICIENT_DATA") for t in bank["tests"]))


def test_missing_input_is_named_not_zero():
    print("=== 8. a missing input is named, never treated as zero ===")
    from stock_analysis import quality as q
    t = dict(BASE_T)
    t.pop("operating_cash_flow")
    st = _st(B("2025-03-31", **t), B("2024-03-31", **BASE_P))
    cc = q.cash_conversion(st, "industrial")
    check("INSUFFICIENT_DATA naming operating cash flow",
          cc["status"] == "INSUFFICIENT_DATA" and "operating cash flow" in cc["explanation"])


if __name__ == "__main__":
    for fn in [v for k, v in dict(globals()).items() if k.startswith("test_")]:
        fn()
    print(f"\n{'ALL PASSED' if not FAILURES else f'{len(FAILURES)} FAILED'}")

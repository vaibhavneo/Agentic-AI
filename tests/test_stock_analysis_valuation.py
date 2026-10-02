"""
Valuation and comparables (stock_analysis/valuation.py, peers.py, market.py) — offline.

Run: python3 tests/test_stock_analysis_valuation.py

The reverse DCF must solve back to the value it was given; peer medians and
ranks are plain arithmetic; the depositary-share ratio is read from the
20-F's own wording in each of the three phrasings met on real filings
(Alibaba's cover, Toyota's "Each American Depositary Share representing ten",
TSMC's "each ADS represents five (5) common shares" deep in the report); and a
multiple built on figures far older than the price says so.
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


def test_reverse_dcf_round_trip():
    print("=== 1. reverse DCF solves back to the given value ===")
    from stock_analysis.valuation import reverse_dcf, _pv
    for g in (-0.05, 0.0, 0.08, 0.25):
        ev = _pv(100.0, g, 0.09, 0.025, 10)
        got = reverse_dcf(ev, 100.0)
        check(f"growth {g:+.2f} recovered", got is not None and abs(got - g) < 1e-6, f"{got}")
    check("negative free cash flow has no implied growth", reverse_dcf(1000.0, -5.0) is None)


def test_peer_comparison_arithmetic():
    print("=== 2. peer medians, ranks, premiums ===")
    from stock_analysis.peers import compare
    peers = [{"ok": True, "pe": 10.0, "revenue_growth": 0.05}, {"ok": True, "pe": 20.0, "revenue_growth": 0.10},
             {"ok": True, "pe": 30.0, "revenue_growth": 0.20}, {"ok": False, "pe": 999.0}]
    c = compare({"pe": 30.0, "revenue_growth": 0.15}, peers)
    s = c["stats"]
    check("median ignores excluded peers", s["pe"]["peer_median"] == 20.0)
    check("premium = 30/20 - 1 = 50%", s["pe"]["premium_to_median"] == 0.5)
    check("rank: above 2 of 3 peers", s["pe"]["percentile_vs_peers"] == round(2 / 3, 2))
    check("growth rank above 2 of 3", s["revenue_growth"]["percentile_vs_peers"] == round(2 / 3, 2))


def test_ads_ratio_phrasings():
    print("=== 3. depositary-share ratio from the 20-F's words ===")
    from stock_analysis.market import adr_ratio
    cases = [
        ("Exchange | American Depositary Shares, each representing eight Ordinary Shares | BABA | NYSE", 8.0),
        ("| * | Each American Depositary Share representing ten shares of the registrant’s Common Stock.", 10.0),
        ("held in the form of ADSs (each ADS represents five (5) common shares) held by such holders", 5.0),
        ("American Depositary Shares, each Representing one Ordinary Share, without nominal value", 1.0),
    ]
    for text, want in cases:
        r = adr_ratio(text)
        check(f"ratio {want:g}", r is not None and r["ratio"] == want, str(r and r["ratio"]))
    check("no ratio stated → None, never a guess", adr_ratio("Common shares traded in Taipei.") is None)


def test_staleness_named():
    print("=== 4. old figures against a current price are named ===")
    from stock_analysis.valuation import staleness
    check("21 months apart → warning", staleness("2024-12-31", "2026-10-02") is not None)
    check("one quarter apart → none", staleness("2026-06-30", "2026-10-02") is None)


if __name__ == "__main__":
    for fn in [v for k, v in dict(globals()).items() if k.startswith("test_")]:
        fn()
    print(f"\n{'ALL PASSED' if not FAILURES else f'{len(FAILURES)} FAILED'}")

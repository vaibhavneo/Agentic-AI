"""
Guidance and segment parsing (stock_analysis/guidance.py, segments.py) — offline.

Run: python3 tests/test_stock_analysis_guidance_segments.py

Pins the parsing rules found on real releases and instances: "plus or minus"
ranges (Nvidia), "and … respectively" is two figures not a range, an
exclusion sentence is not guidance (Applied Materials' $0.01), a subtotal is
recognized by arithmetic when the filing does not declare it (Apple's
Products), and one-dimension contexts only.
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


def test_guidance_sentences():
    print("=== 1. guidance sentences ===")
    from stock_analysis.guidance import parse_statement
    r = parse_statement("Revenue is expected to be $108.0 billion, plus or minus 2%.")
    check("plus or minus range", r["metric"] == "revenue" and abs(r["low"] - 105.84e9) < 1 and abs(r["high"] - 110.16e9) < 1)
    r = parse_statement("Gross margins are expected to be 74.0%, plus or minus 50 basis points.")
    check("basis points range", r["unit"] == "%" and r["low"] == 73.5 and r["high"] == 74.5)
    r = parse_statement("Revenue is expected to be between $10.0 billion and $10.5 billion.")
    check("between … and", r["low"] == 10.0e9 and r["high"] == 10.5e9)
    check("'respectively' is two figures, not a range",
          parse_statement("Operating expenses are expected to be approximately $9.2 billion and $9.0 billion, "
                          "respectively.") is None)
    check("an exclusion is not guidance",
          parse_statement("This outlook for non-GAAP diluted EPS excludes charges of $0.01 per share.") is None)


def test_outlook_block():
    print("=== 2. the outlook block ===")
    from stock_analysis.guidance import extract
    text = ("Results\nRevenue was $100 billion.\nOutlook\nNVIDIA's outlook for the third quarter of fiscal 2027 "
            "is as follows:\n• Revenue is expected to be $108.0 billion, plus or minus 2%.\n")
    g = extract(text)
    check("found, with its period", g["found"] and g["period_text"] == "third quarter of fiscal 2027")
    check("statement parsed and quoted", g["statements"][0]["quote"].startswith("• Revenue is expected"))
    check("no outlook section → not found", extract("Revenue was $100 billion. Thanks.")["found"] is False)


def test_segments():
    print("=== 3. segment instance parsing ===")
    from stock_analysis.segments import parse_instance, summarize, _arithmetic_subtotals
    ctx = lambda cid, m, s, e: (f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:segment>'  # noqa: E731
                                f'<xbrldi:explicitMember dimension="srt:ProductOrServiceAxis">{m}</xbrldi:explicitMember>'
                                f'</xbrli:segment></xbrli:entity><xbrli:period><xbrli:startDate>{s}</xbrli:startDate>'
                                f'<xbrli:endDate>{e}</xbrli:endDate></xbrli:period></xbrli:context>')
    fact = lambda cid, v: (f'<us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax contextRef="{cid}" '  # noqa: E731
                           f'unitRef="usd">{v}</us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax>')
    xml = "".join([ctx("a", "x:PhoneMember", "2026-04-01", "2026-06-30"), fact("a", 60),
                   ctx("b", "x:ServicesMember", "2026-04-01", "2026-06-30"), fact("b", 40),
                   ctx("c", "x:PhoneMember", "2025-04-01", "2025-06-30"), fact("c", 50),
                   ctx("d", "x:TotalProductsMember", "2026-04-01", "2026-06-30"), fact("d", 100)])
    rows = summarize(parse_instance(xml), "2026-06-30", (80, 100))["product or service"]
    by = {r["member"]: r for r in rows}
    check("growth vs the same quarter a year earlier", by["x:PhoneMember"]["growth"] == 0.2)
    check("a line equal to the sum of others is a subtotal", by["x:TotalProductsMember"]["subtotal"] is True)
    check("shares exclude the subtotal", by["x:PhoneMember"]["share"] == 0.6)
    check("Apple's Products ≈ iPhone+Mac+Wearables+iPad",
          _arithmetic_subtotals({"P": 78.7, "i": 54.3, "s": 30.7, "m": 10.4, "w": 7.9, "ip": 6.2}) == {"P"})


if __name__ == "__main__":
    for fn in [v for k, v in dict(globals()).items() if k.startswith("test_")]:
        fn()
    print(f"\n{'ALL PASSED' if not FAILURES else f'{len(FAILURES)} FAILED'}")

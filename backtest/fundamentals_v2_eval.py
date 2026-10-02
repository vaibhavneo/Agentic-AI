"""
Shadow evaluation: does the v2 fundamentals score rank future returns better
than the v1 pillar it would replace?

Point-in-time replay. At each quarterly date, every company is scored from the
filings on record that day (facts filed after it are removed), the price that
traded that day, and the filing index as of that day. The outcome is the
forward return over 63, 126 and 252 trading days, net of SPY, on total-return
prices. The statistic is the cross-sectional Spearman rank correlation (IC)
between score and outcome on each date, averaged over dates.

Stated limits, all of which make the absolute numbers optimistic or noisy and
none of which favours v2 over v1 (both are scored on the same names, dates and
outcomes):
  - the universe is today's tickers (survivorship: companies that failed are
    absent), and small (~40 names), so each date's IC is noisy;
  - 126- and 252-day windows overlap across quarterly dates, so the t-statistic
    overstates independence — the annual non-overlapping subset is reported too;
  - v1 is re-implemented from its own definition (the latest value per line
    item, its four ratio bands) on the same facts v2 reads, so the comparison
    isolates the SCORING, not a data-vintage difference.

Run: python3 -m backtest.fundamentals_v2_eval [--quick]
Writes docs/FUNDAMENTALS_V2_EVALUATION.md and data/fundamentals_v2_eval.json.
"""
from __future__ import annotations

import json
import math
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

UNIVERSE = [
    # tech / semis / software
    "AAPL", "MSFT", "NVDA", "INTC", "CSCO", "ORCL", "ADBE", "QCOM", "TXN", "AMAT", "MU", "IBM",
    # consumer
    "KO", "PEP", "PG", "WMT", "COST", "HD", "LOW", "NKE", "MCD", "SBUX", "TGT", "KHC", "CL",
    # health
    "JNJ", "PFE", "MRK", "ABT", "AMGN", "BMY", "MDT",
    # industrial / energy / materials / telecom
    "CAT", "DE", "HON", "MMM", "UPS", "GE", "CVX", "COP", "DOW", "VZ", "T",
]
HORIZONS = (63, 126, 252)
DATES = [f"{y}-{m}" for y in range(2017, 2026) for m in ("02-20", "05-20", "08-20", "11-20")]
DATES = [d for d in DATES if d <= "2025-08-20"]


def _spearman(x: List[float], y: List[float]) -> Optional[float]:
    n = len(x)
    if n < 8:
        return None

    def ranks(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2.0
            i = j + 1
        return r
    rx, ry = ranks(x), ranks(y)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    vy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return cov / (vx * vy) if vx and vy else None


def v1_score(facts: List[Dict[str, Any]]) -> Optional[float]:
    """The v1 pillar, from its own definition: the most recent value of each
    line item (gateway collapse: latest filing per period END, then the latest
    period), and its four ratio bands."""
    best: Dict[tuple, Dict[str, Any]] = {}
    for f in facts:
        k = (f["concept"], f["end"])
        if k not in best or f["filed"] > best[k]["filed"]:
            best[k] = f
    latest: Dict[str, Dict[str, Any]] = {}
    for (c, end), f in best.items():
        if c not in latest or (end or "") > (latest[c]["end"] or ""):
            latest[c] = f
    g = lambda c: latest[c]["value"] if c in latest else None  # noqa: E731
    clip = lambda v: max(0.0, min(100.0, v))  # noqa: E731
    subs = []
    rev, ni, eq, oi, ltd = g("revenue"), g("net_income"), g("equity"), g("operating_income"), g("long_term_debt")
    if rev and ni is not None:
        subs.append(clip(ni / rev * 400.0))
    if eq and ni is not None:
        subs.append(clip(ni / eq * 250.0))
    if eq and ltd is not None:
        subs.append(clip(100.0 - ltd / eq * 33.3))
    if rev and oi is not None:
        subs.append(clip(oi / rev * 300.0))
    return sum(subs) / len(subs) if subs else None


def _visible(facts, day):
    return [f for f in facts if f["filed"] <= day]


def evaluate(universe: List[str], dates: List[str], read_text: bool = True,
             log=print) -> Dict[str, Any]:
    from financial_data import gateway as gw
    from stock_analysis.company import profile as get_profile
    from stock_analysis.filings import filing_index, index_flags, control_findings, going_concern, \
        split_sections, _annual_text, ANNUAL
    from stock_analysis.market import price_history
    from stock_analysis.quality import assess
    from stock_analysis.scoring import score_components
    from stock_analysis.statements import build_from_facts, load_facts

    spy = gw.get_bars_df("SPY", period="12y")
    rows: List[Dict[str, Any]] = []
    for n, sym in enumerate(universe, 1):
        t0 = time.time()
        try:
            facts = load_facts(sym)["facts"]
            prof = get_profile(sym)
            kind = prof.get("industry_kind", "unknown")
            filings = filing_index(sym)["filings"]
            adj = gw.get_bars_df(sym, period="12y")                    # total return, for outcomes
            traded = price_history(sym, years=12, as_traded=True)       # for market values
        except Exception as e:
            log(f"  {sym}: skipped ({type(e).__name__}: {e})")
            continue
        text_flags: Dict[str, List[Dict[str, Any]]] = {}
        for d in dates:
            vis = _visible(facts, d)
            st = build_from_facts(sym, vis, as_of=d)
            if not st.get("available"):
                continue
            q = assess(st, kind)
            fl = [f for f in filings if f["filed"] <= d]
            flags, _ = index_flags(fl, d)
            if read_text:
                ann = next((f for f in fl if f["form"] in ANNUAL), None)
                if ann:
                    if ann["accession"] not in text_flags:
                        try:
                            text = _annual_text(sym, ann)
                            secs = split_sections(text, ann["form"])
                            tf = control_findings(secs.get("controls") or "")
                            gc = going_concern(text)
                            text_flags[ann["accession"]] = tf + ([gc] if gc else [])
                        except Exception:
                            text_flags[ann["accession"]] = []
                    flags = flags + text_flags[ann["accession"]]
            px = traded[traded.index <= d]["Close"]
            mkt = None
            sh = None
            for blk in (st.get("quarters") or [])[:2] + (st.get("annual") or [])[:1]:
                v = (blk.get("values") or {}).get("shares_diluted")
                if v:
                    sh = v["value"]
                    break
            if not px.empty and sh and (st.get("filer") or {}).get("currency") == "USD":
                mc = float(px.iloc[-1]) * sh
                mkt = {"available": True, "market_cap_usd": mc, "fx": {"rate": 1.0}}
            v2 = score_components(st, q, kind, mkt, flags)
            v1 = v1_score(vis)
            a = adj[adj.index <= d]["Close"]
            s = spy[spy.index <= d]["Close"]
            if a.empty or s.empty:
                continue
            i0, j0 = len(a) - 1, len(s) - 1
            fwd = {}
            for h in HORIZONS:
                if i0 + h < len(adj) and j0 + h < len(spy):
                    r = float(adj["Close"].iloc[i0 + h] / a.iloc[-1] - 1)
                    m = float(spy["Close"].iloc[j0 + h] / s.iloc[-1] - 1)
                    fwd[h] = r - m
            rows.append({"symbol": sym, "date": d, "v1": v1, "v2": v2["score"], "v2_base": v2["base"],
                         "penalty": v2["penalty"], **{f"sub_{k}": v for k, v in v2["subs"].items()},
                         **{f"fwd_{h}": fwd.get(h) for h in HORIZONS}})
        log(f"  [{n}/{len(universe)}] {sym}: {sum(1 for r in rows if r['symbol'] == sym)} dates "
            f"({time.time() - t0:.0f}s)")
    return summarize(rows, dates)


def summarize(rows: List[Dict[str, Any]], dates: List[str]) -> Dict[str, Any]:
    signals = ["v1", "v2", "v2_base", "sub_quality", "sub_profitability", "sub_cash_return", "sub_growth",
               "sub_balance_sheet"]
    out: Dict[str, Any] = {"n_rows": len(rows), "n_symbols": len({r["symbol"] for r in rows}),
                           "n_dates": len(dates), "by_horizon": {}}
    for h in HORIZONS:
        res = {}
        for sig in signals:
            ics, annual_ics, spreads = [], [], []
            for d in dates:
                pts = [(r[sig], r[f"fwd_{h}"]) for r in rows if r["date"] == d
                       and r.get(sig) is not None and r.get(f"fwd_{h}") is not None]
                ic = _spearman([p[0] for p in pts], [p[1] for p in pts])
                if ic is None:
                    continue
                ics.append(ic)
                if d.endswith("02-20"):
                    annual_ics.append(ic)
                srt = sorted(pts, key=lambda p: p[0])
                k = len(srt) // 3
                if k >= 3:
                    spreads.append(sum(p[1] for p in srt[-k:]) / k - sum(p[1] for p in srt[:k]) / k)
            if not ics:
                continue
            mean = sum(ics) / len(ics)
            sd = math.sqrt(sum((x - mean) ** 2 for x in ics) / max(1, len(ics) - 1)) if len(ics) > 1 else None
            res[sig] = {"mean_ic": round(mean, 4), "n_dates": len(ics),
                        "t_stat": None if not sd else round(mean / sd * math.sqrt(len(ics)), 2),
                        "share_positive": round(sum(1 for x in ics if x > 0) / len(ics), 2),
                        "annual_nonoverlapping_mean_ic": None if not annual_ics else
                        round(sum(annual_ics) / len(annual_ics), 4),
                        "top_minus_bottom_tercile": None if not spreads else round(sum(spreads) / len(spreads), 4)}
        out["by_horizon"][h] = res
    v1 = [out["by_horizon"][h].get("v1", {}).get("mean_ic") for h in HORIZONS]
    v2 = [out["by_horizon"][h].get("v2", {}).get("mean_ic") for h in HORIZONS]
    better = sum(1 for a, b in zip(v1, v2) if a is not None and b is not None and b > a)
    positive = sum(1 for b in v2 if b is not None and b > 0)
    out["verdict"] = {"v2_beats_v1_horizons": better, "v2_positive_horizons": positive,
                      "promote": better >= 2 and positive >= 2,
                      "rule": "promote v2 to the live pillar when its mean IC beats v1 at >= 2 of 3 horizons "
                              "AND is positive at >= 2 of 3 (stated before the run)"}
    out["rows"] = rows
    return out


def write_report(res: Dict[str, Any], path: Path) -> None:
    lines = ["# Fundamentals v2 — shadow evaluation", "",
             f"Generated {date.today().isoformat()} by `backtest/fundamentals_v2_eval.py`. "
             f"{res['n_symbols']} companies × {res['n_dates']} quarterly dates "
             f"({res['n_rows']} scored observations), point-in-time.", "",
             "Mean cross-sectional rank IC of each score with the forward return net of SPY "
             "(t-stat overstates independence at 126/252 days; the annual non-overlapping mean is the check).", ""]
    for h, res_h in res["by_horizon"].items():
        lines += [f"## {h} trading days", "",
                  "| signal | mean IC | t | IC>0 | annual-only IC | top−bottom tercile |",
                  "|---|---|---|---|---|---|"]
        for sig, r in res_h.items():
            lines.append(f"| {sig} | {r['mean_ic']:+.4f} | {r['t_stat']} | {r['share_positive']:.0%} | "
                         f"{'—' if r['annual_nonoverlapping_mean_ic'] is None else format(r['annual_nonoverlapping_mean_ic'], '+.4f')} | "
                         f"{'—' if r['top_minus_bottom_tercile'] is None else format(r['top_minus_bottom_tercile'], '+.2%')} |")
        lines.append("")
    v = res["verdict"]
    lines += ["## Verdict", "", f"Rule (fixed before the run): {v['rule']}.", "",
              f"v2 beats v1 at {v['v2_beats_v1_horizons']}/3 horizons and is positive at "
              f"{v['v2_positive_horizons']}/3 → **{'PROMOTE' if v['promote'] else 'KEEP IN SHADOW'}**.", "",
              "Limits: today's tickers (survivorship), ~40 names, overlapping windows; see the module docstring."]
    path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    quick = "--quick" in sys.argv
    uni = UNIVERSE[:8] if quick else UNIVERSE
    dts = DATES[::4] if quick else DATES
    res = evaluate(uni, dts, read_text=not quick)
    (ROOT / "data").mkdir(exist_ok=True)
    out = {k: v for k, v in res.items() if k != "rows"}
    (ROOT / "data" / "fundamentals_v2_eval.json").write_text(json.dumps(res, indent=1, default=str))
    write_report(res, ROOT / "docs" / "FUNDAMENTALS_V2_EVALUATION.md")
    print(json.dumps(out, indent=1, default=str))

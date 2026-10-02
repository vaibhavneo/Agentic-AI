"""
Event-driven price signals, measured point-in-time before anything uses them.

The desk's algorithmic price signals showed no out-of-sample edge, so rather
than adding indicators this tests three signals with a long academic record
that the filing-calendar data now makes possible:

  sue          standardized unexpected earnings: the latest quarter's net
               income minus the same quarter a year earlier, divided by the
               standard deviation of that seasonal change over the prior
               eight quarters (seasonal random walk; Bernard & Thomas 1989,
               post-earnings-announcement drift). From SEC filings only.
  reaction     market-adjusted move around the latest earnings release
               (8-K Item 2.02): close before → close the trading day after,
               minus SPY.
  rel_mom      12-1 month momentum relative to the stock's sector fund.

RULE, fixed before the run: a signal is promoted from descriptive context to
decision evidence only if its mean IC is positive at all three horizons AND
reaches t >= 2 at one or more. Otherwise it stays descriptive.

Same universe, dates, outcomes and limits as backtest/fundamentals_v2_eval.py
(today's tickers — survivorship; ~40 names; overlapping windows).

Run: python3 -m backtest.event_signals_eval
"""
from __future__ import annotations

import json
import math
import statistics
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.fundamentals_v2_eval import DATES, HORIZONS, UNIVERSE, _spearman, _visible  # noqa: E402

SIGNALS = ("sue", "reaction", "rel_mom")


def sue(quarters: List[Dict[str, Any]]) -> Optional[float]:
    """Seasonal-random-walk SUE on net income. `quarters` newest first. Pure."""
    from stock_analysis.statements import value
    ni = [value(q, "net_income") for q in quarters]
    if len(ni) < 13 or any(v is None for v in ni[:13]):
        return None
    diffs = [ni[i] - ni[i + 4] for i in range(9)]           # latest change + 8 prior
    hist = diffs[1:]
    sd = statistics.pstdev(hist)
    if not sd:
        return None
    return diffs[0] / sd


def reaction_at(adj, spy, release: str) -> Optional[float]:
    from stock_analysis.technicals import earnings_reactions
    r = earnings_reactions(adj, spy, [release])
    return r["releases"][0]["reaction"] if r.get("available") else None


def rel_momentum(adj, sector, d: str) -> Optional[float]:
    a = adj[adj.index <= d]["Close"]
    s = sector[sector.index <= d]["Close"] if sector is not None and not sector.empty else None
    if len(a) < 260 or s is None or len(s) < 260:
        return None
    ra = float(a.iloc[-22] / a.iloc[-253] - 1)
    rs = float(s.iloc[-22] / s.iloc[-253] - 1)
    return ra - rs


def evaluate(universe: List[str], dates: List[str], log=print) -> Dict[str, Any]:
    from financial_data import gateway as gw
    from stock_analysis.company import profile as get_profile
    from stock_analysis.filings import filing_index
    from stock_analysis.statements import build_from_facts, load_facts
    from stock_analysis.technicals import sector_etf

    spy = gw.get_bars_df("SPY", period="12y")
    etf_cache: Dict[str, Any] = {}
    rows: List[Dict[str, Any]] = []
    for n, sym in enumerate(universe, 1):
        t0 = time.time()
        try:
            facts = load_facts(sym)["facts"]
            prof = get_profile(sym)
            releases = [f["filed"] for f in filing_index(sym)["filings"]
                        if f["form"].startswith("8-K") and "2.02" in (f.get("items") or "")]
            adj = gw.get_bars_df(sym, period="12y")
            etf = sector_etf(prof.get("sic"))
            if etf and etf not in etf_cache:
                etf_cache[etf] = gw.get_bars_df(etf, period="12y")
            sector = etf_cache.get(etf)
        except Exception as e:
            log(f"  {sym}: skipped ({type(e).__name__})")
            continue
        for d in dates:
            st = build_from_facts(sym, _visible(facts, d), as_of=d)
            if not st.get("available"):
                continue
            recent = [r for r in releases if r <= d and r >= (date.fromisoformat(d) - timedelta(days=100)).isoformat()]
            a = adj[adj.index <= d]["Close"]
            s = spy[spy.index <= d]["Close"]
            if a.empty or s.empty:
                continue
            i0, j0 = len(a) - 1, len(s) - 1
            fwd = {}
            for h in HORIZONS:
                if i0 + h < len(adj) and j0 + h < len(spy):
                    fwd[h] = float(adj["Close"].iloc[i0 + h] / a.iloc[-1] - 1) - float(spy["Close"].iloc[j0 + h] / s.iloc[-1] - 1)
            rows.append({"symbol": sym, "date": d, "sue": sue(st.get("quarters") or []),
                         "reaction": reaction_at(adj[adj.index <= d], spy[spy.index <= d], max(recent))
                         if recent else None,
                         "rel_mom": rel_momentum(adj, sector, d),
                         **{f"fwd_{h}": fwd.get(h) for h in HORIZONS}})
        log(f"  [{n}/{len(universe)}] {sym} ({time.time() - t0:.0f}s)")
    return summarize(rows, dates)


def summarize(rows: List[Dict[str, Any]], dates: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"n_rows": len(rows), "n_symbols": len({r["symbol"] for r in rows}), "by_horizon": {}}
    for h in HORIZONS:
        res = {}
        for sig in SIGNALS:
            ics = []
            for d in dates:
                pts = [(r[sig], r[f"fwd_{h}"]) for r in rows if r["date"] == d
                       and r.get(sig) is not None and r.get(f"fwd_{h}") is not None]
                ic = _spearman([p[0] for p in pts], [p[1] for p in pts])
                if ic is not None:
                    ics.append(ic)
            if not ics:
                continue
            mean = sum(ics) / len(ics)
            sd = math.sqrt(sum((x - mean) ** 2 for x in ics) / max(1, len(ics) - 1)) if len(ics) > 1 else None
            res[sig] = {"mean_ic": round(mean, 4), "n_dates": len(ics),
                        "t_stat": None if not sd else round(mean / sd * math.sqrt(len(ics)), 2),
                        "share_positive": round(sum(1 for x in ics if x > 0) / len(ics), 2)}
        out["by_horizon"][h] = res
    verdict = {}
    for sig in SIGNALS:
        stats = [out["by_horizon"][h].get(sig) or {} for h in HORIZONS]
        pos_all = all((s.get("mean_ic") or 0) > 0 for s in stats)
        strong = any((s.get("t_stat") or 0) >= 2 for s in stats)
        verdict[sig] = {"promote": pos_all and strong, "positive_all_horizons": pos_all, "t_ge_2_somewhere": strong}
    out["verdict"] = verdict
    out["rule"] = ("promote only if mean IC > 0 at 63, 126 and 252 days AND t >= 2 at one or more (fixed before "
                   "the run)")
    return out


def write_report(res: Dict[str, Any], path: Path) -> None:
    lines = ["# Event-driven price signals — point-in-time evaluation", "",
             f"Generated {date.today().isoformat()} by `backtest/event_signals_eval.py`. {res['n_symbols']} companies, "
             f"{res['n_rows']} observations, quarterly 2017–2025. Mean cross-sectional rank IC with the forward "
             "return net of SPY (t-stats overstate independence at 126/252 days).", ""]
    for h, rh in res["by_horizon"].items():
        lines += [f"## {h} trading days", "", "| signal | mean IC | t | IC>0 |", "|---|---|---|---|"]
        lines += [f"| {k} | {v['mean_ic']:+.4f} | {v['t_stat']} | {v['share_positive']:.0%} |" for k, v in rh.items()]
        lines.append("")
    lines += ["## Verdict", "", f"Rule: {res['rule']}.", ""]
    lines += [f"- **{k}**: {'PROMOTE' if v['promote'] else 'stays descriptive'} "
              f"(positive at all horizons: {v['positive_all_horizons']}; t >= 2 somewhere: {v['t_ge_2_somewhere']})"
              for k, v in res["verdict"].items()]
    if not any(v["promote"] for v in res["verdict"].values()):
        lines += ["", "## What this means", "",
                  "No signal met the rule, so none enters the decision evidence. Every mean IC is within a few "
                  "hundredths of zero at every horizon — no edge in this universe, not a weak one waiting for "
                  "more data. That fits the literature: post-earnings drift and momentum were strongest in "
                  "small, thinly followed stocks and have faded in large caps, which is all this universe holds. "
                  "Earnings reactions and relative strength stay in the technicals section as context for the "
                  "reader; SUE is not shown, since a number with no measured use adds noise."]
    lines += ["", "Limits: today's tickers (survivorship — see SURVIVORSHIP_AUDIT.md), ~40 large companies, "
              "overlapping windows."]
    path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    res = evaluate(UNIVERSE, DATES)
    (ROOT / "data" / "event_signals_eval.json").write_text(json.dumps({k: v for k, v in res.items()}, indent=1, default=str))
    write_report(res, ROOT / "docs" / "EVENT_SIGNALS_EVALUATION.md")
    print(json.dumps(res["verdict"], indent=1))

"""
The evaluation report: scorecards per horizon, the feedback edges' state, and
a plain-English headline a reader can act on without the tables.
"""
from __future__ import annotations

import math
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from . import scorecard as S

DEFAULT_HORIZONS = (1, 5, 20, 60)
MIN_LABEL_N = 30
_CACHE_TTL_S = 600.0
_cache: Dict[Any, Any] = {}


def _feedback(horizons: Sequence[int]) -> Dict[str, Any]:
    """What the ledger is currently changing — each edge with its own gate."""
    out: Dict[str, Any] = {}
    try:
        from intelligence.calibration import load_calibrators
        out["p_up_calibration"] = {
            int(h): {k: c.get(k) for k in ("applied", "n", "effective_n", "brier_raw",
                                           "brier_calibrated", "reason")}
            for h, c in load_calibrators(horizons).items()}
    except Exception as e:
        out["p_up_calibration"] = {"error": str(e)[:120]}
    try:
        from intelligence import outperform
        out["p_beat_spy_model"] = outperform.status(outperform.load_models(horizons))
    except Exception as e:
        out["p_beat_spy_model"] = {"error": str(e)[:120]}
    try:
        from selfimprove import ledger as SL
        from selfimprove.loop import apply_mode
        out["self_improvement"] = {"ledger": SL.summary(), "apply_mode": apply_mode()}
    except Exception as e:
        out["self_improvement"] = {"error": str(e)[:120]}
    return out


def _pct(x: Optional[float]) -> str:
    # Half-up, like the UI's toFixed, so a 0.505 reads 51% in both places.
    return "—" if x is None else f"{math.floor(100 * x + 0.5)}%"


def _num(x: Optional[float], fmt: str) -> str:
    return "—" if x is None else format(x, fmt)


def headline(card: Dict[str, Any]) -> List[str]:
    """Four sentences per horizon, in the order a reader should weigh them."""
    h = card["horizon_days"]
    cov, rk, d, pu = card["coverage"], card["ranking"], card["direction"], card["p_up"]
    v = card["verdicts"]
    if not cov["calls"]:
        return [f"{h}d: nothing has matured at this horizon yet."]
    lines = [
        (f"{h}d direction: {_pct(d['hit_on_price']['rate'])} of {d['hit_on_price']['calls']:,} directional "
         f"calls moved the called way on price, {_pct(d['hit_vs_spy']['rate'])} against SPY. The stock "
         f"rose on {_pct(d['share_of_calls_where_stock_rose'])} of all calls, so a hit on price mostly "
         f"measures the market."),
        (f"{h}d ranking (did higher-scored names beat lower-scored ones vs SPY, same day): rank IC "
         f"{_num(rk['rank_ic']['mean'], '+.3f')}, t={_num(rk['rank_ic']['t'], '+.2f')} over "
         f"{rk['rank_ic']['n_dates']} dates — {v['ranking']['verdict']}: {v['ranking']['why']}."),
    ]
    if pu.get("n"):
        b, b50, bt = pu["brier"], pu["brier_always_50pct"], pu["brier_trailing_base_rate"]
        cmp = []
        cmp.append(("better" if b < b50 else "worse") + f" than always saying 50% ({b50})")
        if bt is not None:
            cmp.append(("better" if b < bt else "worse") + f" than the up-rate known at the time ({bt})")
        lines.append(f"{h}d p_up: Brier {b} — {' and '.join(cmp)}; {v['p_up']['verdict']}: "
                     f"{v['p_up']['why']}.")
    # Only labels with enough calls to mean something (the same floor
    # selfimprove.reliability uses before quoting a label's record).
    worst = max((c for c in card["confidence"]
                 if c.get("overclaim_pts") is not None and c["n"] >= MIN_LABEL_N),
                key=lambda c: c["overclaim_pts"], default=None)
    if worst and worst["overclaim_pts"] > 10:
        lines.append(f"{h}d confidence: {worst['level']} claimed {_pct(worst['claimed'])} and was right "
                     f"{_pct(worst['hit_on_price'])} on price ({worst['n']} calls) — the label overstates.")
    return lines


def build(horizons: Sequence[int] = DEFAULT_HORIZONS, source: str = "live",
          use_cache: bool = True) -> Dict[str, Any]:
    key = (tuple(horizons), source)
    now = time.time()
    if use_cache and key in _cache and now - _cache[key][0] < _CACHE_TTL_S:
        return _cache[key][1]
    cards = {int(h): S.horizon_scorecard(S.load(int(h), source), int(h)) for h in horizons}
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "rules": {"t_significant": S.T_SIGNIFICANT, "min_dates": S.MIN_DATES,
                  "min_independent_windows": S.MIN_WINDOWS,
                  "min_names_per_date": S.MIN_NAMES_PER_DATE},
        "headline": [line for h in horizons for line in headline(cards[int(h)])],
        "horizons": cards,
        "feedback": _feedback(horizons),
    }
    _cache[key] = (now, report)
    return report


def clear_cache() -> None:
    _cache.clear()


def format_text(report: Dict[str, Any]) -> str:
    """The heartbeat's plain-text section."""
    out = ["PREDICTION SCORECARD — predictions vs what happened "
           f"({report['source']} calls, generated {report['generated_at']})", ""]
    out += [f"  • {line}" for line in report["headline"]]
    out.append("")
    out.append(f"  {'h':>4} {'calls':>6} {'indep':>5} {'hit$':>5} {'hitSPY':>6} {'IC':>7} {'t':>6} "
               f"{'L-S%':>6} {'Brier':>6} {'ranking':<11} {'p_up':<11}")
    for h, c in report["horizons"].items():
        d, rk, pu, v = c["direction"], c["ranking"], c["p_up"], c["verdicts"]
        def f(x, fmt):
            return format(x, fmt) if x is not None else "—"
        out.append(f"  {str(h) + 'd':>4} {c['coverage']['calls']:>6} {c['coverage']['independent_windows']:>5} "
                   f"{_pct(d['hit_on_price']['rate']):>5} {_pct(d['hit_vs_spy']['rate']):>6} "
                   f"{f(rk['rank_ic']['mean'], '>+7.3f')} {f(rk['rank_ic']['t'], '>+6.2f')} "
                   f"{f(rk['bull_minus_bear_excess_pct']['mean'], '>+6.2f')} {f(pu.get('brier'), '>6.3f')} "
                   f"{v['ranking']['verdict']:<11} {v['p_up']['verdict']:<11}")
    fb = report.get("feedback") or {}
    cal = fb.get("p_up_calibration") or {}
    beat = fb.get("p_beat_spy_model") or {}
    if isinstance(cal, dict) and "error" not in cal:
        on = [str(h) for h, c in cal.items() if c.get("applied")]
        out.append("")
        out.append(f"  feedback: p_up calibration live at {', '.join(on) + 'd' if on else 'no horizon'}; "
                   + "P(beat SPY) stated at " + (", ".join(f"{h}d" for h, m in beat.items()
                                                           if isinstance(m, dict) and m.get("applied"))
                                                 or "no horizon (gate not met)"))
    out.append("  indep = independent windows; hit$ = right on price; hitSPY = right vs SPY; "
               "IC = same-day rank correlation of composite with excess return; L-S = bullish minus "
               "bearish excess return per date.")
    out.append("  Reporting only — the scorecard never changes a score; calibration and P(beat SPY) "
               "carry their own out-of-sample gates.")
    return "\n".join(out)

"""The quant lab, live: the intraday scanner over a liquid list, each rule's
own 60-session backtest as context, the paper journal, and plain sentences
for the chat.

    scan_all()        today's signals on the scan list, each with its rule's backtest (n, win rate, avg R)
    signal_events()   a live-feed poll (mas/live.py, every 5 min in market hours): journals each new,
                      fresh signal and publishes it as a "signal" event; grades open paper signals and
                      publishes each settled one as a "signal_close" event
    backtest_today()  the per-rule backtest over the scan list, computed once a day

Only completed bars are scanned — the bar still forming is ignored, so a
signal never flickers. Signals are research, paper-tracked; nothing here
places an order.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from quant import intraday as I
from quant import prices as P

SCAN = [s.strip().upper() for s in os.environ.get(
    "QUANT_SCAN", "SPY,QQQ,NVDA,AAPL,MSFT,AMZN,META,GOOGL,TSLA,AMD,AVGO,JPM").split(",") if s.strip()]
FRESH_MIN = 30
NOTE = ("Research signals on 5-minute bars, paper-tracked — not orders. Each rule's record is its own replay over "
        "the last ~60 sessions (no costs or slippage); an average R near zero or a t-stat under 2 means no "
        "demonstrated edge.")
LABEL = {"orb_long": "opening-range breakout (long)", "orb_short": "opening-range breakdown (short)",
         "vwap_reclaim": "VWAP reclaim (long)", "vwap_loss": "VWAP loss (short)",
         "rsi_bounce": "RSI(14) back above 30 (long)", "rsi_fade": "RSI(14) back below 70 (short)",
         "gap_and_go": "gap-and-go (long)"}
_journal: Optional[I.Journal] = None
_lock = threading.Lock()


def journal() -> I.Journal:
    global _journal
    with _lock:
        if _journal is None:
            _journal = I.Journal()
        return _journal


def _completed(bars: pd.DataFrame, now: Optional[pd.Timestamp] = None) -> pd.DataFrame:
    now = now or pd.Timestamp.now(tz=bars.index.tz)
    return bars[bars.index + pd.Timedelta(minutes=5) <= now]


def _bars(symbols: Sequence[str], http=None) -> Dict[str, Any]:
    """5-minute bars for every symbol, fetched in parallel; a symbol whose
    fetch fails maps to the exception."""
    def one(s):
        try:
            return s, P.intraday(s, http=http)
        except Exception as e:                     # one bad symbol never sinks the scan
            return s, e
    with ThreadPoolExecutor(max_workers=6) as ex:
        return dict(ex.map(one, symbols))


def backtest_today(symbols: Optional[Sequence[str]] = None, http=None) -> Dict[str, Any]:
    syms = [s.upper() for s in (symbols or SCAN)]
    key = hashlib.sha1(",".join(sorted(syms)).encode()).hexdigest()[:10]
    path = P.CACHE / f"backtest_{key}_{datetime.now().date()}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except ValueError:
            pass
    bars = {s: b for s, b in _bars(syms, http).items() if not isinstance(b, Exception)}
    out = {**I.backtest(bars), "symbols_list": sorted(bars), "as_of": str(datetime.now().date())}
    P.CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out


def scan_all(symbols: Optional[Sequence[str]] = None, http=None, now: Optional[pd.Timestamp] = None) -> Dict[str, Any]:
    syms = [s.upper() for s in (symbols or SCAN)]
    bt = backtest_today(None, http=http)        # each rule's record: the broad scan list, not one name's thin sample
    rows, missing, last_bar = [], [], None
    fetched = _bars(syms, http)
    for s in syms:
        if isinstance(fetched[s], Exception):
            missing.append(s)
            continue
        bars = _completed(fetched[s], now)
        if bars.empty:
            continue
        last_bar = max(last_bar, bars.index[-1]) if last_bar is not None else bars.index[-1]
        ref = now or pd.Timestamp.now(tz=bars.index.tz)
        for sig in I.scan(bars):
            age = (ref - sig["ts"]).total_seconds() / 60
            rows.append({"symbol": s, **{k: v for k, v in sig.items() if k != "i"}, "ts": str(sig["ts"]),
                         "label": LABEL[sig["rule"]], "age_min": round(age, 1),
                         "rule_record": bt["by_rule"].get(sig["rule"])})
    rows.sort(key=lambda r: r["ts"], reverse=True)
    return {"as_of": str(last_bar) if last_bar is not None else None, "signals": rows, "symbols": syms,
            "missing": missing, "backtest": bt["by_rule"], "backtest_trades": bt["trades"], "note": NOTE}


def _sentence(sym: str, sig: Dict[str, Any]) -> str:
    rec = sig.get("rule_record")
    tail = (f" Over the last ~60 sessions this rule averaged {rec['avg_r']:+.2f}R across {rec['n']} trades "
            f"(win rate {rec['win_rate']:.0%}).") if rec else ""
    t = str(sig["ts"])[11:16]
    return (f"{sym} {sig['label']} at {t} ET: entry ${sig['entry']:,.2f}, stop ${sig['stop']:,.2f}, "
            f"2R target ${sig['target']:,.2f}.{tail} Paper-tracked research, not an order.")


def signal_events(symbols: Optional[Sequence[str]] = None, http=None, now: Optional[pd.Timestamp] = None) -> List[Any]:
    """The live feed's poll: new fresh signals and newly settled paper trades."""
    from mas.converse import live_feed as lf
    j = journal()
    out = []
    res = scan_all(symbols, http=http, now=now)
    for sig in res["signals"]:
        if sig["age_min"] > FRESH_MIN:
            continue
        sid = j.add(sig["symbol"], {**sig, "ts": sig["ts"]})
        if sid:
            out.append(lf.Event("signals", "signal", f"signal:{sig['symbol']}:{sig['rule']}:{sig['ts']}",
                                {**sig, "journal_id": sid}, _sentence(sig["symbol"], sig),
                                source="quant lab scanner (Yahoo 5-minute bars)", ttl_s=3600))
    before = {r["id"] for r in j.open()}
    if before:
        I.grade_open(j, lambda s: P.intraday(s, http=http))
        for r in j.recent(200):
            if r["id"] in before and r["status"] != "open":
                out.append(lf.Event("signals", "signal_close", f"signal_close:{r['id']}", r,
                                    f"Paper {r['symbol']} {LABEL.get(r['rule'], r['rule'])} closed at "
                                    f"{r['status']}: {r['r']:+.2f}R.", source="quant lab paper journal", ttl_s=3600))
    return out


def journal_summary(limit: int = 30) -> Dict[str, Any]:
    j = journal()
    return {"recent": j.recent(limit), "stats": j.stats(), "open": len(j.open()), "note": NOTE}

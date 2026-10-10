"""quant/swing.py on hand-built daily bars (no network)."""
import numpy as np
import pandas as pd
import pytest

from quant import prices as P
from quant import swing as S


def _bars(closes, opens=None, highs=None, lows=None):
    idx = pd.bdate_range("2021-01-04", periods=len(closes))
    c = np.asarray(closes, float)
    o = np.asarray(opens if opens is not None else np.r_[c[0], c[:-1]], float)
    h = np.asarray(highs if highs is not None else np.maximum(o, c) + 0.5, float)
    lo = np.asarray(lows if lows is not None else np.minimum(o, c) - 0.5, float)
    return pd.DataFrame({"open": o, "high": h, "low": lo, "close": c, "adjclose": c, "volume": 1e6}, index=idx)


def _uptrend(n=260):
    return list(100 + np.arange(n) * 0.1 + np.where(np.arange(n) % 2, 0.3, -0.3))


def test_a_breakout_in_an_uptrend_fires_and_hits_its_target():
    closes = _uptrend() + [140.0] + [141.0] * 3 + [160.0] * 8
    d = S.indicators(_bars(closes))
    i = 260
    assert S.fires(d)["breakout_20"][i] and not S.fires(d)["breakout_20"][i - 1]
    t = S.trade(d, i, "breakout_20")
    assert t["exit"] == "target" and t["r"] == pytest.approx(2.0)


def test_a_gap_through_the_stop_fills_at_the_open_not_the_stop():
    closes = _uptrend() + [140.0, 141.0, 100.0] + [100.0] * 8
    opens = list(np.r_[closes[0], closes[:-1]])
    opens[262] = 100.0                                          # gaps far below the stop
    d = S.indicators(_bars(closes, opens=opens))
    t = S.trade(d, 260, "breakout_20")
    assert t["exit"] == "stop_gap" and t["r"] < -1.0


def test_rsi2_pullback_exits_on_the_first_close_above_the_5_day_average():
    closes = _uptrend() + [124.0, 122.5, 121.0, 130.0, 131.0]   # pullback that stays above the 200-day
    d = S.indicators(_bars(closes))
    i = 262
    assert S.fires(d)["rsi2_pullback"][i]
    t = S.trade(d, i, "rsi2_pullback")
    assert t["exit"] == "exit_rule" and t["exit_i"] == 263 and t["r"] > 0


def test_a_trade_still_open_at_the_end_is_not_counted():
    closes = _uptrend() + [140.0, 141.0]
    d = S.indicators(_bars(closes))
    assert S.trade(d, 260, "breakout_20") is None


def test_backtest_compares_each_rule_with_its_own_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "CACHE", tmp_path)
    rng = np.random.default_rng(3)
    frames = {}
    for k in range(4):
        r = rng.normal(0.0006, 0.015, 700)
        frames[f"S{k}"] = _bars(list(100 * np.cumprod(1 + r)))
    monkeypatch.setattr(S, "_daily", lambda syms, http=None: {s: frames[s] for s in syms if s in frames})
    bt = S.backtest(list(frames), use_cache=False)
    assert bt["symbols"] == 4 and bt["trades"] > 0 and bt["split_date"]
    for rule, v in bt["by_rule"].items():
        assert v["baseline"]["n"] > 0 and v["edge_vs_baseline"] == pytest.approx(v["avg_r"] - v["baseline"]["avg_r"], abs=1e-3)
        assert v["verdict"] in ("skill", "mixed", "no edge") and "first_half" in v and "edge_pct_per_trade" in v
        if v["verdict"] == "skill":
            assert v["beats_baseline_both_halves"] and v["t_stat"] >= 2
    assert "survivorship" in bt["note"]


def test_scan_reports_todays_signals_with_reference_levels(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "CACHE", tmp_path)
    df = _bars(_uptrend() + [140.0])
    monkeypatch.setattr(S, "_daily", lambda syms, http=None: {s: df for s in syms})
    out = S.scan(["ZZZ"])
    sig = [r for r in out["signals"] if r["rule"] == "breakout_20"][0]
    assert sig["symbol"] == "ZZZ" and sig["close"] == 140.0 and sig["stop_ref"] < 140 < sig["target_ref"]
    assert "next open" in out["note"]

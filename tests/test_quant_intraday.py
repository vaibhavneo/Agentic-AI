"""quant/intraday.py on hand-built 5-minute bars (no network)."""
import pandas as pd
import pytest

from quant import intraday as I

NY = "America/New_York"


def _day(date, closes, vols=None, opens=None, spread=0.05):
    idx = pd.date_range(f"{date} 09:30", periods=len(closes), freq="5min", tz=NY)
    opens = opens or [closes[0]] + closes[:-1]
    vols = vols or [1000] * len(closes)
    return pd.DataFrame({"open": opens, "high": [max(o, c) + spread for o, c in zip(opens, closes)],
                         "low": [min(o, c) - spread for o, c in zip(opens, closes)],
                         "close": closes, "volume": vols}, index=idx)


def _flat_days(n, px=100.0):
    days = pd.bdate_range("2026-09-01", periods=n)
    return [_day(d.date(), [px + (0.1 if i % 2 else -0.1) for i in range(78)]) for d in days], days


def _breakout_day(date, vol_on_break=3000):
    closes = [100.0, 100.4, 100.2, 99.8, 100.3, 100.1]         # opening range 99.75 .. 100.45
    closes += [100.2, 100.3, 101.0, 101.4, 101.8, 102.2]       # 10:00 bar holds, 10:10 breaks out
    closes += [102.0] * (78 - len(closes))
    vols = [1000] * 78
    vols[8] = vol_on_break
    return _day(date, closes, vols)


def test_opening_range_breakout_has_levels_from_the_range():
    history, days = _flat_days(8)
    bars = pd.concat(history + [_breakout_day(pd.Timestamp("2026-09-15").date())])
    sigs = {s["rule"]: s for s in I.scan(bars)}
    orb = sigs["orb_long"]
    assert str(orb["ts"].time()) == "10:10:00" and orb["entry"] == 101.0
    assert orb["stop"] == pytest.approx(99.75) and orb["target"] == pytest.approx(101.0 + 2 * 1.25)
    assert orb["rvol"] == 3.0


def test_breakout_on_ordinary_volume_is_not_a_signal():
    history, _ = _flat_days(8)
    bars = pd.concat(history + [_breakout_day(pd.Timestamp("2026-09-15").date(), vol_on_break=1000)])
    assert "orb_long" not in {s["rule"] for s in I.scan(bars)}


def test_gap_and_go_needs_a_two_percent_gap_holding_its_open():
    history, _ = _flat_days(6)
    gap = _day(pd.Timestamp("2026-09-15").date(), [103.0, 103.4, 103.8] + [104.0] * 75, opens=[102.8] + [103.0, 103.4, 103.8] + [104.0] * 74)
    sigs = {s["rule"]: s for s in I.scan(pd.concat(history + [gap]))}
    assert "gap_and_go" in sigs and sigs["gap_and_go"]["stop"] == pytest.approx(102.75)
    small = _day(pd.Timestamp("2026-09-15").date(), [101.0, 101.4, 101.8] + [102.0] * 75)
    assert "gap_and_go" not in {s["rule"] for s in I.scan(pd.concat(history + [small]))}


def test_grading_takes_the_stop_when_one_bar_touches_both():
    sig = {"entry": 100.0, "stop": 99.0, "target": 102.0, "side": "long"}
    later = _day("2026-09-15", [100.0, 100.5])
    later.iloc[1, later.columns.get_loc("high")] = 102.5
    later.iloc[1, later.columns.get_loc("low")] = 98.5
    assert I.grade(sig, later)["outcome"] == "stop" and I.grade(sig, later)["r"] == -1.0
    later = _day("2026-09-15", [100.5, 101.5])
    g = I.grade(sig, later)
    assert g["outcome"] == "close" and g["r"] == pytest.approx(1.5)
    short = {"entry": 100.0, "stop": 101.0, "target": 98.0, "side": "short"}
    assert I.grade(short, _day("2026-09-15", [99.0, 97.5]))["outcome"] == "target"


def test_backtest_grades_every_signal_in_r():
    history, _ = _flat_days(8)
    bars = pd.concat(history + [_breakout_day(pd.Timestamp("2026-09-15").date())])
    bt = I.backtest({"TEST": bars})
    orb = bt["by_rule"]["orb_long"]
    assert orb["n"] == 1 and orb["avg_r"] == pytest.approx((102.0 - 101.0) / 1.25, abs=1e-3)
    assert "no costs" in bt["note"]


def test_journal_dedupes_and_settles_at_the_next_session(tmp_path):
    j = I.Journal(tmp_path / "j.db")
    history, _ = _flat_days(8)
    day = _breakout_day(pd.Timestamp("2026-09-15").date())
    sig = [s for s in I.scan(pd.concat(history + [day])) if s["rule"] == "orb_long"][0]
    assert j.add("TEST", sig) and j.add("TEST", sig) is None
    # Still the same session: the trade stays open.
    assert I.grade_open(j, lambda s: pd.concat(history + [day])) == 0 and len(j.open()) == 1
    nxt = _day(pd.Timestamp("2026-09-16").date(), [102.0] * 78)
    assert I.grade_open(j, lambda s: pd.concat(history + [day, nxt])) == 1
    row = j.recent()[0]
    assert row["status"] == "close" and row["r"] == pytest.approx(0.8)
    assert j.stats()["orb_long"] == {"n": 1, "win_rate": 1.0, "avg_r": 0.8}

"""
The daily run's reliability: retries, ordering of the learning jobs, per-ticker
timing, sleep detection, and settings that no longer depend on an import's
side effects. Offline; the ledger-touching steps are stubbed.

Background (2026-10-04): runs that normally take 8-15 minutes took 2-3 hours.
macOS's power log showed the laptop asleep mid-run (lid closed at 14:31 on
10-02, finishing at 16:50 during maintenance wakes, four tickers failing). And
the self-improvement cycle was running on a background thread started by
importing web.app, concurrently with the day's calls.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import pytest


def _rec(ticker):
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    df = pd.DataFrame({"Close": [50.0 + i * 0.1 for i in range(300)]}, index=idx)
    return ({"ticker": ticker, "current_price": 79.9, "action": "HOLD", "composite": 61.0,
             "pillars": {"technical": {"score": 70, "confidence": 1.0},
                         "algo": {"score": 66, "confidence": 1.0},
                         "fundamentals": {"score": 58, "confidence": 0.8}},
             "levels": {"atr_14": 2.0}, "algo_signals": {"algo_score": 66}}, df)


@pytest.fixture
def hb(monkeypatch):
    import agents.heartbeat as hb
    monkeypatch.setattr(hb, "already_frozen", lambda t, d: False)
    monkeypatch.setattr(hb.pl, "freeze_prediction", lambda rec: "sid")
    return hb


def test_a_transient_failure_is_retried_and_recovered(hb):
    calls = {}

    def flaky(t):
        calls[t] = calls.get(t, 0) + 1
        if t == "XOM" and calls[t] == 1:
            raise RuntimeError("No data for ticker 'XOM'")
        return _rec(t)

    res = hb.run_daily(["MSFT", "XOM", "KO"], recommend_fn=flaky, grade=False, refit=False)
    assert res["errors"] == 0 and res["frozen"] == 3
    assert res["retried"] == 1 and res["recovered"] == 1
    xom = next(r for r in res["results"] if r["ticker"] == "XOM")
    assert xom["retry"] is True and xom["status"] == "done"
    assert calls == {"MSFT": 1, "XOM": 2, "KO": 1}         # only the failure is retried


def test_a_persistent_failure_is_reported_with_both_reasons(hb):
    def broken(t):
        raise RuntimeError("delisted")
    res = hb.run_daily(["ZZZZ"], recommend_fn=broken, grade=False, refit=False)
    assert res["errors"] == 1 and res["recovered"] == 0
    assert "delisted" in res["results"][0]["first_reason"]


def test_retry_can_be_turned_off(hb):
    def broken(t):
        raise RuntimeError("x")
    res = hb.run_daily(["ZZZZ"], recommend_fn=broken, grade=False, refit=False, retry_errors=False)
    assert res["errors"] == 1 and res["retried"] == 0


def test_learning_runs_after_grading_and_before_fitting_and_scoring(hb, monkeypatch):
    order = []
    monkeypatch.setattr(hb.pl, "refresh_outcomes", lambda ticker=None: (order.append("grade") or {"matured": 1}))
    import intelligence.calibration as cal
    monkeypatch.setattr(cal, "load_calibrators", lambda hs, source="all": (order.append("fit") or {}))

    def rec(t):
        order.append("score")
        return _rec(t)
    hb.run_daily(["MSFT"], recommend_fn=rec, after_grade=lambda: order.append("learn"))
    assert order.index("grade") < order.index("learn") < order.index("fit") < order.index("score")


def test_a_failing_learning_step_does_not_sink_the_run(hb):
    def boom():
        raise RuntimeError("loop exploded")
    res = hb.run_daily(["MSFT"], recommend_fn=_rec, grade=False, refit=False, after_grade=boom)
    assert res["frozen"] == 1
    assert "loop exploded" in res["after_grade"]["error"]


def test_every_result_carries_its_time_and_the_run_reports_sleep(hb, monkeypatch):
    class Clock:                     # wall clock runs 100x faster than monotonic: "asleep"
        def __init__(self):
            self.n = 0

        def time(self):
            self.n += 1
            return 1000.0 + 100.0 * self.n

        def monotonic(self):
            self.n += 1
            return 1.0 * self.n

        def sleep(self, s):
            pass
    monkeypatch.setattr(hb, "time", Clock())
    res = hb.run_daily(["MSFT", "KO"], recommend_fn=_rec, grade=False, refit=False)
    assert all("elapsed_s" in r for r in res["results"])
    assert res["asleep_s"] > 0


def test_awake_runs_report_no_sleep(hb):
    res = hb.run_daily(["MSFT"], recommend_fn=_rec, grade=False, refit=False)
    assert res["asleep_s"] < 1.0


# ── run_heartbeat: settings and job order ────────────────────────────────

def test_prepare_env_disables_the_side_effect_scheduler_and_loads_env(tmp_path, monkeypatch):
    import run_heartbeat as rh
    monkeypatch.delenv("MAINTENANCE_SCHEDULER", raising=False)
    monkeypatch.delenv("SELFIMPROVE_APPLY", raising=False)
    monkeypatch.setenv("ALREADY_SET", "from-shell")
    env = tmp_path / ".env"
    env.write_text("SELFIMPROVE_APPLY=1\nALREADY_SET=from-file\n# comment\n")
    rh.prepare_env(str(env))
    assert os.environ["MAINTENANCE_SCHEDULER"] == "0"
    assert os.environ["SELFIMPROVE_APPLY"] == "1"          # the loop applies, as before
    assert os.environ["ALREADY_SET"] == "from-shell"       # the shell wins over .env


def test_prepare_env_respects_an_explicit_scheduler_setting(tmp_path, monkeypatch):
    import run_heartbeat as rh
    monkeypatch.setenv("MAINTENANCE_SCHEDULER", "1")
    rh.prepare_env(str(tmp_path / "missing.env"))
    assert os.environ["MAINTENANCE_SCHEDULER"] == "1"


def test_upkeep_jobs_run_in_a_fixed_order_at_fixed_points(monkeypatch):
    import run_heartbeat as rh
    from data import maintenance as M
    seen = []
    monkeypatch.setattr(M, "run_job", lambda job, min_interval_sec=0.0, force=False:
                        (seen.append((job, min_interval_sec)) or {"job": job, "ran": True}))
    rh.pre_forecast_jobs()
    assert [j for j, _ in seen] == [M.GRADE_OUTCOMES, M.GRADE_OPTIONS, M.SELF_IMPROVE]
    assert all(i == 0.0 for _, i in seen)
    seen.clear()
    rh.post_forecast_jobs()
    assert seen == [(M.FILING_WATCH, M.JOB_INTERVALS[M.FILING_WATCH]),
                    (M.SCREENER_REFRESH, M.DEFAULT_INTERVAL_SEC)]


def test_the_scheduled_wrapper_keeps_the_machine_awake_and_the_thread_off():
    text = (Path(__file__).parent.parent / "cron_heartbeat.sh").read_text()
    assert "caffeinate -i -s" in text
    assert "MAINTENANCE_SCHEDULER=0 $CAFF" in text


def test_challengers_are_frozen_at_the_call_but_not_on_a_back_dated_run(hb, monkeypatch):
    import evaluation.challengers as ch
    seen = []
    monkeypatch.setattr(ch, "record_frozen", lambda sid, close: (seen.append((sid, len(close))) or 3))
    live = hb.forecast_and_freeze("MSFT", recommend_fn=_rec)
    assert live["challengers_frozen"] == 3 and seen == [("sid", 300)]
    back = hb.forecast_and_freeze("MSFT", recommend_fn=_rec, as_of="2025-03-03")
    assert back["challengers_frozen"] == 0 and len(seen) == 1

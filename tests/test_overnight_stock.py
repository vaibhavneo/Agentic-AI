"""Overnight 2026-10-07: watchlist coverage, concurrent-safe cache writes, the
wide replay's merge step."""
import json
import multiprocessing as mp
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# OptionsPilot's research universe (ranking.pipeline.DEFAULT_UNIVERSE, v6.0.0 — copied 2026-10-08). Its ideas need
# a fresh desk view per name, and the desk only calls what the heartbeat covers.
OPTIONSPILOT_UNIVERSE = {
    "AAPL", "AMZN", "AVGO", "BAC", "CAT", "COST", "CSCO", "CVX", "DIS", "GOOGL", "GS",
    "HD", "HON", "JNJ", "JPM", "KO", "LLY", "MCD", "META", "MSFT", "NEE", "NFLX",
    "NVDA", "ORCL", "PFE", "PG", "TSLA", "UNH", "UNP", "V", "XOM"}


def _watchlist():
    names = set()
    for line in (Path(__file__).resolve().parents[1] / "watchlist.txt").read_text().splitlines():
        names |= {t.strip().upper() for t in line.split("#", 1)[0].replace(",", " ").split() if t.strip()}
    return names


def test_the_daily_watchlist_covers_every_optionspilot_name():
    assert not (OPTIONSPILOT_UNIVERSE - _watchlist())


def _hammer(args):
    root, n = args
    os.environ["FIL_CACHE_DIR"] = root
    import importlib
    import financial_data.cache as C
    importlib.reload(C)
    for i in range(n):
        C.put("prov", "kind", "SAME", {"writer": os.getpid(), "i": i, "pad": "x" * 20000})
    return True


def test_concurrent_writers_never_leave_a_corrupt_cache_file(tmp_path):
    with mp.get_context("spawn").Pool(4) as pool:
        assert all(pool.map(_hammer, [(str(tmp_path), 25)] * 4))
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert not [p for p in files if p.name.endswith(".tmp")]           # no stray temp files
    import gzip
    for p in files:
        opener = gzip.open if p.suffix == ".gz" else open
        with opener(p, "rt") as fh:
            assert json.load(fh)["pad"] == "x" * 20000                    # parses, whole


def test_replay_merge_is_idempotent_and_keeps_snapshots_immutable(tmp_path, monkeypatch):
    import importlib
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import replay_wide as R
    monkeypatch.setattr(R, "WORK", tmp_path / "work")
    monkeypatch.setattr(R, "MERGED", tmp_path / "merged.db")
    (tmp_path / "work").mkdir()
    from data import prediction_ledger as pl
    prev = pl._db_override
    try:
        for k, tickers in enumerate((["MSFT"], ["KO"])):
            pl.set_db_path(tmp_path / "work" / f"w{k}.db")
            for t in tickers:
                pl.freeze_prediction({"ticker": t, "generated_at": "2020-03-02T00:00:00", "current_price": 10.0,
                                      "action": "BUY", "confidence": {}, "pillars": {}, "claims": {},
                                      "replay_run_id": f"wide-w{k}"})
        monkeypatch.setattr(R, "_isolate", lambda db: pl.set_db_path(db))
        first = R.merge()
        again = R.merge()
    finally:
        pl.set_db_path(prev)
    assert first == {"inserted": 2, "snapshots": 2}
    assert again == {"inserted": 0, "snapshots": 2}
    conn = sqlite3.connect(tmp_path / "merged.db")
    try:
        import pytest
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("UPDATE prediction_snapshots SET action='SELL'")
    finally:
        conn.close()

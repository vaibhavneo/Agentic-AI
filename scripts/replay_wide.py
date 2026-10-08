#!/usr/bin/env python3
"""
Wide point-in-time replay: the desk's deterministic call for every watchlist
name at every month-start over years, graded like live calls — so the
scorecard can reach verdicts the live ledger needs years to earn (a 20-day
horizon needs 20 non-overlapping windows; monthly replay gives ~100).

    python3 scripts/replay_wide.py                 # 6 workers, 2017-01 .. 2025-06, watchlist.txt
    python3 scripts/replay_wide.py --workers 4 --start 2019-01-01
    python3 scripts/replay_wide.py --finish-only   # merge + grade + score what is done

Kept OUT of the live ledger on purpose: it writes data/replay_wide.db.
Calibration and self-improvement learn from everything in the live ledger
(`source="all"`), so thousands of replay rows there would change tomorrow's live
calls before anyone has read the result. Whether replay evidence should feed
learning is a decision, not a side effect.

Each worker writes its OWN database (data/replay_wide/w<k>.db) — no lock
contention — and is resumable: a killed run picks up where it stopped (the run
id is fixed per worker and done cells are skipped). `finish` merges the
snapshots into one database, grades outcomes over full price history, rebuilds
the challenger scores point-in-time, and writes the replay scorecard to
docs/REPLAY_WIDE_RESULTS.md.

What a replay call is and is not: technical, algo and SEC point-in-time
fundamentals are rebuilt as of each date; social and research pillars cannot be
(no archive), so the composite is the deterministic core. The universe is
today's watchlist, so names that failed before 2025 are absent (survivorship;
the 2017 audit found it conservative for the quality screen).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORK = REPO / "data" / "replay_wide"
MERGED = REPO / "data" / "replay_wide.db"


def _tickers(path: Path) -> list:
    out, seen = [], set()
    for line in path.read_text().splitlines():
        for t in line.split("#", 1)[0].replace(",", " ").split():
            t = t.strip().upper()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
    return out


def _isolate(db: Path) -> None:
    """Point every store at `db` BEFORE anything imports data.store."""
    os.environ["STOCK_AGENT_DB_PATH"] = str(db)
    os.environ["MAINTENANCE_SCHEDULER"] = "0"
    sys.path.insert(0, str(REPO))


def worker(k: int, tickers: list, start: str, end: str, cadence: str) -> int:
    _isolate(WORK / f"w{k}.db")
    from agents.replay import run_replay
    done = [0]

    def progress(run):
        done[0] += 1
        if done[0] % 25 == 0:
            print(f"[w{k}] {run.get('done_items')}/{run.get('total_items')} cells", flush=True)
    r = run_replay({"run_id": f"wide-w{k}", "tickers": tickers, "start": start, "end": end,
                    "cadence": cadence}, progress_cb=progress, evaluate=False)
    print(f"[w{k}] finished: done={r['done']} skipped={r['skipped']} errors={r['errors']}", flush=True)
    return 0


def merge() -> dict:
    """Copy every worker's snapshots into the merged database. Content-addressed
    ids make this idempotent; the immutability triggers allow INSERT."""
    _isolate(MERGED)
    from data import prediction_ledger as pl
    pl._conn().close()                                 # schema + triggers
    conn = sqlite3.connect(MERGED, timeout=60)
    n = 0
    try:
        for f in sorted(WORK.glob("w*.db")):
            conn.execute("ATTACH DATABASE ? AS w", (str(f),))
            cols = [r[1] for r in conn.execute("PRAGMA w.table_info(prediction_snapshots)")]
            if cols:
                collist = ", ".join(cols)
                cur = conn.execute(f"INSERT OR IGNORE INTO prediction_snapshots ({collist}) "
                                   f"SELECT {collist} FROM w.prediction_snapshots")
                n += cur.rowcount
            conn.commit()
            conn.execute("DETACH DATABASE w")
        total = conn.execute("SELECT COUNT(*) FROM prediction_snapshots").fetchone()[0]
    finally:
        conn.close()
    return {"inserted": n, "snapshots": total}


def finish() -> dict:
    m = merge()
    print(f"[finish] merged: {m}", flush=True)
    from data import prediction_ledger as pl
    conn = pl._conn()
    tickers = [r[0] for r in conn.execute("SELECT DISTINCT ticker FROM prediction_snapshots")]
    conn.close()
    t0 = time.time()
    graded = 0
    for t in tickers:
        graded += (pl.refresh_outcomes(ticker=t) or {}).get("matured", 0)
    print(f"[finish] graded {graded} outcomes in {time.time() - t0:.0f}s", flush=True)
    from evaluation.challengers import reconstruct
    print(f"[finish] challengers: {reconstruct()}", flush=True)
    from evaluation.report import build, format_text
    rep = build((5, 20, 60, 126), "replay", use_cache=False)
    (REPO / "docs" / "REPLAY_WIDE_RESULTS.json").write_text(json.dumps(rep, indent=1, default=str))
    write_markdown(rep, m)
    print(format_text(rep), flush=True)
    return rep


def write_markdown(rep: dict, merged: dict) -> None:
    from evaluation.report import format_text
    lines = ["# Wide point-in-time replay — results", "",
             f"Generated {rep['generated_at']} by `scripts/replay_wide.py` from {merged['snapshots']:,} "
             "replayed calls (data/replay_wide.db, kept out of the live ledger).", "",
             "Replay calls rebuild technical, algo and SEC point-in-time fundamentals as of each "
             "month-start; social and research pillars cannot be rebuilt. Universe = today's watchlist "
             "(survivorship applies). Verdict rules are the scorecard's: |t| ≥ 2 across call dates "
             "and ≥ 20 independent windows.", "", "```", format_text(rep), "```", "",
             "## Desk vs simple models (replay)", ""]
    for h, card in rep["horizons"].items():
        lines.append(f"**{h}d**")
        lines.append("")
        lines.append("| model | rank IC | desk on same names | t (desk − model) | verdict |")
        lines.append("|---|---|---|---|---|")
        for name, c in (card.get("challengers") or {}).items():
            def f(v):
                return "—" if v is None else f"{v:+.3f}"
            lines.append(f"| {name} | {f(c['challenger_rank_ic']['mean'])} | "
                         f"{f(c['composite_rank_ic_same_names']['mean'])} | "
                         f"{c['composite_minus_challenger']['t'] if c['composite_minus_challenger']['t'] is not None else '—'} | "
                         f"{c['verdict']} |")
        p = card.get("paper") or {}
        if p.get("periods"):
            lines.append("")
            lines.append(f"Paper portfolio ({h}d, top third, {p['cost_bps_per_trade']} bps/trade): "
                         f"{p['long']['total_pct']:+.1f}% vs {p['universe']['total_pct']:+.1f}% for all names and "
                         f"{p['spy']['total_pct']:+.1f}% for SPY over {p['periods']} periods "
                         f"(t vs names {p['long_vs_universe']['t']}).")
        lines.append("")
    (REPO / "docs" / "REPLAY_WIDE_RESULTS.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--start", default="2017-01-01")
    ap.add_argument("--end", default="2025-06-30")
    ap.add_argument("--cadence", default="M")
    ap.add_argument("--tickers-file", default=str(REPO / "watchlist.txt"))
    ap.add_argument("--worker", type=int, help=argparse.SUPPRESS)
    ap.add_argument("--slice", help=argparse.SUPPRESS)
    ap.add_argument("--finish-only", action="store_true")
    a = ap.parse_args()

    if a.worker is not None:
        return worker(a.worker, a.slice.split(","), a.start, a.end, a.cadence)
    if a.finish_only:
        finish()
        return 0

    WORK.mkdir(parents=True, exist_ok=True)
    tickers = _tickers(Path(a.tickers_file))
    slices = [tickers[i::a.workers] for i in range(a.workers)]
    print(f"{len(tickers)} tickers × monthly {a.start}..{a.end} across {a.workers} workers", flush=True)
    procs = [subprocess.Popen([sys.executable, __file__, "--worker", str(k), "--slice", ",".join(s),
                               "--start", a.start, "--end", a.end, "--cadence", a.cadence])
             for k, s in enumerate(slices) if s]
    codes = [p.wait() for p in procs]
    print(f"workers exited {codes}", flush=True)
    finish()
    return 0 if all(c == 0 for c in codes) else 1


if __name__ == "__main__":
    sys.exit(main())

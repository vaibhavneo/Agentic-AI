"""
Coach service unit tests (M-P1a) — every trigger exercised with a FIRING and a
SILENT case over synthetic memory fixtures, plus accept/dismiss persistence
that survives a simulated restart. Deterministic; builds its own temp mission
space + concepts.json + aios.db, so it never touches real memory.

Run: python3 learn_agent/tests/test_coach_service.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent      # learn_agent/
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import coach_service as cs   # noqa: E402

FAILURES: list[str] = []
TODAY = date(2026, 7, 20)


def check(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}  {detail}")
    if not cond:
        FAILURES.append(name)


def _epoch(d: date) -> float:
    from datetime import datetime
    return datetime(d.year, d.month, d.day, 12, 0).timestamp()


def _mission(root: Path, mid, title, tasks, status="active", log_date=None):
    d = root / mid
    d.mkdir(parents=True, exist_ok=True)
    (d / "mission.json").write_text(json.dumps({
        "id": mid, "title": title, "type": "build", "goal": f"goal {mid}",
        "corpora": ["curated-wiki"], "cross_corpus": False,
        "status": status, "created": "2026-07-01"}))
    (d / "plan.md").write_text("# plan\n## Tasks\n" + "\n".join(
        f"- [{'x' if done else ' '}] {t}" for t, done in tasks) + "\n")
    (d / "questions.md").write_text("# open questions\n")
    log = d / "log.md"
    log.write_text("# log\n- seeded\n")
    if log_date:
        ts = _epoch(log_date)
        os.utime(log, (ts, ts))


def _concepts(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"concepts": {
        "Kelly Criterion": {   # low-confidence + gap (alpha task names it)
            "name": "Kelly Criterion", "confidence": 0.3, "principle": "sizing",
            "updated": "2026-07-20", "sources": [{"corpus": "finance", "source": "hilpisch.md"}],
            "verification": {"status": "unsupported", "flags": []}},
        "Solid Concept": {     # silent: high confidence, fresh
            "name": "Solid Concept", "confidence": 0.95, "principle": "x",
            "updated": "2026-07-20", "sources": [{"corpus": "curated-wiki", "source": "a.md"}],
            "verification": {"status": "supported", "flags": []}},
        "Old Idea": {          # retention-decay: high conf but stale timestamp
            "name": "Old Idea", "confidence": 0.85, "principle": "y",
            "updated": "2026-06-15", "sources": [{"corpus": "curated-wiki", "source": "b.md"}],
            "verification": {"status": "supported", "flags": []}},
        "Contradicted Thing": {  # contradiction: explicit flag
            "name": "Contradicted Thing", "confidence": 0.9, "principle": "z",
            "updated": "2026-07-20", "sources": [{"corpus": "curated-wiki", "source": "c.md"}],
            "verification": {"status": "supported", "flags": ["contradiction: sources disagree"]}},
    }}))


def _coach(tmp: Path, **kw) -> cs.Coach:
    missions = tmp / "missions"
    concepts = tmp / "concepts.json"
    _concepts(concepts)
    return cs.Coach(missions_dir=missions, concepts_path=concepts,
                    db_path=tmp / "aios.db",
                    retrieval_stats_path=tmp / "retrieval_stats.json",
                    today=TODAY, known_corpora={"finance", "curated-wiki"}, **kw)


def test_triggers_fire_and_stay_silent():
    print("=== 7 triggers: firing + silent cases ===")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        m = tmp / "missions"
        _mission(m, "alpha", "Alpha", [("implement kelly criterion sizing", False)],
                 log_date=date(2026, 7, 19))                 # fresh
        _mission(m, "beta", "Beta", [("done a", True), ("done b", True)],
                 log_date=date(2026, 7, 19))                 # all done → close
        _mission(m, "gamma", "Gamma", [("generic task", False)],
                 log_date=date(2026, 7, 5))                  # 15d → stale
        _mission(m, "zombie", "Zombie", [("x", False)], status="closed",
                 log_date=date(2026, 1, 1))                  # excluded
        coach = _coach(tmp)
        recs = coach.scan()
        fired = {r["trigger"] for r in recs}

        for trig in ["gap-blocks-task", "low-confidence-concept", "retention-decay",
                     "contradiction", "mission-ready-to-close", "stale-mission"]:
            check(f"fires: {trig}", trig in fired, str(sorted(fired)))
        check("every rec cites non-empty evidence",
              all(r["evidence"] for r in recs))
        check("every rec has a stable id + action",
              all(r["id"] and r["action"] for r in recs))
        # silent cases
        check("solid, fresh concept does NOT surface",
              not any("Solid Concept" in r["action"] for r in recs))
        check("closed mission excluded",
              not any(r.get("mission") == "zombie" for r in recs))
        check("gap fires only on the weak-concept mission (alpha, not gamma)",
              any(r["trigger"] == "gap-blocks-task" and r["mission"] == "alpha" for r in recs)
              and not any(r["trigger"] == "gap-blocks-task" and r["mission"] == "gamma" for r in recs))
        # low-confidence carries a corpus-scoped dispatch (P8/P9)
        lc = [r for r in recs if r["trigger"] == "low-confidence-concept"][0]
        check("low-confidence rec carries retrieve_context dispatch scoped to concept corpora",
              lc["dispatch"] and lc["dispatch"]["skill"] == "retrieve_context"
              and lc["dispatch"]["inputs"]["corpora"] == ["finance"], str(lc["dispatch"]))
        check("housekeeping trigger (stale) has no auto-dispatch",
              all(r["dispatch"] is None for r in recs if r["trigger"] == "stale-mission"))


def test_hot_unread_book_optional_source():
    print("=== hot-unread-book: silent without stats, fires with them ===")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _mission(tmp / "missions", "alpha", "Alpha", [("t", False)], log_date=date(2026, 7, 19))
        coach = _coach(tmp)
        check("silent when retrieval_stats.json absent",
              not any(r["trigger"] == "hot-unread-book" for r in coach.scan()))
        (tmp / "retrieval_stats.json").write_text(json.dumps({"sources": [
            {"corpus": "ai-books", "source": "hilpisch-ch10.md", "hits": 6, "read": False},
            {"corpus": "ai-books", "source": "already-read.md", "hits": 9, "read": True}]}))
        recs = [r for r in coach.scan() if r["trigger"] == "hot-unread-book"]
        check("fires only for the unread hot source",
              len(recs) == 1 and "hilpisch-ch10.md" in recs[0]["action"], str(recs))


def test_determinism():
    print("=== deterministic ids + ordering across scans ===")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _mission(tmp / "missions", "alpha", "Alpha",
                 [("implement kelly criterion sizing", False)], log_date=date(2026, 7, 5))
        coach = _coach(tmp)
        a = [(r["id"], r["trigger"]) for r in coach.scan()]
        b = [(r["id"], r["trigger"]) for r in coach.scan()]
        check("two scans identical (ids + order)", a == b, str(a))
        check("ranked: gap-blocks-task ahead of stale-mission",
              [t for _, t in a].index("gap-blocks-task")
              < [t for _, t in a].index("stale-mission"))


def test_accept_dismiss_persist_across_restart():
    print("=== accept/dismiss persist across a simulated restart ===")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        m = tmp / "missions"
        _mission(m, "gamma", "Gamma", [("generic task", False)], log_date=date(2026, 7, 5))
        _mission(m, "beta", "Beta", [("done", True)], log_date=date(2026, 7, 19))
        coach = _coach(tmp)
        recs = coach.recommendations()
        check("recommendations returns pending, capped", 0 < len(recs) <= cs.MAX_RECS)
        stale = next(r for r in recs if r["trigger"] == "stale-mission")
        close = next(r for r in recs if r["trigger"] == "mission-ready-to-close")

        coach.dismiss(stale["id"])
        coach.accept(close["id"])                      # no dispatch (housekeeping)

        # simulate a restart: brand-new Coach on the SAME db
        coach2 = _coach(tmp)
        ids2 = {r["id"] for r in coach2.recommendations()}
        check("dismissed id stays hidden after restart", stale["id"] not in ids2)
        check("accepted id stays hidden after restart", close["id"] not in ids2)

        acc = coach2._status_map()
        check("dismissed persisted in db", acc.get(stale["id"]) == "dismissed")
        check("accepted persisted in db", acc.get(close["id"]) == "accepted")

        # error paths
        for bad_call in (lambda: coach2.accept("deadbeef0000"),
                         lambda: coach2.dismiss("deadbeef0000")):
            try:
                bad_call()
                check("unknown id raises KeyError", False)
            except KeyError:
                check("unknown id raises KeyError", True)


def test_accept_returns_dispatch_shape():
    print("=== accept records status + reports dispatch outcome ===")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _mission(tmp / "missions", "gamma", "Gamma", [("generic task", False)],
                 log_date=date(2026, 7, 5))
        coach = _coach(tmp)
        stale = next(r for r in coach.recommendations() if r["trigger"] == "stale-mission")
        res = coach.accept(stale["id"])
        check("accept marks accepted", res["status"] == "accepted")
        check("housekeeping accept reports no dispatch", res["dispatched"] is False)


if __name__ == "__main__":
    test_triggers_fire_and_stay_silent()
    test_hot_unread_book_optional_source()
    test_determinism()
    test_accept_dismiss_persist_across_restart()
    test_accept_returns_dispatch_shape()
    print(f"\n{'=' * 60}")
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("ALL PASS — coach triggers fire/stay-silent by contract; "
          "accept/dismiss persist")

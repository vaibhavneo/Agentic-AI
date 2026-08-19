"""Per-reader topic mastery — Milestone 5's actual feature.

SQLite-backed (stdlib, no new dependency), same connection pattern as
stock_agent/data/store.py — timeout=10 + check_same_thread=False because
Flask's threaded=True means concurrent requests can hit this from
different threads; row_factory=Row for dict-like access; schema applied on
every connect via CREATE TABLE IF NOT EXISTS, which is idempotent and
needs no separate migration step.

Two tables:
  exposure       — append-only log, one row per topic per answer that
                   touched it, direct (match_topics() judged it relevant)
                   or prereq (surfaced as background by
                   curriculum.prerequisite_gaps()). This is written
                   automatically by pipeline.run() after every real
                   answer — never a separate client action, so it can't be
                   silently skipped.
  manual_status  — one row per topic the reader has explicitly marked,
                   the one genuine write this milestone exposes through a
                   POST endpoint (/api/mastery/mark).

This is intentionally NOT a general "user" or "session" system — this app
has exactly one reader, no login, no multi-tenant concept anywhere else in
the codebase, and inventing one here would be scope this milestone doesn't
need.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# ai_brain/memory/ — one level, not two. ai_brain/ already has its own
# memory/ subdirectory (research_notebook.json lives there), and the
# Dockerfile explicitly prepares /app/memory (writable by the non-root
# `brain` user) for exactly this purpose — its own comment says "the app
# writes nothing outside memory/". A first cut of this path used
# .parent.parent, which happens to land in the *monorepo's* top-level
# memory/ when run locally from inside this checkout (silently "worked"
# there) but resolves to unwritable "/" inside the container, where the
# Docker build context is ai_brain/ alone and there is no monorepo
# structure above it at all. Caught by smoke_deployment.py against the
# real deployed instance — /api/ask crashed right after "understand", the
# exact stage 2b first calls mastery.known_topic_ids().
_DB_PATH = Path(__file__).parent / "memory" / "mastery.db"

_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS exposure (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id       TEXT    NOT NULL,
    ts             TEXT    NOT NULL,
    exposure_type  TEXT    NOT NULL,      -- 'direct' | 'prereq'
    depth          TEXT,
    verdict        TEXT
);

CREATE TABLE IF NOT EXISTS manual_status (
    topic_id    TEXT PRIMARY KEY,
    status      TEXT    NOT NULL,          -- 'known' | 'review'
    updated_at  TEXT    NOT NULL
);
"""

# A prerequisite the reader has been directly asked about (and answered
# about — evidence_engine/professor_engine actually engaged with it) this
# many times no longer needs to keep showing up as "background you might
# not know" every time a topic that depends on it comes up.
KNOWN_AFTER_DIRECT_COUNT = 3


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def record_exposure(topic_ids, exposure_type: str, depth: str = "", verdict: str = "") -> None:
    """One row per topic_id. exposure_type is 'direct' or 'prereq'."""
    if not topic_ids:
        return
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = _connect()
    try:
        conn.executemany(
            "INSERT INTO exposure (topic_id, ts, exposure_type, depth, verdict) "
            "VALUES (?, ?, ?, ?, ?)",
            [(tid, ts, exposure_type, depth, verdict) for tid in topic_ids])
        conn.commit()
    finally:
        conn.close()


def mastery_summary() -> list[dict]:
    """Per topic that has ever been exposed or manually marked: counts,
    last-seen timestamp, and any manual status."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT topic_id, "
            "  COUNT(*) AS exposure_count, "
            "  SUM(CASE WHEN exposure_type = 'direct' THEN 1 ELSE 0 END) AS direct_count, "
            "  SUM(CASE WHEN exposure_type = 'prereq' THEN 1 ELSE 0 END) AS prereq_count, "
            "  MAX(ts) AS last_seen "
            "FROM exposure GROUP BY topic_id").fetchall()
        by_topic = {r["topic_id"]: dict(r) for r in rows}
        for r in conn.execute("SELECT topic_id, status FROM manual_status").fetchall():
            by_topic.setdefault(r["topic_id"], {
                "topic_id": r["topic_id"], "exposure_count": 0,
                "direct_count": 0, "prereq_count": 0, "last_seen": None})
            by_topic[r["topic_id"]]["manual_status"] = r["status"]
        for rec in by_topic.values():
            rec.setdefault("manual_status", None)
        return sorted(by_topic.values(), key=lambda r: -(r["exposure_count"] or 0))
    finally:
        conn.close()


def mark_topic(topic_id: str, status: str | None) -> dict:
    """status is 'known', 'review', or None to clear a prior mark."""
    conn = _connect()
    try:
        if status is None:
            conn.execute("DELETE FROM manual_status WHERE topic_id = ?", (topic_id,))
        else:
            conn.execute(
                "INSERT INTO manual_status (topic_id, status, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(topic_id) DO UPDATE SET status = excluded.status, "
                "updated_at = excluded.updated_at",
                (topic_id, status, datetime.now(timezone.utc).isoformat(timespec="seconds")))
        conn.commit()
        row = conn.execute("SELECT topic_id, status, updated_at FROM manual_status WHERE topic_id = ?",
                           (topic_id,)).fetchone()
        return dict(row) if row else {"topic_id": topic_id, "status": None, "updated_at": None}
    finally:
        conn.close()


def known_topic_ids(min_direct_count: int = KNOWN_AFTER_DIRECT_COUNT) -> set[str]:
    """Topics prerequisite_gaps() should stop surfacing as background: either
    manually marked known, or directly engaged with often enough that
    re-explaining "you might not know this" would be patronizing rather
    than useful."""
    conn = _connect()
    try:
        known = {r["topic_id"] for r in
                conn.execute("SELECT topic_id FROM manual_status WHERE status = 'known'").fetchall()}
        known |= {r["topic_id"] for r in conn.execute(
            "SELECT topic_id FROM exposure WHERE exposure_type = 'direct' "
            "GROUP BY topic_id HAVING COUNT(*) >= ?", (min_direct_count,)).fetchall()}
        return known
    finally:
        conn.close()

"""SQLite connection + migration runner.

Local-first: one file on disk (app.config.DB_PATH), no server process.
All queries elsewhere in the codebase MUST be parameterized (`?` placeholders) —
never string-format user input into SQL.
"""
from __future__ import annotations

import os
import sqlite3
import threading

from app import config

_local = threading.local()


def get_connection() -> sqlite3.Connection:
    """One connection per thread (Flask's dev server is threaded)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        _local.conn = conn
    return conn


def close_connection(_exception=None) -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def _applied_migrations(conn: sqlite3.Connection) -> set[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  filename TEXT PRIMARY KEY,"
        "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
        ")"
    )
    rows = conn.execute("SELECT filename FROM schema_migrations").fetchall()
    return {row["filename"] for row in rows}


def run_migrations(conn: sqlite3.Connection | None = None) -> list[str]:
    """Applies every .sql file in migrations/ that hasn't been applied yet, in
    filename order. Each migration runs in its own transaction. Returns the
    list of newly-applied filenames."""
    owns_conn = conn is None
    conn = conn or get_connection()
    applied = _applied_migrations(conn)
    newly_applied = []

    migration_files = sorted(
        f for f in os.listdir(config.MIGRATIONS_DIR) if f.endswith(".sql")
    )
    for filename in migration_files:
        if filename in applied:
            continue
        path = os.path.join(config.MIGRATIONS_DIR, filename)
        with open(path, "r") as f:
            sql = f.read()
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_migrations (filename) VALUES (?)", (filename,)
        )
        conn.commit()
        newly_applied.append(filename)

    if owns_conn:
        pass  # connection is cached on the thread-local; caller doesn't own it
    return newly_applied


def init_db() -> None:
    run_migrations()

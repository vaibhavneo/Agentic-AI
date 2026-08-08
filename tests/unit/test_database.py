from database.db import get_connection, run_migrations


def test_migrations_are_idempotent():
    first = run_migrations()
    second = run_migrations()
    assert second == []  # nothing re-applied


def test_expected_tables_exist():
    conn = get_connection()
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {r["name"] for r in rows}
    assert {"profiles", "medications", "medication_logs", "safety_events"} <= names


def test_foreign_keys_enforced():
    conn = get_connection()
    fk_status = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk_status == 1

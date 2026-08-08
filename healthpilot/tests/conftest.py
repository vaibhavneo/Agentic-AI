import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch, tmp_path):
    """Every test gets its own throwaway SQLite file + a fresh connection,
    so tests never see each other's data and never touch the real dev DB."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("HEALTHPILOT_DB_PATH", str(db_path))

    from app import config
    monkeypatch.setattr(config, "DB_PATH", str(db_path))

    from database import db as db_module
    db_module._local = type(db_module._local)()  # fresh thread-local, drops any cached connection

    db_module.init_db()
    yield
    db_module.close_connection()

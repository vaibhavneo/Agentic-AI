"""Central config loaded from environment / .env. No secrets hard-coded here."""
from __future__ import annotations

import os

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

DB_PATH = os.environ.get("HEALTHPILOT_DB_PATH", os.path.join(BASE_DIR, "data", "healthpilot.db"))
MIGRATIONS_DIR = os.path.join(BASE_DIR, "migrations")

PORT = int(os.environ.get("HEALTHPILOT_PORT", "3000"))
SECRET_KEY = os.environ.get("HEALTHPILOT_SECRET_KEY", "dev-only-insecure-key-set-HEALTHPILOT_SECRET_KEY")

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

USDA_FDC_API_KEY = os.environ.get("USDA_FDC_API_KEY", "")

EXPORT_DIR = os.path.join(BASE_DIR, "data", "exports")
IMPORT_DIR = os.path.join(BASE_DIR, "data", "imports")


def ai_configured() -> bool:
    return bool(DEEPSEEK_API_KEY or ANTHROPIC_API_KEY)

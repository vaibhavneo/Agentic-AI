"""
JSON-file-backed Chart Bundle persistence. One file per chart_id, so two
profiles can never mix - reading one profile's file cannot leak data from
another. chart_id is always a fixed-format hash string (see chart_bundle.
make_chart_id), and this module additionally rejects any chart_id
containing a path separator or "..", blocking path traversal.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

CHARTS_DIR = Path(__file__).parent / "data" / "charts"


def _ensure_dir() -> None:
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)


def _safe_path(chart_id: str) -> Optional[Path]:
    if not chart_id or not isinstance(chart_id, str):
        return None
    if "/" in chart_id or "\\" in chart_id or ".." in chart_id:
        return None
    if not chart_id.startswith("chart_"):
        return None
    return CHARTS_DIR / f"{chart_id}.json"


def save_chart(bundle: dict) -> None:
    _ensure_dir()
    path = _safe_path(bundle["chart_id"])
    if path is None:
        raise ValueError("invalid chart_id")
    path.write_text(json.dumps(bundle, indent=2))


def load_chart(chart_id: str) -> Optional[dict]:
    path = _safe_path(chart_id)
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def list_charts() -> list[dict]:
    _ensure_dir()
    out = []
    for f in sorted(CHARTS_DIR.glob("chart_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text())
            out.append({
                "chart_id": data.get("chart_id"),
                "profile_name": data.get("profile_name"),
                "created_at": data.get("created_at"),
                "birth_data": data.get("birth_data"),
            })
        except (json.JSONDecodeError, OSError):
            continue
    return out

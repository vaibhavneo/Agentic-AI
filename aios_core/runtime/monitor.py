"""
Skill Runtime — Observability.
Memory snapshots (change detection) + execution metrics appended to
brain/runtime/metrics.jsonl (one JSON line per dispatch, success or failure).
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

METRICS_PATH = Path(__file__).parent / "metrics.jsonl"


def snapshot(root: Path | None) -> dict[str, str]:
    """path → sha1, for every file under root."""
    if root is None or not root.exists():
        return {}
    out = {}
    for f in sorted(root.rglob("*")):
        if f.is_file():
            out[str(f.relative_to(root))] = hashlib.sha1(f.read_bytes()).hexdigest()
    return out


def diff(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Relative paths created, modified, or deleted."""
    changed = [p for p in after if before.get(p) != after[p]]
    deleted = [p for p in before if p not in after]
    return sorted(changed + deleted)


class Timer:
    def __enter__(self):
        self.t0 = time.time()
        return self

    def __exit__(self, *_):
        self.elapsed_ms = round((time.time() - self.t0) * 1000, 1)


def record(skill_id: str, version: str, ok: bool, elapsed_ms: float,
           memory_changes: list[str], artifacts: list[str],
           confidence: float | None = None, failure: str | None = None,
           attempts: int = 1) -> dict:
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "skill": skill_id, "version": version, "ok": ok,
        "elapsed_ms": elapsed_ms,
        "attempts": attempts,
        "retries": max(0, attempts - 1),
        "confidence": confidence,
        "memory_changes": memory_changes,
        "artifacts": artifacts,
        "failure": failure,
    }
    with open(METRICS_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry

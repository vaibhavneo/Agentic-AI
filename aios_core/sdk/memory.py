"""
AIOS Core SDK — Memory API (stable).

Notebook-first memory (PROJECT_CHARTER.md P1): files are the only durable
memory. This API gives safe read access, change detection (sha1 snapshot/diff),
compliance auditing, and execution-metrics access — without letting a caller
bypass the runtime's write-permission enforcement (writes still happen through
skill dispatch, whose memory contract the dispatcher enforces).

    from aios_core import memory
    text = memory.read(root, "state.md")
    audit = memory.audit(root)          # compliance (file bounds, one-line log)
    recent = memory.recent_metrics(20)
"""
from __future__ import annotations

import json
from pathlib import Path

from ..runtime import monitor
from ..runtime.dispatcher import dispatch

__all__ = ["read", "list_files", "snapshot", "diff", "audit",
           "metrics_path", "recent_metrics"]


def read(root, name: str) -> str:
    """Read one memory file. Traversal-safe (basename only). Raises FileNotFoundError."""
    p = Path(root) / Path(name).name
    if not p.exists():
        raise FileNotFoundError(f"{p.name} not in {root}")
    return p.read_text()


def list_files(root, pattern: str = "*.md") -> list[str]:
    root = Path(root)
    return sorted(f.name for f in root.glob(pattern)) if root.exists() else []


def snapshot(root) -> dict[str, str]:
    """{relpath: sha1} for every file under root (change-detection primitive)."""
    return monitor.snapshot(Path(root) if root else None)


def diff(before: dict, after: dict) -> list[str]:
    return monitor.diff(before, after)


def audit(root, max_lines: int = 200) -> dict:
    """Run the memory_compression compliance audit over a memory root
    (file-size bounds, one-line log entries, separation of concerns).
    Read-only — dispatched as a skill so permissions are enforced."""
    r = dispatch("memory_compression", {"memory_root": str(root), "max_lines": max_lines})
    if not r.ok:
        return {"compliant": False, "error": r.failure, "detail": r.failure_detail}
    return r.output


def metrics_path() -> Path:
    return monitor.METRICS_PATH


def recent_metrics(n: int = 30) -> list[dict]:
    p = monitor.METRICS_PATH
    if not p.exists():
        return []
    lines = p.read_text().strip().splitlines()[-n:]
    return [json.loads(x) for x in lines]

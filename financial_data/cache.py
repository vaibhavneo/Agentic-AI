"""
FIL — local response cache.

Purpose is not speed but courtesy and reproducibility: SEC asks for <10 req/sec
and a backtest sweeping 500 names would otherwise hammer them on every re-run.

Cache holds RAW provider payloads (pre-normalization), so a schema fix in a
provider takes effect on the next parse without re-downloading. Everything here
is rebuildable and gitignored — never source of truth (P2).

Design note: JSON, not parquet. The plan named parquet, but that needs pyarrow,
and this repo is stdlib-first — a new heavyweight dependency to store a few MB
of filings is a bad trade. Recorded as a deliberate deviation in FIL.md rather
than silently swapped.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

# FIL_CACHE_DIR moves the cache off the repo checkout — on Railway, onto the
# persistent volume, so a deploy stops throwing away every SEC fetch. Entries
# there are gzip-compressed (FIL_CACHE_COMPRESS, on by default whenever the
# directory is overridden): SEC company-facts files run ~5 MB as JSON and the
# volume is 500 MB. The in-repo cache stays plain JSON, as the tracked
# snapshots and tests expect.
CACHE_DIR = Path(os.environ["FIL_CACHE_DIR"]) if os.environ.get("FIL_CACHE_DIR") else Path(__file__).parent / ".cache"
COMPRESS = os.environ.get("FIL_CACHE_COMPRESS", "1" if os.environ.get("FIL_CACHE_DIR") else "0") == "1"

_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def _safe(part: str) -> str:
    """Filesystem-safe key segment. Symbols like `BRK.B` and `^GSPC` are real,
    and must not escape the cache dir or collide."""
    return _SAFE.sub("_", str(part))[:64] or "_"


def path_for(provider: str, kind: str, key: str) -> Path:
    return CACHE_DIR / _safe(provider) / _safe(kind) / f"{_safe(key)}.json"


def get(provider: str, kind: str, key: str, max_age_sec: Optional[int] = None) -> Optional[Any]:
    """Return the cached payload, or None on miss/stale/corrupt.

    A corrupt cache file returns None rather than raising: the cache is an
    optimization, and a bad file should cost a re-fetch, never an outage.
    """
    p = path_for(provider, kind, key)
    gz = p.with_name(p.name + ".gz")
    if gz.exists() and (not p.exists() or gz.stat().st_mtime >= p.stat().st_mtime):
        p = gz
    if not p.exists():
        return None
    if max_age_sec is not None and (time.time() - p.stat().st_mtime) > max_age_sec:
        return None
    try:
        if p.suffix == ".gz":
            import gzip
            with gzip.open(p, "rt") as fh:
                return json.load(fh)
        with p.open() as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError, EOFError):
        return None


def put(provider: str, kind: str, key: str, payload: Any) -> Path:
    """Write atomically — a backtest interrupted mid-write must not leave a
    truncated file that poisons the next run."""
    p = path_for(provider, kind, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    if COMPRESS:
        import gzip
        p = p.with_name(p.name + ".gz")
        tmp = p.with_suffix(".tmp")
        with gzip.open(tmp, "wt") as fh:
            json.dump(payload, fh)
    else:
        tmp = p.with_suffix(".tmp")
        with tmp.open("w") as fh:
            json.dump(payload, fh)
    os.replace(tmp, p)
    return p


def clear(provider: Optional[str] = None) -> int:
    """Delete cached files; returns the count removed. Safe by construction —
    the cache is rebuildable."""
    root = CACHE_DIR / _safe(provider) if provider else CACHE_DIR
    if not root.exists():
        return 0
    n = 0
    for pattern in ("*.json", "*.json.gz"):
        for f in root.rglob(pattern):
            f.unlink()
            n += 1
    return n

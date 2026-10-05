#!/usr/bin/env python3
"""
Persistence for a free Hugging Face Space: the Space's disk is wiped on every
restart and rebuild, so the app's data lives in a PRIVATE Hugging Face dataset
and this sidecar keeps the two in step.

    restore   before the app starts: download every persisted file that is not
              already on disk (a fresh container has none).
    loop      every HF_PERSIST_INTERVAL seconds (default 120), and once more on SIGTERM:
              upload whatever changed. SQLite files are copied with SQLite's
              online backup API, so the upload is a consistent database even
              while the app is writing; -wal/-shm/-journal files are never sent.

Environment (set by the deploy tool):
    HF_PERSIST_REPO      <user>/<app>-data   (a private dataset; persistence is
                                              off when unset)
    HF_TOKEN             a token with write access to that dataset
    HF_PERSIST_PATHS     comma-separated files or directories, relative to the
                         working directory
    HF_PERSIST_INTERVAL  seconds between syncs (default 120)

THE ONE RULE THAT MATTERS: never upload until a restore has succeeded. If the
restore fails (network down at boot), the app starts on an empty database, and
uploading that would overwrite the real backup with nothing. Uploads stay off,
and the loop keeps retrying the restore until it works.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import signal
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

SKIP_SUFFIXES = ("-wal", "-shm", "-journal")
SQLITE_SUFFIXES = (".db", ".sqlite", ".sqlite3")
STATE_DIR = Path(os.environ.get("HF_PERSIST_STATE", "/tmp/hf_persist"))
RESTORED_MARKER = STATE_DIR / "restored"
SQUASH_EVERY = 100          # commits; keeps the dataset's history from growing without bound


def log(msg: str) -> None:
    print(f"[persist] {msg}", flush=True)


def config() -> Optional[Dict]:
    repo = os.environ.get("HF_PERSIST_REPO", "").strip()
    token = os.environ.get("HF_TOKEN", "").strip()
    paths = [p.strip().strip("/") for p in os.environ.get("HF_PERSIST_PATHS", "").split(",") if p.strip()]
    if not (repo and token and paths):
        return None
    return {"repo": repo, "token": token, "paths": paths,
            "interval": float(os.environ.get("HF_PERSIST_INTERVAL", "120"))}


def _api(cfg):
    from huggingface_hub import HfApi
    return HfApi(token=cfg["token"])


def _covered(name: str, paths: List[str]) -> bool:
    return any(name == p or name.startswith(p + "/") for p in paths)


def restore(cfg: Dict, api=None, root: Path = Path(".")) -> Dict:
    """Download every persisted file missing locally. Raises on failure — the
    caller must NOT mark the restore done unless this returns."""
    api = api or _api(cfg)
    from huggingface_hub import hf_hub_download
    files = [f for f in api.list_repo_files(cfg["repo"], repo_type="dataset")
             if _covered(f, cfg["paths"]) and not f.endswith(SKIP_SUFFIXES)]
    got = 0
    for name in files:
        dest = root / name
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = hf_hub_download(cfg["repo"], name, repo_type="dataset", token=cfg["token"],
                              local_dir=str(STATE_DIR / "download"))
        shutil.move(src, dest)
        got += 1
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    RESTORED_MARKER.write_text(str(time.time()))
    return {"files_in_backup": len(files), "restored": got}


def _local_files(paths: List[str], root: Path) -> List[Path]:
    out = []
    for p in paths:
        full = root / p
        if full.is_file():
            out.append(full)
        elif full.is_dir():
            out += [f for f in sorted(full.rglob("*")) if f.is_file()]
    return [f for f in out if not f.name.endswith(SKIP_SUFFIXES)]


def _snapshot(path: Path, tmpdir: Path) -> Path:
    """A consistent copy: SQLite's backup API for databases, bytes otherwise."""
    if path.suffix in SQLITE_SUFFIXES:
        dst = tmpdir / (hashlib.sha1(str(path).encode()).hexdigest() + path.suffix)
        src = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
        try:
            out = sqlite3.connect(dst)
            try:
                src.backup(out)
            finally:
                out.close()
        finally:
            src.close()
        return dst
    return path


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Syncer:
    def __init__(self, cfg: Dict, api=None, root: Path = Path(".")):
        self.cfg, self.api, self.root = cfg, api or _api(cfg), root
        self.sent: Dict[str, str] = {}
        self.commits = 0
        self.lock = threading.Lock()

    def sync(self) -> Dict:
        """Upload what changed since the last sync. Refuses before a restore."""
        if not RESTORED_MARKER.exists():
            return {"uploaded": 0, "refused": "no successful restore yet"}
        from huggingface_hub import CommitOperationAdd
        with self.lock, tempfile.TemporaryDirectory() as td:
            ops, digests = [], {}
            for f in _local_files(self.cfg["paths"], self.root):
                rel = f.relative_to(self.root).as_posix()
                try:
                    snap = _snapshot(f, Path(td))
                except sqlite3.Error as e:
                    log(f"skip {rel}: {e}")
                    continue
                d = _digest(snap)
                if self.sent.get(rel) == d:
                    continue
                ops.append(CommitOperationAdd(path_in_repo=rel, path_or_fileobj=str(snap)))
                digests[rel] = d
            if not ops:
                return {"uploaded": 0}
            self.api.create_commit(self.cfg["repo"], repo_type="dataset", operations=ops,
                                   commit_message=f"sync {len(ops)} file(s)")
            self.sent.update(digests)
            self.commits += 1
            if self.commits % SQUASH_EVERY == 0:
                try:
                    self.api.super_squash_history(self.cfg["repo"], repo_type="dataset")
                except Exception as e:                # optional housekeeping
                    log(f"history squash skipped: {e}")
            return {"uploaded": len(ops), "files": sorted(digests)}

    def prime(self) -> None:
        """After a restore, the local files ARE the backup: record their
        digests so the first sync does not re-upload them unchanged."""
        with tempfile.TemporaryDirectory() as td:
            for f in _local_files(self.cfg["paths"], self.root):
                try:
                    self.sent[f.relative_to(self.root).as_posix()] = _digest(_snapshot(f, Path(td)))
                except sqlite3.Error:
                    pass


def try_restore(cfg: Dict, api=None, root: Path = Path(".")) -> bool:
    try:
        r = restore(cfg, api=api, root=root)
        log(f"restored {r['restored']} of {r['files_in_backup']} file(s) from {cfg['repo']}")
        return True
    except Exception as e:
        log(f"restore failed ({type(e).__name__}: {str(e)[:160]}); uploads stay off until it succeeds")
        return False


def loop(cfg: Dict, api=None, root: Path = Path("."), once: bool = False) -> None:
    syncer = Syncer(cfg, api=api, root=root)
    if RESTORED_MARKER.exists():
        syncer.prime()
    stop = threading.Event()

    def final(*_):
        try:
            r = syncer.sync()
            log(f"final sync: {r}")
        finally:
            stop.set()
            sys.exit(0)
    if not once:
        signal.signal(signal.SIGTERM, final)
    while not stop.is_set():
        if not RESTORED_MARKER.exists() and try_restore(cfg, api=api, root=root):
            syncer.prime()
        try:
            r = syncer.sync()
            if r.get("uploaded"):
                log(f"uploaded {r['uploaded']} file(s): {', '.join(r['files'])}")
        except Exception as e:
            log(f"sync failed ({type(e).__name__}: {str(e)[:160]}); will retry")
        if once:
            return
        stop.wait(cfg["interval"])


def main(argv: List[str]) -> int:
    cfg = config()
    if cfg is None:
        log("persistence off (HF_PERSIST_REPO, HF_TOKEN or HF_PERSIST_PATHS not set)")
        return 0
    cmd = argv[1] if len(argv) > 1 else "loop"
    if cmd == "restore":
        return 0 if try_restore(cfg) else 1
    if cmd == "loop":
        loop(cfg)
        return 0
    if cmd == "sync-once":
        loop(cfg, once=True)
        return 0
    log(f"unknown command {cmd!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

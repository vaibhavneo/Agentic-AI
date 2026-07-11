"""
Corpus Manager (AIOS P0.1) — multiple independent knowledge corpora.
Source of truth: memory/corpora/registry.json (files-first, decision D8/D9).
SQLite only ever mirrors stats; this module is the API.

See learn_agent/AIOS_ARCHITECTURE.md §6.5.2.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
CORPORA_DIR = ROOT / "memory" / "corpora"
REGISTRY_PATH = CORPORA_DIR / "registry.json"


def load_registry() -> dict:
    if REGISTRY_PATH.exists():
        return json.loads(REGISTRY_PATH.read_text())
    return {"registry_version": "1.0.0", "corpora": {}}


def save_registry(reg: dict) -> None:
    CORPORA_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(reg, indent=1, ensure_ascii=False))


def register(corpus: dict) -> dict:
    """corpus = {id, name, description, source_dirs[], ingest_profile?,
    reliability?, tags?}. index_path is derived, never caller-supplied."""
    required = {"id", "name", "description", "source_dirs"}
    missing = required - set(corpus)
    if missing:
        raise ValueError(f"corpus missing fields: {sorted(missing)}")
    reg = load_registry()
    cid = corpus["id"]
    corpus.setdefault("ingest_profile", {"extensions": [".md", ".txt"], "chunk_size": 1200})
    corpus.setdefault("reliability", 1.0)
    corpus.setdefault("tags", [])
    corpus["index_path"] = str(CORPORA_DIR / cid / "chunks.json")
    existing_stats = reg["corpora"].get(cid, {}).get("stats")
    corpus["stats"] = existing_stats or {"files": 0, "chunks": 0, "last_ingested": None}
    reg["corpora"][cid] = corpus
    save_registry(reg)
    return corpus


def get(corpus_id: str) -> dict:
    reg = load_registry()
    if corpus_id not in reg["corpora"]:
        raise KeyError(f"unknown corpus: {corpus_id}")
    return reg["corpora"][corpus_id]


def list_corpora() -> list[dict]:
    return list(load_registry()["corpora"].values())


def ingest_corpus(corpus_id: str) -> dict:
    """(Re)build one corpus's index from its source_dirs."""
    from second_brain.ingest import ingest
    c = get(corpus_id)
    prof = c["ingest_profile"]
    total_files, total_chunks = 0, 0
    all_chunks = []
    src_used = []
    for src in c["source_dirs"]:
        r = ingest(src, tuple(prof["extensions"]),
                   index_path=c["index_path"], chunk_size=prof["chunk_size"])
        if "error" in r:
            continue
        # multi-source corpora: merge (ingest overwrote; re-read and accumulate)
        data = json.loads(Path(c["index_path"]).read_text())
        for ch in data["chunks"]:
            ch["source"] = f"{Path(src).name}/{ch['source']}"
        all_chunks.extend(data["chunks"])
        total_files += r["files"]
        src_used.append(src)
    Path(c["index_path"]).parent.mkdir(parents=True, exist_ok=True)
    Path(c["index_path"]).write_text(json.dumps(
        {"source_dir": ";".join(src_used), "n_files": total_files,
         "chunks": all_chunks}, ensure_ascii=False))
    total_chunks = len(all_chunks)

    reg = load_registry()
    reg["corpora"][corpus_id]["stats"] = {
        "files": total_files, "chunks": total_chunks,
        "last_ingested": datetime.now().isoformat(timespec="seconds")}
    save_registry(reg)
    return {"corpus": corpus_id, "files": total_files, "chunks": total_chunks}


def adopt_index(corpus_id: str, existing_index: str | Path) -> dict:
    """Adopt an already-built chunks.json as this corpus's index (no re-chunk)."""
    c = get(corpus_id)
    data = json.loads(Path(existing_index).expanduser().read_text())
    dest = Path(c["index_path"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, ensure_ascii=False))
    reg = load_registry()
    reg["corpora"][corpus_id]["stats"] = {
        "files": data.get("n_files", 0), "chunks": len(data.get("chunks", [])),
        "last_ingested": datetime.now().isoformat(timespec="seconds")}
    save_registry(reg)
    return reg["corpora"][corpus_id]["stats"]

"""
Second Brain — Structured Concept Memory (replaces flat knowledge_cache.md
as source of truth; the markdown becomes a rendered VIEW).

Store: memory/concepts.json
Each concept:
  {
    "name": str,                # unique key
    "principle": str,
    "when_to_use": str,
    "sources": [str],           # claimed source files / provenance
    "confidence": float | None, # 0-1, assigned by critic.py (None = unverified)
    "verification": {           # written by critic.py
        "status": "supported" | "partial" | "unsupported" | "unverified",
        "evidence": [ {"source": str, "score": float} ],
        "flags": [str],
    },
    "relationships": [ {"to": str, "type": str} ],   # e.g. type: "complements", "depends-on"
    "created": str, "updated": str
  }
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
STORE = ROOT / "memory" / "concepts.json"
CACHE_MD = ROOT / "memory" / "knowledge_cache.md"


def load() -> dict:
    if STORE.exists():
        return json.loads(STORE.read_text())
    return {"concepts": {}}


def save(data: dict) -> None:
    STORE.write_text(json.dumps(data, indent=1, ensure_ascii=False))


def upsert(concept: dict) -> None:
    data = load()
    name = concept["name"]
    today = date.today().isoformat()
    existing = data["concepts"].get(name, {})
    concept.setdefault("confidence", existing.get("confidence"))
    concept.setdefault("verification", existing.get("verification",
                       {"status": "unverified", "evidence": [], "flags": []}))
    concept.setdefault("relationships", existing.get("relationships", []))
    concept["created"] = existing.get("created", today)
    concept["updated"] = today
    data["concepts"][name] = concept
    save(data)


def link(name_a: str, name_b: str, rel_type: str = "complements") -> bool:
    """Add a directed relationship a → b (and store nothing if either missing)."""
    data = load()
    if name_a not in data["concepts"] or name_b not in data["concepts"]:
        return False
    rels = data["concepts"][name_a]["relationships"]
    if not any(r["to"] == name_b and r["type"] == rel_type for r in rels):
        rels.append({"to": name_b, "type": rel_type})
        save(data)
    return True


def migrate_from_markdown(md_path: Path = CACHE_MD) -> int:
    """One-time migration: parse the flat knowledge_cache.md into the store."""
    text = md_path.read_text()
    blocks = re.split(r"^## ", text, flags=re.M)[1:]
    n = 0
    for b in blocks:
        lines = b.strip().splitlines()
        name = lines[0].strip()
        body = "\n".join(lines[1:])
        principle = _field(body, "Principle")
        when = _field(body, "When to use")
        sources = [s.strip() for s in _field(body, "Sources").split(",") if s.strip()]
        if not principle:
            continue
        upsert({"name": name, "principle": principle,
                "when_to_use": when, "sources": sources})
        n += 1
    return n


def render_markdown() -> str:
    """Regenerate knowledge_cache.md as a VIEW of the store (with confidence)."""
    data = load()
    lines = [
        "# knowledge_cache.md — Distilled Mental Models (RENDERED VIEW)",
        "<!-- SOURCE OF TRUTH: memory/concepts.json — edit via concept_store.py, not here. -->",
        "",
    ]
    for name, c in data["concepts"].items():
        conf = c.get("confidence")
        status = c.get("verification", {}).get("status", "unverified")
        badge = f"{conf:.2f} ({status})" if conf is not None else "unverified"
        lines.append(f"## {name}")
        lines.append(f"**Confidence:** {badge}")
        lines.append(f"**Principle:** {c['principle']}")
        lines.append(f"**When to use:** {c['when_to_use']}")
        srcs = ", ".join(f"{s['corpus']}:{s['source']}" if isinstance(s, dict) else s
                         for s in c["sources"])
        lines.append(f"**Sources:** {srcs}")
        rels = c.get("relationships", [])
        if rels:
            lines.append("**Related:** " + "; ".join(f"{r['type']} → {r['to']}" for r in rels))
        flags = c.get("verification", {}).get("flags", [])
        if flags:
            lines.append("**Flags:** " + "; ".join(flags))
        lines.append("")
    out = "\n".join(lines)
    CACHE_MD.write_text(out)
    return out


def _field(body: str, label: str) -> str:
    m = re.search(rf"\*\*{label}:\*\*\s*(.+)", body)
    return m.group(1).strip() if m else ""


if __name__ == "__main__":
    n = migrate_from_markdown()
    print(f"migrated {n} concepts → {STORE}")

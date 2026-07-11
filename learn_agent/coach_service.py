"""
learn_agent/coach_service.py — M-P1a Coach service.

The system initiates: seven DETERMINISTIC trigger scanners run over files the
platform already owns (mission plan.md/log.md, memory/concepts.json) and emit
ranked, evidence-cited recommendations. Accept/dismiss is persisted in a
`recommendations` table inside the existing aios.db — a rebuildable index, not
a source of truth (PROJECT_CHARTER.md P2; architecture §6.3). Every scanner is
a pure function of injected inputs so it is unit-testable with fixtures.

Boundaries (PROJECT_CHARTER.md P3/P6/P8/P10):
  - triggers live here, never in a route (P10 thin surfaces);
  - every recommendation cites file/concept/corpus evidence — no unsourced
    claims (P3/P6);
  - accepting a recommendation DISPATCHES through the runtime (`skill.run`),
    never a hand-rolled action — reasoning/retrieval is reused, not
    reimplemented (P8);
  - ranking is deterministic; an optional LLM re-rank is explicitly out of
    scope for the floor version (triggers are floors, not ceilings).

This SUPERSEDES the labeled 3-rule proto-coach that shipped in
mission_control_service.py (D16); that module now delegates here.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aios_core import mission as _mission, skill as _skill   # noqa: E402

DEFAULT_STALE_DAYS = 5        # a mission untouched this long surfaces
DEFAULT_RETENTION_DAYS = 14   # a concept untouched this long → retention check
LOW_CONFIDENCE = 0.6          # concepts.json confidence floor
MAX_RECS = 5                  # cap (playbook risk mitigation: cap + dedupe)

# Priority order (lower = surfaced first): unblock real work over housekeeping.
_RANK = {"gap-blocks-task": 0, "mission-ready-to-close": 1,
         "low-confidence-concept": 2, "retention-decay": 3,
         "stale-mission": 4, "hot-unread-book": 5, "contradiction": 6}

_REC_SCHEMA = """
CREATE TABLE IF NOT EXISTS recommendations(
  id TEXT PRIMARY KEY, ts TEXT, trigger TEXT, action_json TEXT,
  evidence TEXT, status TEXT);
"""


def _rid(trigger: str, key: str) -> str:
    """Deterministic id: the same (trigger, target) always hashes the same, so
    a dismissed suggestion stays dismissed across restarts and re-scans."""
    return hashlib.sha1(f"{trigger}|{key}".encode()).hexdigest()[:12]


class Coach:
    """Trigger scanners + accept/dismiss persistence. Locations are injectable
    (mirrors MissionStore) so tests drive it with synthetic fixtures."""

    def __init__(self, missions_dir=None, concepts_path=None, db_path=None,
                 retrieval_stats_path=None, today=None,
                 stale_days=DEFAULT_STALE_DAYS,
                 retention_days=DEFAULT_RETENTION_DAYS, low_conf=LOW_CONFIDENCE,
                 known_corpora=None):
        self.store = (_mission.MissionStore(missions_dir=missions_dir)
                      if missions_dir else _mission.default_store)
        self.concepts_path = Path(concepts_path) if concepts_path else \
            ROOT / "memory" / "concepts.json"
        self.db_path = Path(db_path) if db_path else self.store.db_path
        self.retrieval_stats_path = Path(retrieval_stats_path) if retrieval_stats_path \
            else ROOT / "memory" / "retrieval_stats.json"
        self.today = today or date.today()
        self.stale_days = stale_days
        self.retention_days = retention_days
        self.low_conf = low_conf
        self._known = set(known_corpora) if known_corpora is not None else None

    # ── data access (files the SDK/pipeline already own) ─────────────────────
    def _missions(self) -> list[dict]:
        return self.store.list_all()

    def _concepts(self) -> dict:
        if not self.concepts_path.exists():
            return {}
        return json.loads(self.concepts_path.read_text()).get("concepts", {})

    def _db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(_REC_SCHEMA)
        return conn

    def _days_since(self, iso: str | None) -> int | None:
        if not iso:
            return None
        try:
            return (self.today - date.fromisoformat(iso[:10])).days
        except ValueError:
            return None

    @staticmethod
    def _corpora_of(concept: dict) -> list[str]:
        return sorted({s["corpus"] for s in concept.get("sources", [])
                       if s.get("corpus")})

    def _registered_corpora(self) -> set:
        """Ids of corpora the gateway can actually retrieve from. Cached per
        instance; injectable for tests. Reads only the corpus registry, not
        any index."""
        if self._known is None:
            from aios_core import retrieval as _retrieval
            self._known = {c["id"] for c in _retrieval.list_corpora()}
        return self._known

    def _verify_dispatch(self, name: str, concept: dict) -> dict | None:
        """A safe, read-only dispatch that gathers evidence for a concept via
        the retrieve_context skill — scoped to the concept's OWN source corpora
        that are actually registered (P9: scope is never guessed; provenance
        labels like 'workspace' are not retrievable corpora). None when nothing
        retrievable remains."""
        corpora = [c for c in self._corpora_of(concept)
                   if c in self._registered_corpora()]
        if not corpora:
            return None
        return {"skill": "retrieve_context",
                "inputs": {"query": name[:200], "corpora": corpora, "top_k": 5}}

    def _rec(self, trigger, key, mission, title, action, evidence, dispatch=None):
        return {"id": _rid(trigger, key), "trigger": trigger, "mission": mission,
                "mission_title": title, "action": action, "evidence": evidence,
                "rank": _RANK.get(trigger, 9), "dispatch": dispatch}

    # ── the seven triggers (each: pure over files, cites evidence) ───────────
    def t_gap_blocks_task(self) -> list[dict]:
        """A mission's next unchecked task names a concept that is not solid
        (missing or below the confidence floor) — the gap blocks the task."""
        out = []
        concepts = self._concepts()
        weak = {n: c for n, c in concepts.items()
                if (c.get("confidence") or 0) < self.low_conf}
        for m in self._missions():
            if m.get("status") != "active":
                continue
            nxt = next((t for t in m.get("tasks", []) if not t["done"]), None)
            if not nxt:
                continue
            desc = nxt["description"].lower()
            for n, c in weak.items():
                words = [w for w in re.split(r"[^a-z0-9]+", n.lower()) if len(w) > 3]
                if words and any(w in desc for w in words):
                    out.append(self._rec(
                        "gap-blocks-task", f"{m['id']}:{n}", m["id"], m["title"],
                        f"Shore up '{n}' — blocks task: {nxt['description']}",
                        f"plan.md task #{nxt['id']} in {m['id']}; concept '{n}' "
                        f"confidence {c.get('confidence')} < {self.low_conf}",
                        self._verify_dispatch(n, c)))
                    break
        return out

    def t_low_confidence(self) -> list[dict]:
        out = []
        for n, c in self._concepts().items():
            conf = c.get("confidence")
            if conf is None or conf >= self.low_conf:
                continue
            status = c.get("verification", {}).get("status", "unverified")
            out.append(self._rec(
                "low-confidence-concept", n, None, None,
                f"Verify or gather evidence for concept: {n}",
                f"concepts.json '{n}' confidence {conf} < {self.low_conf} "
                f"(status {status})", self._verify_dispatch(n, c)))
        return out

    def t_stale_mission(self) -> list[dict]:
        out = []
        for m in self._missions():
            if m.get("status") != "active":
                continue
            log_f = self.store.missions_dir / m["id"] / "log.md"
            if log_f.exists():
                age = (self.today
                       - datetime.fromtimestamp(log_f.stat().st_mtime).date()).days
                basis = "log.md last modified"
            else:
                age = self._days_since(m.get("created"))
                basis = "created"
            if age is not None and age >= self.stale_days:
                out.append(self._rec(
                    "stale-mission", m["id"], m["id"], m["title"],
                    f"Resume or explicitly pause '{m['title']}' — untouched {age}d",
                    f"{basis} {age}d ago (>= {self.stale_days}d)"))
        return out

    def t_hot_unread_book(self) -> list[dict]:
        """Fires on sources retrieved often but not yet read/ingested. Consumes
        an OPTIONAL memory/retrieval_stats.json (per-source hit counts). The
        gateway does not yet emit that file — recorded as a gap; this trigger
        is forward-compatible and simply yields nothing until it exists,
        rather than fabricating a signal (P7)."""
        p = self.retrieval_stats_path
        if not p.exists():
            return []
        try:
            stats = json.loads(p.read_text())
        except (ValueError, OSError):
            return []
        out = []
        for e in stats.get("sources", []):
            if e.get("hits", 0) >= e.get("hot_threshold", 5) and not e.get("read"):
                out.append(self._rec(
                    "hot-unread-book", f"{e.get('corpus')}:{e.get('source')}",
                    None, None,
                    f"Read/ingest hot source: {e.get('source')} "
                    f"({e['hits']} retrieval hits)",
                    f"retrieval_stats.json: {e.get('corpus')}/{e.get('source')} "
                    f"hit {e['hits']}x, unread"))
        return out

    def t_retention_decay(self) -> list[dict]:
        out = []
        for n, c in self._concepts().items():
            age = self._days_since(c.get("updated"))
            if age is not None and age >= self.retention_days:
                out.append(self._rec(
                    "retention-decay", n, None, None,
                    f"Retention check: revisit '{n}' (untouched {age}d)",
                    f"concepts.json '{n}' updated {age}d ago "
                    f"(>= {self.retention_days}d)", self._verify_dispatch(n, c)))
        return out

    def t_contradiction(self) -> list[dict]:
        """Deferred detector (playbook M-P1a: "defer the detector; stub the
        trigger"). Fires ONLY on a concept explicitly flagged 'contradiction';
        no paired-evidence detector exists yet (recorded gap). Never invents a
        contradiction."""
        out = []
        for n, c in self._concepts().items():
            flags = c.get("verification", {}).get("flags", [])
            if any("contradict" in str(f).lower() for f in flags):
                out.append(self._rec(
                    "contradiction", n, None, None,
                    f"Resolve contradiction on '{n}'",
                    f"concepts.json '{n}' carries a contradiction flag"))
        return out

    def t_ready_to_close(self) -> list[dict]:
        out = []
        for m in self._missions():
            if m.get("status") != "active":
                continue
            tasks = m.get("tasks", [])
            if tasks and all(t["done"] for t in tasks):
                out.append(self._rec(
                    "mission-ready-to-close", m["id"], m["id"], m["title"],
                    f"Close '{m['title']}' — all tasks done; write lessons-learned",
                    f"plan.md: {len(tasks)}/{len(tasks)} tasks checked "
                    f"(progress {m.get('progress')}%)"))
        return out

    # ── scan / rank (pure — no persistence) ──────────────────────────────────
    def scan(self) -> list[dict]:
        recs = []
        for trigger in (self.t_gap_blocks_task, self.t_low_confidence,
                        self.t_stale_mission, self.t_hot_unread_book,
                        self.t_retention_decay, self.t_contradiction,
                        self.t_ready_to_close):
            recs.extend(trigger())
        best = {}                       # dedupe by action, keep highest priority
        for r in recs:
            k = r["action"]
            if k not in best or r["rank"] < best[k]["rank"]:
                best[k] = r
        return sorted(best.values(), key=lambda r: (r["rank"], r["id"]))

    # ── persistence-backed API (accept/dismiss) ──────────────────────────────
    def _status_map(self) -> dict:
        conn = self._db()
        rows = {r["id"]: r["status"]
                for r in conn.execute("SELECT id, status FROM recommendations")}
        conn.close()
        return rows

    def _upsert_pending(self, recs) -> None:
        conn = self._db()
        ts = datetime.now().isoformat(timespec="seconds")
        for r in recs:
            conn.execute(
                "INSERT OR IGNORE INTO recommendations"
                "(id, ts, trigger, action_json, evidence, status) VALUES(?,?,?,?,?,?)",
                (r["id"], ts, r["trigger"], json.dumps(r), r["evidence"], "pending"))
        conn.commit()
        conn.close()

    def recommendations(self, persist: bool = True, limit: int = MAX_RECS) -> list[dict]:
        """Ranked, capped, dismissal-aware recommendations. Persists newly-seen
        ones as 'pending'; hides anything already accepted or dismissed."""
        status = self._status_map()
        visible = [r for r in self.scan()
                   if status.get(r["id"]) not in ("dismissed", "accepted")]
        if persist:
            self._upsert_pending(visible)
        for r in visible:
            r["status"] = "pending"
        return visible[:limit]

    def _set_status(self, rec_id: str, status: str) -> dict:
        self.recommendations(persist=True)          # ensure the id exists
        conn = self._db()
        cur = conn.execute("UPDATE recommendations SET status=? WHERE id=?",
                            (status, rec_id))
        conn.commit()
        changed = cur.rowcount
        conn.close()
        if not changed:
            raise KeyError(f"unknown recommendation: {rec_id}")
        return {"id": rec_id, "status": status}

    def dismiss(self, rec_id: str) -> dict:
        return self._set_status(rec_id, "dismissed")

    def accept(self, rec_id: str, context: dict | None = None) -> dict:
        """Mark accepted and DISPATCH the underlying action through the runtime
        when the recommendation carries a dispatch descriptor (evidence-
        gathering via retrieve_context). Housekeeping triggers with no safe
        auto-action are simply recorded as accepted."""
        self.recommendations(persist=True)
        conn = self._db()
        row = conn.execute(
            "SELECT action_json FROM recommendations WHERE id=?", (rec_id,)).fetchone()
        if row is None:
            conn.close()
            raise KeyError(f"unknown recommendation: {rec_id}")
        rec = json.loads(row["action_json"])
        conn.execute("UPDATE recommendations SET status='accepted' WHERE id=?", (rec_id,))
        conn.commit()
        conn.close()
        result = {"id": rec_id, "status": "accepted",
                  "trigger": rec["trigger"], "dispatched": False}
        disp = rec.get("dispatch")
        if disp:
            try:
                d = _skill.run(disp["skill"], disp["inputs"], context).to_dict()
                out = d.get("output") or {}
                result.update(dispatched=True, dispatch_ok=d["ok"],
                              dispatch_skill=disp["skill"],
                              dispatch_summary=(f"{out.get('n', '?')} hits"
                                                if d["ok"] else d.get("failure")))
            except Exception as e:                       # never let a dispatch 500 the accept
                result.update(dispatched=True, dispatch_ok=False,
                              dispatch_error=str(e))
        return result


# Module-level default coach (real locations) + thin functions.
default_coach = Coach()


def scan():
    return default_coach.scan()


def recommendations(persist: bool = True, limit: int = MAX_RECS):
    return default_coach.recommendations(persist, limit)


def accept(rec_id: str, context: dict | None = None):
    return default_coach.accept(rec_id, context)


def dismiss(rec_id: str):
    return default_coach.dismiss(rec_id)

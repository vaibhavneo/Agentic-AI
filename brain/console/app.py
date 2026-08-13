"""
AI Brain — Operator Console (port 5052)
Thin HTTP layer over EXISTING APIs only: runtime dispatcher/registry/monitor,
second_brain pipeline, and the memory files. No backend logic lives here —
every endpoint is a wrapper around an existing call.
"""
from __future__ import annotations

import json
import threading
import sys
from pathlib import Path

BRAIN = Path(__file__).parent.parent
ROOT = BRAIN.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify, request, send_from_directory

# Depend ONLY on the AIOS Core public SDK (PROJECT_CHARTER.md P10, req #3).
from aios_core import skill, workflow, memory, mission as mission_sdk
from aios_core.runtime.registry import Registry   # discovery (health panel)
from second_brain import corpus_manager

# The teacher skill's ONE model seam. Reused, not reimplemented (the app's
# LLM adapter lives in learn_agent — brain/console must not fork it). Called
# as `teacher_adapter.make_llm_adapter()` (not imported by name) so tests can
# monkeypatch the module attribute the same way learn_agent's own tests do.
from learn_agent import teacher_adapter
import teach_session as ts

def dispatch(sid, inputs, context=None):
    return skill.run(sid, inputs, context)

METRICS_PATH = memory.metrics_path()

MEMORY = ROOT / "memory"
UPLOADS = MEMORY / "uploads"
WIKI_BOOKS = Path("~/Documents/brain/Vaibhav's Second Brain/wiki/books").expanduser()
SESSIONS_PATH = MEMORY / "teacher_sessions.json"
DEFAULT_CORPUS = "ai-books"              # the actual book library (25.8k chunks);
                                          # curated-wiki (96 chunks, hand-written notes)
                                          # was a misleading default — most questions
                                          # aren't in scope for it. /api/search below
                                          # keeps curated-wiki deliberately (debug tool).

app = Flask(__name__, static_folder="static")

# Planner runs are long-lived → the SDK's canonical background runner
# (no more hand-rolled thread+dict; req #4 eliminate duplicated runtime logic).
_planner_job = workflow.BackgroundRun()
_planner_goal = {"goal": None}


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ── Dashboard / health ─────────────────────────────────────────────────────
@app.route("/api/health")
def health():
    reg = Registry()
    idx = MEMORY / "index" / "chunks.json"
    concepts = MEMORY / "concepts.json"
    out = {
        "skills_registered": len(reg.list_ids()),
        "index": None, "concepts": None,
        "memory_files": sorted(f.name for f in MEMORY.glob("*.md")),
        "last_metric": None,
        "planner_running": _planner_job.running,
    }
    if idx.exists():
        d = json.loads(idx.read_text())
        out["index"] = {"files": d.get("n_files"), "chunks": len(d.get("chunks", [])),
                        "source_dir": d.get("source_dir")}
    if concepts.exists():
        c = json.loads(concepts.read_text())["concepts"]
        out["concepts"] = {"n": len(c),
                           "unverified_or_unsupported": sum(
                               1 for v in c.values()
                               if v.get("verification", {}).get("status") not in ("supported", "partial"))}
    if METRICS_PATH.exists():
        lines = METRICS_PATH.read_text().strip().splitlines()
        if lines:
            out["last_metric"] = json.loads(lines[-1])
    return jsonify(out)


# ── Upload + ingestion ─────────────────────────────────────────────────────
@app.route("/api/upload", methods=["POST"])
def upload():
    UPLOADS.mkdir(parents=True, exist_ok=True)
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "no file"}), 400
    name = Path(f.filename).name          # strip any path components
    if not name.endswith((".md", ".txt")):
        return jsonify({"error": "only .md/.txt supported by book_ingestion"}), 400
    (UPLOADS / name).write_bytes(f.read())
    return jsonify({"saved": name, "uploads": sorted(p.name for p in UPLOADS.iterdir())})


@app.route("/api/ingest", methods=["POST"])
def ingest():
    data = request.json or {}
    corpus_id = data.get("corpus_id")
    if corpus_id:
        # Rebuild a registered corpus (memory/corpora/<id>/chunks.json) straight
        # from its source_dirs — the self-service fix for exactly the failure
        # mode that broke this console once already: a corpus's index file
        # ends up corrupted or missing (e.g. an un-pulled Git LFS pointer sitting
        # where the real chunks.json belongs) while the source library on disk
        # is still intact. No need to touch git or wait on an operator.
        r = dispatch("book_ingestion", {"corpus_id": corpus_id})
        if not r.ok:
            return jsonify({"error": r.failure, "detail": r.failure_detail}), 500
        return jsonify({"note": f"corpus '{corpus_id}' rebuilt from its source_dirs",
                        **r.output, "metrics": r.metrics})
    source = data.get("source", "wiki")
    src_dir = str(UPLOADS) if source == "uploads" else str(WIKI_BOOKS)
    r = dispatch("book_ingestion", {"source_dir": src_dir})
    if not r.ok:
        return jsonify({"error": r.failure, "detail": r.failure_detail}), 500
    return jsonify({"note": "index rebuilt from source (backend semantics: one index)",
                    **r.output, "metrics": r.metrics})


@app.route("/api/corpora")
def corpora_status():
    """Per-corpus health — surfaces a corpus whose registry stats claim chunks
    but whose index file is missing/corrupted (the failure mode that silently
    broke every out-of-scope Ask query until it was diagnosed and rebuilt)."""
    out = []
    for c in corpus_manager.list_corpora():
        idx = Path(c["index_path"])
        stats = c.get("stats", {})
        status = "ok"
        if not idx.exists():
            status = "missing_index"
        elif stats.get("chunks", 0) == 0:
            status = "never_ingested"
        else:
            try:
                d = json.loads(idx.read_text())
                if len(d.get("chunks", [])) == 0:
                    status = "empty_index"
            except (json.JSONDecodeError, UnicodeDecodeError):
                status = "corrupted_index"  # e.g. an un-pulled Git LFS pointer stub
        out.append({"id": c["id"], "name": c.get("name", c["id"]),
                    "status": status, "stats": stats})
    return jsonify({"corpora": out})


# ── Search / retrieval ─────────────────────────────────────────────────────
@app.route("/api/search")
def search():
    q = request.args.get("q", "").strip()
    if len(q) < 3:
        return jsonify({"error": "query too short"}), 400
    r = dispatch("retrieve_context", {"query": q, "corpora": ["curated-wiki"]})   # operator override (gateway scope)
    if not r.ok:
        return jsonify({"error": r.failure, "detail": r.failure_detail}), 500
    return jsonify(r.output)


# ── Teacher (conversational) ────────────────────────────────────────────────
@app.route("/api/scopes")
def scopes():
    """Corpora + missions the Ask tab lets the operator pick as REQUIRED
    retrieval scope (P9 — the console never guesses it for the user)."""
    corpora = [{"id": c["id"], "name": c.get("name", c["id"])}
               for c in corpus_manager.list_corpora()]
    missions = [{"id": m["id"], "title": m["title"], "corpora": m.get("corpora", [])}
                for m in mission_sdk.list_all()]
    return jsonify({"corpora": corpora, "missions": missions, "default_corpus": DEFAULT_CORPUS})


@app.route("/api/ask", methods=["POST"])
def ask():
    data = request.json or {}
    message = (data.get("message") or "").strip()
    mission_id = data.get("mission_id")
    corpora = data.get("corpora")
    if not mission_id and not corpora:
        return jsonify({"error": "scope required: pick a mission or corpus "
                                  "(P9 — scope is never guessed)"}), 400
    if len(message) < 3:
        return jsonify({"error": "message too short"}), 400

    session_id = (data.get("session_id") or "").strip() or ts.new_session_id()
    store = ts.load_store(SESSIONS_PATH)
    session = ts.get_session(store, session_id)
    turn = ts.resolve_turn(session, message, explicit_topic=data.get("topic"),
                           explicit_mode=data.get("mode"), explicit_depth=data.get("depth"))

    inputs = {"topic": turn["topic"], "mode": turn["mode"], "depth": turn["depth"]}
    if mission_id:
        inputs["mission_id"] = mission_id
    if corpora:
        inputs["corpora"] = corpora
    if data.get("cross_corpus") is not None:
        inputs["cross_corpus"] = bool(data["cross_corpus"])
    if turn["is_followup"] and session.get("last_concept"):
        mastery = ts.build_mastery_input(store, session["last_concept"])
        if mastery:
            inputs["mastery"] = mastery

    context = {"agent_adapter": teacher_adapter.make_llm_adapter()}
    r = dispatch("teacher", inputs, context)
    if not r.ok:
        return jsonify({"error": r.failure, "detail": r.failure_detail,
                        "resolved": turn, "session_id": session_id}), 502

    lesson = r.output
    concept_name = lesson["concept_candidate"]["name"]
    ts.record_turn(store, session_id, turn["topic"], turn["mode"], turn["depth"], concept_name)
    ts.bump_mastery(store, concept_name)
    ts.save_store(SESSIONS_PATH, store)
    return jsonify({"session_id": session_id, "resolved": turn, "lesson": lesson,
                    "speech": ts.to_speech(lesson["explanation"])})


# ── Recursive planner ──────────────────────────────────────────────────────
@app.route("/api/planner/run", methods=["POST"])
def planner_run():
    data = request.json or {}
    goal = data.get("goal", "")
    criteria = data.get("stability_criteria", [])
    if not goal or not criteria:
        return jsonify({"error": "goal and stability_criteria required"}), 400
    memory_root = data.get("memory_root") or str(MEMORY / "console_runs" / "latest")
    inputs = {"goal": goal, "memory_root": memory_root,
              "stability_criteria": criteria,
              "max_cycles": int(data.get("max_cycles", 10))}
    _planner_goal["goal"] = goal
    started = _planner_job.start_loop("recursive_planner", inputs, label=goal,
                                      max_dispatches=inputs["max_cycles"] + 2)
    if not started:
        return jsonify({"error": "planner already running"}), 409
    return jsonify({"started": True, "goal": goal, "memory_root": memory_root})


@app.route("/api/planner/status")
def planner_status():
    s = _planner_job.status()
    r = s["result"]
    return jsonify({
        "running": s["running"], "goal": _planner_goal["goal"],
        "final_status": s["final_status"],
        "cycles": [{"cycle": c["output"]["cycle"], "status": c["output"]["status"],
                    "task": c["output"]["atomic_task"]["description"],
                    "criteria": c["output"].get("criteria_state", {})}
                   for c in (r["cycles"] if r else []) if c.get("output")],
    })


# ── Memory files ───────────────────────────────────────────────────────────
@app.route("/api/memory")
def memory_list():
    return jsonify({"files": sorted(f.name for f in MEMORY.glob("*.md"))})


@app.route("/api/memory/<name>")
def memory_file(name):
    p = (MEMORY / Path(name).name)        # no traversal
    if not (p.exists() and p.suffix == ".md"):
        return jsonify({"error": "not found"}), 404
    return jsonify({"name": p.name, "content": p.read_text()})


# ── Execution logs / artifacts / validation ────────────────────────────────
@app.route("/api/logs")
def logs():
    entries = []
    if METRICS_PATH.exists():
        entries = [json.loads(x) for x in
                   METRICS_PATH.read_text().strip().splitlines()[-30:]]
    return jsonify({"metrics": list(reversed(entries))})


@app.route("/api/artifacts")
def artifacts():
    arts = []
    if METRICS_PATH.exists():
        for line in METRICS_PATH.read_text().strip().splitlines():
            e = json.loads(line)
            for a in e.get("artifacts", []):
                arts.append({"artifact": a, "skill": e["skill"], "ts": e["ts"]})
    reports = [str(p.relative_to(ROOT)) for p in
               (MEMORY / "validation_report.md", MEMORY / "critic_report.md",
                MEMORY / "concepts.json") if p.exists()]
    return jsonify({"from_metrics": arts[-20:], "reports": reports})


@app.route("/api/validation")
def validation():
    from second_brain.loop import check as loop_check     # existing API
    r = dispatch("critic", {})
    return jsonify({
        "loop": loop_check(),
        "critic": r.output if r.ok else {"error": r.failure},
        "reports": {
            "validation_report": (MEMORY / "validation_report.md").exists(),
            "critic_report": (MEMORY / "critic_report.md").exists(),
        },
    })


if __name__ == "__main__":
    print("\n  AI Brain Operator Console → http://localhost:5052\n")
    app.run(host="0.0.0.0", port=5052, debug=False, threaded=True)

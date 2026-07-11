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
from aios_core import skill, workflow, memory
from aios_core.runtime.registry import Registry   # discovery (health panel)

def dispatch(sid, inputs, context=None):
    return skill.run(sid, inputs, context)

METRICS_PATH = memory.metrics_path()

MEMORY = ROOT / "memory"
UPLOADS = MEMORY / "uploads"
WIKI_BOOKS = Path("~/Documents/brain/Vaibhav's Second Brain/wiki/books").expanduser()

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
    source = (request.json or {}).get("source", "wiki")
    src_dir = str(UPLOADS) if source == "uploads" else str(WIKI_BOOKS)
    r = dispatch("book_ingestion", {"source_dir": src_dir})
    if not r.ok:
        return jsonify({"error": r.failure, "detail": r.failure_detail}), 500
    return jsonify({"note": "index rebuilt from source (backend semantics: one index)",
                    **r.output, "metrics": r.metrics})


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

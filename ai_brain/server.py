"""HTTP server for the AI Brain, on Flask (Milestone 5).

Migrated off pure stdlib http.server for one reason only: Milestone 5 needs
real persistence (per-reader topic mastery, memory/mastery.db) for the
first time in this app's life, and that means a POST endpoint with a real
JSON body. Hand-rolling that on BaseHTTPRequestHandler was the other option
on the table; the user picked a real framework instead. Every route below
is a deliberate byte-for-byte port of the previous handler's behavior, not
a redesign — same paths, same query-param names and defaults, same error
shapes, same static-file guard. The one genuinely new behavior is
/api/mastery and /api/mastery/mark (Milestone 5's actual feature); see
mastery.py.

SSE pattern (/api/ask) is copied from stock_agent/web/app.py, a sibling
Flask app in this same repo that already has this working in production:
Response(stream_with_context(generator), mimetype="text/event-stream",
headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}) — the
exact two headers this app's own handler already set by hand. Unlike
stock_agent's SSE route, no thread/queue polling is needed here:
pipeline.run() is already a generator, and it already manages its own
heartbeats during long model calls (see pipeline.py's _teach()), so the
Flask route can just iterate it directly.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from flask import Flask, Response, jsonify, request, stream_with_context

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from brain_tutor import BRAIN_CORPORA, BRAIN_ROOT  # noqa: E402
from pipeline import run as answer_stream           # noqa: E402  (9-stage flow)
import mastery                                       # noqa: E402  (Milestone 5)
import conversation                                  # noqa: E402  (session persistence)

WEB_ROOT = HERE / "web"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".woff2": "font/woff2",
    ".svg": "image/svg+xml",
}

app = Flask(__name__)


@app.before_request
def _handle_options():
    # The old handler answered OPTIONS on any path the same way (204, no
    # body) — do the same here rather than listing methods=["OPTIONS"] on
    # every single route.
    if request.method == "OPTIONS":
        return "", 204


@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


def _lab():
    import brainlab
    return brainlab


# ── /api/ask — the streaming answer ────────────────────────────────────────

@app.route("/api/ask")
def api_ask():
    question = (request.args.get("q") or "").strip()
    if not question:
        return jsonify({"error": "q parameter required"}), 400
    mode = request.args.get("mode", "explain")
    depth = request.args.get("depth", "intermediate")
    # Session persistence: the server owns conversation state (one ongoing
    # transcript — AI Brain is single-reader, see conversation.py's
    # docstring), not the client. The frontend sends nothing but the bare
    # question, same as before; prior turns are loaded here and threaded
    # into the pipeline so a follow-up like "why?" has something to resolve
    # against.
    history = conversation.load_conversation().get("messages", [])

    def generate():
        try:
            for stage, payload in answer_stream(question, mode=mode, depth=depth, history=history):
                yield f"event: {stage}\ndata: {json.dumps(payload, default=str)}\n\n"
                if stage == "done" and payload.get("prose"):
                    conversation.append_turn(question, payload["prose"])
        except (BrokenPipeError, ConnectionResetError):
            return                      # reader navigated away mid-answer
        except Exception as exc:
            try:
                yield f"event: error\ndata: {json.dumps({'message': f'{type(exc).__name__}: {exc}'})}\n\n"
            except Exception:
                pass

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Brain Lab: everything below is computed, never generated ───────────────

@app.route("/api/lab")
def api_lab_info():
    lab = _lab()
    return jsonify({"operations": lab.OPERATIONS,
                    "matrix_operations": lab.MATRIX_OPS,
                    "surfaces": lab.PRESET_SURFACES})


@app.route("/api/symbolic")
def api_symbolic():
    expr = (request.args.get("expr") or "").strip()
    if not expr:
        return jsonify({"ok": False, "error": "expr parameter required",
                        "operations": _lab().OPERATIONS}), 400
    subs = {}
    for pair in (request.args.get("subs") or "").split(","):
        if "=" in pair:
            k, _, v = pair.partition("=")
            subs[k.strip()] = v.strip()
    return jsonify(_lab().evaluate(
        expr,
        operation=request.args.get("op", "simplify"),
        variable=request.args.get("var", "x"),
        at=request.args.get("at"),
        order=int(request.args.get("order", "6") or 6),
        subs=subs or None,
        variables=request.args.get("vars", "")))


@app.route("/api/matrix")
def api_matrix():
    m = (request.args.get("m") or "").strip()
    if not m:
        return jsonify({"ok": False, "error": "m parameter required (the matrix)",
                        "operations": _lab().MATRIX_OPS}), 400
    try:
        n_iter = int(request.args.get("iter", "50"))
    except ValueError:
        n_iter = 50
    return jsonify(_lab().matrix_lab(
        m, operation=request.args.get("op", "summary"),
        rhs=request.args.get("b", ""), n_iter=n_iter))


@app.route("/api/descent")
def api_descent():
    f = (request.args.get("f") or "").strip()
    if not f:
        return jsonify({"ok": False, "error": "f parameter required",
                        "surfaces": list(_lab().PRESET_SURFACES)}), 400
    try:
        return jsonify(_lab().gradient_descent(
            f, start=request.args.get("start", "1, 1"),
            lr=float(request.args.get("lr", "0.1")),
            steps=int(request.args.get("steps", "60")),
            variables=request.args.get("vars", ""),
            momentum=float(request.args.get("momentum", "0"))))
    except ValueError as exc:
        return jsonify({"ok": False, "error": f"bad parameter: {exc}"}), 400


# ── conversation (session persistence) ──────────────────────────────────

@app.route("/api/conversation")
def api_conversation():
    return jsonify(conversation.load_conversation())


@app.route("/api/conversation/reset", methods=["POST"])
def api_conversation_reset():
    conversation.reset_conversation()
    return jsonify({"ok": True})


# ── curriculum ───────────────────────────────────────────────────────────

@app.route("/api/curriculum")
def api_curriculum():
    """The curriculum, and which topics a question would match."""
    import curriculum as CUR
    q = (request.args.get("q") or "").strip()
    if q:
        return jsonify({"question": q, "matched": [
            {"id": t.id, "title": t.title, "level": t.level,
             "key_concepts": t.key_concepts, "key_equations": t.key_equations,
             "intuition": t.intuition}
            for t in CUR.match_topics(q, int(request.args.get("k", "4") or 4))]})
    return jsonify({"total": len(CUR.TOPICS), "levels": CUR.LEVELS,
                    "topics": [{"id": t.id, "title": t.title, "level": t.level,
                                "prerequisites": t.prerequisites,
                                "key_concepts": t.key_concepts,
                                "key_equations": t.key_equations,
                                "intuition": t.intuition, "shelves": t.shelves}
                               for t in CUR.TOPICS.values()]})


# ── mastery (Milestone 5) ───────────────────────────────────────────────

@app.route("/api/mastery")
def api_mastery():
    import curriculum as CUR
    rows = mastery.mastery_summary()
    for r in rows:
        t = CUR.TOPICS.get(r["topic_id"])
        r["title"] = t.title if t else r["topic_id"]
        r["level"] = t.level if t else None
    return jsonify({"topics": rows})


@app.route("/api/recommend")
def api_recommend():
    """What to study next, from real prerequisite gaps and mastery data —
    no LLM call needed, curriculum.recommend_next() is pure computation over
    the reader's own mastery state, so this is instant and free. The same
    logic /api/ask reaches for a literal "what should I learn next" question
    (question_type=whats_next), exposed directly so the Curriculum tab can
    show it without the reader having to ask in words."""
    import curriculum as CUR
    known = mastery.known_topic_ids()
    exposed = mastery.exposed_topic_ids()
    recent = mastery.recently_studied(limit=3)
    n = int(request.args.get("n", "5") or 5)
    recs = CUR.recommend_next(known, exposed, recent, n=n)
    return jsonify({"recommended": [
        {"id": t.id, "title": t.title, "level": t.level, "intuition": t.intuition,
         "prerequisites": t.prerequisites}
        for t in recs],
        "based_on": {"known_count": len(known), "exposed_count": len(exposed),
                     "recent": recent}})


@app.route("/api/mastery/mark", methods=["POST"])
def api_mastery_mark():
    import curriculum as CUR
    body = request.get_json(silent=True) or {}
    topic_id = (body.get("topic_id") or "").strip()
    status = body.get("status")
    if topic_id not in CUR.TOPICS:
        return jsonify({"ok": False, "error": f"unknown topic_id: {topic_id!r}"}), 400
    if status not in ("known", "review", None):
        return jsonify({"ok": False, "error": f"status must be 'known', 'review', or null: {status!r}"}), 400
    record = mastery.mark_topic(topic_id, status)
    return jsonify({"ok": True, "topic_id": topic_id, "record": record})


# ── shelves / status ─────────────────────────────────────────────────────

@app.route("/api/shelves")
def api_shelves():
    """What the brain can actually see right now.

    The deployed instance has no book indexes (they live on the machine
    with the books), so this reports the real state rather than implying a
    library that isn't there.
    """
    try:
        sys.path.insert(0, str(BRAIN_ROOT))
        from second_brain import fts
        rows = [r for r in fts.status() if r["corpus"] in BRAIN_CORPORA]
        ready = [r for r in rows if r["has_index"]]
        return jsonify({
            "available": bool(ready),
            "total": len(BRAIN_CORPORA),
            "indexed": len(ready),
            "total_mb": round(sum(r["db_mb"] for r in ready), 1),
            "shelves": sorted(rows, key=lambda r: -r["db_mb"]),
        })
    except Exception as exc:
        return jsonify({"available": False, "total": len(BRAIN_CORPORA),
                        "indexed": 0, "reason": f"{type(exc).__name__}: {exc}",
                        "shelves": []})


@app.route("/api/status")
def api_status():
    return jsonify({"ok": True, "corpora": len(BRAIN_CORPORA),
                    "key_set": bool(os.getenv("DEEPSEEK_API_KEY"))})


# ── /api/research/* — real literature search + a persistent notebook,
# reusing research.py/research_loop.py's existing, already-correct
# investigate() and draft_paper() generators. Same SSE-forwarding shape as
# /api/ask (server.py:76-107) — GET, not POST, since the frontend drives
# these with EventSource, which is GET-only by browser spec. ───────────────

def _research():
    import research
    return research


def _research_loop():
    import research_loop
    return research_loop


@app.route("/api/research/threads")
def api_research_threads():
    return jsonify({"threads": _research().threads()})


@app.route("/api/research/thread")
def api_research_thread():
    name = (request.args.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name parameter required"}), 400
    return jsonify({"thread": name, "state": _research().thread(name)})


@app.route("/api/research/investigate")
def api_research_investigate():
    thread = (request.args.get("thread") or "").strip()
    question = (request.args.get("q") or "").strip()
    if not thread or not question:
        return jsonify({"error": "thread and q parameters required"}), 400
    depth = request.args.get("depth", "intermediate")
    use_arxiv = request.args.get("use_arxiv", "1") not in ("0", "false", "no")

    def generate():
        try:
            for stage, payload in _research_loop().investigate(thread, question, depth, use_arxiv=use_arxiv):
                yield f"event: {stage}\ndata: {json.dumps(payload, default=str)}\n\n"
        except (BrokenPipeError, ConnectionResetError):
            return                      # reader navigated away mid-run
        except Exception as exc:
            try:
                yield f"event: error\ndata: {json.dumps({'message': f'{type(exc).__name__}: {exc}'})}\n\n"
            except Exception:
                pass

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/research/draft")
def api_research_draft():
    thread = (request.args.get("thread") or "").strip()
    if not thread:
        return jsonify({"error": "thread parameter required"}), 400
    depth = request.args.get("depth", "intermediate")

    def generate():
        try:
            for stage, payload in _research_loop().draft_paper(thread, depth):
                yield f"event: {stage}\ndata: {json.dumps(payload, default=str)}\n\n"
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            try:
                yield f"event: error\ndata: {json.dumps({'message': f'{type(exc).__name__}: {exc}'})}\n\n"
            except Exception:
                pass

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── projects: a cognitive context layer over the same JSON-file-store ──────
# pattern research.py's notebook already established — plain POST+JSON, not
# SSE, since nothing here streams (unlike /api/research/* above, which is
# GET-only specifically because EventSource requires it).

def _projects():
    import projects
    return projects


@app.route("/api/projects")
def api_projects():
    return jsonify({"projects": _projects().list_projects()})


@app.route("/api/projects/create", methods=["POST"])
def api_projects_create():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    goal = (body.get("goal") or "").strip()
    return jsonify({"project": name, "state": _projects().create(name, goal=goal)})


@app.route("/api/projects/<name>")
def api_projects_get(name):
    state = _projects().get(name)
    if not state:
        return jsonify({"error": f"unknown project: {name!r}"}), 404
    return jsonify({"project": name, "state": state, "brief": _projects().brief(name)})


@app.route("/api/projects/<name>/record", methods=["POST"])
def api_projects_record(name):
    if not _projects().get(name):
        return jsonify({"error": f"unknown project: {name!r} — create it first"}), 404
    body = request.get_json(silent=True) or {}
    state = _projects().record(
        name,
        goal=(body.get("goal") or "").strip(),
        question=(body.get("question") or "").strip(),
        decision=(body.get("decision") or "").strip(),
        note=(body.get("note") or "").strip(),
        link=(body.get("link") or "").strip(),
    )
    return jsonify({"project": name, "state": state})


# ── static files (must be registered last — it's the catch-all) ───────────

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def static_files(path):
    target = WEB_ROOT / "index.html" if not path else (WEB_ROOT / path).resolve()
    root = WEB_ROOT.resolve()
    if not str(target).startswith(str(root)) or not target.exists() or target.is_dir():
        return "", 404
    body = target.read_bytes()
    # content_type=, not mimetype= — CONTENT_TYPES values already include
    # "; charset=utf-8" for text types (matching the old handler's exact
    # header string), and Werkzeug's mimetype= param auto-appends its own
    # charset on top of that if given a value that isn't a bare mime type,
    # doubling it in the actual response header.
    resp = Response(body, content_type=CONTENT_TYPES.get(target.suffix, "application/octet-stream"))
    resp.headers["Cache-Control"] = ("public, max-age=86400" if "vendor" in str(target)
                                     else "no-store")
    return resp


def main() -> int:
    port = int(os.getenv("PORT", "5054"))
    print(f"  AI Brain  →  http://0.0.0.0:{port}", flush=True)
    print(f"  shelves configured: {len(BRAIN_CORPORA)}", flush=True)
    print(f"  DEEPSEEK_API_KEY: {'SET' if os.getenv('DEEPSEEK_API_KEY') else 'from .env'}",
          flush=True)
    # debug=False is not optional: Flask's reloader would double-spawn the
    # process, which breaks Railway's health-check timing. threaded=True
    # matches ThreadingHTTPServer's old concurrency model — one thread per
    # request, needed since /api/ask holds a connection open for the whole
    # streamed answer.
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

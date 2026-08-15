"""HTTP server for the AI Brain.

Serves the single-page UI and one streaming endpoint. Deliberately stdlib-only
(no Flask) so the deployed image stays small and the only real dependency is
the OpenAI client.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from brain_tutor import BRAIN_CORPORA, BRAIN_ROOT  # noqa: E402
from pipeline import run as answer_stream           # noqa: E402  (9-stage flow)

WEB_ROOT = HERE / "web"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".woff2": "font/woff2",
    ".svg": "image/svg+xml",
}


class BrainHandler(BaseHTTPRequestHandler):
    server_version = "AIBrain/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/ask":
            self._ask(parsed.query)
        elif parsed.path == "/api/shelves":
            self._shelves()
        elif parsed.path == "/api/lab":
            self._lab_info()
        elif parsed.path == "/api/symbolic":
            self._symbolic(parsed.query)
        elif parsed.path == "/api/matrix":
            self._matrix(parsed.query)
        elif parsed.path == "/api/descent":
            self._descent(parsed.query)
        elif parsed.path == "/api/curriculum":
            self._curriculum(parsed.query)
        elif parsed.path == "/api/status":
            self._json({"ok": True, "corpora": len(BRAIN_CORPORA),
                        "key_set": bool(os.getenv("DEEPSEEK_API_KEY"))})
        else:
            self._static(parsed.path)

    # ── Brain Lab: everything below is computed, never generated ─────────

    def _lab(self):
        import brainlab
        return brainlab

    def _lab_info(self) -> None:
        """What the lab can do — the UI builds its controls from this."""
        lab = self._lab()
        self._json({"operations": lab.OPERATIONS,
                    "matrix_operations": lab.MATRIX_OPS,
                    "surfaces": lab.PRESET_SURFACES})

    def _symbolic(self, query: str) -> None:
        p = parse_qs(query)
        expr = p.get("expr", [""])[0].strip()
        if not expr:
            self._json({"ok": False, "error": "expr parameter required",
                        "operations": self._lab().OPERATIONS}, status=400)
            return
        subs = {}
        for pair in p.get("subs", [""])[0].split(","):
            if "=" in pair:
                k, _, v = pair.partition("=")
                subs[k.strip()] = v.strip()
        self._json(self._lab().evaluate(
            expr,
            operation=p.get("op", ["simplify"])[0],
            variable=p.get("var", ["x"])[0],
            at=p.get("at", [None])[0],
            order=int(p.get("order", ["6"])[0] or 6),
            subs=subs or None,
            variables=p.get("vars", [""])[0]))

    def _matrix(self, query: str) -> None:
        p = parse_qs(query)
        m = p.get("m", [""])[0].strip()
        if not m:
            self._json({"ok": False, "error": "m parameter required (the matrix)",
                        "operations": self._lab().MATRIX_OPS}, status=400)
            return
        try:
            n_iter = int(p.get("iter", ["50"])[0])
        except ValueError:
            n_iter = 50
        self._json(self._lab().matrix_lab(
            m, operation=p.get("op", ["summary"])[0],
            rhs=p.get("b", [""])[0], n_iter=n_iter))

    def _descent(self, query: str) -> None:
        p = parse_qs(query)
        f = p.get("f", [""])[0].strip()
        if not f:
            self._json({"ok": False, "error": "f parameter required",
                        "surfaces": list(self._lab().PRESET_SURFACES)}, status=400)
            return
        try:
            self._json(self._lab().gradient_descent(
                f, start=p.get("start", ["1, 1"])[0],
                lr=float(p.get("lr", ["0.1"])[0]),
                steps=int(p.get("steps", ["60"])[0]),
                variables=p.get("vars", [""])[0],
                momentum=float(p.get("momentum", ["0"])[0])))
        except ValueError as exc:
            self._json({"ok": False, "error": f"bad parameter: {exc}"}, status=400)

    def _curriculum(self, query: str) -> None:
        """The curriculum, and which topics a question would match."""
        import curriculum as CUR
        p = parse_qs(query)
        q = p.get("q", [""])[0].strip()
        if q:
            self._json({"question": q, "matched": [
                {"id": t.id, "title": t.title, "level": t.level,
                 "key_concepts": t.key_concepts, "key_equations": t.key_equations,
                 "intuition": t.intuition}
                for t in CUR.match_topics(q, int(p.get("k", ["4"])[0] or 4))]})
            return
        self._json({"total": len(CUR.TOPICS), "levels": CUR.LEVELS,
                    "topics": [{"id": t.id, "title": t.title, "level": t.level,
                                "prerequisites": t.prerequisites,
                                "key_concepts": t.key_concepts,
                                "key_equations": t.key_equations,
                                "intuition": t.intuition, "shelves": t.shelves}
                               for t in CUR.TOPICS.values()]})

    # ── endpoints ────────────────────────────────────────────────────────

    def _shelves(self) -> None:
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
            self._json({
                "available": bool(ready),
                "total": len(BRAIN_CORPORA),
                "indexed": len(ready),
                "total_mb": round(sum(r["db_mb"] for r in ready), 1),
                "shelves": sorted(rows, key=lambda r: -r["db_mb"]),
            })
        except Exception as exc:
            self._json({"available": False, "total": len(BRAIN_CORPORA),
                        "indexed": 0, "reason": f"{type(exc).__name__}: {exc}",
                        "shelves": []})

    def _ask(self, query: str) -> None:
        params = parse_qs(query)
        question = params.get("q", [""])[0].strip()
        if not question:
            self._json({"error": "q parameter required"}, status=400)
            return
        mode = params.get("mode", ["explain"])[0]
        depth = params.get("depth", ["intermediate"])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self._cors()
        self.end_headers()

        def emit(event: str, data: dict) -> None:
            self.wfile.write(
                f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n".encode())
            self.wfile.flush()

        try:
            for stage, payload in answer_stream(question, mode=mode, depth=depth):
                emit(stage, payload)
        except (BrokenPipeError, ConnectionResetError):
            return                      # reader navigated away mid-answer
        except Exception as exc:
            try:
                emit("error", {"message": f"{type(exc).__name__}: {exc}"})
            except Exception:
                pass

    # ── plumbing ─────────────────────────────────────────────────────────

    def _static(self, path: str) -> None:
        target = WEB_ROOT / "index.html" if path == "/" else (WEB_ROOT / path.lstrip("/")).resolve()
        root = WEB_ROOT.resolve()
        if not str(target).startswith(str(root)) or not target.exists() or target.is_dir():
            self.send_error(404)
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type",
                         CONTENT_TYPES.get(target.suffix, "application/octet-stream"))
        self.send_header("Cache-Control",
                         "public, max-age=86400" if "vendor" in str(target) else "no-store")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, indent=2, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")


def main() -> int:
    ap = argparse.ArgumentParser(description="Serve the AI Brain")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=int(os.getenv("PORT", "5054")))
    args = ap.parse_args()
    print(f"  AI Brain  →  http://{args.host}:{args.port}", flush=True)
    print(f"  shelves configured: {len(BRAIN_CORPORA)}", flush=True)
    print(f"  DEEPSEEK_API_KEY: {'SET' if os.getenv('DEEPSEEK_API_KEY') else 'from .env'}",
          flush=True)
    ThreadingHTTPServer((args.host, args.port), BrainHandler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

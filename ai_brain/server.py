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

from brain_tutor import BRAIN_CORPORA, BRAIN_ROOT, answer_stream  # noqa: E402

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
        elif parsed.path == "/api/status":
            self._json({"ok": True, "corpora": len(BRAIN_CORPORA),
                        "key_set": bool(os.getenv("DEEPSEEK_API_KEY"))})
        else:
            self._static(parsed.path)

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

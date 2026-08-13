"""
Operator Console tests — exercises every main UI workflow through the same
HTTP endpoints the page calls (Flask test client; deterministic, no browser).

Run: python3 brain/tests/test_console.py
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

BRAIN = Path(__file__).parent.parent
sys.path.insert(0, str(BRAIN / "console"))

import app as console_app          # noqa: E402  (module, so tests can monkeypatch attrs)
from app import app, MEMORY        # noqa: E402
import teach_session                # noqa: E402

FAILURES: list[str] = []
client = app.test_client()


def stub_teacher_adapter(manifest, inputs, context):
    """Model-free stand-in — same contract as brain/skills/teacher/tests/test_skill.py."""
    return {"explanation": "RAG grounds generation in retrieved passages instead of "
                           "relying on parametric memory alone.",
            "exercise": {"prompt": "Name the two phases of a RAG pipeline.", "kind": "recall"},
            "mastery_check": {"question": "Why ground generation in retrieval?",
                              "expected_signal": "mentions reduced hallucination / provenance"},
            "principle": "RAG retrieves before it reasons.",
            "when_to_use": "When an answer must be traceable to a source document."}


def check(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}  {detail}")
    if not cond:
        FAILURES.append(name)


def test_dashboard_health():
    print("=== dashboard / health ===")
    r = client.get("/api/health").get_json()
    check("skills registered visible", r["skills_registered"] >= 10, r["skills_registered"])
    check("index stats present", r["index"] and r["index"]["chunks"] > 0)
    check("concepts summary present", r["concepts"] and r["concepts"]["n"] >= 10)
    check("memory files listed", "state.md" in r["memory_files"])


def test_upload_and_ingest():
    print("=== upload + ingestion ===")
    data = {"file": (io.BytesIO(b"# Test Doc\n\nAtomic tasks beat big rewrites."),
                     "console_test_doc.md")}
    r = client.post("/api/upload", data=data,
                    content_type="multipart/form-data").get_json()
    check("upload accepted", r.get("saved") == "console_test_doc.md", str(r))
    r2 = client.post("/api/upload", data={"file": (io.BytesIO(b"x"), "evil.exe")},
                     content_type="multipart/form-data").get_json()
    check("non-md/txt upload rejected", "error" in r2)

    r3 = client.post("/api/ingest", json={"source": "uploads"}).get_json()
    check("ingest uploads runs via runtime dispatch", r3.get("chunks", 0) >= 1, str(r3)[:80])
    check("ingestion progress/stats surfaced",
          "files" in r3 and "metrics" in r3 and r3["metrics"]["elapsed_ms"] is not None)

    # restore the main index for the remaining tests (and for the operator)
    r4 = client.post("/api/ingest", json={"source": "wiki"}).get_json()
    check("re-ingest wiki corpus restores main index", r4.get("files") == 36, str(r4.get("files")))


def test_search():
    print("=== search + retrieved chunks ===")
    r = client.get("/api/search?q=agent+design+patterns").get_json()
    check("search returns chunks", r["n"] > 0)
    check("chunks carry source + corpus + confidence",
          all("source" in h and "corpus" in h and "confidence" in h for h in r["hits"]))
    r2 = client.get("/api/search?q=zz").get_json()
    check("too-short query rejected", "error" in r2)
    r3 = client.get("/api/search?q=zzqxv+wvvptk+qqrst").get_json()
    check("gibberish → honest empty", r3["n"] == 0)


def test_planner_workflow():
    print("=== run recursive planner from console ===")
    import shutil
    mem = MEMORY / "console_runs" / "test"
    shutil.rmtree(mem, ignore_errors=True)   # idempotent: fresh run each time
    r = client.post("/api/planner/run", json={
        "goal": "bootstrap console test memory and converge",
        "memory_root": str(mem),
        "stability_criteria": [{"id": "state", "description": "state.md exists",
                                "check": "test -f state.md"}]}).get_json()
    check("planner started", r.get("started") is True, str(r))
    for _ in range(100):                       # poll like the UI does
        s = client.get("/api/planner/status").get_json()
        if not s["running"] and s["final_status"]:
            break
        time.sleep(0.2)
    check("planner reached STABLE", s["final_status"] == "STABLE", str(s["final_status"]))
    check("cycle table populated (status + task + criteria)",
          len(s["cycles"]) >= 2 and all("status" in c and "criteria" in c for c in s["cycles"]))
    r2 = client.post("/api/planner/run", json={"goal": "", "stability_criteria": []}).get_json()
    check("missing goal/criteria rejected", "error" in r2)


def test_memory_view():
    print("=== memory file viewer ===")
    files = client.get("/api/memory").get_json()["files"]
    check("memory list includes core files", {"state.md", "plan.md", "log.md"} <= set(files))
    r = client.get("/api/memory/state.md").get_json()
    check("state.md content served", "loop_iteration" in r["content"])
    r2 = client.get("/api/memory/..%2F..%2Fetc%2Fpasswd")
    check("path traversal blocked", r2.status_code == 404)


def test_logs_artifacts_validation():
    print("=== logs / artifacts / validation ===")
    r = client.get("/api/logs").get_json()
    check("execution log entries present", len(r["metrics"]) > 0)
    check("entries carry ok/elapsed/retries/memory_changes",
          all(k in r["metrics"][0] for k in ("ok", "elapsed_ms", "retries", "memory_changes")))
    a = client.get("/api/artifacts").get_json()
    check("reports listed as artifacts", any("critic_report" in p for p in a["reports"]))
    v = client.get("/api/validation").get_json()
    check("validation: pipeline stable", v["loop"]["stable"] is True)
    check("validation: critic summary present", v["critic"]["n"] >= 10)


def test_ask_scope_required():
    print("=== /api/ask: scope is required, never guessed (P9) ===")
    r = client.post("/api/ask", json={"message": "Explain retrieval-augmented generation"})
    check("missing scope rejected with 400", r.status_code == 400, str(r.get_json()))
    check("rejection names the reason", "scope" in r.get_json().get("error", "").lower())
    r2 = client.post("/api/ask", json={"message": "hi", "corpora": ["curated-wiki"]})
    check("too-short message rejected", r2.status_code == 400, str(r2.get_json()))


def test_ask_lesson_roundtrip_and_mastery_loop():
    print("=== /api/ask: lesson round-trips full schema + mastery feeds the next turn ===")
    orig_make_adapter = console_app.teacher_adapter.make_llm_adapter
    orig_sessions_path = console_app.SESSIONS_PATH
    orig_dispatch = console_app.dispatch
    captured_inputs = []

    def capturing_dispatch(sid, inputs, context=None):
        captured_inputs.append(dict(inputs))
        return orig_dispatch(sid, inputs, context)

    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "teacher_sessions.json"
    console_app.teacher_adapter.make_llm_adapter = lambda *a, **k: stub_teacher_adapter
    console_app.SESSIONS_PATH = tmp
    console_app.dispatch = capturing_dispatch
    try:
        r1 = client.post("/api/ask", json={
            "message": "Explain retrieval-augmented generation", "corpora": ["curated-wiki"]})
        check("turn 1 ok", r1.status_code == 200, str(r1.get_json())[:200])
        j1 = r1.get_json()
        for key in ("session_id", "resolved", "lesson", "speech"):
            check(f"turn 1 response has '{key}'", key in j1)
        lesson = j1.get("lesson", {})
        for key in ("topic", "mode", "adaptation", "explanation", "source_evidence",
                    "exercise", "mastery_check", "recommended_next_action",
                    "concept_candidate", "provenance_grounded"):
            check(f"lesson has schema key '{key}'", key in lesson)
        check("turn 1 is a fresh topic, not a follow-up", j1["resolved"]["is_followup"] is False)
        check("turn 1 sent no mastery (nothing known yet)",
              "mastery" not in captured_inputs[0], str(captured_inputs[0].get("mastery")))
        sid = j1["session_id"]

        r2 = client.post("/api/ask", json={
            "message": "simpler please", "corpora": ["curated-wiki"], "session_id": sid})
        check("turn 2 ok", r2.status_code == 200, str(r2.get_json())[:200])
        j2 = r2.get_json()
        check("turn 2 recognized as a follow-up", j2["resolved"]["is_followup"] is True)
        check("turn 2 reused turn 1's topic (session-threaded)",
              j2["resolved"]["topic"] == j1["resolved"]["topic"], str(j2["resolved"]))
        check("turn 2 asked for intro depth ('simpler')",
              j2["resolved"]["depth"] == "intro", j2["resolved"]["depth"])
        check("turn 2 fed back the mastery learned from turn 1 (closes the loop)",
              captured_inputs[1].get("mastery", {}).get("prior_activity") == 1,
              str(captured_inputs[1].get("mastery")))
        check("turn 2 mastery references the same concept", captured_inputs[1]["mastery"]["concept"]
              == j1["lesson"]["concept_candidate"]["name"])

        store = json.loads(tmp.read_text())
        concept = j2["lesson"]["concept_candidate"]["name"]
        check("mastery store persisted prior_activity across both turns",
              store["mastery"][concept]["prior_activity"] == 2, str(store["mastery"]))
    finally:
        console_app.teacher_adapter.make_llm_adapter = orig_make_adapter
        console_app.SESSIONS_PATH = orig_sessions_path
        console_app.dispatch = orig_dispatch


def test_to_speech_normalizer():
    print("=== to_speech: deterministic markdown/LaTeX → speakable text ===")
    check("empty input", teach_session.to_speech("") == "")
    out = teach_session.to_speech(
        "## Title\n\nThis is **bold** and *italic* text with `code`,\n"
        "a [link](http://example.com), and $E=mc^2$ plus $$\\frac{a}{b}$$.")
    for token in ("**", "##", "`", "$", "\\frac", "[link]", "(http"):
        check(f"no raw markdown/LaTeX token {token!r} leaks through", token not in out, out)
    for word in ("Title", "bold", "italic", "code", "link", "equals", "over"):
        check(f"speakable content preserved: {word!r}", word in out, out)


def test_ui_page():
    print("=== UI page serves with all panels ===")
    html = client.get("/").get_data(as_text=True)
    for panel in ("System Health", "Ingest Documents", "Search Knowledge",
                  "Recursive Planner", "Memory Files", "Execution Log",
                  "Artifacts", "Validation Status", "Ask the Teacher"):
        check(f"panel '{panel}' present", panel in html)


if __name__ == "__main__":
    test_dashboard_health()
    test_upload_and_ingest()
    test_search()
    test_planner_workflow()
    test_memory_view()
    test_logs_artifacts_validation()
    test_ask_scope_required()
    test_ask_lesson_roundtrip_and_mastery_loop()
    test_to_speech_normalizer()
    test_ui_page()
    print(f"\n{'='*60}")
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}"); sys.exit(1)
    print("ALL PASS — console exposes backend without duplicating it")

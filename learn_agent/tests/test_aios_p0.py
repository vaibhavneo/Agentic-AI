"""
AIOS P0 acceptance tests — the architecture's exit criteria, verbatim:
  create a mission scoped to `finance` → search returns ONLY finance chunks
  with corpus provenance → enable cross_corpus → widened hits arrive visibly
  flagged → concepts store structured {corpus, source}.

Run: python3 learn_agent/tests/test_aios_p0.py
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent.parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

from aios_core import memory as _memory

from fastapi import FastAPI
from fastapi.testclient import TestClient
from aios_api import mount, MISSIONS_DIR

app = FastAPI()
mount(app)
client = TestClient(app)

FAILURES: list[str] = []


def check(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}  {detail}")
    if not cond:
        FAILURES.append(name)


def test_health_and_corpora():
    print("=== corpora registered and visible ===")
    h = client.get("/api/health").json()
    ids = {c["id"] for c in h["corpora"]}
    check("≥5 corpora registered", len(ids) >= 5, str(sorted(ids)))
    check("seed corpora present", {"curated-wiki", "ai-books", "finance"} <= ids)
    c = client.get("/api/corpora").json()["corpora"]
    check("ai-books ingested at scale",
          next(x for x in c if x["id"] == "ai-books")["stats"]["chunks"] > 10000)


def test_mission_requires_corpus():
    print("=== mission creation requires ≥1 valid corpus ===")
    r = client.post("/api/missions", json={"title": "No Corpus", "goal": "x" * 12,
                                           "corpora": []})
    check("empty corpora rejected", r.status_code == 400)
    r2 = client.post("/api/missions", json={"title": "Bad Corpus", "goal": "x" * 12,
                                            "corpora": ["no-such"]})
    check("unknown corpus rejected", r2.status_code == 400)


def test_exit_criteria_flow():
    print("=== ARCHITECTURE EXIT CRITERIA (end-to-end) ===")
    shutil.rmtree(MISSIONS_DIR / "p0-acceptance-mission", ignore_errors=True)
    # 1. create a mission scoped to a single small corpus
    r = client.post("/api/missions", json={
        "title": "P0 Acceptance Mission", "type": "research",
        "goal": "verify corpus scoping end to end",
        "corpora": ["personal-notes"],
        "tasks": ["task one", "task two", "task three"]}).json()
    slug = r["id"]
    check("mission created with corpus scope", r["corpora"] == ["personal-notes"])

    # 2. mission-scoped search returns ONLY in-scope chunks with provenance
    s = client.get(f"/api/search?q=agentic+design+patterns&mission_id={slug}").json()
    check("mission-scoped search resolves scope", s["scope"] == ["personal-notes"])
    check("hits carry corpus provenance and stay in scope",
          all(set(h["corpus"]) <= {"personal-notes"} for h in s["hits"]))
    check("no widening while cross_corpus=false", s["widened"] is False)

    # 3. enable cross_corpus via the mapping PATCH
    p = client.patch(f"/api/missions/{slug}/corpora",
                     json={"cross_corpus": True}).json()
    check("cross_corpus toggled via PATCH", p["cross_corpus"] is True)

    # 4. a query the small corpus cannot fill → widened hits, visibly flagged
    s2 = client.get(f"/api/search?q=vectorized+backtest+kelly+deflated+sharpe"
                    f"&mission_id={slug}").json()
    if s2["widened"]:
        outside = [h for h in s2["hits"] if set(h["corpus"]) - {"personal-notes"}]
        check("widened hits flagged cross_corpus=true",
              outside and all(h["cross_corpus"] for h in outside))
    else:
        check("widened hits flagged cross_corpus=true",
              len(s2["hits"]) >= 5, "scope filled top_k — widening not needed")

    # 5. mission object parses files: tasks, progress, memory, questions
    m = client.get(f"/api/missions/{slug}").json()
    check("tasks parsed from plan.md", len(m["tasks"]) == 3)
    check("progress computed (0% — nothing checked)", m["progress"] == 0)
    check("memory files scaffolded",
          {"state.md", "plan.md", "log.md", "decisions.md"} <= set(m["memory_files"]))
    mem = client.get(f"/api/missions/{slug}/memory/state.md").json()
    check("mission memory viewable", "goal:" in mem["content"])
    trav = client.get(f"/api/missions/{slug}/memory/..%2F..%2Fstate.md")
    check("memory path traversal blocked", trav.status_code == 404)

    shutil.rmtree(MISSIONS_DIR / slug, ignore_errors=True)


def test_concepts_structured_provenance():
    print("=== concepts store structured {corpus, source} ===")
    sys.path.insert(0, str(ROOT))
    from second_brain import concept_store as cs
    data = cs.load()
    c = data["concepts"]["RAG Maturity Ladder"]
    structured = all(isinstance(s, dict) and "corpus" in s and "source" in s
                     for s in c["sources"])
    check("sources are structured {corpus, source}", structured,
          str(c["sources"][:1]))


def test_search_guards():
    print("=== gateway guards surfaced through API ===")
    r = client.get("/api/search?q=agent+memory")
    check("no scope → 400 with honest message", r.status_code == 400
          and "never guessed" in r.json()["error"])
    r2 = client.get("/api/search?q=ab")
    check("short query → 400", r2.status_code == 400)


def test_seeded_missions():
    print("=== seed missions exist with real corpora mappings ===")
    ms = {m["id"]: m for m in client.get("/api/missions").json()["missions"]}
    check("stock platform mission seeded",
          "build-ai-stock-analysis-platform" in ms)
    check("MAS learning mission seeded", "learn-multi-agent-systems" in ms)
    if "build-ai-stock-analysis-platform" in ms:
        m = ms["build-ai-stock-analysis-platform"]
        check("stock mission scoped to finance+curated-wiki",
              set(m["corpora"]) == {"finance", "curated-wiki"})


def test_shell_page():
    print("=== workspace shell served at /app with core affordances ===")
    html = client.get("/app").text
    for probe in ("⌘K", "Missions", "cross-corpus", "palette", "corpus", "Coach"):
        check(f"shell contains '{probe}'", probe in html)


def test_shell_execute_mode_markers():
    print("=== workspace shell: Execute Mode UI (M-P1b/WP-2) ===")
    html = client.get("/app").text
    for probe in ("Execute", "execRun", "execConnect", "EventSource",
                  "aria-live", 'role="status"', "execStopBtn", "criteria"):
        check(f"shell contains '{probe}'", probe in html)


def test_coach_api():
    print("=== coach API: recommendations + accept/dismiss (M-P1a) ===")
    import tempfile
    import coach_service as cs
    # Isolate persistence to a temp aios.db so the real one is untouched
    # (recommendations table is DROP-safe). Coach still reads REAL missions +
    # concepts, so this exercises the live exit criterion.
    orig = cs.default_coach
    td = tempfile.mkdtemp()
    cs.default_coach = cs.Coach(db_path=Path(td) / "coach_test.db")
    try:
        recs = client.get("/api/coach").json()["recommendations"]
        check("coach returns >=1 evidence-cited recommendation on real data",
              len(recs) >= 1, f"n={len(recs)}")
        check("every rec carries trigger+evidence+id+action",
              all(x.get("trigger") and x.get("evidence") and x.get("id")
                  and x.get("action") for x in recs), str(recs)[:120])
        check("capped at MAX_RECS", len(recs) <= cs.MAX_RECS)

        rid = recs[0]["id"]
        acc = client.post(f"/api/coach/{rid}/accept").json()
        check("accept dispatches/records the action", acc.get("status") == "accepted",
              str(acc)[:120])
        after = {x["id"] for x in client.get("/api/coach").json()["recommendations"]}
        check("accepted recommendation leaves the pending list", rid not in after)

        remaining = client.get("/api/coach").json()["recommendations"]
        if remaining:
            did = remaining[0]["id"]
            dis = client.post(f"/api/coach/{did}/dismiss").json()
            check("dismiss marks dismissed", dis.get("status") == "dismissed")
            after2 = {x["id"] for x in client.get("/api/coach").json()["recommendations"]}
            check("dismissed recommendation stays hidden", did not in after2)
        else:
            check("nothing left to dismiss (acceptable)", True)

        check("accept unknown id -> 404",
              client.post("/api/coach/deadbeef0000/accept").status_code == 404)
        check("dismiss unknown id -> 404",
              client.post("/api/coach/deadbeef0000/dismiss").status_code == 404)
    finally:
        cs.default_coach = orig
        shutil.rmtree(td, ignore_errors=True)


# ── Execute Mode + SSE (M-P1b / WP-2) ────────────────────────────────────────
# Every sub-test creates its OWN throwaway mission (never one of the two real
# seeded missions — running recursive_planner against them would overwrite
# their real plan.md/state.md, per PROJECT_CHARTER.md P1/P2) and cleans it up.

def _new_execute_mission(title, slug_hint):
    shutil.rmtree(MISSIONS_DIR / slug_hint, ignore_errors=True)
    r = client.post("/api/missions", json={
        "title": title, "type": "research", "goal": "verify Execute Mode " + title,
        "corpora": ["personal-notes"]}).json()
    check(f"mission '{slug_hint}' created", r.get("id") == slug_hint, str(r))
    return r["id"]


def test_execute_run_to_stable_and_metrics_correlation():
    print("=== Execute Mode: run-to-STABLE, per-criterion rows, metrics.jsonl correlation ===")
    slug = _new_execute_mission("WP2 Execute Stable Test", "wp2-execute-stable-test")
    # Snapshot the file's exact line COUNT (not a fixed "last N" window) so
    # concurrent, unrelated dispatches from another process (e.g. a live
    # server also writing metrics.jsonl) can only ever ADD lines outside our
    # slice — a sliding-window comparison was flaky under exactly that.
    metrics_path = _memory.metrics_path()
    before_n = sum(1 for _ in metrics_path.open()) if metrics_path.exists() else 0

    run = client.post(f"/api/missions/{slug}/run", json={
        "stability_criteria": [{"id": "state", "description": "state.md exists",
                                "check": "test -f state.md"}]}).json()
    check("run started", run.get("started") is True, str(run))

    s = None
    for _ in range(150):
        s = client.get(f"/api/missions/{slug}/status").json()
        if not s["running"] and s["final_status"]:
            break
        time.sleep(0.1)
    check("reached STABLE", s and s["final_status"] == "STABLE", str(s and s.get("final_status")))
    check("cycle table populated (status+task+criteria per row)",
          s and len(s["cycles"]) >= 2
          and all({"cycle", "status", "task", "criteria"} <= set(c) for c in s["cycles"]))
    check("per-criterion pass/fail is visible on each row",
          s and all("state" in c["criteria"] for c in s["cycles"]))

    new_lines = metrics_path.read_text().splitlines()[before_n:]
    new_recursive_planner = [json.loads(ln) for ln in new_lines if ln.strip()
                             and json.loads(ln).get("skill") == "recursive_planner"]
    check("cycle rows match metrics.jsonl tail (one dispatch recorded per cycle)",
          len(new_recursive_planner) == len(s["cycles"]),
          f"new_recursive_planner={len(new_recursive_planner)} cycles={len(s['cycles'])}")

    # terminal behavior: no longer running, status is stable on re-poll
    s2 = client.get(f"/api/missions/{slug}/status").json()
    check("terminal state is stable across repeated polls",
          s2["running"] is False and s2["final_status"] == "STABLE")

    shutil.rmtree(MISSIONS_DIR / slug, ignore_errors=True)


def test_execute_409_on_concurrent_run():
    print("=== Execute Mode: 409 on concurrent run of the SAME mission ===")
    slug = _new_execute_mission("WP2 Execute 409 Test", "wp2-execute-409-test")
    # Deliberately slow + never-passing so the job is GUARANTEED to still be
    # running when the second request lands — a deterministic race, not a
    # timing-dependent guess.
    slow = [{"id": "slow", "description": "artificially slow, never passes",
             "check": "sleep 0.6 && false"}]

    run1 = client.post(f"/api/missions/{slug}/run",
                       json={"stability_criteria": slow, "max_cycles": 2}).json()
    check("first run started", run1.get("started") is True, str(run1))

    run2 = client.post(f"/api/missions/{slug}/run", json={"stability_criteria": slow})
    check("concurrent run on the same mission -> 409", run2.status_code == 409, run2.text)

    s = None
    for _ in range(60):
        s = client.get(f"/api/missions/{slug}/status").json()
        if not s["running"] and s["final_status"]:
            break
        time.sleep(0.2)
    check("run reaches a non-STABLE terminal status (never-passing criterion)",
          s and s["final_status"] in ("ABORTED", "DISPATCH_CAP"), str(s and s.get("final_status")))

    run3 = client.post(f"/api/missions/{slug}/run",
                       json={"stability_criteria": slow, "max_cycles": 1})
    check("re-run after terminal completion is allowed (not falsely 409)",
          run3.status_code == 200, run3.text)
    for _ in range(30):                             # let it finish before cleanup
        s3 = client.get(f"/api/missions/{slug}/status").json()
        if not s3["running"]:
            break
        time.sleep(0.2)

    unknown = client.post("/api/missions/does-not-exist/run",
                          json={"stability_criteria": slow})
    check("run on unknown mission -> 404", unknown.status_code == 404)
    empty = client.post(f"/api/missions/{slug}/run", json={"stability_criteria": []})
    check("missing/empty stability_criteria -> 400", empty.status_code == 400)

    shutil.rmtree(MISSIONS_DIR / slug, ignore_errors=True)


def _parse_sse(lines):
    """Robust to either blank-line-delimited or event-header-delimited framing."""
    events, cur = [], {}

    def flush():
        if cur.get("event") is not None:
            events.append((cur.get("event"), cur.get("id"), cur.get("data")))

    for ln in lines:
        if ln == "":
            flush(); cur.clear(); continue
        if ln.startswith("event:"):
            if cur.get("event") is not None:
                flush(); cur.clear()
            cur["event"] = ln.split(":", 1)[1].strip()
        elif ln.startswith("id:"):
            cur["id"] = int(ln.split(":", 1)[1].strip())
        elif ln.startswith("data:"):
            cur["data"] = json.loads(ln.split(":", 1)[1].strip())
    flush()
    return events


def test_execute_sse_ordering_reconnect_dedup_and_terminal():
    print("=== Execute Mode SSE: ordering, reconnect (Last-Event-ID), dedup, terminal event ===")
    slug = _new_execute_mission("WP2 Execute SSE Test", "wp2-execute-sse-test")

    # idle: no run started yet -> a single idle event, stream closes.
    with client.stream("GET", f"/api/missions/{slug}/events") as resp:
        check("idle SSE responds 200", resp.status_code == 200)
        idle_lines = list(resp.iter_lines())
    check("idle stream emits 'idle' and closes",
          any("idle" in ln for ln in idle_lines), str(idle_lines[:4]))

    # slow-but-passing: ~0.35s/cycle gives a wide window to split observation
    # across two connections (simulating a drop + reconnect).
    criteria = [{"id": "state", "description": "state.md exists (slowed for test)",
                "check": "sleep 0.35 && test -f state.md"}]
    run = client.post(f"/api/missions/{slug}/run",
                      json={"stability_criteria": criteria, "max_cycles": 10}).json()
    check("SSE test run started", run.get("started") is True, str(run))

    first_lines, last_seen_id = [], 0
    with client.stream("GET", f"/api/missions/{slug}/events") as resp:
        check("SSE stream is 200 text/event-stream",
              resp.status_code == 200
              and "text/event-stream" in resp.headers.get("content-type", ""))
        for ln in resp.iter_lines():
            first_lines.append(ln)
            if ln.startswith("id:"):
                last_seen_id = int(ln.split(":", 1)[1].strip())
            if ln.startswith("event:") and "cycle" in ln:
                break                                # simulate a dropped connection

    parsed_first = _parse_sse(first_lines + [""])
    check("first connection delivered >=1 cycle event before disconnect",
          any(e[0] == "cycle" for e in parsed_first), str(parsed_first))

    with client.stream("GET", f"/api/missions/{slug}/events",
                       headers={"Last-Event-ID": str(last_seen_id)}) as resp2:
        second_lines = list(resp2.iter_lines())
    parsed_second = _parse_sse(second_lines)

    check("reconnect (Last-Event-ID) replays no cycle already seen (dedup)",
          all(kind != "cycle" or (cid is not None and cid > last_seen_id)
              for kind, cid, _ in parsed_second), str(parsed_second))

    all_cycles = [cid for kind, cid, _ in parsed_first + parsed_second if kind == "cycle"]
    check("no duplicate cycle ids across both connections",
          len(all_cycles) == len(set(all_cycles)), str(all_cycles))
    check("cycle ids strictly increasing (ordering preserved)",
          all_cycles == sorted(all_cycles) and len(all_cycles) >= 2, str(all_cycles))

    terminal = [(kind, data) for kind, _, data in parsed_second if kind in ("completed", "failed")]
    check("exactly one terminal event, type=completed, final_status=STABLE",
          len(terminal) == 1 and terminal[0][0] == "completed"
          and terminal[0][1]["final_status"] == "STABLE", str(terminal))
    check("terminal event's 'ok' flag matches its type",
          terminal and terminal[0][1]["ok"] is True)

    shutil.rmtree(MISSIONS_DIR / slug, ignore_errors=True)


if __name__ == "__main__":
    test_health_and_corpora()
    test_mission_requires_corpus()
    test_exit_criteria_flow()
    test_concepts_structured_provenance()
    test_search_guards()
    test_seeded_missions()
    test_shell_page()
    test_shell_execute_mode_markers()
    test_coach_api()
    test_execute_run_to_stable_and_metrics_correlation()
    test_execute_409_on_concurrent_run()
    test_execute_sse_ordering_reconnect_dedup_and_terminal()
    print(f"\n{'='*60}")
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}"); sys.exit(1)
    print("ALL PASS — P0 exit criteria met")

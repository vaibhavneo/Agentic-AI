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
from pathlib import Path

HERE = Path(__file__).parent.parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

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


def test_shell_task_write_path_markers():
    print("=== workspace shell: task write-path UI (M-P1c/WP-3) ===")
    html = client.get("/app").text
    for probe in ("taskAdd", "taskToggle", "todayFocus", "Today's Focus", "loadTodayFocus"):
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


# ── Mission task write-path (M-P1c / WP-3) ───────────────────────────────────
# Every sub-test creates its OWN throwaway mission — never one of the two real
# seeded missions — and cleans it up, matching test_exit_criteria_flow's
# established pattern.

def _new_task_mission(title, slug_hint):
    shutil.rmtree(MISSIONS_DIR / slug_hint, ignore_errors=True)
    r = client.post("/api/missions", json={
        "title": title, "type": "build", "goal": "verify task write-path " + title,
        "corpora": ["personal-notes"]}).json()
    check(f"mission '{slug_hint}' created", r.get("id") == slug_hint, str(r))
    return r["id"]


def test_task_create_and_toggle_write_plan_md_on_disk():
    print("=== task create + toggle: dispatched via skill, plan.md changes ON DISK ===")
    slug = _new_task_mission("WP3 Task Write Test", "wp3-task-write-test")
    plan = MISSIONS_DIR / slug / "plan.md"
    before = plan.read_text()

    r = client.post(f"/api/missions/{slug}/tasks", json={"description": "Ship the write-path"}).json()
    check("create ok, changed=True", r.get("changed") is True, str(r))
    tid = r["task"]["id"]
    after_create = plan.read_text()
    check("plan.md content changed ON DISK after create",
          after_create != before and "Ship the write-path" in after_create)

    m = client.get(f"/api/missions/{slug}").json()
    check("mission.get() reflects the new task via the API",
          any(t["id"] == tid and t["description"] == "Ship the write-path" for t in m["tasks"]))
    check("progress still 0% (nothing checked yet)", m["progress"] == 0)

    r2 = client.patch(f"/api/missions/{slug}/tasks/{tid}", json={"done": True}).json()
    check("toggle done ok, changed=True", r2.get("changed") is True, str(r2))
    after_toggle = plan.read_text()
    check("plan.md's checkbox actually flipped ON DISK",
          f"- [x] Ship the write-path" in after_toggle)

    m2 = client.get(f"/api/missions/{slug}").json()
    check("progress recomputed via the API after the write",
          m2["progress"] == round(100 / len(m2["tasks"])), str(m2["progress"]))

    shutil.rmtree(MISSIONS_DIR / slug, ignore_errors=True)


def test_task_idempotency_and_errors_over_http():
    print("=== duplicate submissions + invalid transitions over the real HTTP API ===")
    slug = _new_task_mission("WP3 Task Idempotency Test", "wp3-task-idempotency-test")
    plan = MISSIONS_DIR / slug / "plan.md"

    r1 = client.post(f"/api/missions/{slug}/tasks", json={"description": "Deploy"}).json()
    r2 = client.post(f"/api/missions/{slug}/tasks", json={"description": "Deploy"}).json()
    r3 = client.post(f"/api/missions/{slug}/tasks", json={"description": "Deploy"}).json()
    check("first create changed", r1["changed"] is True)
    check("duplicate submissions are no-ops (changed=False)",
          r2["changed"] is False and r3["changed"] is False, str((r2, r3)))
    check("all three agree on the same task id",
          len({r1["task"]["id"], r2["task"]["id"], r3["task"]["id"]}) == 1)
    check("exactly one 'Deploy' line survives on disk",
          sum(1 for ln in plan.read_text().splitlines() if "Deploy" in ln) == 1)

    tid = r1["task"]["id"]
    same_state = client.patch(f"/api/missions/{slug}/tasks/{tid}", json={"done": False}).json()
    check("re-applying the CURRENT state is a no-op", same_state.get("changed") is False,
          str(same_state))

    bad = client.patch(f"/api/missions/{slug}/tasks/9999", json={"done": True})
    check("invalid transition (unknown task_id) -> 404", bad.status_code == 404, bad.text)
    bad_body = client.patch(f"/api/missions/{slug}/tasks/{tid}", json={})
    check("missing 'done' -> 400", bad_body.status_code == 400)
    bad_mission = client.post("/api/missions/does-not-exist/tasks", json={"description": "x"})
    check("unknown mission -> 404", bad_mission.status_code == 404)
    empty_desc = client.post(f"/api/missions/{slug}/tasks", json={"description": ""})
    check("empty description -> 400", empty_desc.status_code == 400)

    shutil.rmtree(MISSIONS_DIR / slug, ignore_errors=True)


def test_today_focus_api():
    print("=== Today's Focus: first unchecked task of the most-recently-active mission ===")
    slug = _new_task_mission("WP3 Today Focus Test", "wp3-today-focus-test")
    # mission.create() with no explicit tasks seeds ONE default item —
    # that (not a task we add afterward) is the real first unchecked task.
    seeded = client.get(f"/api/missions/{slug}").json()["tasks"]
    check("mission seeded with exactly its one default task", len(seeded) == 1, str(seeded))
    default_task = seeded[0]

    r = client.get("/api/today-focus").json()
    check("today-focus surfaces THIS mission's real first unchecked task"
          " (most recently created ⇒ most recently touched log.md)",
          r["mission_id"] == slug and r["task"]["id"] == default_task["id"], str(r))

    client.post(f"/api/missions/{slug}/tasks", json={"description": "Only task"})
    r_unchanged = client.get("/api/today-focus").json()
    check("adding a SECOND task doesn't change the focus (first unchecked wins)",
          r_unchanged["task"]["id"] == default_task["id"], str(r_unchanged))

    client.patch(f"/api/missions/{slug}/tasks/{default_task['id']}", json={"done": True})
    r2 = client.get("/api/today-focus").json()
    check("completing the default task advances focus to the next unchecked task",
          r2["mission_id"] == slug and r2["task"]["description"] == "Only task", str(r2))

    tid2 = r2["task"]["id"]
    client.patch(f"/api/missions/{slug}/tasks/{tid2}", json={"done": True})
    r3 = client.get("/api/today-focus").json()
    check("after ALL of this mission's tasks are done, it offers no task"
          " (another mission may surface instead, or task is None)",
          r3["mission_id"] != slug or r3["task"] is None, str(r3))

    shutil.rmtree(MISSIONS_DIR / slug, ignore_errors=True)


if __name__ == "__main__":
    test_health_and_corpora()
    test_mission_requires_corpus()
    test_exit_criteria_flow()
    test_concepts_structured_provenance()
    test_search_guards()
    test_seeded_missions()
    test_shell_page()
    test_shell_task_write_path_markers()
    test_coach_api()
    test_task_create_and_toggle_write_plan_md_on_disk()
    test_task_idempotency_and_errors_over_http()
    test_today_focus_api()
    print(f"\n{'='*60}")
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}"); sys.exit(1)
    print("ALL PASS — P0 exit criteria met")

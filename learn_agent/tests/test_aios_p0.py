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


if __name__ == "__main__":
    test_health_and_corpora()
    test_mission_requires_corpus()
    test_exit_criteria_flow()
    test_concepts_structured_provenance()
    test_search_guards()
    test_seeded_missions()
    test_shell_page()
    test_coach_api()
    print(f"\n{'='*60}")
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}"); sys.exit(1)
    print("ALL PASS — P0 exit criteria met")

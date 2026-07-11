# AIOS — Personal AI Operating System
## Complete Architecture & UX Redesign for learn_agent (port 8003)

**Status: DESIGN APPROVED with one modification (v1.1) — implementation gated.**
Version 1.1 · 2026-07-05 · Amendment: neither learn_agent nor second_brain is
the default corpus; a **Corpus Manager + Retrieval Gateway** (§6.5) owns all
retrieval. P0 roadmap regenerated accordingly (§8).

---

# 1. Product Thesis

## 1.1 The mental-model shift

| | today (knowledge browser) | target (AI operating system) |
|---|---|---|
| Core question | "What do you want to search?" | "What should happen next on your missions?" |
| Unit of value | an answer | a completed atomic task on a real project |
| AI posture | reactive (waits for prompt) | proactive (recommends, coaches, executes) |
| Memory | chat-scoped, evaporates | notebook-first files, permanent |
| Home screen | search box + categories | mission dashboard + today's focus |
| Session end state | "interesting" | state.md advanced, log appended, artifact produced |

## 1.2 The one-sentence architecture

**learn_agent (8003) becomes the product surface; `brain/` is already the OS kernel.**

Everything the AIOS needs at the system level exists and is tested in this
workspace (per memory/state.md):

| AIOS requirement | already built | where |
|---|---|---|
| Missions with goal/progress/tasks/memory | recursive_planner memory roots | brain/skills/recursive_planner + runtime.run_loop |
| Multi-agent execution | 10 contract skills + dispatcher | brain/skills/, brain/runtime/ |
| Second-brain memory (state/decisions/log/cache) | Fable Loop memory discipline | memory/*.md + memory contract enforcement |
| Mental models w/ confidence | concept store + critic | memory/concepts.json, second_brain/critic.py |
| Knowledge retrieval | ingest + TF-IDF retrieve | second_brain/, learn_agent/knowledge/ |
| Validation/observability | evaluator skill + metrics.jsonl | brain/runtime/monitor.py |
| Teaching LLM | tutor agent (DeepSeek/Anthropic) | learn_agent/agent.py |

**What is genuinely new** (the real build): the Mission data model, the AI
Coach recommendation engine, the knowledge graph assembly, the proactive-
suggestion loop, and the entire workspace UI. Roughly 30% backend, 70% product.

Guiding decisions (inherit from memory/decisions.md): notebook-first memory
(D8), files as source of truth with rendered views (D9), deterministic
scoring over LLM self-grading (D10), honest flags (D11), skills execute only
via the runtime (D12), framework-last (concept: Framework-Last Selection —
vanilla React + Zustand, no LangChain-style meta-framework).

---

# 2. Current-State Audit (8003)

```
learn_agent/
  server.py    FastAPI: GET / (single-page UI) · GET /status · POST /ask ·
               POST /learning-path · POST /reset
  agent.py     RAG tutor: retrieve → cite → teach (3 depth levels)
  knowledge/   ingest.py, sources.py (170+ books, 31 papers → data/index)
  data/index   chunk index
```

Strengths to keep: the tutor persona and citation discipline; the corpus and
ingest pipeline; the dark aesthetic (`--bg:#09090b` zinc palette, Inter +
JetBrains Mono); zero-build single-origin serving.
Weaknesses to replace: stateless sessions; no concept of *me* (no missions,
progress, or memory); single monolithic page; AI never initiates anything.

---

# 3. Information Architecture

## 3.1 Object model (the ontology everything hangs on)

```
Mission (NEW — the center of the product)
 ├─ goal: falsifiable end state          ├─ status: active|paused|done
 ├─ type: build | learn | research       ├─ progress: 0-100 (computed, never stored)
 ├─ memory_root: memory/missions/<slug>/     ← a recursive_planner-compatible root
 │    state.md · plan.md · log.md · decisions.md · notes.md · questions.md
 ├─ corpora: [corpus_id, ...]   ← REQUIRED at creation; declares knowledge scope (§6.5)
 ├─ cross_corpus: bool (default false) ← opt-in to retrieve beyond declared corpora
 ├─ tasks[]        ← parsed from plan.md (files stay source of truth)
 ├─ concepts[]     ← links into concepts.json (learned ↔ required)
 ├─ books[]        ← links into chunk index sources
 ├─ artifacts[]    ← generated code/docs (from metrics.jsonl + workspace paths)
 └─ open_questions[] ← questions.md

Concept (EXISTS) — name, principle, confidence, verification, relationships
Book/Source (EXISTS) — from index; NEW: per-book usage stats (retrieval hits)
Skill (EXISTS) — 10 registry entries; UI shows them as "agents"
Task (NEW view) — atomic plan.md items: id, description, status, mission
Insight (NEW) — dated distillations; append-only insights.md per mission
Recommendation (NEW) — coach output: action, reason, evidence, accepted?
```

## 3.2 The agent roster (requested 10 → mapped, not invented)

| requested agent | implementation | mode |
|---|---|---|
| Planner | recursive_planner skill | python driver (mechanics) + task_executor adapter (reasoning) |
| Researcher | rag_search skill + tutor LLM | hybrid |
| Knowledge Retriever | Retrieval Gateway (§6.5) behind the retrieve_context skill | deterministic |
| Teacher | learn_agent tutor (agent.py) reframed as adapter | LLM |
| Software Architect | NEW agent-type skill `architect` (contract card) | LLM adapter |
| Code Generator | NEW agent-type skill `code_generator` | LLM adapter |
| Critic | critic skill | deterministic |
| Evaluator | evaluator skill | deterministic |
| Memory Manager | memory_compression skill + planner steps 6-7 | deterministic |
| Workflow Coordinator | runtime dispatcher/run_workflow | deterministic |

UI displays the active skill id from dispatch events — "which agent is
working" is metrics truth, not animation theater.

---

# 4. UX Redesign

## 4.1 Layout — the OS shell

```
┌──────┬──────────────────────────────────────────────┬───────────────┐
│      │  ⌘K Command Palette (overlay, fuzzy)         │               │
│ MISS │ ┌──────────────────────────────────────────┐ │  CONTEXT      │
│ ION  │ │                                          │ │  PANEL        │
│ SIDE │ │            WORKSPACE                     │ │  (dockable)   │
│ BAR  │ │  (view switches by mission + mode:       │ │               │
│      │ │   Dashboard · Mission · Learn · Graph    │ │  · retrieved  │
│ ▸ 🏠 │ │   · Execute · Memory)                    │ │    chunks     │
│ ▸ 📈 │ │                                          │ │  · active     │
│ ▸ 🧠 │ │                                          │ │    agent      │
│ ▸ 🪐 │ └──────────────────────────────────────────┘ │  · mission    │
│ ▸ ➕ │ ┌──────────────────────────────────────────┐ │    memory     │
│      │ │ TASK QUEUE / ACTIVITY TIMELINE (bottom   │ │  · open       │
│ 🎯   │ │ drawer, collapsible: live dispatches,    │ │    questions  │
│ coach│ │ cycle table, log tail)                   │ │               │
└──────┴──└──────────────────────────────────────────┘─┴───────────────┘
```

- **Mission Sidebar** (left, 220px, collapsible to icons): pinned missions,
  coach badge (count of pending recommendations), + New Mission.
- **Workspace** (center): one of six views (§4.3).
- **Context Panel** (right, 300px, dockable/closable): always shows *why* —
  retrieved chunks with sources, the currently-executing skill, the mission's
  state.md summary, open questions.
- **Activity drawer** (bottom, collapsed by default): live execution — the
  Task Queue and dispatch timeline from metrics.jsonl.

## 4.2 Keyboard-first + Command Palette

`⌘K` opens the palette. Everything is a command; the palette is the primary
navigation (Linear/Cursor pattern). Grammar: verb-first.

```
go <mission|view>          n  new mission          t  new task
ask <question>             r  run next task        g  open graph
learn <concept>            /  search knowledge     m  memory viewer
coach                      .  accept top recommendation
j/k  navigate lists        e  expand/collapse panel  ?  keymap help
```

## 4.3 The six workspace views (wireframes)

### V1 — Home Dashboard (default)
```
┌ TODAY'S FOCUS ──────────────────────────────┐ ┌ COACH ────────────────┐
│ ▶ Stock Platform: task 4.2 "wire hit-rate   │ │ 3 recommendations     │
│   into confidence UI"  [Run] [Skip] [Why?]  │ │ • Learn: Kelly ✱gap   │
└─────────────────────────────────────────────┘ │   blocks task 4.2     │
┌ MISSIONS ────────────┐ ┌ LEARNING ─────────┐ │ • Read: Hilpisch ch.10│
│ 📈 Stock Platform 72%│ │ concepts: 10       │ │ • Revisit: dSR (14d   │
│ 🧠 Multi-Agent    45%│ │ supported: 9       │ │   since last touch)   │
│ 🪐 Astro AI       88%│ │ mastery Δweek: +2  │ └───────────────────────┘
│ 📚 RL Basics       5%│ │ velocity: 3.5/wk   │ ┌ RECENT INSIGHTS ─────┐
└──────────────────────┘ └────────────────────┘ │ · Grounding beats…    │
┌ EXECUTION HISTORY (metrics.jsonl) ──────────┐ │ · Critic caught bad   │
│ ✓ retrieve_context 45ms · ✓ critic 2.1s ... │ │   source record       │
└─────────────────────────────────────────────┘ └───────────────────────┘
```

### V2 — Mission Workspace (the heart)
```
┌ 📈 Build AI Stock Analysis Platform ─────────── status: ACTIVE · 72% ┐
│ GOAL: grounded BUY/SELL/HOLD where every number is formula-computed  │
├──────────┬────────────────────────────────────────────────────────── ┤
│ Overview │  CURRENT TASK: 4.2 wire hit-rate into confidence UI       │
│ Tasks    │  NEXT RECOMMENDED: 4.3 outcome-check cron   [Run current] │
│ Research │  ┌ plan.md (tasks, checkable) ─┐ ┌ knowledge gaps ──────┐ │
│ Code     │  │ [x] 4.1 SQLite store        │ │ Kelly criterion ✱    │ │
│ Notes    │  │ [ ] 4.2 hit-rate → UI  ◀    │ │ position sizing      │ │
│ Memory   │  │ [ ] 4.3 outcome cron        │ │ [Teach me] [Retrieve]│ │
│ Questions│  └─────────────────────────────┘ └──────────────────────┘ │
│          │  ARTIFACTS: store.py · synthesis.py · 3 test files        │
└──────────┴───────────────────────────────────────────────────────────┘
```
Tabs map 1:1 to memory files (Overview=state.md, Tasks=plan.md,
Notes=notes.md, Memory=full file viewer, Questions=questions.md) — the UI is
a *renderer of the notebook*, never a second store.

### V3 — Learn Mode (tutor, upgraded from /ask)
```
┌ Learning: Kelly Criterion            mission: Stock Platform · gap ✱ ┐
│ [Socratic] [Explain] [Exercise] [Compare] [Mini-project]  depth: ●●○ │
│ ┌ tutor ────────────────────────────────┐ ┌ context panel ─────────┐ │
│ │ Before I explain: you position-sized  │ │ sources retrieved:     │ │
│ │ NVDA at 3.4% yesterday. Why not 34%?  │ │ · Hilpisch p.293       │ │
│ │ > [my answer…]                        │ │ · your concepts: RAG…  │ │
│ └───────────────────────────────────────┘ │ prerequisite check:    │ │
│ On completion: concept upserted to        │ │ ✓ variance ✓ logs     │ │
│ concepts.json (status=unverified → critic)│ └────────────────────── ┘ │
└──────────────────────────────────────────────────────────────────────┘
```

### V4 — Knowledge Graph
Force-directed, typed nodes (Book/Concept/Mission/Skill/Tech/Paper), typed
edges (cites, complements, depends-on, used-by, gap). Click node → context
panel shows details + "retrieve about this" + "teach me". Edge data comes
from concepts.json relationships + book-source links + mission-concept links;
NO new graph database (§8.4).

### V5 — Execute Mode
Mission run console: goal + criteria → run_loop; live cycle table (cycle,
status pill, atomic task, per-criterion ✓/✗); active-agent indicator; artifact
diff viewer. This is the operator-console planner panel, mission-scoped.

### V6 — Memory Browser
All memory roots (global + per-mission), file viewer, decision log timeline,
insights stream, compression-audit status.

## 4.4 Proactivity model (how the AI initiates)

Recommendations are **generated by deterministic triggers + LLM ranking**,
surfaced in three places (coach card, sidebar badge, today's focus). Never
modal, never interruptive; the coach *suggests*, the human *accepts* (`.` key).
Accepted → dispatched; rejected → logged (coach learns preference weights).

Trigger catalog (all computable from existing files):
| trigger | source | example recommendation |
|---|---|---|
| Blocked task references unknown concept | plan.md ∩ concepts.json miss | "Learn Kelly criterion — blocks 4.2" |
| Concept confidence < 0.6 | concepts.json | "Evidence-check 'Grounding…' — ingest more sources" |
| Mission stale N days | mission log.md mtime | "Resume Astro AI or pause it explicitly" |
| Retrieval keeps hitting un-read book | metrics.jsonl + book stats | "Read Hilpisch ch.10 — 6 hits this week" |
| Concept untouched 14+ days | concepts.json updated | "Retention check: dSR" (spaced repetition) |
| Two sources disagree | evidence_validation on paired claims | "Books contradict on X — resolve" |
| All criteria pass | run_loop status | "Mission ready to close — write lessons-learned" |

## 4.5 Coach metrics (all deterministic, from files)

- **learning velocity** = concepts upserted / week (concepts.json timestamps)
- **concept mastery** = critic confidence distribution + exercise pass rate
- **project progress** = checked / total plan.md items
- **knowledge gaps** = task-referenced concepts absent from store
- **confidence** = mean critic confidence (already computed)
- **retention** = days-since-touched histogram → spaced-repetition queue

---

# 5. Frontend Architecture

## 5.1 Stack

React 18 + Vite + TypeScript, Zustand (state), TanStack Query (server cache),
react-force-graph (V4), CodeMirror 6 (code/markdown), cmdk (palette).
No component framework — hand-rolled on the existing zinc token palette.
Rationale: Framework-Last Selection; the topology is simple client-server.

## 5.2 Component hierarchy

```
<AIOSShell>
├─ <CommandPalette/>                       cmdk; registry of all commands
├─ <MissionSidebar>
│   ├─ <MissionList> → <MissionItem/>*    progress ring, status dot
│   ├─ <CoachBadge/>                       pending recommendation count
│   └─ <NewMissionButton/>
├─ <Workspace>                             router on (view, missionId)
│   ├─ <DashboardView>
│   │   ├─ <TodaysFocusCard/> <CoachCard/> <MissionGrid/>
│   │   ├─ <LearningStats/> <InsightsFeed/> <ExecutionHistory/>
│   ├─ <MissionView>
│   │   ├─ <MissionHeader/> <MissionTabs>
│   │   │   ├─ <OverviewTab/> <TaskBoard/> <ResearchTab/>
│   │   │   ├─ <CodeArtifacts/> <NotesEditor/> <MemoryFiles/> <QuestionsTab/>
│   ├─ <LearnView>
│   │   ├─ <TutorThread/> <ModeSelector/> <DepthControl/>
│   │   ├─ <ExerciseCard/> <PrereqChecklist/>
│   ├─ <GraphView>  → <ForceGraph/> <GraphFilters/> <NodeInspector/>
│   ├─ <ExecuteView> → <RunConfig/> <CycleTable/> <AgentIndicator/> <ArtifactDiff/>
│   └─ <MemoryView>  → <RootPicker/> <FileViewer/> <DecisionTimeline/>
├─ <ContextPanel>                          dockable right
│   ├─ <RetrievedChunks/> <ActiveAgent/> <MissionStateSummary/> <OpenQuestions/>
└─ <ActivityDrawer>                        bottom, collapsible
    ├─ <TaskQueue/> <DispatchTimeline/> <LogTail/>
```

## 5.3 State architecture

```ts
// Zustand slices (client state only — server data lives in TanStack Query)
ui:       { view, missionId, panelOpen, drawerOpen, paletteOpen, keymap }
coach:    { recommendations[], accepted[], dismissed[] }        // + persistence
execution:{ running: {missionId, skill, cycle} | null }         // SSE-fed

// TanStack Query keys (all backed by files/SQLite via API; UI never owns truth)
['missions'] ['mission', id] ['mission', id, 'tasks'|'memory'|'artifacts']
['concepts'] ['graph'] ['search', q] ['metrics'] ['coach'] ['health']

// Live updates: single SSE channel /api/events multiplexes
//   dispatch_started/finished · cycle_completed · memory_updated · recommendation_added
// SSE handler → invalidate matching query keys (no client-side state math)
```

Invariant: **the UI is a cache of files.** Every mutation goes through the
API → skill dispatch → files change → SSE → query invalidation. The UI never
computes progress, confidence, or status locally.

---

# 6. Backend Architecture

## 6.1 Topology

```
:8003 learn_agent (FastAPI) — the AIOS gateway (product surface)
 ├─ serves the React bundle
 ├─ /api/* thin handlers                       (no business logic)
 │    ├─ mission_service.py     Mission CRUD = files + SQLite index
 │    ├─ corpus_service.py      registry CRUD + ingest dispatch (§6.5.2)
 │    ├─ coach_service.py       trigger scan (deterministic) + LLM ranking
 │    ├─ graph_service.py       assembles graph JSON from stores
 │    └─ tutor bridge           agent.py, now emitting concept upserts
 │        (all retrieval anywhere above goes through the Gateway — §6.5.3)
 └─ imports brain/runtime dispatcher DIRECTLY (same host, python API —
    no HTTP hop; the runtime is a library, not a service)

brain/runtime  — unchanged (D12)
second_brain/  — unchanged
memory/        — gains missions/ subtree (per-mission memory roots)
```

New agent-type skills (contract cards only — LLM via adapter, per D12):
`architect` (requirements → components/dataflow/decisions), `code_generator`
(task + context → code artifact + test), `teacher` (formalizes agent.py's
tutor as a skill so metrics/observability cover teaching too).

## 6.2 API design (new surface; old endpoints kept during migration)

```
GET  /api/health                 dashboard aggregates (extends console pattern)
GET  /api/events                 SSE: dispatch/cycle/memory/recommendation events

POST /api/missions               {title, type, goal, criteria} → scaffolds memory root
GET  /api/missions               list + computed progress
GET  /api/missions/{id}          full mission object (files parsed)
PATCH/api/missions/{id}          status changes (pause/close → lessons-learned prompt)
POST /api/missions/{id}/run      dispatch run_loop (one at a time; 409 else)
GET  /api/missions/{id}/status   cycle table (console pattern)
POST /api/missions/{id}/tasks    add plan.md item        (writes the FILE)
PATCH/api/missions/{id}/tasks/{tid}  check off / edit    (writes the FILE)
GET  /api/missions/{id}/artifacts

POST /api/ask                    KEPT — now accepts {mission_id?, mode, depth}
POST /api/teach                  Socratic/exercise/compare modes; on completion
                                 → concept_store.upsert (unverified) → critic
GET  /api/search?q=&mission_id=  Retrieval Gateway dispatch (corpus-scoped,
                                 cited chunks w/ corpus + confidence)

GET  /api/corpora                registry list + stats
POST /api/corpora                register a corpus {id, name, source_dirs, ...}
POST /api/corpora/{id}/ingest    (re)build that corpus index (dispatch)
GET  /api/corpora/{id}/stats     files/chunks/last_ingested/retrieval hits
PATCH/api/missions/{id}/corpora  reconfigure mission↔corpus mapping + cross_corpus

GET  /api/concepts               store + confidence (graph node source)
GET  /api/graph                  {nodes[], edges[]} assembled server-side
GET  /api/coach                  current recommendations (ranked)
POST /api/coach/{rec_id}/accept  dispatches the underlying action
POST /api/coach/{rec_id}/dismiss logged for preference weighting
GET  /api/metrics                metrics.jsonl tail (execution history)
GET  /api/memory/{root}/{file}   memory viewer (traversal-blocked)
```

## 6.3 Database changes

Files remain source of truth (D8/D9). SQLite is an **index, rebuildable from
files at any time** — the same relationship concepts.json has to
knowledge_cache.md.

```sql
-- learn_agent/data/aios.db  (all derivable; DROP-safe)
missions(id, slug, title, type, goal, status, memory_root, cross_corpus, created, updated);
mission_corpora(mission_id, corpus_id);              -- mission↔corpus mapping (req. 2)
corpora(id, name, index_path, reliability, files, chunks, last_ingested);  -- mirror of registry.json
tasks(id, mission_id, plan_item_id, description, status, updated);   -- mirror of plan.md
concept_links(mission_id, concept_name, kind);       -- required|learned|gap
retrieval_stats(corpus_id, source, hits, last_hit);  -- per-corpus usage (from gateway)
recommendations(id, ts, trigger, action_json, evidence, status);  -- pending|accepted|dismissed
insights(id, mission_id, ts, text, source_corpus, source);
events(id, ts, type, payload_json);                  -- SSE replay buffer (ring)
```
Migration cost: zero for existing data — the chunk index and concepts.json
are untouched; missions start empty and two seed missions are generated from
existing artifacts (stock_agent → "Build AI Stock Analysis Platform" with
plan reconstructed from its CLAUDE.md phases; vedic_astro likewise).

## 6.4 Knowledge graph assembly (no graph DB)

Nodes = concepts.json ∪ index sources (books) ∪ missions ∪ skills ∪ tags
(technologies/frameworks from manifest+book tags) ∪ papers (source subtype).
Edges = concept relationships (typed, exist) ∪ concept→source (from
`sources[]`) ∪ mission→concept (concept_links) ∪ skill→skill (registry deps)
∪ book→category ∪ corpus→source (§6.5). Assembled on demand, cached 60s.
GraphRAG only if this measurably fails (RAG Maturity Ladder).

## 6.5 Corpus Manager & Retrieval Gateway (v1.1 — supersedes the "default corpus" question)

### 6.5.1 Principle

There is no default corpus. Knowledge is partitioned into **independent,
named corpora**; every mission declares which ones it thinks with; every
retrieved chunk carries provenance back to its corpus. Skills never know
index paths exist.

### 6.5.2 Corpus Manager

Source of truth: `memory/corpora/registry.json` (files-first, D8/D9; SQLite
mirrors stats only). One entry per corpus:

```json
{
  "id": "ai-books",
  "name": "AI Books",
  "description": "170+ books on agentic AI, LLMs, generative AI",
  "source_dirs": ["~/Documents/brain/.../raw/library/agentic-ai", "..."],
  "index_path": "memory/corpora/ai-books/chunks.json",
  "ingest_profile": {"extensions": [".md", ".txt"], "chunk_size": 1200},
  "reliability": 1.0,          ← provenance weight (personal-notes < published books)
  "tags": ["books", "ai"],
  "stats": {"files": 0, "chunks": 0, "last_ingested": null}
}
```

Seed corpora (from existing assets — no re-ingestion invention):
| id | seeded from |
|---|---|
| `ai-books` | learn_agent's 170-book index (adopted as-is, re-homed) |
| `research-papers` | learn_agent's 31 papers (split out of the same index by source tag) |
| `curated-wiki` | second_brain's 36-file verified index (adopted as-is) |
| `finance` | ~/Desktop/AI/Applied AI in Finance |
| `astrology` | vedic_astro book corpus (23 books, existing KB) |
| `personal-notes` | Obsidian vault notes/ (excl. raw/library) |
| `current-project` | per-mission workspace docs (auto-refreshed on run) |
| `product-management`, `web-knowledge` | registered empty; ingest on demand |

Operations (all via runtime dispatch — `book_ingestion` gains an
`index_path` parameter; the ONE backend change this design requires):
`create · ingest/refresh · stats · retire (never silently delete)`.
This also retires the known limitation that `second_brain/ingest.py` writes a
single fixed INDEX_PATH — the "one index world" problem disappears
structurally instead of being worked around.

### 6.5.3 Retrieval Gateway

Location: `second_brain/gateway.py`, exposed to skills through the existing
`retrieve_context` skill (manifest v2.0.0 — breaking: `index_path` input
removed). The ONLY retrieval entry point in the system:

```
retrieve(query, mission_id=None, top_k=5, corpora=None, cross_corpus=None)
```

Skills call `retrieve(query, mission)` — never an index name. Resolution:

```
1. SCOPE      mission_id → mission.corpora  (explicit corpora arg = operator
              override, logged as such; no mission & no override → error:
              "no corpus scope" — scope is never guessed)
2. FAN-OUT    query each in-scope corpus index (same TF-IDF core per corpus)
3. NORMALIZE  raw TF-IDF scores are NOT comparable across corpora (different
              df distributions) → per-corpus min-max normalize to [0,1],
              then multiply by corpus.reliability
4. MERGE+RANK single ranked list on normalized score
5. DEDUP      near-duplicate collapse via 8-gram shingle overlap ≥ 0.8
              (same book in two corpora returns once; provenance keeps BOTH
              corpus ids on the surviving hit)
6. CONFIDENCE hit.confidence = normalized_score × reliability; result-set
              confidence = max(hit confidences) — feeds evidence_validation
7. PROVENANCE every hit: {corpus_id(s), source, chunk_id, raw_score,
              normalized_score, reliability}
8. CROSS-CORPUS if fewer than top_k hits AND mission.cross_corpus=true →
              widen to all corpora; every widened hit is flagged
              "cross_corpus": true (the UI renders these visually distinct;
              the coach may recommend adding that corpus to the mission)
```

Gateway output contract (what retrieve_context v2 emits):
```json
{"hits": [{"text", "source", "corpus": "finance", "confidence": 0.81,
           "cross_corpus": false, "chunk_id": 3}],
 "n": 5, "scope": ["finance", "curated-wiki"], "widened": false}
```

### 6.5.4 Provenance in memory (requirement 6)

- **concepts.json**: `sources[]` entries become structured —
  `{"corpus": "finance", "source": "hilpisch-py-algo.md"}` (migration: string
  entries auto-wrapped with `corpus: "curated-wiki"`, the only corpus that
  existed). The critic's corroboration check becomes corpus-aware: a claimed
  source must be found in its claimed corpus.
- **retrieval.md / mission logs**: every retrieval logged as
  `query → corpus:source (conf)` — one line, compression-compliant.
- **Learn mode**: a concept taught from `personal-notes` evidence enters the
  store with that provenance and a correspondingly lower ceiling on critic
  confidence (reliability weight) — published-book claims and my-own-notes
  claims are never conflated.

### 6.5.5 Contract changes (documented for P0, not yet implemented)

| artifact | change | semver |
|---|---|---|
| retrieve_context skill | input {query, mission_id?, corpora?}; output +corpus/confidence/provenance | 2.0.0 (breaking) |
| rag_search skill | passes mission scope through; citations carry corpus | 2.0.0 |
| book_ingestion skill | +`index_path`, +`corpus_id` inputs | 1.1.0 (compatible) |
| evidence_validation | corpus-aware corroboration | 1.1.0 |
| gateway | NEW module + contract card in registry | 1.0.0 |
| corpora registry.json | NEW memory file (files-first) | — |

UI touchpoints: mission creation requires picking ≥1 corpus; context panel
shows corpus badge per retrieved chunk; cross-corpus hits get a distinct
badge; Corpus Manager screen (list, stats, ingest button) joins the Memory
view as V6b.

---

# 7. Migration Strategy

Old product keeps working at every step; each phase ships usable value.

1. **Parallel mount** — new API under `/api/*`; legacy `/ask`, `/learning-path`
   untouched; React app served at `/app` until parity, then swapped to `/`.
2. **Read-only first** — dashboard/mission views over *existing* data (two
   seed missions, concepts, metrics) before any write path. Proves the render-
   the-notebook model with zero risk.
3. **Write paths via skills only** — task edits, teach-upserts, runs all go
   through dispatcher (memory permissions enforced — no new write code).
4. **Legacy sunset** — `/ask` becomes an alias of `/api/ask`; old single-page
   UI kept at `/legacy` for one phase, then removed.
5. **Rollback** = serve old HTML again; SQLite is derived, files never at risk.

---

# 8. Execution Roadmap (priority = impact ÷ risk)

**P0 — Corpus foundation + mission spine (makes it an AIOS, ~1.5 wk)**
*(regenerated for v1.1 — the gateway now precedes everything, because missions
declare corpora at creation and every later feature retrieves through it)*
1. **Corpus Manager**: `memory/corpora/registry.json` + `book_ingestion` v1.1
   (`index_path`/`corpus_id` params) + seed 3 corpora from existing indexes
   (ai-books, curated-wiki, finance) — zero re-chunking where indexes exist
2. **Retrieval Gateway** (`second_brain/gateway.py`): scope→fan-out→normalize→
   merge→dedup→confidence→provenance; `retrieve_context` skill v2.0.0;
   gateway unit tests (score normalization, dedup, no-scope error,
   cross-corpus flagging) BEFORE any UI consumes it
3. **Mission model**: scaffolding + SQLite index + `mission_corpora` mapping;
   mission creation requires ≥1 corpus; seed 2 missions from real projects
   (stock_agent → finance+curated-wiki; multi-agent-learning → ai-books)
4. **Shell UI**: sidebar + dashboard (V1) + mission workspace (V2, read-only);
   context panel shows corpus badge + confidence per retrieved chunk
5. **Command palette + keyboard nav** (the feel is the product)
   *Exit criteria: create a mission scoped to `finance` → search returns ONLY
   finance chunks with corpus provenance → enable cross_corpus → widened hits
   arrive visibly flagged → concepts store structured {corpus, source}.*

**P1 — The proactive loop (makes it an agent, ~1 wk)**
5. Coach service: 7 deterministic triggers + ranked card + accept/dismiss
6. Execute mode (V5): run_loop + SSE cycle table + active-agent indicator
7. Task write-path (plan.md via dispatch) + Today's Focus
   *Exit: the system recommends a next action every morning and can execute it.*

**P2 — The learning system (makes it a companion, ~1-2 wk)**
8. Learn mode (V3): Socratic/exercise/compare modes; teach→upsert→critic loop
9. Retention queue (spaced repetition from concept timestamps)
10. Knowledge graph (V4) + node inspector
    *Exit: completing a lesson measurably updates concepts.json and the coach notices.*

**P3 — Depth (makes it an architect/executor)**
11. architect + code_generator skills (adapter-gated) + artifact diff viewer
12. Contradiction detection (paired evidence_validation)
13. Memory browser (V6) + insights stream + lessons-learned flow
14. Multi-mission execution queue; preference-weighted coach ranking

Explicit non-goals v1: mobile, multi-user, cloud sync, embeddings (until
TF-IDF measurably fails), auto-executing recommendations without acceptance.

---

# 9. Risks & honest notes

- **Coach quality is the product risk.** Deterministic triggers guarantee a
  floor (recommendations always cite evidence); LLM ranking is only ordering.
  Ship triggers first, measure acceptance rate, iterate.
- **Two index worlds — RESOLVED by §6.5**: both become registered corpora
  behind the gateway; "default corpus" is no longer a concept. New risks it
  introduces: (a) cross-corpus score normalization is heuristic — min-max per
  corpus can overrank a weak corpus's best hit; mitigated by the reliability
  weight and by logging raw + normalized scores so ranking bugs are auditable.
  (b) shingle dedup at 0.8 may miss paraphrased duplicates across corpora —
  acceptable; provenance keeps both visible. (c) gateway is a single choke
  point — deliberately so (one place to upgrade rungs per RAG Maturity
  Ladder), covered by its own unit tests before any consumer ships.
- **progress% is computed** from plan.md — missions without granular plans
  will show misleading numbers; mitigate by requiring ≥3 tasks at creation.
- **One planner run at a time** initially (proven console constraint);
  multi-run queueing is P3, not a P0 promise.
```

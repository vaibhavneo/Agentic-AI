# MISSION CONTROL — architecture

Mission Control is the primary interface for AIOS: a mission-centric,
keyboard-first dashboard that becomes the **default landing page** at `/`
(port 8003), superseding the mission-workspace shell (`/app`, unchanged) as
the first thing an operator sees. Read `PROJECT_CHARTER.md` →
`AIOS_HANDBOOK.md` → `IMPLEMENTATION_PLAYBOOK.md` first.

**Status:** implemented and tested (`learn_agent/tests/test_mission_control.py`,
20/20 checks; full platform regression 10/10 suites green).

---

## 1. Implementation note — vanilla JS now, React documented as the target

The ten dashboard panels, command palette, dockable panels, and keyboard
interactions below are **implemented in vanilla JS** (`mission_control.html`),
reusing the proven CSS/palette pattern from `aios.html` (P0's shell). This is
a deliberate, transparent choice, not a silent substitution:

- No app in this repository uses a JS build pipeline (React/Vite/npm) today —
  every surface (vedic_astro, stock_agent, the operator console, the P0 AIOS
  shell) is a FastAPI/Flask app serving a hand-written HTML+JS file.
  Introducing the first build toolchain in the repo is itself an architectural
  decision, not something to do silently inside a feature request.
- `LESSONS.md` §2 already recorded this exact tradeoff for the P0 shell:
  *"React+Vite for P0 shell — rejected in favor of zero-build single page…
  React remains the documented target if UI complexity grows."* Mission
  Control is that growth point — so this document does its job: it specifies
  the React architecture below as the **target**, so migrating is a
  translation of an already-designed component tree and state model, not a
  redesign. The working, tested, shipped implementation is vanilla JS.
- If/when the migration happens: `npm create vite@latest`, port §3/§4 below
  component-for-component, keep the same `/api/mc/*` contract (§5) — the
  backend does not change either way.

## 2. Wireframes

### 2.1 Overview (default view at `/`)

```
┌ 🛰️ Mission Control    [⌘K — go to mission, panel, search, create…]   3 missions · 25,935 chunks · 11 skills ┐
├──────────┬─────────────────────────────────────────────────────────────────────┬─────────────────────────┤
│ MISSIONS │ 1 CURRENT MISSIONS (2/3 width)      2 TODAY'S PRIORITIES            │ CONTEXT                 │
│ ▸ Stock  │  Build AI Stock Platform  72% ████░ │ • Run: wire hit-rate to UI    │ Recommended next        │
│ ▸ Learn  │  Learn Multi-Agent Sys    45% ██░░░ │   ev: plan.md task #5         │  actions (live, 15s     │
│ MASE     │                                     │ • Verify: Grounding Beats Gen │  poll)                  │
│ ▾ Views  │ 3 LEARNING PROGRESS   4 KNOWLEDGE    │   ev: confidence 0.28 < 0.6   │                         │
│  Mission │  concepts: 10          GROWTH        │                               │ Pending decisions       │
│  Control │  mean conf: 0.91       ai-books 25.8k│ 5 PROJECT STATUS              │  (open questions        │
│  Mission │  supported: 9          curated-w  96 │  Stock Platform      72%      │  across missions)       │
│  Workspce│  unsupported: 1        personal   127│                               │                         │
│          │                                      │ 6 RECENT INSIGHTS             │                         │
│ ↺ reset  │                                      │  RAG Maturity Ladder  1.00    │                         │
│  layout  │                                      │  Grounding Beats Gen  0.28    │                         │
│          │ 7 ARCHITECTURE HEALTH  8 MEMORY STATUS│                              │                         │
│          │  skills: 11             global: ok    │ 9 PENDING DECISIONS           │                         │
│          │  success: 76% (100)     missions: ok  │  none currently               │                         │
│          │  [Run self-check]                     │                               │                         │
│          ├─────────────────────────────────────────────────────────────────────┤                         │
│          │ 10 ACTIVITY TIMELINE / EXECUTION LOG  (wide, scrollable, newest first) │                         │
│          │  08:45:59 memory_compression 0.2ms                                    │                         │
│          │  08:45:58 critic 8.4ms                                                │                         │
└──────────┴─────────────────────────────────────────────────────────────────────┴─────────────────────────┘
```

Each numbered panel header is clickable to collapse/expand (dockable, per
requirement); collapse state persists in `localStorage` (persistent session
state, requirement). Panel 10 spans the full width (`wide`); panels 1/2 span
2/1 columns on a 3-column grid; the rest are single-width.

### 2.2 Command palette (⌘K overlay)

```
┌────────────────────────────────────────────┐
│ Type a command… (esc to close)             │
├────────────────────────────────────────────┤
│ Go to Mission Control              view    │
│ Open Mission Workspace              view   │
│ Run self-check                     action  │
│ Refresh dashboard                       r  │
│ Open: Build AI Stock Platform  mission 72% │
│ Open: Learn Multi-Agent Systems mission 45%│
└────────────────────────────────────────────┘
```

### 2.3 Help overlay (`?`)

```
┌─────────────────────────────┐
│ ⌘K / Ctrl+K   command palette│
│ 1–9           toggle panel N │
│ r             refresh        │
│ ?             this help      │
│ Esc           close overlay  │
└─────────────────────────────┘
```

## 3. React component hierarchy (target architecture)

```
<MissionControlApp>                          top-level; owns polling + layout persistence
├── <TopBar>
│   ├── <Logo/>
│   ├── <CommandPaletteTrigger onOpen={openPalette}/>
│   └── <StatusStrip missions corpora skills/>          (missions·chunks·skills summary)
├── <Shell>
│   ├── <MissionSidebar>
│   │   ├── <MissionList> → <MissionListItem/>*         (progress-badged, click → workspace)
│   │   ├── <NewMissionLink/>                            (→ /app, mission creation lives there)
│   │   ├── <ViewSwitcher/>                               (Mission Control | Mission Workspace)
│   │   └── <LayoutResetButton/>
│   ├── <DashboardGrid>                                   dockable-panel container (CSS grid)
│   │   ├── <Panel id="missions" span={2}><CurrentMissionsWidget/></Panel>
│   │   ├── <Panel id="priorities"><TodaysPrioritiesWidget/></Panel>
│   │   ├── <Panel id="learning"><LearningProgressWidget/></Panel>
│   │   ├── <Panel id="knowledge"><KnowledgeGrowthWidget/></Panel>
│   │   ├── <Panel id="project"><ProjectStatusWidget/></Panel>
│   │   ├── <Panel id="insights"><RecentInsightsWidget/></Panel>
│   │   ├── <Panel id="arch"><ArchitectureHealthWidget onRunSelfCheck/></Panel>
│   │   ├── <Panel id="memory"><MemoryStatusWidget/></Panel>
│   │   ├── <Panel id="decisions"><PendingDecisionsWidget/></Panel>
│   │   └── <Panel id="timeline" span={3}><ActivityTimelineWidget/></Panel>
│   └── <ContextPanel>                                    right rail
│       ├── <RecommendedActionsList/>
│       └── <PendingDecisionsList/>
├── <CommandPalette open items onSelect/>                  fuzzy-filter overlay
└── <KeyboardHelpOverlay open/>                             `?`
```

`<Panel>` is the one reusable primitive: `{id, title, index, span, collapsed,
onToggle, children}` — collapse state lifts to `MissionControlApp` (persisted),
everything else is presentational. This mirrors the vanilla-JS `panel()`
helper function 1:1 — the shipped implementation already factors the UI this
way, which is exactly what makes the React port mechanical rather than a
redesign.

## 4. State management (target: React; shipped: equivalent vanilla JS)

```ts
// Server state — one query, refetched on an interval (React Query / SWR
// shape; the shipped JS does the equivalent with a 15s setInterval + fetch)
useQuery(['mc-summary'], () => fetch('/api/mc/summary').then(r => r.json()), {
  refetchInterval: 15000,          // real-time mission progress (requirement)
  refetchIntervalInBackground: false,   // pause when tab hidden (shipped: `if(!document.hidden)`)
})
// Granular per-panel refetch (e.g. after "Run self-check") invalidates just
// ['mc-summary'] — the bundle is the single source of truth for all 10 panels,
// avoiding 10 separate polling loops.

// Client / session state (Zustand-equivalent; shipped: localStorage + module vars)
interface MissionControlState {
  paletteOpen: boolean
  helpOpen: boolean
  panelLayout: Record<PanelId, {collapsed: boolean}>   // persisted → localStorage('mc_layout_v1')
  activeView: 'overview'                                // room for future views
}
```

Why this split: server data (missions, health, timeline) is always a read
of files the SDK already owns — it is **never** client-authored, so it is
pure query-cache state, refetched, never mutated locally (P1/P2: the UI is a
view over files, not a second store — same invariant the P0 shell already
follows for mission data). Only layout/UI state (which panels are collapsed,
whether an overlay is open) is genuinely client-local, hence `localStorage`
+ a tiny store rather than anything server-synced.

## 5. Backend (unchanged principle: thin surfaces, existing runtime APIs only)

```
learn_agent/
  mission_control_service.py   aggregation ONLY — every function reads through
                               aios_core.{mission,retrieval,memory,skill,workflow}
                               or a direct read of files the SDK already owns
                               (concepts.json, metrics.jsonl). Zero skill logic
                               duplicated (verified: test_no_duplicated_backend_logic).
  mission_control_api.py       one-line FastAPI route wrappers over the service
                               + the `/` route (Mission Control is now the
                               default landing page — DoD).
```

`GET /api/mc/summary` bundles all 10 panels in one call (perceived-latency:
1 request, not 10) — mirrors the existing pattern of the operator console's
`/api/health`. Granular endpoints (`/api/mc/missions`, `/priorities`, …) exist
for independent panel refresh without a full-page reload.

One genuinely new piece of logic: `recommended_actions()` / `today_priorities()`
are a **deliberately small, labeled proto-coach** — 3 deterministic triggers
(next unchecked task, stale mission, low-confidence concept) computed purely
from files already on disk. This is NOT the Coach Service
(`IMPLEMENTATION_PLAYBOOK.md` M-P1a, 7 triggers + accept/dismiss persistence);
it exists so Mission Control has real, evidence-cited priorities on day one,
and is explicitly documented (in the module docstring) as superseded once
M-P1a ships — nothing should be extended here in place of building M-P1a.

`architecture_health()` deliberately does NOT run the 9-suite regression on
every dashboard load (too slow for a panel refresh) — it reports skill
registry size + recent dispatch success rate from `metrics.jsonl` (cheap,
real execution history). The actual deep check
(`brain/workflows/self_check.workflow.json` — evaluator → critic → memory
audit) runs on demand via the "Run self-check" button /
`POST /api/mc/health/run-self-check`, mirroring the operator console's
existing health-vs-validation split.

## 6. Keyboard-first interactions

| key | action |
|---|---|
| `⌘K` / `Ctrl+K` | open command palette |
| `1`–`9` | collapse/expand panel N (numbered per §2.1) |
| `r` | refresh dashboard (re-fetch `/api/mc/summary`) |
| `?` | keyboard help overlay |
| `Esc` | close palette / help |
| `↑`/`↓`/`Enter` (palette open) | navigate / execute command |

## 7. Operator documentation

See `learn_agent/MISSION_CONTROL_GUIDE.md`.

## 8. Tests

`learn_agent/tests/test_mission_control.py` — 20 checks: the DoD itself
(`/` serves Mission Control, `/legacy` and `/app` still work), all panel
endpoints return real SDK data, the on-demand self-check actually dispatches
the real workflow, recommendations cite evidence (P6/P7), and a source-level
check that the service module never imports `second_brain`/`corpus_manager`
directly (retrieval only through the SDK) or reimplements the self-check
workflow. Full platform regression: 10/10 suites green after this change.

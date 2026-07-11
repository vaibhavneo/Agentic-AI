# Mission Control — Operator Guide

Mission Control is the default landing page for AIOS: `http://localhost:8003/`.
Start the server: `cd learn_agent && python3 server.py`.

## What you see

| panel | what it shows | where the data comes from |
|---|---|---|
| Current Missions | every mission, progress bar | `mission.list_all()` (files) |
| Today's Priorities | top 3 recommended actions | next unchecked task, stale missions, low-confidence concepts — see caveat below |
| Learning Progress | concept counts, mean confidence, supported/partial/unsupported | `memory/concepts.json` (critic-verified) |
| Knowledge Growth | chunks per corpus, current snapshot | corpus registry (`memory/corpora/registry.json`) |
| Project Status | missions of type `build`, their progress | same mission data, filtered |
| Recent Insights | most-recently-updated verified concepts | `concepts.json`, sorted by `updated` |
| Architecture Health | skills registered, recent dispatch success rate | `metrics.jsonl` (last 100 dispatches) |
| Memory Status | compliance audit, global + per mission | the `memory_compression` skill via the SDK |
| Pending Decisions | open questions across all missions | each mission's `questions.md` |
| Activity Timeline / Execution Log | recent skill dispatches, newest first | `metrics.jsonl` |

## Caveat: "Today's Priorities" is a stand-in, not the real Coach

The recommendations you see are computed from **3 simple, deterministic
rules** (next unchecked task per active mission, missions untouched 5+ days,
concepts below 0.6 confidence) — every one cites its evidence so you can
verify it yourself. This is intentionally lightweight: the real Coach Service
(7 trigger scanners, accept/dismiss history, ranking) is a separate,
not-yet-built milestone (`IMPLEMENTATION_PLAYBOOK.md` M-P1a). Treat today's
priorities as a floor, not a final answer.

## Actions available

- **Run self-check** (Architecture Health panel) — triggers the platform's
  real `self_check` workflow (the same one `AIOS_HANDBOOK.md` §8 describes):
  runs the pipeline/skill-package/runtime test suites, re-verifies every
  concept with the critic, and audits memory compliance. Takes a few seconds;
  result is cached and shown as "last self-check" on future loads.
- **Collapse/expand any panel** — click its header, or press `1`–`9` (panels
  are numbered left-to-right, top-to-bottom as in the dashboard). Layout is
  remembered per browser (`localStorage`) — refresh the page and it stays.
- **⌘K / Ctrl+K** — command palette: jump views, open a mission (goes to
  Mission Workspace, where mission detail/tasks/search live), run self-check,
  refresh.
- **`r`** — manual refresh. The dashboard also auto-refreshes every 15
  seconds while the tab is visible (paused when backgrounded, to avoid
  needless load).
- **`?`** — keyboard shortcut reference.

## Where the rest of the workspace lives

Mission Control is the *overview*. Creating missions, editing tasks, running
a mission's planner loop, mission-scoped search, and the memory-file viewer
are all in the **Mission Workspace** at `/app` (unchanged from P0) — reachable
from the sidebar ("Mission Workspace") or the command palette. The legacy
book tutor (the original `/ask` chat interface) still works, moved to
`/legacy`.

## If something looks wrong

- **A panel shows stale data** — press `r` or wait for the 15s auto-refresh.
- **Architecture Health shows a low success rate** — check the Activity
  Timeline panel for the failing skill, then run the full validation
  checklist (`IMPLEMENTATION_PLAYBOOK.md` §V) from a terminal for detail.
- **Memory Status shows "issues"** — the compliance audit lists them by name
  (e.g. an over-long log line); fix the named file, the badge clears on the
  next refresh.
- **A recommendation seems wrong** — every one names its evidence (a plan.md
  task id, a confidence number, a file mtime). If the evidence itself is
  stale or wrong, that's a data problem in the underlying mission/concept
  file, not in the dashboard.

## Tests

`python3 learn_agent/tests/test_mission_control.py` — verifies Mission
Control is served at `/`, every panel's data endpoint works, self-check
actually runs, and recommendations always cite evidence.

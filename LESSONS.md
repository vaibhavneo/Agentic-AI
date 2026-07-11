# LESSONS — extracted knowledge from the architecture sessions

What a future implementer cannot derive from the code alone: tradeoffs taken,
alternatives rejected, bugs that taught us rules, and known risks.
ADRs (the decisions themselves) live in `memory/decisions.md` (D1–D12);
this file is the narrative around them.

---

## 1. Lessons learned (each one is now a rule somewhere)

- **L1 — LLMs invent numbers confidently.** The stock agent's original
  entry/target/stop were pure LLM fiction; the vedic agent invented house
  lords for a Taurus lagna. Fix pattern both times: compute the fact, inject
  as labeled ground truth, instruct "cite, don't derive." → Charter P4.
- **L2 — Context beats wording.** The astrology chat hallucinated because the
  browser sent a truncated 5,000-char summary — not because the prompt was
  badly phrased. Recomputing authoritative context server-side fixed it
  instantly. → concept "Context Engineering Over Prompt Tweaking".
- **L3 — Raw TF-IDF idf goes negative on tiny corpora** (`log(n/(1+df))` when
  df≈n), silently making 1–2-chunk corpora unretrievable. Found only because
  a gateway test used a synthetic 1-file corpus. Fixed with sklearn-style
  smoothed idf. Meta-lesson: deterministic synthetic fixtures find bugs that
  realistic data hides.
- **L4 — Metrics must be dimensionally sane.** MaxDD of 32× (3,200% drawdown)
  shipped because the book's literal formula (absolute drawdown) was
  transcribed without asking "can this exceed 1.0?" Every metric needs a
  bounds check in its test (e.g., "max_drawdown in [0,1]").
- **L5 — A losing strategy 'agreeing' is not support.** Grounding originally
  accepted any direction-matching strategy; a negative-Sharpe rule confirmed
  a BUY at HIGH conviction. Rule: agreement requires a positive edge.
  Generalization: corroboration must itself be credible, not merely aligned.
- **L6 — Per-corpus scores are not comparable.** Different df distributions
  make cross-corpus ranking meaningless without normalization; min-max per
  corpus × reliability weight is the current heuristic (audit trail: raw +
  normalized both stored on every hit).
- **L7 — Tests must own their state.** Two incidents: a planner test reusing
  a persistent memory root (resumed already-STABLE — which proved
  resumability but broke the assertion), and module-identity in retries
  (arming `drivers.echo_driver` while the executor imported
  `runtime.drivers.echo_driver` — two module objects). Import via the
  executor's exact module path; wipe scratch roots.
- **L8 — Python 3.9 + FastAPI**: `str | None` in route signatures fails at
  runtime (evaluated annotations). Use `typing.Optional`.
- **L9 — macOS sandboxed preview tools can't read Desktop paths** (TCC).
  Launch dev servers via plain shell; `.claude/launch.json` needs `cwd` not
  absolute script paths.
- **L10 — Adopt, don't re-chunk.** curated-wiki was adopted into the corpus
  system as-is (zero cost); learn_agent's 52MB pickle index was NOT adoptable
  (incompatible format) — its *sources* were registered instead. Check index
  formats before promising adoption.

## 2. Rejected alternatives (don't relitigate without new evidence)

| rejected | in favor of | why |
|---|---|---|
| Vector DB / embeddings at start | pure-python TF-IDF | no external deps; upgrade rung documented (RAG maturity ladder); revisit only when keyword recall measurably fails |
| LangChain/LangGraph/CrewAV as base | contract runtime + dispatcher | topology is simple; frameworks would own the seams we need to control (memory permissions, typed failures) |
| In-memory dict stores | SQLite (durable) or JSON files (rebuildable) | restart-survival was required (stock tracking); files-first for anything a human should read |
| LLM-as-critic self-grading | deterministic scoring (retrieval_support + corroboration) | a generator grading itself reintroduces the hallucination loop (D10) |
| Default retrieval corpus | mission-declared scope, no default | operator decision (v1.1 amendment): scope must be explicit; cross-corpus opt-in + flagged |
| Single shared chunk index | per-corpus indexes behind a gateway | "one index world" caused the console's replace-on-ingest wart; structurally retired |
| Per-varga house-lord tables (astrology) | D-1-only lordship convention | printing per-divisional lords induced the model to misattribute lordships |
| skill.yaml manifest format | manifest.json | one machine format, one parser (stdlib json); content parity is what matters |
| React+Vite for P0 shell | zero-build single page | walking skeleton speed; React remains the documented target if UI complexity grows (architecture §5) — an explicitly deferred, not rejected, choice |
| Full-history ingestion of all 456 books at P0 | curated-first + per-category corpora | signal density; 53MB/25.8k chunks for ONE category already tests retriever limits |

## 3. Known risks & performance notes

- **ai-books scale**: 25,812 chunks ≈ seconds of first-query latency per
  process (tokenize-on-load); per-corpus retriever cache mitigates within a
  process. Next rungs if it hurts: precomputed token cache on disk → SQLite
  FTS5 → embeddings. Don't skip rungs.
- **Cross-corpus normalization is a heuristic** (L6): a weak corpus's best
  hit gets norm 1.0. Reliability weights + audit fields are the guard;
  a learned weighting is future work, gated on logged evidence.
- **Coach quality is the product risk** for P1 (architecture §9): triggers
  give an evidence-backed floor; measure acceptance rate before adding LLM
  cleverness.
- **Single-user assumptions**: last-write-wins on plan.md edits; one planner
  run at a time per surface. Fine now; revisit only with real concurrency.
- **DeepSeek key path**: RESOLVED (D19, 2026-07-10) — distill.py's automated
  LLM path was retired, not exercised: no caller depended on it and it
  violated P9 (direct Retriever) and D9 (wrote the rendered knowledge_cache).
  Distillation is the model-agnostic `concept_distillation` skill; a model
  wires in through the adapter seam (as M-P2a's teacher will), never an inline
  vendor SDK. Lesson: a "known limit" that is dead, contract-violating code is
  a retire signal, not a backlog item.
- **Finance corpus is PDFs**: ingest via pypdf is minutes-slow and
  extraction-lossy; expect lower retrieval quality than md corpora — that's
  partly why its reliability is 0.9.

## 4. Best practices proven here (adopt by default)

- Ground-truth tests against external sources (book values: dSR 3.255≈3.26,
  Kelly ≈4.5, Hilpisch EUR/USD) catch transcription errors self-tests can't.
- Synthetic negative controls everywhere: gibberish→empty retrieval,
  losing-strategy→rejected, hypothesis-without-kill-test→OUTPUT_INVALID.
- Every system audits itself through its own machinery (self_check workflow
  runs the platform's tests via the platform's runtime).
- When a reviewer/critic finds a defect, fix the *record* (data) or the
  *rule* (code), never the verdict (D11) — this happened live: the critic
  caught a malformed source record on its first run.

## 5. Future recommendations (non-binding)

- Wire gateway retrieval stats into corpus registry (needed by the
  hot-unread-book trigger anyway).
- Promote per-mission `current-project` corpora (auto-refresh on run) — designed, unbuilt.
- Consider extracting brain/runtime as a standalone package once a second
  deployment exists; until then, don't (YAGNI).
- The stock agent's outcome-checker (`/api/track/check`) is on-demand; a
  scheduled sweep would make hit-rate data accumulate without manual action —
  that data is what upgrades grounded confidence from "no history yet".

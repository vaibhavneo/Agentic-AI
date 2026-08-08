# Safety

HealthPilot AI is **not a diagnostic system**. This document describes the concrete mechanisms — not just the intent — that keep it that way. Every rule below is enforced in plain Python that ships independently of any LLM call; the LLM's system prompts *also* state these rules (`agents/specialists.py::SAFETY_PREAMBLE`) as a second layer, but the enforcement doesn't depend on the model following instructions.

## What the app must never do

| Rule | Enforcement |
|---|---|
| Diagnose a condition | No code path anywhere maps symptoms/readings to a diagnosis. The BP engine outputs a *category* (normal/elevated/stage_1/stage_2/crisis) and an *urgency*, never a diagnosis. |
| Recommend starting/stopping/changing a medication or dose | `app/medication.py` has zero dose-mutation fields or functions. No tool exposed to the AI Coach can write to `medications`. Specialist system prompts explicitly forbid it as a second layer. |
| Tell the user to skip/delay medical care | Every BP message that escalates points *toward* care ("contact your clinician," "seek emergency care"), never away from it. |
| Recommend food/exercise/medication as an acute response to dangerous BP | `safety/bp_safety.py` is grep-tested (`tests/unit/test_bp_safety.py`) to never contain "medication," "exercise," "sodium," "salt," etc. in any generated message, across every category/symptom combination. |
| Invent a lab result or nutrition value | Nutrition only ever comes from `nutrition/food_service.py` (seed data, USDA, or manual entry) — never computed or guessed by the LLM. The NL logging pipeline's LLM step only proposes *candidate search terms*, never a nutrient number (`nutrition/nl_logging.py`). |
| Auto-recommend potassium supplements/salt substitutes for at-risk users | `safety/potassium_safety.py::can_auto_recommend_potassium_supplement` — blocks whenever any active medication is flagged potassium-risk. Nothing in the app currently auto-recommends supplements at all; this function exists so nothing added later (e.g. a future heart-health feature) can bypass the check. |
| Recommend aggressive high-protein without a kidney-status check | `safety/protein_safety.py::check_protein_target_safety` — blocks any target ≥1.6 g/kg when kidney_disease is `unknown` or `yes`, unless a clinician-provided target overrides it. Falls back to a conservative 0.8 g/kg (RDA baseline) and surfaces the required message: *"Confirm an appropriate protein target with your clinician before using a high-protein setting."* |
| State correlation as causation | `insights/pattern_engine.py` attaches a fixed caveat string to every computed association; `tests/unit/test_pattern_engine.py` asserts it's present and that "causation"-style language never appears. |

## BP safety engine (`safety/bp_safety.py`)

Deterministic, side-effect-free, no LLM call in the module at all.

**Thresholds** (`safety/constants.py`, AHA/ACC-based floors, checked crisis-first so a reading is classified at the more severe of its two numbers):

| Category | Trigger |
|---|---|
| normal | systolic < 120 |
| elevated | systolic 120-129 |
| stage_1 | systolic ≥130 or diastolic ≥80 |
| stage_2 | systolic ≥140 or diastolic ≥90 |
| **crisis** | systolic ≥180 or diastolic ≥120 |

**Escalation logic:**
- **Crisis, no symptoms** → urgent guidance: rest 5 min, take a second reading; if it stays high, contact a clinician today or seek urgent care.
- **Crisis + a checklist symptom** (chest pain, shortness of breath, severe headache, vision changes, difficulty speaking, numbness/weakness, confusion, back pain — `BP_EMERGENCY_SYMPTOMS`, a **fixed set matched literally, never LLM-parsed**) → emergency instruction: call emergency services / go to the ER now. Repeat-measurement advice is explicitly *not* shown here — the module doesn't want a delay while someone waits to re-measure.
- **A symptom alone, without a crisis-range reading, never escalates** — tested explicitly across all four lower categories (`test_symptoms_alone_without_crisis_range_never_trigger_emergency`).
- **Stage 2** → warning: re-measure to confirm, contact a clinician if it persists over a few days.
- **Normal/elevated/stage_1** → informational only.

Every reading above `info` severity is written to the append-only `safety_events` audit table (`vitals/bp_service.py::record_bp`) independent of the per-reading snapshot stored on `bp_readings` itself.

**Input validation guards against a real class of bug**: systolic/diastolic/pulse are range-checked (50-300 / 30-200 / 20-250 mmHg/bpm), *and* diastolic ≥ systolic is rejected outright — found and fixed during the M3 self-review (an 80/120 reading was silently accepted and misclassified before the fix; see `tests/unit/test_bp_service.py::test_record_bp_rejects_diastolic_greater_than_systolic`).

## AI Coach scoping

`agents/tool_registry.py` is the *only* surface the chat agentic loop can reach, and it exposes exclusively read tools (`get_*`, `calculate_*`, `search_food`, `analyze_health_patterns`, `generate_daily_plan` which doesn't persist). **Nothing that writes a BP reading, meal, workout, or plan is reachable from freeform chat** — data entry stays in the dedicated UI forms, each with the same deterministic validation as everywhere else. This means a misread or adversarial chat message can, at worst, produce a wrong *answer*, never a wrong *write* — and in particular, can never fabricate a BP reading that triggers (or fails to trigger) the safety engine.

`agents/tool_registry.py::execute_tool` also strips any `profile_id` a tool call's arguments contain and always injects the server-side session's profile_id — an LLM cannot read another profile's data by passing a different id in a tool call (tested in `test_execute_tool_strips_model_supplied_profile_id`).

## Symptom input is never free-text-parsed

The BP-recording UI presents symptoms as a fixed checklist (`safety/constants.py::BP_EMERGENCY_SYMPTOMS`); `safety/bp_safety.py::validate_symptoms` rejects anything outside that set. There is no code path where an LLM interprets "I feel kind of chest-painy" into a symptom flag.

## Known gaps / non-goals

- The app does not currently attempt to detect a genuine medical emergency from anything *other* than the BP-crisis-plus-symptom rule (e.g. it doesn't monitor SpO2 or HR for emergency thresholds). Those fields are tracked but not safety-gated — a deliberate scope limit for this build, documented so it isn't mistaken for a broader safety net.
- Pattern-analysis minimum sample size (`insights/pattern_engine.py::MIN_SAMPLE_SIZE = 5`) is deliberately low so a new profile can see *something* quickly. It should be raised (10-14+) for any deployment with real users, where a stronger evidentiary bar matters more than early gratification. This is a one-line change, called out here so it isn't missed.

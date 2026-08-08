# Evaluation contract — healthpilot_vitals_agent v1.0.0

- **E1:** dispatching this skill with a real question produces the same
  `answer` / `data_used` / `ai_used` that HealthPilot's own `/coach/ask`
  endpoint would have returned for the same (profile_id, message,
  specialist) before this retrofit. Proven in
  `healthpilot/tests/integration/test_aios_core_retrofit.py`.
- **E2:** a dispatch that attempts a write under `memory_root` is rejected
  with `MEMORY_VIOLATION`, never silently allowed. Proven by the same test
  file's negative test.

# Evaluation contract — healthpilot_log_coach_interaction v1.0.0

- **E1:** a dispatch appends exactly one new line to
  `conversations/<profile_id>.md` under the supplied `memory_root`, and
  reports that relative path in `file_written`.
- **E2:** a dispatch attempting to write outside `conversations/*.md` (e.g.
  a hypothetical bug writing to `conversations/../escape.md` or a sibling
  directory) is rejected with `MEMORY_VIOLATION` — proven in
  `healthpilot/tests/integration/test_aios_core_retrofit.py`.

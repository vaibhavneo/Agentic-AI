---
name: memory_compression
version: 1.0.0
description: Compress working memory into durable file summaries (Step 6 of recursive_planner). Use at every cycle end and whenever a memory file exceeds ~150 lines.
reference_impl: memory/ discipline (state.md overwrite, log.md one-liners, plan.md pruning)
---
# memory_compression
**Purpose:** keep memory files readable in one pass forever — history grows O(cycles) lines, not O(tokens).
**Inputs:** cycle events (in-context) · target memory files
**Outputs:** log.md +1 line (`date cycleID summary`) · state.md rewritten as snapshot · plan.md completed phases collapsed to one line.
**Rules:** transcripts/tool-dumps/reasoning traces are FORBIDDEN in memory files · facts no longer true LEAVE state.md · decisions ≠ plans ≠ state ≠ log (wrong-file content is a violation) · compress on the write that crosses 150 lines.
**Deterministic check:** M6 in recursive_planner/evaluation.md (no file >200 lines; log entries ≤1 line).

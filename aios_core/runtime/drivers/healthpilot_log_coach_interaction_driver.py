"""
Deterministic driver for healthpilot_log_coach_interaction (v1.0.0).

Writes ONE metadata-only audit line per Coach interaction under
<memory_root>/conversations/<profile_id>.md — timestamp, which specialist
answered, ai_used, and the NAMES of tools called (never their results,
which can carry real health values — consistent with HealthPilot's own
SAFETY.md: "No health data or medication details in logs by default").
Purely additive: this is a new side-channel audit trail, not a migration of
HealthPilot's own SQLite-backed data, and nothing reads it back to answer a
question — see manifest.json's memory contract (append_only,
conversations/*.md only).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def run(inputs: dict, context: dict) -> dict:
    root = Path(inputs["memory_root"]).expanduser()
    conv_dir = root / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)

    profile_id = inputs["profile_id"]
    path = conv_dir / f"{profile_id}.md"

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tools = ", ".join(inputs.get("tool_names", [])) or "(none)"
    line = f"- {ts} | specialist={inputs['specialist']} | ai_used={inputs['ai_used']} | tools=[{tools}]\n"

    with open(path, "a") as f:
        f.write(line)

    return {"file_written": str(path.relative_to(root))}

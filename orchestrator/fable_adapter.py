"""
Central Orchestrator's ONE model-naming file (P8: no runtime/skill code
names a vendor or model — reasoning enters only through an adapter).

Wires Claude Fable 5 (claude-fable-5) as the central_orchestrator skill's
`agent_adapter`: given a free-text task and the app roster, choose which
app should handle it. This is the ONLY generative step in the whole
orchestrator — the driver (central_orchestrator_driver.py) never trusts
this adapter's answer blindly; it validates app_id against the known
roster and falls back to brain_think if it doesn't resolve (H-O3).

Fable-5-specific API shape this adapter respects:
  - thinking is always on; never send {"type": "disabled"} (400s) — omit
    the `thinking` param entirely, matching the "adaptive"/default behavior.
  - no assistant message prefill.
  - can return stop_reason == "refusal" — checked BEFORE reading `content`.
  - server-side `fallbacks` wired to claude-opus-4-8 so a refusal or
    transient failure doesn't silently break routing for that turn.
"""
from __future__ import annotations

import json

_SYSTEM = (
    "You are a routing classifier for a multi-app AI system. Given a "
    "free-text task and a roster of available apps (id -> description), "
    "choose the SINGLE best app_id for the task. If no app clearly fits, "
    "return app_id null (a deterministic fallback handles that case, not "
    "you). Return STRICT JSON: {\"app_id\": <string-or-null>, "
    "\"reasoning\": <one sentence>}. No prose outside the JSON."
)

MODEL = "claude-fable-5"
FALLBACK_MODEL = "claude-opus-4-8"


def make_llm_adapter(call_llm=None):
    """Return an agent_adapter(manifest, inputs, context) -> {app_id,
    reasoning} backed by Claude Fable 5. `call_llm(messages, system) -> str`
    is injectable for tests; defaults to a real Anthropic Messages API call
    with the model's own required shape (no thinking:disabled, no prefill,
    refusal-checked, opus fallback wired server-side)."""
    if call_llm is None:
        call_llm = _default_call_llm

    def adapter(manifest, inputs, context):
        task = inputs["task"]
        roster = inputs.get("apps", {})
        roster_desc = "\n".join(f"- {app_id}: {meta.get('description', '')}"
                                for app_id, meta in roster.items())
        user = f"Task: {task}\n\nAvailable apps:\n{roster_desc}"
        raw = call_llm([{"role": "user", "content": user}], _SYSTEM)
        try:
            data = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        except (ValueError, json.JSONDecodeError) as e:
            raise ValueError(f"central_orchestrator adapter did not return "
                             f"parseable JSON: {e}")
        return {"app_id": data.get("app_id"), "reasoning": data.get("reasoning", "")}

    return adapter


def _default_call_llm(messages: list, system: str) -> str:
    import os
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system,
        messages=messages,
        fallbacks={"model": FALLBACK_MODEL},
    )
    if resp.stop_reason == "refusal":
        raise ValueError("central_orchestrator adapter: model declined to "
                         "answer (stop_reason=refusal)")
    return "".join(block.text for block in resp.content if hasattr(block, "text"))

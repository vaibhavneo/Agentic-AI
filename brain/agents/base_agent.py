"""
Base Agent — implements the 5-step Cognitive Loop (Ahmad):
  Perceive → Reason → Act → Observe → Adapt

Uses ReAct pattern (Gullí #6) with tool calling.
All specialist agents inherit from this.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import anthropic


@dataclass
class AgentStep:
    step_num: int
    thought: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)
    elapsed_ms: float = 0.0


@dataclass
class AgentResult:
    output: str
    steps: list[AgentStep] = field(default_factory=list)
    success: bool = True
    error: str = ""
    total_tokens: int = 0


class BaseAgent:
    """
    ReAct agent with tool use, memory injection, and self-correction.

    Subclasses override:
      - name: str
      - system_prompt: str
      - tools: list[dict]  (subset of TOOL_SCHEMAS they need)
    """

    name: str = "BaseAgent"
    system_prompt: str = "You are a helpful AI assistant."
    tools: list[dict] = []

    def __init__(
        self,
        client: anthropic.Anthropic,
        tool_dispatcher,
        memory_system=None,
        model: str = "claude-sonnet-4-6",
        max_steps: int = 20,
        verbose: bool = True,
    ):
        self.client      = client
        self.dispatch    = tool_dispatcher
        self.memory      = memory_system
        self.model       = model
        self.max_steps   = max_steps
        self.verbose     = verbose

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"  [{self.name}] {msg}")

    def _build_system(self, memory_context: str = "") -> str:
        base = self.system_prompt
        if memory_context:
            base += f"\n\n## Relevant Memory\n{memory_context}"
        return base

    def run(self, task: str, context: str = "") -> AgentResult:
        """Execute the agent cognitive loop."""
        t0 = time.time()

        # 1. Perceive — inject memory if available
        memory_ctx = ""
        if self.memory:
            memory_ctx = self.memory.format_for_context(task, max_tokens=1500)

        system = self._build_system(memory_ctx)
        user_content = task
        if context:
            user_content = f"Context:\n{context}\n\nTask:\n{task}"

        messages = [{"role": "user", "content": user_content}]
        steps: list[AgentStep] = []
        total_tokens = 0

        for step_num in range(1, self.max_steps + 1):
            t_step = time.time()
            step = AgentStep(step_num=step_num)

            # 2. Reason — call the LLM
            try:
                kwargs: dict[str, Any] = {
                    "model": self.model,
                    "max_tokens": 4096,
                    "system": system,
                    "messages": messages,
                }
                if self.tools:
                    kwargs["tools"] = self.tools

                resp = self.client.messages.create(**kwargs)
                total_tokens += resp.usage.input_tokens + resp.usage.output_tokens

            except Exception as e:
                return AgentResult(
                    output="", success=False, error=str(e), steps=steps
                )

            step.elapsed_ms = (time.time() - t_step) * 1000

            # Extract text thoughts
            for block in resp.content:
                if hasattr(block, "text"):
                    step.thought = block.text

            # 3. Act — if LLM wants to use tools
            if resp.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": resp.content})
                tool_results_content = []

                for block in resp.content:
                    if block.type == "tool_use":
                        step.tool_calls.append({
                            "tool": block.name,
                            "input": block.input,
                        })
                        self._log(f"→ {block.name}({_fmt_input(block.input)})")

                        # 4. Observe — run tool and get result
                        result_str = self.dispatch(block.name, block.input)
                        step.tool_results.append({
                            "tool": block.name,
                            "result": result_str[:500],
                        })
                        self._log(f"  ← {result_str[:120]}...")

                        tool_results_content.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_str,
                        })

                messages.append({"role": "user", "content": tool_results_content})
                steps.append(step)

                # 5. Adapt — loop continues with new context
                continue

            # Terminal — model gave final answer
            steps.append(step)
            final_text = step.thought or ""

            # Store event in memory
            if self.memory and final_text:
                self.memory.remember_event(
                    event_type=f"agent_{self.name}",
                    content=f"Task: {task[:200]}\nResult: {final_text[:300]}",
                    metadata={"steps": step_num, "tokens": total_tokens},
                )

            return AgentResult(
                output=final_text,
                steps=steps,
                success=True,
                total_tokens=total_tokens,
            )

        # Exceeded max steps
        last_thought = steps[-1].thought if steps else ""
        return AgentResult(
            output=last_thought or "Task incomplete — max steps reached.",
            steps=steps,
            success=False,
            error="Max steps exceeded",
            total_tokens=total_tokens,
        )


def _fmt_input(inp: dict) -> str:
    parts = []
    for k, v in inp.items():
        v_str = str(v)[:60].replace("\n", " ")
        parts.append(f"{k}={v_str!r}")
    return ", ".join(parts)

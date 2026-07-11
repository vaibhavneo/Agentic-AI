"""
Agentic AI Brain — Central Orchestrator
========================================

Architecture: Brain / Perception / Action paradigm (Raieli)
  Brain     = this orchestrator (plans, decides, routes)
  Perception = user input + memory retrieval + tool outputs
  Action    = specialist agent execution + tool calls

Patterns implemented (from 60-book library synthesis):
  - Orchestrator-Subagent (Gullí #12)
  - Agent Router (Arsanjani)
  - Plan-and-Execute (Gullí #7) for complex multi-step tasks
  - Parallel Processing (Gullí #14) for independent sub-tasks
  - Human-in-the-Loop (Gullí #16) via confidence scoring
  - Self-Correction / Reflection (Gullí #9)
  - Critic + Writer (Ahmad #25) for quality gate
  - Memory across all 5 types (Huyen + Arsanjani)
  - Observability (Gullí #21) — step logging + token tracking
  - Watchdog Timeout (Arsanjani robustness #3)
  - Guardrails (Gullí #17) — input/output safety
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anthropic

# Add brain dir to path
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    ORCHESTRATOR_MODEL, FAST_MODEL, CODE_MODEL,
    MAX_AGENT_STEPS, MAX_RETRIES, TIMEOUT_SECONDS,
    PARALLEL_AGENTS, MEMORY_DIR, ANTHROPIC_API_KEY,
)
from memory.memory_system import MemorySystem
from tools.tool_registry import TOOL_SCHEMAS, dispatch
from agents.specialist_agents import RouterAgent, CriticAgent


# ── Observability / Trace ──────────────────────────────────────────────────

@dataclass
class Trace:
    task: str
    plan: list[str] = field(default_factory=list)
    agent_used: str = ""
    steps_taken: int = 0
    total_tokens: int = 0
    elapsed_s: float = 0.0
    success: bool = True

    def summary(self) -> str:
        return (
            f"Agent={self.agent_used} | Steps={self.steps_taken} | "
            f"Tokens={self.total_tokens} | Time={self.elapsed_s:.1f}s | "
            f"Success={self.success}"
        )


# ── Guardrails ─────────────────────────────────────────────────────────────

_BLOCKED_PATTERNS = [
    r"(?i)(hack|exploit|ddos|malware|ransomware|phishing|steal.{0,20}password)",
    r"(?i)(generate.{0,30}(drug|weapon|bomb|explosive))",
    r"(?i)(child.{0,20}(pornography|abuse|explicit))",
]

def _check_guardrails(text: str) -> tuple[bool, str]:
    for pattern in _BLOCKED_PATTERNS:
        if re.search(pattern, text):
            return False, "Request blocked by safety guardrails."
    return True, ""


# ══════════════════════════════════════════════════════════════════════════
# Orchestrator Brain
# ══════════════════════════════════════════════════════════════════════════

class Brain:
    """
    The central orchestrator.

    Cognitive Loop (Ahmad's 5-step):
      1. Get Mission   — receive + validate user input
      2. Scan Scene    — recall memory, assess complexity
      3. Think Through — plan: simple route OR multi-step plan
      4. Take Action   — execute via specialist agents
      5. Learn/Adapt   — store result in memory, update blackboard
    """

    PLANNER_SYSTEM = """You are a master AI orchestrator. Given a user task, determine the best execution strategy.

Output a JSON object with this exact structure:
{
  "complexity": "simple" | "complex",
  "strategy": "single_agent" | "parallel" | "sequential_pipeline",
  "steps": [
    {"id": "1", "task": "...", "agent": "research|code|data|build_app|critic|content|general", "depends_on": []}
  ],
  "reasoning": "brief explanation"
}

Rules:
- simple tasks → single_agent with one step
- complex tasks → break into 2-4 steps
- parallel: steps with no dependencies can run simultaneously
- sequential_pipeline: output of step N feeds step N+1
- Always end with a synthesis step if multiple steps

Agent types: research, code, data, build_app, critic, content, general"""

    def __init__(self, api_key: str = "", verbose: bool = True):
        # Prefer Anthropic key; fall back to DeepSeek via compatibility shim
        ant_key = api_key or ANTHROPIC_API_KEY or os.getenv("ANTHROPIC_API_KEY", "")
        ds_key  = os.getenv("DEEPSEEK_API_KEY", "")

        # Also read from health-agent/.env if present
        _env = Path(__file__).parent.parent / "health-agent" / ".env"
        if _env.exists():
            for _line in _env.read_text().splitlines():
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    if _v.strip() and _v.strip() != "paste_your_key_here":
                        os.environ.setdefault(_k.strip(), _v.strip())
            if not ds_key:
                ds_key = os.getenv("DEEPSEEK_API_KEY", "")

        if ant_key:
            self.client = anthropic.Anthropic(api_key=ant_key)
            self._provider = "anthropic"
        elif ds_key:
            from deepseek_compat import DeepSeekAnthropic
            self.client = DeepSeekAnthropic(api_key=ds_key)
            self._provider = "deepseek"
            if verbose:
                print("🔄 Using DeepSeek as LLM backend")
        else:
            raise ValueError(
                "No API key found. Set ANTHROPIC_API_KEY or DEEPSEEK_API_KEY."
            )
        self.memory  = MemorySystem(MEMORY_DIR)
        self.router  = RouterAgent(self.client, self.memory, verbose=verbose)
        self.critic  = CriticAgent(
            client=self.client,
            tool_dispatcher=dispatch,
            memory_system=self.memory,
            verbose=verbose,
        )
        self.verbose = verbose
        self._traces: list[Trace] = []

    # ── Step 3: Plan ────────────────────────────────────────────────────

    def _plan(self, task: str) -> dict:
        """Use orchestrator LLM to decide execution strategy."""
        try:
            resp = self.client.messages.create(
                model=ORCHESTRATOR_MODEL,
                max_tokens=1024,
                system=self.PLANNER_SYSTEM,
                messages=[{"role": "user", "content": task}],
            )
            text = resp.content[0].text
            # extract JSON
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                return json.loads(m.group())
        except Exception:
            pass
        # fallback: single agent
        return {
            "complexity": "simple",
            "strategy": "single_agent",
            "steps": [{"id": "1", "task": task, "agent": "general", "depends_on": []}],
            "reasoning": "fallback",
        }

    # ── Step 4: Execute ──────────────────────────────────────────────────

    def _execute_step(self, step: dict, context: str = "") -> tuple[str, str]:
        """Run a single step, returns (agent_name, output)."""
        agent_hint = step.get("agent", "general")
        step_task  = step.get("task", "")
        if context:
            step_task = f"{step_task}\n\nContext from previous steps:\n{context}"

        # Route with hint (inject hint into task so router picks right agent)
        hinted_task = f"[Use {agent_hint} agent] {step_task}"
        agent_name, result = self.router.route(hinted_task)
        return agent_name, result.output, result.steps, result.total_tokens

    def _execute_parallel(self, steps: list[dict]) -> dict[str, str]:
        """Run independent steps in parallel threads."""
        results: dict[str, str] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=PARALLEL_AGENTS) as ex:
            futures = {
                ex.submit(self._execute_step, step): step["id"]
                for step in steps
            }
            for future in concurrent.futures.as_completed(futures, timeout=TIMEOUT_SECONDS):
                step_id = futures[future]
                try:
                    _, output, _, _ = future.result()
                    results[step_id] = output
                except Exception as e:
                    results[step_id] = f"[Step {step_id} failed: {e}]"
        return results

    def _execute_plan(self, plan: dict) -> tuple[str, str, int]:
        """Execute a multi-step plan, return (final_output, agent_used, total_tokens)."""
        steps      = plan.get("steps", [])
        strategy   = plan.get("strategy", "single_agent")
        completed: dict[str, str] = {}
        total_tokens = 0
        last_agent   = "general"

        if strategy == "parallel":
            # group by dependency level
            level0 = [s for s in steps if not s.get("depends_on")]
            rest   = [s for s in steps if s.get("depends_on")]
            if self.verbose and len(level0) > 1:
                print(f"\n⚡ Running {len(level0)} steps in parallel...")
            completed.update(self._execute_parallel(level0))

            # sequential for dependent steps
            for step in rest:
                ctx = "\n\n".join(
                    f"[Step {dep}]: {completed.get(dep, '')}"
                    for dep in step.get("depends_on", [])
                )
                _, output, _, toks = self._execute_step(step, ctx)
                completed[step["id"]] = output
                total_tokens += toks
                last_agent = step.get("agent", "general")

        else:  # sequential_pipeline or single_agent
            for step in steps:
                ctx = "\n\n".join(
                    f"[Step {dep}]: {completed.get(dep, '')}"
                    for dep in step.get("depends_on", [])
                )
                _, output, _, toks = self._execute_step(step, ctx)
                completed[step["id"]] = output
                total_tokens += toks
                last_agent = step.get("agent", "general")

        # final output is the last completed step
        last_id  = steps[-1]["id"] if steps else "1"
        final    = completed.get(last_id, "No output produced.")
        return final, last_agent, total_tokens

    # ── Quality Gate (Critic) ────────────────────────────────────────────

    def _quality_gate(self, task: str, output: str) -> str:
        """Run critic on output for complex tasks. Return (possibly improved) output."""
        critique = self.critic.run(
            f"Evaluate this output for the task: {task[:300]}\n\nOutput:\n{output[:1500]}"
        )
        if "critical issues" in critique.output.lower() and len(critique.output) > 200:
            # Try to extract the revised version if critic provided one
            m = re.search(r"## Revised Version\n(.*?)(?:##|$)", critique.output, re.DOTALL)
            if m:
                return m.group(1).strip()
        return output  # output was good, return as-is

    # ── Main Entry Point ─────────────────────────────────────────────────

    def think(self, task: str, auto_critique: bool = False) -> str:
        """
        Main Brain entry point.
        Takes a user task → plans → executes → optionally critiques → returns answer.
        """
        t0 = time.time()
        trace = Trace(task=task)

        # ── 1. Get Mission — input validation (guardrails)
        ok, reason = _check_guardrails(task)
        if not ok:
            return f"⚠️  {reason}"

        # ── 2. Scan Scene — memory recall
        if self.verbose:
            print("\n🧠 Brain thinking...")
        mem_ctx = self.memory.format_for_context(task, max_tokens=800)
        if mem_ctx and self.verbose:
            print(f"📚 Memory context loaded ({len(mem_ctx)} chars)")

        # ── 3. Think Through — plan
        plan = self._plan(task)
        complexity = plan.get("complexity", "simple")
        strategy   = plan.get("strategy", "single_agent")
        trace.plan = [s.get("task", "") for s in plan.get("steps", [])]

        if self.verbose:
            print(f"📋 Plan: {complexity} / {strategy} / {len(plan.get('steps', 1))} step(s)")
            if plan.get("reasoning") and plan["reasoning"] != "fallback":
                print(f"   Reasoning: {plan['reasoning']}")

        # ── 4. Take Action — execute
        try:
            if len(plan.get("steps", [])) == 1:
                # Simple: direct route
                step = plan["steps"][0]
                agent_name, result = self.router.route(task)
                final_output = result.output
                trace.agent_used  = agent_name
                trace.steps_taken = len(result.steps)
                trace.total_tokens = result.total_tokens
            else:
                final_output, last_agent, toks = self._execute_plan(plan)
                trace.agent_used   = last_agent
                trace.total_tokens = toks

        except Exception as e:
            trace.success = False
            return f"❌ Execution error: {e}"

        # ── Optional Quality Gate (Critic)
        if auto_critique and complexity == "complex" and len(final_output) > 200:
            if self.verbose:
                print("\n🔍 Running quality check...")
            final_output = self._quality_gate(task, final_output)

        # ── 5. Learn / Adapt — store in memory
        self.memory.remember_event(
            event_type="brain_task",
            content=f"Task: {task[:300]}\nOutput preview: {final_output[:400]}",
            metadata={
                "agent": trace.agent_used,
                "tokens": trace.total_tokens,
                "complexity": complexity,
            },
        )
        self.memory.blackboard.write("last_task", task, agent="brain")
        self.memory.blackboard.write("last_output", final_output[:500], agent="brain")

        trace.elapsed_s = time.time() - t0
        self._traces.append(trace)

        if self.verbose:
            print(f"\n✅ {trace.summary()}")

        return final_output

    def stats(self) -> dict:
        """Return session statistics (observability pattern)."""
        if not self._traces:
            return {}
        return {
            "total_tasks": len(self._traces),
            "total_tokens": sum(t.total_tokens for t in self._traces),
            "avg_time_s": sum(t.elapsed_s for t in self._traces) / len(self._traces),
            "success_rate": sum(1 for t in self._traces if t.success) / len(self._traces),
            "agents_used": list({t.agent_used for t in self._traces}),
        }

"""
Specialist Agents — 8 expert agents covering the major domains from Ahmad's 30 catalog.

Each is a thin subclass of BaseAgent with a tailored system prompt and tool subset.
The Router Agent classifies intent and selects the right specialist.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

import anthropic

from .base_agent import BaseAgent, AgentResult
from tools.tool_registry import TOOL_SCHEMAS, dispatch

if TYPE_CHECKING:
    from memory.memory_system import MemorySystem


# ── Tool subsets ───────────────────────────────────────────────────────────
_ALL_TOOLS    = TOOL_SCHEMAS
_SEARCH_TOOLS = [t for t in TOOL_SCHEMAS if t["name"] in ("web_search", "get_datetime")]
_CODE_TOOLS   = [t for t in TOOL_SCHEMAS if t["name"] in ("run_python", "run_shell", "read_file", "write_file", "list_directory", "create_agent_app")]
_FILE_TOOLS   = [t for t in TOOL_SCHEMAS if t["name"] in ("read_file", "write_file", "list_directory", "run_python")]
_MATH_TOOLS   = [t for t in TOOL_SCHEMAS if t["name"] in ("calculate", "run_python")]
_BUILD_TOOLS  = [t for t in TOOL_SCHEMAS if t["name"] in ("create_agent_app", "write_file", "run_python", "run_shell")]


# ══════════════════════════════════════════════════════════════════════════
# 1. Research Agent (Ahmad #7) — web search + synthesis
# ══════════════════════════════════════════════════════════════════════════

class ResearchAgent(BaseAgent):
    name = "ResearchAgent"
    tools = _SEARCH_TOOLS

    system_prompt = """You are an expert research analyst with deep knowledge across science,
technology, business, and society. Your mission:

1. Break complex questions into research sub-questions
2. Search the web systematically to gather current information
3. Cross-reference multiple sources for accuracy
4. Synthesize findings into a clear, structured report
5. Always cite sources and distinguish facts from analysis

Use the web_search tool multiple times (3-5 searches) to gather comprehensive information.
Structure your final answer with: Summary → Key Findings → Analysis → Conclusion.
Be thorough, accurate, and intellectually honest."""


# ══════════════════════════════════════════════════════════════════════════
# 2. Code Agent (Ahmad #9, #10) — code generation + execution + review
# ══════════════════════════════════════════════════════════════════════════

class CodeAgent(BaseAgent):
    name = "CodeAgent"
    tools = _CODE_TOOLS

    system_prompt = """You are a senior software engineer and architect. You:

1. Write clean, efficient, production-quality code
2. Run code to verify it works before presenting it
3. Handle errors gracefully — if code fails, diagnose and fix it
4. Follow best practices: type hints, docstrings where needed, no magic numbers
5. Can build complete applications end-to-end

For code generation:
- Use run_python to test your code immediately
- Use write_file to save complete programs
- Use create_agent_app to scaffold full agentic AI applications

Self-correction: if code errors, read the traceback carefully, identify root cause, fix it.
Max 3 correction attempts before explaining why it's difficult."""


# ══════════════════════════════════════════════════════════════════════════
# 3. Data Analysis Agent (Ahmad #6)
# ══════════════════════════════════════════════════════════════════════════

class DataAnalysisAgent(BaseAgent):
    name = "DataAnalysisAgent"
    tools = _FILE_TOOLS + _MATH_TOOLS

    system_prompt = """You are a data scientist and analyst. You:

1. Read and analyze data files (CSV, JSON, text)
2. Perform statistical analysis using Python
3. Generate insights from numerical and textual data
4. Create clear visualizations (as code or ASCII)
5. Explain findings in plain language

For every analysis:
- Start by reading/exploring the data
- Compute descriptive statistics
- Look for patterns, outliers, and trends
- Present findings clearly with numbers to support claims

Use run_python for computations. Use calculate for quick math."""


# ══════════════════════════════════════════════════════════════════════════
# 4. App Builder Agent (Ahmad #9 + create_agent_app tool)
# ══════════════════════════════════════════════════════════════════════════

class AppBuilderAgent(BaseAgent):
    name = "AppBuilderAgent"
    tools = _BUILD_TOOLS

    system_prompt = """You are an expert AI application architect who builds complete,
working agentic AI applications from user requirements.

Your process:
1. Understand the user's requirements clearly
2. Choose the right app architecture (chatbot / RAG / multi-agent / code-agent / research-agent)
3. Use create_agent_app to generate the scaffolded application
4. Enhance it with custom logic using write_file
5. Test it with run_python to verify it works
6. Explain how to run and use it

Always:
- Generate working, runnable code
- Include a README-style explanation in your response
- Tell the user exactly how to run the app
- Suggest next improvements they can make

App types available: chatbot, rag, multi_agent, code_agent, research_agent"""


# ══════════════════════════════════════════════════════════════════════════
# 5. Critic/Evaluator Agent (Ahmad #25) — quality review
# ══════════════════════════════════════════════════════════════════════════

class CriticAgent(BaseAgent):
    name = "CriticAgent"
    tools = []

    system_prompt = """You are a rigorous quality evaluator and critic. You:

1. Evaluate any content, code, plan, or answer for quality
2. Identify specific weaknesses, errors, and gaps
3. Score outputs on: accuracy, completeness, clarity, usefulness (1-10 each)
4. Provide actionable, specific improvement suggestions
5. Distinguish between critical issues and minor polish

Format your critique as:
## Strengths
## Critical Issues (must fix)
## Improvements (should fix)
## Scores
## Revised Version (if requested)

Be honest, specific, and constructive. Not everything needs major changes."""


# ══════════════════════════════════════════════════════════════════════════
# 6. Content Creation Agent (Ahmad #20)
# ══════════════════════════════════════════════════════════════════════════

class ContentAgent(BaseAgent):
    name = "ContentAgent"
    tools = _SEARCH_TOOLS + [t for t in TOOL_SCHEMAS if t["name"] == "write_file"]

    system_prompt = """You are a world-class content creator and writer. You create:
- Blog posts, articles, essays
- Technical documentation
- Marketing copy and social media posts
- Scripts, stories, and creative writing
- Emails and professional communications

Your writing is: clear, engaging, well-structured, appropriate for the audience.

Process:
1. If factual content needed, search for accurate information first
2. Structure before writing (outline)
3. Write with strong opening, clear body, memorable close
4. Adapt tone/style to the request (formal/casual/technical/creative)
5. Save long-form content to file if requested

Always ask yourself: "Would the reader find this genuinely valuable?"""


# ══════════════════════════════════════════════════════════════════════════
# 7. General Assistant Agent (Ahmad #2)
# ══════════════════════════════════════════════════════════════════════════

class AssistantAgent(BaseAgent):
    name = "AssistantAgent"
    tools = _ALL_TOOLS

    system_prompt = """You are a highly capable AI assistant with access to a full suite of tools.
You can search the web, run code, read/write files, perform calculations, and build applications.

Approach every task by:
1. Understanding what's truly being asked
2. Choosing the right tools for the job
3. Executing systematically with self-verification
4. Presenting results clearly and concisely

You are proactive — if you can do something that would clearly help the user, do it.
You are precise — verify your work before presenting it.
You are honest — if you're uncertain, say so and explain why."""


# ══════════════════════════════════════════════════════════════════════════
# Router Agent — classifies intent → routes to specialist
# Pattern: Routing (Gullí #5) + Agent Router (Arsanjani)
# ══════════════════════════════════════════════════════════════════════════

AGENT_DESCRIPTIONS = {
    "research":  "Research, web search, fact-finding, news, current events, explanations",
    "code":      "Writing code, debugging, programming, software development, scripts",
    "data":      "Data analysis, statistics, CSV/JSON analysis, calculations, charts",
    "build_app": "Building AI apps, creating agents, scaffolding applications",
    "critic":    "Reviewing, evaluating, critiquing, improving existing content or code",
    "content":   "Writing blog posts, articles, emails, creative writing, documentation",
    "general":   "General questions, conversation, mixed tasks, unclear requests",
}


class RouterAgent:
    """Classifies user intent and routes to the correct specialist agent."""

    def __init__(self, client: anthropic.Anthropic, memory_system=None, verbose=True):
        self.client  = client
        self.memory  = memory_system
        self.verbose = verbose

        # Instantiate all specialists
        common = dict(client=client, tool_dispatcher=dispatch,
                      memory_system=memory_system, verbose=verbose)
        self._agents: dict[str, BaseAgent] = {
            "research":  ResearchAgent(**common),
            "code":      CodeAgent(**common),
            "data":      DataAnalysisAgent(**common),
            "build_app": AppBuilderAgent(**common),
            "critic":    CriticAgent(**common),
            "content":   ContentAgent(**common),
            "general":   AssistantAgent(**common),
        }

    def _classify(self, task: str) -> str:
        desc_block = "\n".join(f'- "{k}": {v}' for k, v in AGENT_DESCRIPTIONS.items())
        prompt = f"""Classify this user request into exactly one category.

Categories:
{desc_block}

User request: {task}

Respond with ONLY the category name (one word). Nothing else."""

        resp = self.client.messages.create(
            model="claude-haiku-4-5-20251001",  # fast model for routing
            max_tokens=20,
            messages=[{"role": "user", "content": prompt}],
        )
        category = resp.content[0].text.strip().lower().strip('"\'')
        return category if category in self._agents else "general"

    def route(self, task: str) -> tuple[str, AgentResult]:
        category = self._classify(task)
        if self.verbose:
            print(f"\n🧭 Routing → {category.upper()} agent")
        agent = self._agents[category]
        result = agent.run(task)
        return category, result

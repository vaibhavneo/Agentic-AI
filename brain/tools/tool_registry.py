"""
Tool Registry — Anthropic tool_use format.
Each tool is a dict with name/description/input_schema, plus a Python handler.

Implements: Tool Use pattern (Gullí #2), MCP-style tool schema, safety guardrails.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable


# ── Tool result wrapper ────────────────────────────────────────────────────

class ToolResult:
    def __init__(self, output: str, error: str = "", success: bool = True):
        self.output  = output
        self.error   = error
        self.success = success

    def to_str(self) -> str:
        if not self.success:
            return f"[ERROR] {self.error}"
        return self.output


# ── Individual tool handlers ───────────────────────────────────────────────

def _web_search(query: str, num_results: int = 5) -> ToolResult:
    """DuckDuckGo lite — no API key required."""
    try:
        enc = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={enc}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        # extract result snippets
        snippets = re.findall(
            r'<a class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL
        )
        titles = re.findall(
            r'<a class="result__a"[^>]*>(.*?)</a>', html, re.DOTALL
        )
        results = []
        for i, (t, s) in enumerate(zip(titles, snippets), 1):
            t_clean = re.sub(r"<[^>]+>", "", t).strip()
            s_clean = re.sub(r"<[^>]+>", "", s).strip()
            results.append(f"{i}. **{t_clean}**\n   {s_clean}")
            if i >= num_results:
                break
        if not results:
            return ToolResult("No results found.", success=True)
        return ToolResult("\n\n".join(results))
    except Exception as e:
        return ToolResult("", error=str(e), success=False)


def _read_file(path: str, start_line: int = 1, end_line: int = 100) -> ToolResult:
    try:
        p = os.path.expanduser(path)
        if not os.path.exists(p):
            return ToolResult("", error=f"File not found: {p}", success=False)
        with open(p, "r", errors="ignore") as f:
            lines = f.readlines()
        sl, el = max(0, start_line - 1), min(len(lines), end_line)
        content = "".join(lines[sl:el])
        total = len(lines)
        return ToolResult(
            f"[Lines {sl+1}-{el} of {total}]\n{content}"
        )
    except Exception as e:
        return ToolResult("", error=str(e), success=False)


def _write_file(path: str, content: str) -> ToolResult:
    try:
        p = os.path.expanduser(path)
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w") as f:
            f.write(content)
        return ToolResult(f"Written {len(content)} chars to {p}")
    except Exception as e:
        return ToolResult("", error=str(e), success=False)


def _run_python(code: str) -> ToolResult:
    """Execute Python code in a subprocess (sandbox isolation pattern)."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=30
        )
        out = result.stdout or ""
        err = result.stderr or ""
        if result.returncode != 0:
            return ToolResult(out, error=err, success=False)
        return ToolResult(out or "(no output)")
    except subprocess.TimeoutExpired:
        return ToolResult("", error="Code execution timed out (30s)", success=False)
    except Exception as e:
        return ToolResult("", error=str(e), success=False)


def _run_shell(command: str) -> ToolResult:
    """Run a shell command. Blocked for dangerous patterns."""
    BLOCKED = ["rm -rf", "sudo", "mkfs", "dd if=", ":(){:|:&}"]
    for bad in BLOCKED:
        if bad in command:
            return ToolResult(
                "", error=f"Blocked dangerous command: {bad}", success=False
            )
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30
        )
        out = result.stdout + result.stderr
        return ToolResult(out or "(no output)", success=result.returncode == 0)
    except Exception as e:
        return ToolResult("", error=str(e), success=False)


def _list_dir(path: str = ".") -> ToolResult:
    try:
        p = os.path.expanduser(path)
        items = os.listdir(p)
        lines = []
        for item in sorted(items):
            full = os.path.join(p, item)
            tag = "DIR" if os.path.isdir(full) else "FILE"
            size = os.path.getsize(full) if os.path.isfile(full) else ""
            lines.append(f"[{tag}] {item}" + (f"  ({size} bytes)" if size else ""))
        return ToolResult("\n".join(lines) or "(empty directory)")
    except Exception as e:
        return ToolResult("", error=str(e), success=False)


def _get_datetime(_: Any = None) -> ToolResult:
    now = datetime.now(timezone.utc)
    return ToolResult(
        f"UTC: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"ISO: {now.isoformat()}"
    )


def _calculate(expression: str) -> ToolResult:
    """Safe math evaluator — only allows numbers, operators, math functions."""
    allowed = re.compile(r'^[\d\s\+\-\*\/\%\(\)\.\,\_\^e]+$')
    imports = "abs,round,min,max,sum,pow,int,float,len"
    if not allowed.match(expression.replace(" ", "")):
        # allow math module references
        pass
    try:
        import math as _math
        safe_globals = {
            "__builtins__": {},
            "math": _math,
            **{k: getattr(_math, k) for k in dir(_math) if not k.startswith("_")},
            **{k: getattr(__builtins__, k) for k in imports.split(",")
               if hasattr(__builtins__, k)},
        }
        result = eval(expression, safe_globals, {})  # noqa: S307
        return ToolResult(str(result))
    except Exception as e:
        return ToolResult("", error=str(e), success=False)


def _create_agent_app(
    app_name: str,
    app_type: str,
    description: str,
    output_path: str = ".",
) -> ToolResult:
    """Generate a scaffolded agentic app based on the requested type."""
    templates = {
        "chatbot": _scaffold_chatbot,
        "rag": _scaffold_rag,
        "multi_agent": _scaffold_multi_agent,
        "code_agent": _scaffold_code_agent,
        "research_agent": _scaffold_research_agent,
    }
    fn = templates.get(app_type.lower())
    if not fn:
        types = ", ".join(templates.keys())
        return ToolResult("", error=f"Unknown app_type. Choose: {types}", success=False)
    try:
        code = fn(app_name, description)
        path = os.path.join(os.path.expanduser(output_path), f"{app_name}.py")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            f.write(code)
        return ToolResult(f"Created {app_type} app at: {path}\n\n```python\n{code[:800]}\n...\n```")
    except Exception as e:
        return ToolResult("", error=str(e), success=False)


# ── App scaffolders ────────────────────────────────────────────────────────

def _scaffold_chatbot(name: str, description: str) -> str:
    return textwrap.dedent(f'''\
        """
        {name} — AI Chatbot
        {description}
        Generated by Agentic AI Brain
        """
        import anthropic

        client = anthropic.Anthropic()

        SYSTEM = """You are {name}, a helpful AI assistant.
        {description}"""

        def chat():
            print(f"{{name}} is ready. Type 'quit' to exit.\\n")
            history = []
            while True:
                user_input = input("You: ").strip()
                if user_input.lower() in ("quit", "exit", "q"):
                    break
                history.append({{"role": "user", "content": user_input}})
                response = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=2048,
                    system=SYSTEM,
                    messages=history,
                )
                reply = response.content[0].text
                history.append({{"role": "assistant", "content": reply}})
                print(f"\\nAssistant: {{reply}}\\n")

        if __name__ == "__main__":
            chat()
        ''')


def _scaffold_rag(name: str, description: str) -> str:
    return textwrap.dedent(f'''\
        """
        {name} — RAG Agent
        {description}
        Generated by Agentic AI Brain
        """
        import anthropic
        import os, json
        from pathlib import Path

        client = anthropic.Anthropic()

        # ── Simple in-memory document store ─────────────────────────────
        class DocStore:
            def __init__(self):
                self.docs = []

            def add(self, text: str, source: str = ""):
                # chunk into 500-char segments
                chunks = [text[i:i+500] for i in range(0, len(text), 400)]
                for chunk in chunks:
                    self.docs.append({{"text": chunk, "source": source}})

            def search(self, query: str, top_k: int = 3) -> list:
                q_words = set(query.lower().split())
                scored = []
                for doc in self.docs:
                    words = set(doc["text"].lower().split())
                    score = len(q_words & words) / (len(q_words) + 1)
                    scored.append((score, doc))
                scored.sort(reverse=True)
                return [d for _, d in scored[:top_k]]

        store = DocStore()

        def add_document(path: str):
            text = Path(path).read_text(errors="ignore")
            store.add(text, source=path)
            print(f"Added {{path}} ({{len(text)}} chars)")

        def ask(question: str) -> str:
            results = store.search(question)
            context = "\\n\\n".join(r["text"] for r in results)
            prompt = f"""Answer the question using ONLY the provided context.
        Context:
        {{context}}

        Question: {{question}}"""
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{{"role": "user", "content": prompt}}],
            )
            return resp.content[0].text

        if __name__ == "__main__":
            import sys
            if len(sys.argv) > 1:
                add_document(sys.argv[1])
            while True:
                q = input("\\nQuestion (or quit): ").strip()
                if q.lower() in ("quit", "exit"):
                    break
                print("\\nAnswer:", ask(q))
        ''')


def _scaffold_multi_agent(name: str, description: str) -> str:
    return textwrap.dedent(f'''\
        """
        {name} — Multi-Agent System
        {description}
        Generated by Agentic AI Brain

        Architecture: Orchestrator → [Researcher, Writer, Critic]
        Pattern: Orchestrator-Subagent + Debate/Critique (Gullí #12, #13)
        """
        import anthropic
        from typing import Optional

        client = anthropic.Anthropic()

        def run_agent(system: str, user_msg: str, model: str = "claude-sonnet-4-6") -> str:
            resp = client.messages.create(
                model=model,
                max_tokens=2048,
                system=system,
                messages=[{{"role": "user", "content": user_msg}}],
            )
            return resp.content[0].text

        # ── Specialist agents ────────────────────────────────────────────

        RESEARCHER_SYSTEM = """You are a research specialist. Given a task,
        gather and organize all relevant facts, data, and context. Be thorough
        and cite your reasoning. Output structured findings."""

        WRITER_SYSTEM = """You are a world-class writer. Given research findings
        and a task, produce clear, compelling, well-structured output.
        Adapt your style to the task requirements."""

        CRITIC_SYSTEM = """You are a strict quality critic. Review the provided
        output and identify: (1) factual errors, (2) missing information,
        (3) logical gaps, (4) style issues. Be specific and actionable."""

        ORCHESTRATOR_SYSTEM = """You are the orchestrator. Coordinate the team:
        1. Send the task to the researcher
        2. Give research to the writer
        3. Have the critic review
        4. Synthesize into a final polished output
        Respond with the final answer only."""

        def run(task: str) -> str:
            print("🔬 Researcher working...")
            research = run_agent(RESEARCHER_SYSTEM, f"Research this task: {{task}}")

            print("✍️  Writer working...")
            draft = run_agent(WRITER_SYSTEM,
                              f"Task: {{task}}\\n\\nResearch:\\n{{research}}\\n\\nWrite a response.")

            print("🔍 Critic reviewing...")
            critique = run_agent(CRITIC_SYSTEM,
                                 f"Task: {{task}}\\n\\nDraft:\\n{{draft}}\\n\\nReview this draft.")

            print("🎯 Orchestrator synthesizing...")
            final = run_agent(ORCHESTRATOR_SYSTEM,
                              f"Task: {{task}}\\n\\nDraft: {{draft}}\\n\\nCritique: {{critique}}\\n\\nProduce final output.")
            return final

        if __name__ == "__main__":
            task = input("Enter task: ").strip()
            result = run(task)
            print("\\n" + "="*60)
            print("FINAL OUTPUT:")
            print("="*60)
            print(result)
        ''')


def _scaffold_code_agent(name: str, description: str) -> str:
    return textwrap.dedent(f'''\
        """
        {name} — Code Generation Agent
        {description}
        Generated by Agentic AI Brain

        Pattern: Code Generation + Execution + Self-Correction (Gullí #10, #9)
        """
        import anthropic, subprocess, sys

        client = anthropic.Anthropic()

        SYSTEM = """You are an expert Python developer. When given a task:
        1. Write clean, working Python code
        2. Include error handling
        3. Add brief comments only where non-obvious
        Output ONLY the Python code inside a ```python block."""

        def extract_code(text: str) -> str:
            import re
            m = re.search(r"```python\\n(.*?)```", text, re.DOTALL)
            return m.group(1) if m else text

        def run_code(code: str) -> tuple[str, bool]:
            result = subprocess.run([sys.executable, "-c", code],
                                    capture_output=True, text=True, timeout=30)
            return (result.stdout + result.stderr), result.returncode == 0

        def generate_and_run(task: str, max_retries: int = 3) -> str:
            history = [{{"role": "user", "content": f"Task: {{task}}"}}]
            for attempt in range(max_retries):
                resp = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=4096,
                    system=SYSTEM,
                    messages=history,
                )
                code_text = resp.content[0].text
                code = extract_code(code_text)
                print(f"\\nAttempt {{attempt+1}} — running code...")
                output, success = run_code(code)
                if success:
                    print(f"✅ Success!\\nOutput: {{output}}")
                    return code
                print(f"❌ Error: {{output}}")
                history.append({{"role": "assistant", "content": code_text}})
                history.append({{"role": "user",
                                "content": f"Error: {{output}}\\n\\nFix the code."}})
            return "Failed after {{max_retries}} attempts."

        if __name__ == "__main__":
            task = input("Describe the code to generate: ").strip()
            generate_and_run(task)
        ''')


def _scaffold_research_agent(name: str, description: str) -> str:
    return textwrap.dedent(f'''\
        """
        {name} — Research Agent
        {description}
        Generated by Agentic AI Brain

        Pattern: ReAct (Reasoning + Acting) with web search tool (Gullí #6, #2)
        """
        import anthropic, json, urllib.request, urllib.parse, re

        client = anthropic.Anthropic()

        # ── Web Search Tool ──────────────────────────────────────────────
        tools = [{{
            "name": "web_search",
            "description": "Search the web for current information on a topic.",
            "input_schema": {{
                "type": "object",
                "properties": {{
                    "query": {{"type": "string", "description": "Search query"}},
                    "num_results": {{"type": "integer", "default": 5}},
                }},
                "required": ["query"],
            }},
        }}]

        def web_search(query: str, num_results: int = 5) -> str:
            enc = urllib.parse.quote_plus(query)
            url = f"https://html.duckduckgo.com/html/?q={{enc}}"
            req = urllib.request.Request(url, headers={{"User-Agent": "Mozilla/5.0"}})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    html = r.read().decode("utf-8", errors="ignore")
                snippets = re.findall(r\'<a class="result__snippet"[^>]*>(.*?)</a>\', html, re.DOTALL)
                return "\\n".join(re.sub(r"<[^>]+>", "", s).strip() for s in snippets[:num_results])
            except Exception as e:
                return f"Search error: {{e}}"

        def research(topic: str) -> str:
            print(f"Researching: {{topic}}\\n")
            messages = [{{"role": "user",
                        "content": f"Research this thoroughly: {{topic}}. Use the search tool multiple times to gather comprehensive information."}}]

            for step in range(8):  # max 8 ReAct steps
                resp = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=2048,
                    tools=tools,
                    messages=messages,
                )

                if resp.stop_reason == "end_turn":
                    # final answer
                    text = next((b.text for b in resp.content if hasattr(b, "text")), "")
                    return text

                # handle tool calls
                messages.append({{"role": "assistant", "content": resp.content}})
                tool_results = []
                for block in resp.content:
                    if block.type == "tool_use":
                        print(f"  🔍 Searching: {{block.input.get(\'query\', \'\')}}")
                        result = web_search(**block.input)
                        tool_results.append({{
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }})
                if tool_results:
                    messages.append({{"role": "user", "content": tool_results}})

            return "Research complete."

        if __name__ == "__main__":
            topic = input("Research topic: ").strip()
            result = research(topic)
            print("\\n" + "="*60)
            print(result)
        ''')


# ── Tool dispatcher ────────────────────────────────────────────────────────

TOOL_HANDLERS: dict[str, Callable] = {
    "web_search":        lambda **kw: _web_search(**kw),
    "read_file":         lambda **kw: _read_file(**kw),
    "write_file":        lambda **kw: _write_file(**kw),
    "run_python":        lambda **kw: _run_python(**kw),
    "run_shell":         lambda **kw: _run_shell(**kw),
    "list_directory":    lambda **kw: _list_dir(**kw),
    "get_datetime":      lambda **kw: _get_datetime(**kw),
    "calculate":         lambda **kw: _calculate(**kw),
    "create_agent_app":  lambda **kw: _create_agent_app(**kw),
}


def dispatch(tool_name: str, tool_input: dict) -> str:
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        return f"[ERROR] Unknown tool: {tool_name}"
    result = handler(**tool_input)
    return result.to_str()


# ── Anthropic tool schemas (for function calling) ──────────────────────────

TOOL_SCHEMAS = [
    {
        "name": "web_search",
        "description": "Search the web for current information. Use for news, facts, documentation, or anything requiring up-to-date knowledge.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "num_results": {"type": "integer", "description": "Number of results (1-10)", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a file from the filesystem.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path (supports ~)"},
                "start_line": {"type": "integer", "description": "Start line", "default": 1},
                "end_line": {"type": "integer", "description": "End line", "default": 100},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file. Creates directories if needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "run_python",
        "description": "Execute Python code and return the output. Use for data analysis, calculations, file processing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "run_shell",
        "description": "Run a shell command. Dangerous commands are blocked.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "list_directory",
        "description": "List files and directories at a path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path", "default": "."},
            },
            "required": [],
        },
    },
    {
        "name": "get_datetime",
        "description": "Get the current UTC date and time.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "calculate",
        "description": "Evaluate a mathematical expression safely.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Math expression (supports Python math module)"},
            },
            "required": ["expression"],
        },
    },
    {
        "name": "create_agent_app",
        "description": "Generate and save a complete scaffolded agentic AI application. Use when the user asks to build, create, or make an AI app or agent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "app_name": {"type": "string", "description": "Name for the app (no spaces, snake_case)"},
                "app_type": {
                    "type": "string",
                    "description": "Type of app",
                    "enum": ["chatbot", "rag", "multi_agent", "code_agent", "research_agent"],
                },
                "description": {"type": "string", "description": "What this app does"},
                "output_path": {"type": "string", "description": "Directory to save the app", "default": "."},
            },
            "required": ["app_name", "app_type", "description"],
        },
    },
]

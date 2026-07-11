from __future__ import annotations
"""
Web UI for the Agentic AI Brain.
Run: python3 web_server.py
Open: http://localhost:8001
"""
import os
import sys
import time
import json
import uuid
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Load env from health-agent/.env (shares DeepSeek key)
for _env in [
    Path(__file__).parent / ".env",
    Path(__file__).parent.parent / "health-agent" / ".env",
    Path(__file__).parent.parent / "stock_agent" / ".env",
]:
    if _env.exists():
        for _line in _env.read_text().splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                if _v.strip() and _v.strip() not in ("paste_your_key_here", "your_key_here"):
                    os.environ.setdefault(_k.strip(), _v.strip())

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
import uvicorn

app = FastAPI(title="Agentic AI Brain")

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Agentic AI Brain</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, sans-serif; background: #0a0e1a; color: #e2e8f0; min-height: 100vh; display: flex; flex-direction: column; }
header { background: #111827; border-bottom: 1px solid #1f2937; padding: 14px 24px; display: flex; align-items: center; gap: 12px; }
header h1 { font-size: 18px; font-weight: 700; color: #f8fafc; }
.badge { background: #6366f122; color: #818cf8; border: 1px solid #6366f144; border-radius: 999px; padding: 2px 10px; font-size: 12px; }
.provider { font-size: 12px; color: #64748b; margin-left: auto; }
main { flex: 1; display: grid; grid-template-columns: 320px 1fr; gap: 0; height: calc(100vh - 53px); }
.sidebar { background: #111827; border-right: 1px solid #1f2937; padding: 16px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
.sidebar h2 { font-size: 11px; color: #475569; text-transform: uppercase; letter-spacing: .08em; margin-bottom: 4px; }
.preset { background: #1f2937; border: 1px solid #374151; border-radius: 8px; padding: 10px 12px; cursor: pointer; transition: all .15s; }
.preset:hover { background: #374151; border-color: #6366f1; }
.preset-label { font-size: 11px; color: #6366f1; margin-bottom: 3px; font-weight: 600; }
.preset-text { font-size: 13px; color: #cbd5e1; line-height: 1.4; }
.chat-area { display: flex; flex-direction: column; height: 100%; }
.messages { flex: 1; overflow-y: auto; padding: 24px; display: flex; flex-direction: column; gap: 16px; }
.msg { max-width: 80%; }
.msg.user { align-self: flex-end; }
.msg.agent { align-self: flex-start; }
.msg-bubble { padding: 12px 16px; border-radius: 12px; line-height: 1.6; font-size: 14px; white-space: pre-wrap; }
.msg.user .msg-bubble { background: #6366f1; color: white; border-bottom-right-radius: 4px; }
.msg.agent .msg-bubble { background: #1f2937; color: #e2e8f0; border-bottom-left-radius: 4px; border: 1px solid #374151; }
.msg-meta { font-size: 11px; color: #475569; margin-top: 4px; padding: 0 4px; }
.msg.user .msg-meta { text-align: right; }
.trace-bar { background: #0f172a; border-top: 1px solid #1f2937; padding: 8px 16px; font-size: 11px; color: #475569; display: flex; gap: 16px; }
.trace-item { display: flex; align-items: center; gap: 4px; }
.trace-item span { color: #94a3b8; }
.input-area { background: #111827; border-top: 1px solid #1f2937; padding: 16px 24px; display: flex; gap: 12px; align-items: flex-end; }
textarea { flex: 1; background: #1f2937; border: 1px solid #374151; border-radius: 10px; color: #e2e8f0; padding: 10px 14px; font-size: 14px; resize: none; outline: none; font-family: inherit; line-height: 1.5; max-height: 120px; }
textarea:focus { border-color: #6366f1; }
.send-btn { background: #6366f1; color: white; border: none; border-radius: 10px; padding: 10px 20px; font-size: 14px; font-weight: 600; cursor: pointer; white-space: nowrap; }
.send-btn:hover { background: #4f46e5; }
.send-btn:disabled { background: #374151; color: #6b7280; cursor: not-allowed; }
.thinking { display: flex; gap: 4px; align-items: center; padding: 14px 16px; }
.dot { width: 7px; height: 7px; background: #6366f1; border-radius: 50%; animation: bounce .8s infinite; }
.dot:nth-child(2) { animation-delay: .15s; }
.dot:nth-child(3) { animation-delay: .3s; }
@keyframes bounce { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-5px); } }
.empty-state { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; color: #475569; }
.empty-icon { font-size: 48px; }
.empty-title { font-size: 18px; font-weight: 600; color: #64748b; }
.empty-sub { font-size: 13px; }
.agent-tag { display: inline-block; background: #6366f122; color: #818cf8; border-radius: 4px; padding: 1px 6px; font-size: 11px; font-weight: 600; margin-right: 4px; }
</style>
</head>
<body>
<header>
  <div style="font-size:24px">🧠</div>
  <h1>Agentic AI Brain</h1>
  <div class="badge">7 Specialist Agents</div>
  <div class="badge">5-Type Memory</div>
  <div class="badge">9 Tools</div>
  <div class="provider" id="provider-label">Loading...</div>
</header>
<main>
  <div class="sidebar">
    <h2>Quick Tasks</h2>
    <div class="preset" onclick="setTask('Research the latest developments in multi-agent AI systems in 2025 and summarize key trends')">
      <div class="preset-label">🔍 Research Agent</div>
      <div class="preset-text">Latest multi-agent AI trends in 2025</div>
    </div>
    <div class="preset" onclick="setTask('Write a Python function that implements binary search with proper docstrings and unit tests')">
      <div class="preset-label">💻 Code Agent</div>
      <div class="preset-text">Binary search with tests</div>
    </div>
    <div class="preset" onclick="setTask('Analyze this dataset and find patterns: sales=[120,145,132,178,165,190,210,198,225,240] months=[Jan-Oct]')">
      <div class="preset-label">📊 Data Analysis Agent</div>
      <div class="preset-text">Analyze sales trend data</div>
    </div>
    <div class="preset" onclick="setTask('Explain quantum entanglement as if I am a 10-year-old, using a simple analogy')">
      <div class="preset-label">📝 Content Agent</div>
      <div class="preset-text">Explain quantum entanglement simply</div>
    </div>
    <div class="preset" onclick="setTask('What is the capital of France and what is 15 * 23?')">
      <div class="preset-label">🤖 Assistant Agent</div>
      <div class="preset-text">Quick Q&amp;A + calculation</div>
    </div>
    <div class="preset" onclick="setTask('Plan and create a Python Flask app with a /health endpoint that returns server uptime and memory usage')">
      <div class="preset-label">🏗️ App Builder Agent</div>
      <div class="preset-text">Build a Flask health endpoint</div>
    </div>
    <div class="preset" onclick="setTask('Research the pros and cons of LangGraph vs CrewAI for building multi-agent systems, then write a comparison article')">
      <div class="preset-label">⚡ Multi-Agent (Parallel)</div>
      <div class="preset-text">Research + write comparison article</div>
    </div>
  </div>

  <div class="chat-area">
    <div class="messages" id="messages">
      <div class="empty-state" id="empty">
        <div class="empty-icon">🧠</div>
        <div class="empty-title">Agentic AI Brain</div>
        <div class="empty-sub">Ask anything — I'll plan, route, and execute with specialist agents</div>
      </div>
    </div>
    <div class="trace-bar" id="trace-bar" style="display:none">
      <div class="trace-item">Agent: <span id="t-agent">—</span></div>
      <div class="trace-item">Steps: <span id="t-steps">—</span></div>
      <div class="trace-item">Tokens: <span id="t-tokens">—</span></div>
      <div class="trace-item">Time: <span id="t-time">—</span></div>
    </div>
    <div class="input-area">
      <textarea id="task" placeholder="Ask the Brain anything..." rows="1"
        onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendTask()}"
        oninput="this.style.height='auto';this.style.height=this.scrollHeight+'px'"></textarea>
      <button class="send-btn" id="send-btn" onclick="sendTask()">Send</button>
    </div>
  </div>
</main>

<script>
function setTask(text) {
  const ta = document.getElementById('task');
  ta.value = text;
  ta.style.height = 'auto';
  ta.style.height = ta.scrollHeight + 'px';
  ta.focus();
}

function addMessage(role, content, meta) {
  const el = document.getElementById('empty');
  if (el) el.remove();
  const msgs = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  const agentTag = meta && meta.agent ? '<span class="agent-tag">' + meta.agent + '</span>' : '';
  div.innerHTML = '<div class="msg-bubble">' + agentTag + escHtml(content) + '</div>' +
    (meta ? '<div class="msg-meta">' + (meta.label || '') + '</div>' : '');
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
  return div;
}

function addThinking() {
  const el = document.getElementById('empty');
  if (el) el.remove();
  const msgs = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = 'msg agent';
  div.id = 'thinking';
  div.innerHTML = '<div class="msg-bubble"><div class="thinking"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div></div>';
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
}

function removeThinking() {
  const el = document.getElementById('thinking');
  if (el) el.remove();
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

async function sendTask() {
  const ta = document.getElementById('task');
  const task = ta.value.trim();
  if (!task) return;
  ta.value = '';
  ta.style.height = 'auto';

  addMessage('user', task);
  addThinking();

  const btn = document.getElementById('send-btn');
  btn.disabled = true;

  try {
    const resp = await fetch('/think', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({task})
    });
    const data = await resp.json();
    removeThinking();
    if (data.error) {
      addMessage('agent', '⚠️ ' + data.error, {label: 'Error'});
    } else {
      addMessage('agent', data.output, {
        agent: data.agent_used,
        label: data.elapsed_s + 's  ·  ' + data.total_tokens + ' tokens'
      });
      // Update trace bar
      document.getElementById('t-agent').textContent  = data.agent_used || '—';
      document.getElementById('t-steps').textContent  = data.steps_taken || '—';
      document.getElementById('t-tokens').textContent = data.total_tokens || '—';
      document.getElementById('t-time').textContent   = (data.elapsed_s || '—') + 's';
      document.getElementById('trace-bar').style.display = 'flex';
    }
  } catch(e) {
    removeThinking();
    addMessage('agent', '⚠️ Network error: ' + e.message, {label: 'Error'});
  } finally {
    btn.disabled = false;
    ta.focus();
  }
}

// Check status on load
fetch('/status').then(r=>r.json()).then(d=>{
  document.getElementById('provider-label').textContent =
    'Backend: ' + (d.provider || 'unknown') + ' · Ready';
}).catch(()=>{
  document.getElementById('provider-label').textContent = 'Backend: offline';
});
</script>
</body>
</html>"""


_brain = None
_brain_lock = threading.Lock()


def get_brain():
    global _brain
    with _brain_lock:
        if _brain is None:
            from brain import Brain
            _brain = Brain(verbose=False)
    return _brain


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML


@app.get("/status")
async def status():
    try:
        brain = get_brain()
        return {"status": "ok", "provider": getattr(brain, "_provider", "unknown")}
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


@app.post("/think")
async def think(request: Request):
    data = await request.json()
    task = data.get("task", "").strip()
    if not task:
        return JSONResponse({"error": "No task provided"}, status_code=400)
    try:
        brain = get_brain()
        t0 = time.time()
        output = brain.think(task)
        elapsed = round(time.time() - t0, 1)
        # Pull last trace
        trace = brain._traces[-1] if brain._traces else None
        return {
            "output": output,
            "agent_used": trace.agent_used if trace else "general",
            "steps_taken": trace.steps_taken if trace else 0,
            "total_tokens": trace.total_tokens if trace else 0,
            "elapsed_s": elapsed,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


if __name__ == "__main__":
    print("🧠 Starting Agentic AI Brain on http://localhost:8001")
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning")

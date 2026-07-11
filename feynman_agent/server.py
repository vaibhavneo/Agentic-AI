from __future__ import annotations
"""
Feynman Agent Web Server — http://localhost:8002
"""
import os, sys, uuid, logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Load env keys
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
                if _v.strip() not in ("", "paste_your_key_here"):
                    os.environ.setdefault(_k.strip(), _v.strip())

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

logging.basicConfig(level=logging.WARNING)
app = FastAPI(title="Feynman QM Agent")

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Feynman — Quantum Mechanics Tutor</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Merriweather:ital,wght@0,300;0,400;1,300&family=Inter:wght@400;500;600&display=swap');
* { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #0d1117; --surface: #161b22; --border: #21262d;
  --text: #e6edf3; --muted: #8b949e; --accent: #f0883e;
  --accent2: #58a6ff; --green: #3fb950; --red: #f85149;
}
body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; display: flex; flex-direction: column; }
header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 0 24px; height: 56px; display: flex; align-items: center; gap: 16px; }
.logo { display: flex; align-items: center; gap: 10px; }
.logo-icon { font-size: 26px; }
.logo-text h1 { font-size: 16px; font-weight: 600; color: var(--text); }
.logo-text p { font-size: 11px; color: var(--muted); }
.hbadge { background: var(--accent)22; color: var(--accent); border: 1px solid var(--accent)44; border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: 600; }
.kbstat { margin-left: auto; font-size: 12px; color: var(--muted); display: flex; align-items: center; gap: 6px; }
.dot-live { width: 7px; height: 7px; border-radius: 50%; background: var(--green); }

main { flex: 1; display: grid; grid-template-columns: 260px 1fr; height: calc(100vh - 56px); }

/* Sidebar */
.sidebar { background: var(--surface); border-right: 1px solid var(--border); overflow-y: auto; padding: 16px 12px; display: flex; flex-direction: column; gap: 12px; }
.sidebar-section h3 { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: .1em; margin-bottom: 8px; padding: 0 4px; }
.topic-btn { width: 100%; text-align: left; background: none; border: 1px solid transparent; border-radius: 6px; padding: 8px 10px; cursor: pointer; color: var(--text); font-size: 13px; font-family: inherit; transition: all .15s; line-height: 1.4; }
.topic-btn:hover { background: var(--border); border-color: var(--accent)44; color: var(--accent); }
.topic-btn .emoji { margin-right: 6px; }
.divider { height: 1px; background: var(--border); }
.new-chat-btn { width: 100%; padding: 9px; background: var(--accent)22; border: 1px solid var(--accent)44; border-radius: 6px; color: var(--accent); font-size: 13px; font-weight: 600; cursor: pointer; font-family: inherit; transition: all .15s; }
.new-chat-btn:hover { background: var(--accent)33; }

/* Chat */
.chat-col { display: flex; flex-direction: column; height: 100%; }
.messages { flex: 1; overflow-y: auto; padding: 28px 32px; display: flex; flex-direction: column; gap: 24px; }
.welcome { text-align: center; padding: 48px 24px; }
.welcome-icon { font-size: 64px; margin-bottom: 12px; }
.welcome h2 { font-size: 22px; font-weight: 600; margin-bottom: 8px; color: var(--text); }
.welcome p { color: var(--muted); font-size: 14px; line-height: 1.7; max-width: 500px; margin: 0 auto; }
.welcome-quote { font-family: 'Merriweather', serif; font-style: italic; color: var(--accent); margin-top: 16px; font-size: 13px; }

.turn { display: flex; flex-direction: column; gap: 4px; }
.turn.user { align-items: flex-end; }
.turn.feynman { align-items: flex-start; }
.turn-label { font-size: 11px; color: var(--muted); padding: 0 4px; }
.bubble { max-width: 78%; padding: 14px 18px; border-radius: 12px; line-height: 1.75; font-size: 14px; white-space: pre-wrap; word-break: break-word; }
.turn.user .bubble { background: var(--accent2)22; border: 1px solid var(--accent2)44; color: var(--text); border-bottom-right-radius: 4px; }
.turn.feynman .bubble { background: var(--surface); border: 1px solid var(--border); color: var(--text); border-bottom-left-radius: 4px; font-family: 'Merriweather', serif; font-size: 14px; font-weight: 300; }
.sources { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 4px; }
.source-tag { background: var(--accent)11; color: var(--accent); border: 1px solid var(--accent)22; border-radius: 4px; padding: 1px 7px; font-size: 10px; font-family: 'Inter', sans-serif; }
.thinking-bubble { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; border-bottom-left-radius: 4px; padding: 14px 18px; display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 13px; }
.dots { display: flex; gap: 4px; }
.dot { width: 6px; height: 6px; background: var(--accent); border-radius: 50%; animation: pulse .9s infinite; }
.dot:nth-child(2) { animation-delay: .2s; }
.dot:nth-child(3) { animation-delay: .4s; }
@keyframes pulse { 0%,100% { opacity: .3; transform: scale(.8); } 50% { opacity: 1; transform: scale(1); } }

/* Input */
.input-bar { background: var(--surface); border-top: 1px solid var(--border); padding: 16px 24px; }
.input-row { display: flex; gap: 10px; align-items: flex-end; background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 8px 8px 8px 14px; transition: border-color .15s; }
.input-row:focus-within { border-color: var(--accent); }
textarea { flex: 1; background: none; border: none; color: var(--text); font-size: 14px; resize: none; outline: none; font-family: 'Inter', sans-serif; line-height: 1.5; max-height: 120px; padding: 4px 0; }
textarea::placeholder { color: var(--muted); }
.ask-btn { background: var(--accent); color: #0d1117; border: none; border-radius: 7px; width: 36px; height: 36px; display: flex; align-items: center; justify-content: center; cursor: pointer; font-size: 16px; flex-shrink: 0; transition: all .15s; font-weight: bold; }
.ask-btn:hover { background: #ffa64d; }
.ask-btn:disabled { background: var(--border); color: var(--muted); cursor: not-allowed; }
.hint { font-size: 11px; color: var(--muted); text-align: center; margin-top: 8px; }

/* Math rendering hint */
code { background: var(--border); padding: 1px 5px; border-radius: 3px; font-family: monospace; font-size: 13px; }
</style>
</head>
<body>
<header>
  <div class="logo">
    <div class="logo-icon">⚛️</div>
    <div class="logo-text">
      <h1>Feynman Agent</h1>
      <p>Quantum Mechanics Tutor · RAG-powered from your physics library</p>
    </div>
  </div>
  <div class="hbadge">Richard Feynman Persona</div>
  <div class="kbstat"><div class="dot-live"></div><span id="kb-stat">Loading knowledge base...</span></div>
</header>

<main>
  <div class="sidebar">
    <button class="new-chat-btn" onclick="newChat()">+ New Session</button>
    <div class="divider"></div>

    <div class="sidebar-section">
      <h3>🔬 Core QM</h3>
      <button class="topic-btn" onclick="ask('What is a wave function and what does it physically mean? Start from scratch.')"><span class="emoji">🌊</span>Wave Functions</button>
      <button class="topic-btn" onclick="ask('Derive the Schrödinger equation from first principles and explain every term physically.')"><span class="emoji">📐</span>Schrödinger Equation</button>
      <button class="topic-btn" onclick="ask('Explain the Heisenberg uncertainty principle — not just the math, but WHY it has to be true physically.')"><span class="emoji">🎯</span>Uncertainty Principle</button>
      <button class="topic-btn" onclick="ask('What is quantum superposition? Use an analogy before giving the math.')"><span class="emoji">🔀</span>Superposition</button>
      <button class="topic-btn" onclick="ask('Explain quantum entanglement from scratch — what is it, why does it happen, and what does it NOT mean?')"><span class="emoji">🔗</span>Entanglement</button>
    </div>

    <div class="sidebar-section">
      <h3>⚡ Key Systems</h3>
      <button class="topic-btn" onclick="ask('Solve the quantum harmonic oscillator — show me the physical insight, not just algebra.')"><span class="emoji">🎵</span>Harmonic Oscillator</button>
      <button class="topic-btn" onclick="ask('Walk me through the hydrogen atom solution in quantum mechanics. What determines the energy levels?')"><span class="emoji">⚛️</span>Hydrogen Atom</button>
      <button class="topic-btn" onclick="ask('What is quantum spin? Why is it not like a spinning top?')"><span class="emoji">🔄</span>Quantum Spin</button>
      <button class="topic-btn" onclick="ask('Explain the double-slit experiment and what it reveals about the nature of quantum reality.')"><span class="emoji">🔦</span>Double-Slit Experiment</button>
    </div>

    <div class="sidebar-section">
      <h3>🧩 Advanced</h3>
      <button class="topic-btn" onclick="ask('Explain the path integral formulation of quantum mechanics — what is the physical idea?')"><span class="emoji">🛤️</span>Path Integrals</button>
      <button class="topic-btn" onclick="ask('What is perturbation theory and when do we use it?')"><span class="emoji">📊</span>Perturbation Theory</button>
      <button class="topic-btn" onclick="ask('What is the measurement problem in quantum mechanics? What really happens when we observe something?')"><span class="emoji">👁️</span>Measurement Problem</button>
      <button class="topic-btn" onclick="ask('Explain quantum tunneling — how can a particle go through a wall?')"><span class="emoji">🚇</span>Quantum Tunneling</button>
    </div>

    <div class="sidebar-section">
      <h3>💡 Feynman Style</h3>
      <button class="topic-btn" onclick="ask('Explain quantum mechanics to me as if I am 10 years old.')"><span class="emoji">🧒</span>Explain Like I'm 10</button>
      <button class="topic-btn" onclick="ask('What is the most beautiful idea in all of physics, in your opinion?')"><span class="emoji">✨</span>Most Beautiful Idea</button>
      <button class="topic-btn" onclick="ask('What did you mean when you said nobody really understands quantum mechanics?')"><span class="emoji">🤔</span>"Nobody understands QM"</button>
    </div>
  </div>

  <div class="chat-col">
    <div class="messages" id="messages">
      <div class="welcome" id="welcome">
        <div class="welcome-icon">⚛️</div>
        <h2>Welcome to Feynman Agent</h2>
        <p>I'm Richard Feynman — physicist, teacher, and eternal student of nature. Ask me anything about quantum mechanics. I'll start from first principles and build up until it clicks.</p>
        <p class="welcome-quote">"If you think you understand quantum mechanics, you don't understand quantum mechanics."</p>
      </div>
    </div>
    <div class="input-bar">
      <div class="input-row">
        <textarea id="q" placeholder="Ask me anything about quantum mechanics..." rows="1"
          onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendQ()}"
          oninput="this.style.height='auto';this.style.height=this.scrollHeight+'px'"></textarea>
        <button class="ask-btn" id="ask-btn" onclick="sendQ()">↑</button>
      </div>
      <div class="hint">Enter to send · Shift+Enter for newline · Powered by your physics library (Feynman Lectures, Griffiths, Shankar, Sakurai + 30 more books)</div>
    </div>
  </div>
</main>

<script>
let SESSION_ID = crypto.randomUUID();

function ask(q) {
  document.getElementById('q').value = q;
  sendQ();
}

function newChat() {
  SESSION_ID = crypto.randomUUID();
  const msgs = document.getElementById('messages');
  msgs.innerHTML = `<div class="welcome" id="welcome">
    <div class="welcome-icon">⚛️</div>
    <h2>New Session Started</h2>
    <p>Ask me anything about quantum mechanics — I'm ready to start fresh!</p>
  </div>`;
}

function esc(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function addTurn(role, text, sources) {
  const w = document.getElementById('welcome');
  if (w) w.remove();
  const msgs = document.getElementById('messages');

  const div = document.createElement('div');
  div.className = 'turn ' + role;
  const label = role === 'user' ? 'You' : 'Prof. Feynman';

  let sourcesHtml = '';
  if (sources && sources.length > 0) {
    const tags = sources.slice(0,4).map(s => {
      const short = s.replace(/\(.*?\)/g,'').replace(/\.pdf$/,'').trim().slice(0,45);
      return `<span class="source-tag">📚 ${esc(short)}</span>`;
    }).join('');
    sourcesHtml = `<div class="sources">${tags}</div>`;
  }

  div.innerHTML = `
    <div class="turn-label">${label}</div>
    <div class="bubble">${esc(text)}</div>
    ${sourcesHtml}
  `;
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
  return div;
}

function addThinking() {
  const w = document.getElementById('welcome');
  if (w) w.remove();
  const msgs = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = 'turn feynman';
  div.id = 'thinking';
  div.innerHTML = `
    <div class="turn-label">Prof. Feynman</div>
    <div class="thinking-bubble">
      <div class="dots"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>
      Thinking through the physics...
    </div>`;
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
}

async function sendQ() {
  const ta = document.getElementById('q');
  const q = ta.value.trim();
  if (!q) return;
  ta.value = '';
  ta.style.height = 'auto';

  addTurn('user', q);
  addThinking();
  document.getElementById('ask-btn').disabled = true;

  try {
    const resp = await fetch('/ask', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question: q, session_id: SESSION_ID})
    });
    const data = await resp.json();
    document.getElementById('thinking').remove();
    if (data.error) {
      addTurn('feynman', '⚠️ ' + data.error);
    } else {
      addTurn('feynman', data.answer, data.sources);
    }
  } catch(e) {
    document.getElementById('thinking').remove();
    addTurn('feynman', '⚠️ Network error: ' + e.message);
  } finally {
    document.getElementById('ask-btn').disabled = false;
    ta.focus();
  }
}

// Load KB status
fetch('/status').then(r=>r.json()).then(d=>{
  const el = document.getElementById('kb-stat');
  if (d.kb_chunks) {
    el.textContent = d.kb_chunks.toLocaleString() + ' chunks · ' + d.kb_books + ' books · ' + d.provider;
  } else {
    el.textContent = d.status || 'Ready';
  }
}).catch(()=>{
  document.getElementById('kb-stat').textContent = 'offline';
});
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML


@app.get("/status")
async def status():
    try:
        from agent import get_session, _kb, _provider
        # Trigger KB load
        sess = get_session("__probe__")
        from agent import _kb as kb, _provider as prov
        books = len(set(kb.get("sources", []))) if kb else 0
        return {
            "status": "ok",
            "kb_chunks": kb.get("total", 0) if kb else 0,
            "kb_books": books,
            "provider": prov or "unknown",
        }
    except Exception as e:
        return {"status": "loading", "detail": str(e)}


@app.post("/ask")
async def ask(request: Request):
    data = await request.json()
    question = data.get("question", "").strip()
    session_id = data.get("session_id", "default")
    if not question:
        return JSONResponse({"error": "No question provided"}, status_code=400)
    try:
        from agent import get_session
        agent = get_session(session_id)
        result = agent.ask(question, session_id)
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/reset")
async def reset(request: Request):
    data = await request.json()
    session_id = data.get("session_id", "default")
    from agent import reset_session
    reset_session(session_id)
    return {"status": "ok"}


if __name__ == "__main__":
    print("⚛️  Starting Feynman Agent on http://localhost:8002")
    print("📚 Ingesting physics library on first run — may take 1-2 min...")
    uvicorn.run(app, host="127.0.0.1", port=8002, log_level="warning")

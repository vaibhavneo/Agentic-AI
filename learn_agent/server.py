from __future__ import annotations
"""
AI Learning Agent — Web Server
http://localhost:8003
"""
import os, sys, uuid, logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

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
app = FastAPI(title="AI Learning Agent")

# AIOS P0 — mission/corpus/gateway API (mission workspace lives at /app)
# Mission Control — the new default landing page at "/" (see MISSION_CONTROL.md)
# (legacy tutor endpoints below are untouched, now served at /legacy)
try:
    from aios_api import mount as _aios_mount
    _aios_mount(app)
except Exception as _e:
    logging.warning(f"AIOS API not mounted: {_e}")

try:
    from mission_control_api import mount as _mc_mount
    _mc_mount(app)
except Exception as _e:
    logging.warning(f"Mission Control not mounted: {_e}")

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>AI Learning Agent</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#09090b;--surface:#18181b;--surface2:#27272a;--border:#3f3f46;
  --text:#fafafa;--muted:#a1a1aa;--accent:#818cf8;--accent-dim:#818cf822;
  --green:#4ade80;--yellow:#fbbf24;--red:#f87171;--blue:#60a5fa;
  --purple:#c084fc;--orange:#fb923c;--teal:#2dd4bf;
}
body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);height:100vh;display:flex;flex-direction:column}

/* Header */
header{background:var(--surface);border-bottom:1px solid var(--border);padding:0 20px;height:52px;display:flex;align-items:center;gap:12px;flex-shrink:0}
.hlogo{font-size:20px}
.htitle{font-size:15px;font-weight:700}
.hsub{font-size:11px;color:var(--muted);margin-left:2px}
.hbadges{display:flex;gap:6px;margin-left:8px}
.badge{background:var(--accent-dim);color:var(--accent);border:1px solid var(--accent)44;border-radius:5px;padding:2px 8px;font-size:11px;font-weight:600;white-space:nowrap}
.badge.green{background:#4ade8022;color:var(--green);border-color:#4ade8044}
.badge.yellow{background:#fbbf2422;color:var(--yellow);border-color:#fbbf2444}
#kb-badge{margin-left:auto;font-size:11px;color:var(--muted);display:flex;align-items:center;gap:5px}
.live-dot{width:6px;height:6px;border-radius:50%;background:var(--green)}

/* Layout */
main{flex:1;display:grid;grid-template-columns:250px 1fr 220px;min-height:0}

/* Left sidebar — Topics */
.topics{background:var(--surface);border-right:1px solid var(--border);overflow-y:auto;padding:12px 10px;display:flex;flex-direction:column;gap:10px}
.topics h3{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;padding:0 4px;margin-top:4px}
.topic-chip{width:100%;text-align:left;background:none;border:1px solid transparent;border-radius:6px;padding:7px 10px;cursor:pointer;color:var(--text);font-size:12.5px;font-family:inherit;transition:all .12s;line-height:1.4;display:flex;align-items:flex-start;gap:6px}
.topic-chip:hover{background:var(--surface2);border-color:var(--accent)44}
.topic-chip .tc-icon{flex-shrink:0;font-size:14px}
.topic-chip .tc-text{flex:1}
.divider{height:1px;background:var(--border);margin:2px 0}

/* Category filter */
.cat-filter{display:flex;flex-wrap:wrap;gap:4px;padding:8px 10px;border-bottom:1px solid var(--border)}
.cat-btn{background:var(--surface2);border:1px solid var(--border);border-radius:4px;padding:3px 8px;font-size:11px;cursor:pointer;color:var(--muted);font-family:inherit;transition:all .12s}
.cat-btn:hover,.cat-btn.active{color:var(--accent);border-color:var(--accent)66;background:var(--accent-dim)}

/* Chat area */
.chat{display:flex;flex-direction:column;min-height:0}
.messages{flex:1;overflow-y:auto;padding:20px 24px;display:flex;flex-direction:column;gap:20px}

.welcome{text-align:center;padding:40px 20px;max-width:560px;margin:0 auto}
.welcome-icon{font-size:56px;margin-bottom:12px}
.welcome h2{font-size:20px;font-weight:700;margin-bottom:8px}
.welcome p{color:var(--muted);font-size:13px;line-height:1.7}
.kb-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:16px;text-align:left}
.kb-card{background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:10px 12px}
.kb-card-label{font-size:10px;color:var(--muted);margin-bottom:3px}
.kb-card-val{font-size:18px;font-weight:700;color:var(--accent)}
.kb-card-sub{font-size:11px;color:var(--muted);margin-top:1px}

.turn{display:flex;flex-direction:column;gap:4px}
.turn.user{align-items:flex-end}
.turn.ai{align-items:flex-start}
.turn-label{font-size:10px;color:var(--muted);padding:0 4px;font-weight:500}
.bubble{max-width:82%;padding:12px 16px;border-radius:12px;line-height:1.75;font-size:13.5px;white-space:pre-wrap;word-break:break-word}
.turn.user .bubble{background:var(--accent)22;border:1px solid var(--accent)44;border-bottom-right-radius:3px}
.turn.ai .bubble{background:var(--surface);border:1px solid var(--border);border-bottom-left-radius:3px}
.src-row{display:flex;flex-wrap:wrap;gap:4px;padding:0 2px}
.src-chip{display:inline-flex;align-items:center;gap:4px;background:var(--surface2);border:1px solid var(--border);border-radius:4px;padding:2px 7px;font-size:10.5px;color:var(--muted);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.src-chip .cat-dot{width:5px;height:5px;border-radius:50%;flex-shrink:0}

.thinking{display:flex;align-items:center;gap:8px;background:var(--surface);border:1px solid var(--border);border-radius:10px;border-bottom-left-radius:3px;padding:12px 16px;color:var(--muted);font-size:13px}
.dots{display:flex;gap:3px}
.dot{width:5px;height:5px;background:var(--accent);border-radius:50%;animation:dp .9s infinite}
.dot:nth-child(2){animation-delay:.2s}
.dot:nth-child(3){animation-delay:.4s}
@keyframes dp{0%,100%{opacity:.2;transform:scale(.7)}50%{opacity:1;transform:scale(1)}}

/* Input */
.input-area{background:var(--surface);border-top:1px solid var(--border);padding:12px 16px;flex-shrink:0}
.input-wrap{display:flex;gap:8px;align-items:flex-end;background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:8px 8px 8px 14px;transition:border-color .15s}
.input-wrap:focus-within{border-color:var(--accent)}
textarea{flex:1;background:none;border:none;color:var(--text);font-size:13.5px;resize:none;outline:none;font-family:inherit;line-height:1.5;max-height:100px}
textarea::placeholder{color:var(--muted)}
.send-btn{background:var(--accent);color:#09090b;border:none;border-radius:7px;width:34px;height:34px;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:15px;font-weight:700;flex-shrink:0;transition:all .12s}
.send-btn:hover{filter:brightness(1.15)}
.send-btn:disabled{background:var(--border);color:var(--muted);cursor:not-allowed}
.input-hint{font-size:10.5px;color:var(--muted);margin-top:6px;text-align:center}

/* Right sidebar — Learning paths */
.right-panel{background:var(--surface);border-left:1px solid var(--border);overflow-y:auto;padding:12px 10px;display:flex;flex-direction:column;gap:10px}
.right-panel h3{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;padding:0 4px}
.path-btn{width:100%;text-align:left;background:none;border:1px solid var(--border);border-radius:6px;padding:8px 10px;cursor:pointer;color:var(--text);font-size:12px;font-family:inherit;transition:all .12s;line-height:1.4}
.path-btn:hover{background:var(--surface2);border-color:var(--green)66;color:var(--green)}
.session-btn{width:100%;padding:8px;background:var(--surface2);border:1px solid var(--border);border-radius:6px;color:var(--muted);font-size:12px;cursor:pointer;font-family:inherit;transition:all .12s;margin-top:4px}
.session-btn:hover{border-color:var(--red)66;color:var(--red)}
.stats-grid{display:flex;flex-direction:column;gap:6px}
.stat-row2{background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px}
.stat-label2{font-size:10px;color:var(--muted);margin-bottom:2px}
.stat-val2{font-size:14px;font-weight:700;color:var(--text)}

/* Category colors */
.cat-agentic{color:#818cf8} .cat-research{color:#fbbf24} .cat-vibe{color:#4ade80}
.cat-ai{color:#60a5fa} .cat-finance{color:#2dd4bf} .cat-health{color:#f87171}
.cat-quantum{color:#c084fc}
</style>
</head>
<body>
<header>
  <div class="hlogo">🤖</div>
  <div>
    <div class="htitle">AI Learning Agent</div>
  </div>
  <div class="hbadges">
    <span class="badge">Agentic AI</span>
    <span class="badge yellow">LLMs</span>
    <span class="badge green">GenAI</span>
  </div>
  <div id="kb-badge"><div class="live-dot"></div><span id="kb-stat">Loading...</span></div>
</header>

<main>
  <!-- Left: Topics -->
  <div class="topics">
    <h3>🤖 Agentic AI</h3>
    <button class="topic-chip" onclick="ask('What are the core agentic AI design patterns and when should I use each one?')"><span class="tc-icon">🔄</span><span class="tc-text">Agentic Design Patterns</span></button>
    <button class="topic-chip" onclick="ask('Explain the ReAct (Reasoning + Acting) pattern with a concrete example')"><span class="tc-icon">⚡</span><span class="tc-text">ReAct Pattern</span></button>
    <button class="topic-chip" onclick="ask('How do I build a multi-agent system? What are the main orchestration patterns?')"><span class="tc-icon">🕸️</span><span class="tc-text">Multi-Agent Systems</span></button>
    <button class="topic-chip" onclick="ask('How does RAG work and what are the different RAG architectures?')"><span class="tc-icon">🔍</span><span class="tc-text">RAG Architectures</span></button>
    <button class="topic-chip" onclick="ask('What is MCP (Model Context Protocol) and how do I build an MCP server?')"><span class="tc-icon">🔌</span><span class="tc-text">MCP Protocol</span></button>
    <button class="topic-chip" onclick="ask('Compare LangGraph vs CrewAI vs AutoGen vs OpenAI Agents SDK — which should I use?')"><span class="tc-icon">📊</span><span class="tc-text">Framework Comparison</span></button>
    <button class="topic-chip" onclick="ask('How do I add memory to an AI agent? What are the 5 types of agent memory?')"><span class="tc-icon">🧠</span><span class="tc-text">Agent Memory Systems</span></button>

    <div class="divider"></div>
    <h3>🤯 LLMs & Foundation Models</h3>
    <button class="topic-chip" onclick="ask('Explain the transformer architecture from scratch — attention, positional encoding, everything')"><span class="tc-icon">🏗️</span><span class="tc-text">Transformer Architecture</span></button>
    <button class="topic-chip" onclick="ask('What is RLHF and how does it work? What are the alternatives?')"><span class="tc-icon">🎯</span><span class="tc-text">RLHF & Alignment</span></button>
    <button class="topic-chip" onclick="ask('How does fine-tuning work? When should I fine-tune vs use RAG vs prompt engineering?')"><span class="tc-icon">🔧</span><span class="tc-text">Fine-Tuning vs RAG</span></button>
    <button class="topic-chip" onclick="ask('What is context engineering? How do I manage context windows effectively?')"><span class="tc-icon">📝</span><span class="tc-text">Context Engineering</span></button>
    <button class="topic-chip" onclick="ask('How do I evaluate LLM outputs? What metrics and evaluation frameworks should I use?')"><span class="tc-icon">📏</span><span class="tc-text">LLM Evaluation</span></button>

    <div class="divider"></div>
    <h3>🎨 Generative AI</h3>
    <button class="topic-chip" onclick="ask('How do diffusion models work? Explain the forward and reverse process.')"><span class="tc-icon">🌊</span><span class="tc-text">Diffusion Models</span></button>
    <button class="topic-chip" onclick="ask('What is prompt engineering? Give me the most effective techniques.')"><span class="tc-icon">✍️</span><span class="tc-text">Prompt Engineering</span></button>
    <button class="topic-chip" onclick="ask('How do multimodal AI models work — vision + language combined?')"><span class="tc-icon">👁️</span><span class="tc-text">Multimodal AI</span></button>

    <div class="divider"></div>
    <h3>🏭 Production AI</h3>
    <button class="topic-chip" onclick="ask('What is the production AI engineering stack? How do I take an agent to production?')"><span class="tc-icon">🚀</span><span class="tc-text">Production Engineering</span></button>
    <button class="topic-chip" onclick="ask('How do I make AI agents reliable and handle failures gracefully?')"><span class="tc-icon">🛡️</span><span class="tc-text">Reliability Patterns</span></button>
    <button class="topic-chip" onclick="ask('How do I add observability and monitoring to an AI agent system?')"><span class="tc-icon">📡</span><span class="tc-text">Observability & Tracing</span></button>
  </div>

  <!-- Center: Chat -->
  <div class="chat">
    <div class="cat-filter" id="cat-filter">
      <button class="cat-btn active" onclick="setCategory('All', this)">All</button>
    </div>
    <div class="messages" id="messages">
      <div class="welcome" id="welcome">
        <div class="welcome-icon">🤖</div>
        <h2>AI Learning Agent</h2>
        <p>Your personal tutor for Agentic AI, LLMs, Generative AI, and production engineering — grounded in your full book and research paper library.</p>
        <div class="kb-grid" id="kb-grid">
          <div class="kb-card"><div class="kb-card-label">Knowledge Chunks</div><div class="kb-card-val" id="stat-chunks">—</div><div class="kb-card-sub">indexed passages</div></div>
          <div class="kb-card"><div class="kb-card-label">Books & Papers</div><div class="kb-card-val" id="stat-books">—</div><div class="kb-card-sub">source documents</div></div>
        </div>
      </div>
    </div>
    <div class="input-area">
      <div class="input-wrap">
        <textarea id="q" placeholder="Ask anything about AI agents, LLMs, RAG, frameworks, production engineering..." rows="1"
          onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendQ()}"
          oninput="this.style.height='auto';this.style.height=Math.min(this.scrollHeight,100)+'px'"></textarea>
        <button class="send-btn" id="send-btn" onclick="sendQ()">↑</button>
      </div>
      <div class="input-hint">Enter to send · Shift+Enter for newline · Filter by category above</div>
    </div>
  </div>

  <!-- Right: Learning paths + stats -->
  <div class="right-panel">
    <h3>📚 Learning Paths</h3>
    <button class="path-btn" onclick="learningPath('building production-ready agentic AI systems from scratch')">🏗️ Build Agentic Systems</button>
    <button class="path-btn" onclick="learningPath('understanding and working with Large Language Models')">🧠 Master LLMs</button>
    <button class="path-btn" onclick="learningPath('implementing RAG systems for production')">🔍 RAG Engineering</button>
    <button class="path-btn" onclick="learningPath('going from prototype to production AI deployment')">🚀 Production Deployment</button>
    <button class="path-btn" onclick="learningPath('multi-agent system design and orchestration')">🕸️ Multi-Agent Design</button>
    <button class="path-btn" onclick="learningPath('fine-tuning and adapting foundation models')">🔧 Fine-Tuning Models</button>

    <div class="divider" style="margin:4px 0"></div>
    <h3>📊 Knowledge Base</h3>
    <div class="stats-grid" id="cat-stats"></div>

    <div class="divider" style="margin:4px 0"></div>
    <button class="session-btn" onclick="newSession()">🔄 New Session</button>
  </div>
</main>

<script>
let SESSION_ID = crypto.randomUUID();
let activeCategory = 'All';
const CAT_COLORS = {
  "Agentic AI":"#818cf8","Research Papers":"#fbbf24","Vibe Coding":"#4ade80",
  "AI & ML":"#60a5fa","AI in Finance":"#2dd4bf","AI in Healthcare":"#f87171","Quantum Computing":"#c084fc"
};

function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

function setCategory(cat, btn) {
  activeCategory = cat;
  document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
}

function ask(q) {
  document.getElementById('q').value = q;
  sendQ();
}

function newSession() {
  SESSION_ID = crypto.randomUUID();
  const msgs = document.getElementById('messages');
  msgs.innerHTML = `<div class="welcome" id="welcome">
    <div class="welcome-icon">🤖</div>
    <h2>New Session</h2>
    <p>Fresh start! Ask me anything about AI agents, LLMs, or generative AI.</p>
  </div>`;
}

function addTurn(role, text, sources) {
  const w = document.getElementById('welcome');
  if(w) w.remove();
  const msgs = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = 'turn ' + role;
  const label = role === 'user' ? 'You' : 'AI Tutor';

  let srcHtml = '';
  if(sources && sources.length) {
    const chips = sources.slice(0,5).map(s => {
      const color = CAT_COLORS[s.category] || '#a1a1aa';
      const name = s.source.split('(')[0].replace(/\.pdf$/,'').trim().slice(0,38);
      return `<span class="src-chip"><span class="cat-dot" style="background:${color}"></span>${esc(name)}</span>`;
    }).join('');
    srcHtml = `<div class="src-row">${chips}</div>`;
  }

  div.innerHTML = `<div class="turn-label">${label}</div><div class="bubble">${esc(text)}</div>${srcHtml}`;
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
}

function addThinking(label) {
  const w = document.getElementById('welcome');
  if(w) w.remove();
  const msgs = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = 'turn ai';
  div.id = 'thinking';
  div.innerHTML = `<div class="turn-label">AI Tutor</div>
    <div class="thinking"><div class="dots"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>${esc(label||'Searching knowledge base...')}</div>`;
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
}

async function sendQ() {
  const ta = document.getElementById('q');
  const q = ta.value.trim();
  if(!q) return;
  ta.value = '';
  ta.style.height = 'auto';
  addTurn('user', q);
  addThinking('Retrieving from ' + (activeCategory === 'All' ? 'all sources' : activeCategory) + '...');
  document.getElementById('send-btn').disabled = true;
  try {
    const resp = await fetch('/ask', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({question:q, session_id:SESSION_ID, category:activeCategory})
    });
    const data = await resp.json();
    document.getElementById('thinking').remove();
    if(data.error) addTurn('ai', '⚠️ '+data.error);
    else addTurn('ai', data.answer, data.sources);
  } catch(e) {
    document.getElementById('thinking').remove();
    addTurn('ai', '⚠️ Error: '+e.message);
  } finally {
    document.getElementById('send-btn').disabled = false;
    ta.focus();
  }
}

async function learningPath(topic) {
  addTurn('user', 'Give me a learning path for: ' + topic);
  addThinking('Building your learning path...');
  document.getElementById('send-btn').disabled = true;
  try {
    const resp = await fetch('/learning-path', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({topic, session_id:SESSION_ID})
    });
    const data = await resp.json();
    document.getElementById('thinking').remove();
    if(data.error) addTurn('ai', '⚠️ '+data.error);
    else addTurn('ai', data.path);
  } catch(e) {
    document.getElementById('thinking').remove();
    addTurn('ai', '⚠️ Error: '+e.message);
  } finally {
    document.getElementById('send-btn').disabled = false;
  }
}

// Load status + build category filter
fetch('/status').then(r=>r.json()).then(d=>{
  if(d.kb_chunks){
    document.getElementById('kb-stat').textContent =
      d.kb_chunks.toLocaleString()+' chunks · '+d.kb_books+' docs · '+d.provider;
    const sc = document.getElementById('stat-chunks');
    const sb = document.getElementById('stat-books');
    if(sc) sc.textContent = d.kb_chunks.toLocaleString();
    if(sb) sb.textContent = d.kb_books;

    // Category filter buttons
    const cf = document.getElementById('cat-filter');
    const cats = Object.keys(d.categories||{});
    cats.forEach(cat => {
      const btn = document.createElement('button');
      btn.className = 'cat-btn';
      btn.textContent = cat;
      btn.onclick = () => setCategory(cat, btn);
      cf.appendChild(btn);
    });

    // Category stats
    const sg = document.getElementById('cat-stats');
    const sorted = Object.entries(d.categories||{}).sort((a,b)=>b[1]-a[1]);
    sorted.forEach(([cat, cnt]) => {
      const color = CAT_COLORS[cat]||'#a1a1aa';
      const div = document.createElement('div');
      div.className = 'stat-row2';
      div.innerHTML = `<div class="stat-label2" style="color:${color}">${cat}</div><div class="stat-val2">${cnt.toLocaleString()} <span style="font-size:10px;font-weight:400;color:var(--muted)">chunks</span></div>`;
      sg.appendChild(div);
    });
  }
}).catch(()=>{ document.getElementById('kb-stat').textContent='offline'; });
</script>
</body>
</html>"""


@app.get("/legacy", response_class=HTMLResponse)
async def index():
    return HTML


@app.get("/status")
async def status():
    try:
        from agent import get_kb_stats, get_session, _provider
        get_session("__probe__")
        from agent import _provider as prov
        stats = get_kb_stats()
        return {
            "status": "ok",
            "kb_chunks": stats.get("total_chunks", 0),
            "kb_books": stats.get("total_books", 0),
            "categories": stats.get("categories", {}),
            "provider": prov or "unknown",
        }
    except Exception as e:
        return {"status": "loading", "detail": str(e)}


@app.post("/ask")
async def ask_endpoint(request: Request):
    data = await request.json()
    question = data.get("question", "").strip()
    session_id = data.get("session_id", "default")
    category = data.get("category", "All")
    if not question:
        return JSONResponse({"error": "No question"}, status_code=400)
    try:
        from agent import get_session
        agent = get_session(session_id)
        result = agent.ask(question, category=category)
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/learning-path")
async def learning_path(request: Request):
    data = await request.json()
    topic = data.get("topic", "")
    session_id = data.get("session_id", "default")
    try:
        from agent import get_session
        agent = get_session(session_id)
        path = agent.suggest_path(topic)
        return {"path": path}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/reset")
async def reset(request: Request):
    data = await request.json()
    from agent import reset_session
    reset_session(data.get("session_id", "default"))
    return {"status": "ok"}


if __name__ == "__main__":
    print("🤖 Starting AI Learning Agent on http://localhost:8003")
    print("📚 Ingesting knowledge base (first run ~2 min)...")
    uvicorn.run(app, host="127.0.0.1", port=8003, log_level="warning")

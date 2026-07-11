from __future__ import annotations
"""
Web UI server for the Health Vitals Monitoring Agent.
Run: python3 server.py
Then open: http://localhost:8000
"""
import os
import sys
import uuid
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

# Load env from this project's .env, then fall back to the shared stock_agent/.env
from dotenv import load_dotenv
load_dotenv()
for _env in [Path(__file__).parent / ".env",
             Path(__file__).parent.parent / "stock_agent" / ".env"]:
    if _env.exists():
        for _line in _env.read_text().splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                if _v.strip() and _v.strip() != "paste_your_key_here":
                    os.environ.setdefault(_k.strip(), _v.strip())

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Health Vitals Monitoring Agent")

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Health Vitals Monitor</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }
  header { background: #1e293b; border-bottom: 1px solid #334155; padding: 16px 24px; display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 20px; font-weight: 700; color: #f8fafc; }
  header span { font-size: 13px; color: #94a3b8; }
  .badge { background: #22c55e22; color: #22c55e; border: 1px solid #22c55e44; border-radius: 999px; padding: 2px 10px; font-size: 12px; }
  main { max-width: 960px; margin: 0 auto; padding: 32px 24px; }
  .card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 24px; margin-bottom: 24px; }
  h2 { font-size: 15px; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 16px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 20px; }
  label { display: block; font-size: 12px; color: #64748b; margin-bottom: 4px; }
  input, select, textarea { width: 100%; background: #0f172a; border: 1px solid #334155; border-radius: 8px; color: #e2e8f0; padding: 8px 12px; font-size: 14px; outline: none; transition: border-color .15s; }
  input:focus, select:focus, textarea:focus { border-color: #3b82f6; }
  input::placeholder { color: #475569; }
  .row { display: flex; gap: 12px; align-items: flex-end; margin-bottom: 12px; }
  .row .field { flex: 1; }
  btn-group { display: flex; gap: 8px; }
  button { padding: 10px 20px; border: none; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; transition: all .15s; }
  .btn-primary { background: #3b82f6; color: white; }
  .btn-primary:hover { background: #2563eb; }
  .btn-demo { background: #7c3aed; color: white; }
  .btn-demo:hover { background: #6d28d9; }
  .btn-secondary { background: #334155; color: #e2e8f0; }
  .btn-secondary:hover { background: #475569; }
  .btn-group { display: flex; gap: 8px; flex-wrap: wrap; }
  #results { display: none; }
  .summary-box { background: #0f172a; border-radius: 8px; padding: 16px; margin-bottom: 16px; border-left: 4px solid #22c55e; }
  .summary-box.has-critical { border-left-color: #ef4444; }
  .summary-box.has-warning { border-left-color: #f59e0b; }
  .summary-title { font-size: 13px; color: #94a3b8; margin-bottom: 8px; }
  .summary-vitals { font-size: 13px; color: #cbd5e1; margin-bottom: 8px; line-height: 1.8; }
  .summary-text { font-size: 14px; color: #e2e8f0; line-height: 1.6; }
  .alert-table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .alert-table th { text-align: left; padding: 8px 12px; color: #64748b; font-weight: 500; border-bottom: 1px solid #334155; }
  .alert-table td { padding: 10px 12px; border-bottom: 1px solid #1e293b; vertical-align: top; line-height: 1.5; }
  .sev { display: inline-block; padding: 2px 8px; border-radius: 999px; font-weight: 700; font-size: 11px; }
  .sev-CRITICAL { background: #ef444422; color: #ef4444; border: 1px solid #ef444444; }
  .sev-WARNING  { background: #f59e0b22; color: #f59e0b; border: 1px solid #f59e0b44; }
  .sev-INFO     { background: #3b82f622; color: #3b82f6; border: 1px solid #3b82f644; }
  .no-alerts { text-align: center; padding: 32px; color: #22c55e; font-size: 15px; }
  .spinner { display: none; width: 20px; height: 20px; border: 2px solid #334155; border-top-color: #3b82f6; border-radius: 50%; animation: spin .7s linear infinite; margin-left: 8px; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .loading { display: flex; align-items: center; gap: 8px; color: #94a3b8; font-size: 14px; padding: 16px; }
  .tab-bar { display: flex; gap: 4px; margin-bottom: 16px; }
  .tab { padding: 6px 14px; border-radius: 6px; font-size: 13px; cursor: pointer; color: #64748b; border: 1px solid transparent; }
  .tab.active { background: #3b82f622; color: #3b82f6; border-color: #3b82f644; }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }
  .file-input-wrap { position: relative; }
  .file-input-wrap input[type=file] { opacity: 0; position: absolute; inset: 0; cursor: pointer; }
  .file-label { display: flex; align-items: center; gap: 8px; background: #0f172a; border: 1px dashed #334155; border-radius: 8px; padding: 12px; font-size: 13px; color: #64748b; cursor: pointer; }
  .stat-row { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 12px; }
  .stat { background: #0f172a; border-radius: 8px; padding: 10px 16px; font-size: 13px; }
  .stat-val { font-size: 20px; font-weight: 700; color: #f8fafc; }
  .stat-label { color: #64748b; font-size: 11px; margin-top: 2px; }
</style>
</head>
<body>
<header>
  <div style="font-size:22px">🏥</div>
  <h1>Health Vitals Monitor</h1>
  <span>Powered by DeepSeek + LangGraph</span>
  <div class="badge" style="margin-left:auto">● Live</div>
</header>
<main>

<div class="card">
  <h2>Input Vitals</h2>
  <div class="tab-bar">
    <div class="tab active" onclick="switchTab('manual')">Manual Entry</div>
    <div class="tab" onclick="switchTab('text')">Text / JSON Feed</div>
    <div class="tab" onclick="switchTab('file')">File Upload (PDF/DOCX)</div>
    <div class="tab" onclick="switchTab('screen')">Screenshot</div>
  </div>

  <!-- Manual Entry -->
  <div id="tab-manual" class="tab-panel active">
    <div class="grid">
      <div><label>Patient ID</label><input id="patient_id" placeholder="P001" value="P001"></div>
      <div><label>Heart Rate (bpm)</label><input id="heart_rate" type="number" placeholder="72"></div>
      <div><label>Systolic BP (mmHg)</label><input id="systolic_bp" type="number" placeholder="120"></div>
      <div><label>Diastolic BP (mmHg)</label><input id="diastolic_bp" type="number" placeholder="80"></div>
      <div><label>SpO2 (%)</label><input id="spo2" type="number" placeholder="98"></div>
      <div><label>Temperature (°C)</label><input id="temperature" type="number" step="0.1" placeholder="36.6"></div>
      <div><label>Resp. Rate (/min)</label><input id="respiratory_rate" type="number" placeholder="16"></div>
      <div><label>Glucose (mg/dL)</label><input id="glucose" type="number" placeholder="95"></div>
    </div>
  </div>

  <!-- Text Feed -->
  <div id="tab-text" class="tab-panel">
    <div style="margin-bottom:8px">
      <label>Paste vitals as text or JSON</label>
      <textarea id="text_feed" rows="3" placeholder='HR=88 BP=145/92 SpO2=94 Temp=37.8 patient=P001&#10;or: {"heart_rate": 88, "spo2": 94, "patient_id": "P001"}'></textarea>
    </div>
  </div>

  <!-- File Upload -->
  <div id="tab-file" class="tab-panel">
    <div class="file-input-wrap">
      <div class="file-label" id="file-label">📎 Click to upload PDF or DOCX health report</div>
      <input type="file" id="file_upload" accept=".pdf,.docx" onchange="updateFileLabel()">
    </div>
    <p style="color:#475569;font-size:12px;margin-top:8px">Lab reports, discharge summaries, clinical notes</p>
  </div>

  <!-- Screenshot -->
  <div id="tab-screen" class="tab-panel">
    <div class="file-input-wrap">
      <div class="file-label" id="screen-label">📸 Upload screenshot of monitor / health app</div>
      <input type="file" id="screen_upload" accept="image/*" onchange="updateScreenLabel()">
    </div>
    <p style="color:#475569;font-size:12px;margin-top:8px">Hospital monitor, smartwatch, phone health app screenshots</p>
  </div>

  <div class="btn-group" style="margin-top:20px">
    <button class="btn-primary" onclick="analyze()">▶ Analyze Vitals</button>
    <button class="btn-demo" onclick="loadDemo('normal')">Demo: Normal</button>
    <button class="btn-demo" onclick="loadDemo('warning')">Demo: Warning</button>
    <button class="btn-demo" onclick="loadDemo('critical')">Demo: Critical</button>
    <div class="spinner" id="spinner"></div>
  </div>
</div>

<div class="card" id="results">
  <h2>Analysis Results</h2>
  <div id="results-body"></div>
</div>

</main>
<script>
let activeTab = 'manual';

function switchTab(tab) {
  activeTab = tab;
  document.querySelectorAll('.tab').forEach((t,i) => t.classList.toggle('active', ['manual','text','file','screen'][i] === tab));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.getElementById('tab-' + tab).classList.add('active');
}

const DEMOS = {
  normal:   {patient_id:'DEMO-001', heart_rate:72, systolic_bp:118, diastolic_bp:76, spo2:98, temperature:36.6, respiratory_rate:16, glucose:95},
  warning:  {patient_id:'DEMO-001', heart_rate:95, systolic_bp:152, diastolic_bp:96, spo2:94, temperature:37.8, respiratory_rate:22, glucose:155},
  critical: {patient_id:'DEMO-001', heart_rate:38, systolic_bp:85,  diastolic_bp:52, spo2:88, temperature:39.8, respiratory_rate:32, glucose:48},
};

function loadDemo(name) {
  switchTab('manual');
  const d = DEMOS[name];
  ['patient_id','heart_rate','systolic_bp','diastolic_bp','spo2','temperature','respiratory_rate','glucose'].forEach(k => {
    const el = document.getElementById(k);
    if (el) el.value = d[k] || '';
  });
}

function updateFileLabel() {
  const f = document.getElementById('file_upload').files[0];
  if (f) document.getElementById('file-label').textContent = '📎 ' + f.name;
}
function updateScreenLabel() {
  const f = document.getElementById('screen_upload').files[0];
  if (f) document.getElementById('screen-label').textContent = '📸 ' + f.name;
}

async function analyze() {
  document.getElementById('spinner').style.display = 'inline-block';
  document.getElementById('results').style.display = 'none';

  try {
    let resp;
    if (activeTab === 'manual') {
      const data = {};
      ['patient_id','heart_rate','systolic_bp','diastolic_bp','spo2','temperature','respiratory_rate','glucose'].forEach(k => {
        const v = document.getElementById(k).value;
        if (v !== '') data[k] = k === 'patient_id' ? v : parseFloat(v);
      });
      resp = await fetch('/analyze/manual', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(data)});
    } else if (activeTab === 'text') {
      const text = document.getElementById('text_feed').value;
      resp = await fetch('/analyze/text', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({text})});
    } else if (activeTab === 'file') {
      const file = document.getElementById('file_upload').files[0];
      if (!file) { alert('Please select a file first.'); return; }
      const fd = new FormData(); fd.append('file', file);
      resp = await fetch('/analyze/file', {method:'POST', body: fd});
    } else if (activeTab === 'screen') {
      const file = document.getElementById('screen_upload').files[0];
      if (!file) { alert('Please select a screenshot first.'); return; }
      const fd = new FormData(); fd.append('file', file);
      resp = await fetch('/analyze/screenshot', {method:'POST', body: fd});
    }

    const result = await resp.json();
    renderResults(result);
  } catch(e) {
    document.getElementById('results-body').innerHTML = '<p style="color:#ef4444">Error: ' + e.message + '</p>';
    document.getElementById('results').style.display = 'block';
  } finally {
    document.getElementById('spinner').style.display = 'none';
  }
}

function renderResults(r) {
  const alerts = r.all_alerts || [];
  const critCount = alerts.filter(a => a.severity === 'CRITICAL').length;
  const warnCount = alerts.filter(a => a.severity === 'WARNING').length;

  let boxClass = 'summary-box';
  if (critCount > 0) boxClass += ' has-critical';
  else if (warnCount > 0) boxClass += ' has-warning';

  let html = '<div class="' + boxClass + '">';
  html += '<div class="summary-title">Reading</div>';
  if (r.reading) {
    const rd = r.reading;
    const vitals = [
      rd.heart_rate && 'HR: ' + rd.heart_rate + ' bpm',
      (rd.systolic_bp && rd.diastolic_bp) && 'BP: ' + rd.systolic_bp + '/' + rd.diastolic_bp + ' mmHg',
      rd.spo2 && 'SpO2: ' + rd.spo2 + '%',
      rd.temperature && 'Temp: ' + rd.temperature + '°C',
      rd.respiratory_rate && 'RR: ' + rd.respiratory_rate + '/min',
      rd.glucose && 'Glucose: ' + rd.glucose + ' mg/dL',
    ].filter(Boolean);
    html += '<div class="summary-vitals">' + vitals.join('&nbsp;&nbsp;|&nbsp;&nbsp;') + '</div>';
  }
  if (r.llm_summary) html += '<div class="summary-text">' + r.llm_summary + '</div>';
  html += '</div>';

  html += '<div class="stat-row">';
  html += stat(alerts.length, 'Total Alerts');
  html += stat(critCount, 'Critical', '#ef4444');
  html += stat(warnCount, 'Warnings', '#f59e0b');
  html += stat((r.dispatched_alerts||[]).length, 'Dispatched', '#22c55e');
  html += '</div>';

  if (alerts.length === 0) {
    html += '<div class="no-alerts">✅ All vitals within normal range</div>';
  } else {
    html += '<table class="alert-table" style="margin-top:16px"><thead><tr><th>Severity</th><th>Vital</th><th>Value</th><th>Source</th><th>Finding</th><th>Action</th></tr></thead><tbody>';
    alerts.forEach(a => {
      html += '<tr>';
      html += '<td><span class="sev sev-' + a.severity + '">' + a.severity + '</span></td>';
      html += '<td>' + a.vital_name + '</td>';
      html += '<td>' + a.vital_value + '</td>';
      html += '<td style="color:#64748b">' + a.triggered_by + '</td>';
      html += '<td>' + a.message + '</td>';
      html += '<td>' + a.recommendation + '</td>';
      html += '</tr>';
    });
    html += '</tbody></table>';
  }

  document.getElementById('results-body').innerHTML = html;
  document.getElementById('results').style.display = 'block';
  document.getElementById('results').scrollIntoView({behavior:'smooth'});
}

function stat(val, label, color) {
  const c = color || '#f8fafc';
  return '<div class="stat"><div class="stat-val" style="color:' + c + '">' + val + '</div><div class="stat-label">' + label + '</div></div>';
}
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML


@app.post("/analyze/manual")
async def analyze_manual(request: Request):
    data = await request.json()
    return _run(data, "manual")


@app.post("/analyze/text")
async def analyze_text(request: Request):
    body = await request.json()
    from extractors.manual_feed import parse_manual_input
    data = parse_manual_input(body.get("text", ""))
    return _run(data, "manual")


@app.post("/analyze/file")
async def analyze_file(request: Request):
    import tempfile, os
    from fastapi import UploadFile
    form = await request.form()
    file: UploadFile = form["file"]
    suffix = "." + file.filename.rsplit(".", 1)[-1].lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        if suffix == ".pdf":
            from extractors.pdf_extractor import extract_from_pdf
            data = extract_from_pdf(tmp_path)
        elif suffix == ".docx":
            from extractors.docx_extractor import extract_from_docx
            data = extract_from_docx(tmp_path)
        else:
            return JSONResponse({"error": "Unsupported file type"}, status_code=400)
        return _run(data, "file")
    finally:
        os.unlink(tmp_path)


@app.post("/analyze/screenshot")
async def analyze_screenshot(request: Request):
    import tempfile, os
    from fastapi import UploadFile
    form = await request.form()
    file: UploadFile = form["file"]
    suffix = "." + file.filename.rsplit(".", 1)[-1].lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        from extractors.screenshot import extract_from_screenshot
        data = extract_from_screenshot(tmp_path)
        return _run(data, "screenshot")
    finally:
        os.unlink(tmp_path)


def _run(data: dict, source: str) -> JSONResponse:
    from agents.orchestrator import build_health_agent, HealthAgentState
    agent = build_health_agent()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    state = HealthAgentState(raw_input=data, input_source=source)
    result = agent.invoke(state, config)
    # Serialize pydantic objects
    out = {}
    for k, v in result.items():
        if hasattr(v, "model_dump"):
            out[k] = v.model_dump(mode="json")
        elif isinstance(v, list):
            out[k] = [i.model_dump(mode="json") if hasattr(i, "model_dump") else i for i in v]
        else:
            out[k] = v
    return JSONResponse(out)


@app.get("/api/status")
async def status():
    from agents.llm_analyzer import _load_env_key
    key, provider = _load_env_key()
    return {"ok": bool(key), "provider": provider, "key_set": bool(key)}


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8787))
    from agents.llm_analyzer import _load_env_key
    _, prov = _load_env_key()
    print(f"\n🏥 Health Vitals Monitoring Agent → http://localhost:{port}")
    print(f"   LLM: {'DeepSeek deepseek-chat' if prov == 'deepseek' else 'Anthropic' if prov == 'anthropic' else 'NOT SET'}")
    print("   Press Ctrl+C to stop\n")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

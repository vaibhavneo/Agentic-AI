from __future__ import annotations
"""
LLM-powered vitals analyzer using Claude.
Catches what thresholds miss: trends, multi-vital patterns, clinical context.
"""
import os
import json
import re
import uuid
import logging
from datetime import datetime
from pathlib import Path

from models.vitals import VitalsReading
from models.alerts import Alert, AlertSeverity

logger = logging.getLogger(__name__)


def _load_env_key() -> tuple[str, str]:
    """Resolve an API key. Prefer DeepSeek, fall back to Anthropic.
    Searches this project's .env, then the shared stock_agent/.env."""
    for env_path in [
        Path(__file__).parent.parent / ".env",
        Path(__file__).parent.parent.parent / "stock_agent" / ".env",
    ]:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    dk = os.getenv("DEEPSEEK_API_KEY", "")
    if dk and dk != "paste_your_key_here":
        return dk, "deepseek"
    ak = os.getenv("ANTHROPIC_API_KEY", "")
    if ak and ak != "paste_your_key_here":
        return ak, "anthropic"
    return "", "none"


_client = None
_provider = "none"


def _get_client():
    """Lazily build the LLM client so importing this module never crashes."""
    global _client, _provider
    if _client is None:
        key, provider = _load_env_key()
        _provider = provider
        if provider == "deepseek":
            from openai import OpenAI
            _client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
        elif provider == "anthropic":
            import anthropic
            _client = anthropic.Anthropic(api_key=key)
        else:
            raise RuntimeError(
                "No API key. Add DEEPSEEK_API_KEY to health-agent/.env "
                "(or stock_agent/.env)."
            )
    return _client

SYSTEM_PROMPT = """You are an expert clinical analyst AI. Analyze patient vital signs for health risks.

You look for:
- Dangerous trends (e.g. BP rising over multiple readings)
- Concerning combinations (e.g. elevated HR + falling SpO2 together)
- Early warning signs not yet crossing hard thresholds
- Patterns suggesting deterioration

You are NOT a replacement for a physician. Always recommend clinical follow-up for concerns."""

ANALYSIS_PROMPT = """Analyze these patient vitals and identify any health risks or concerns.

Current Reading: {current}

Recent History ({n_history} readings):
{history}

Respond with ONLY valid JSON (no markdown, no extra text):
{{"summary": "<2-3 sentence clinical assessment>", "alerts": [{{"vital_name": "<name>", "vital_value": <number>, "severity": "INFO|WARNING|CRITICAL", "message": "<observation>", "recommendation": "<action>"}}]}}

Only include alerts for real concerns. Empty alerts array is fine if vitals look stable."""


def analyze_vitals_with_llm(
    reading: VitalsReading,
    history: list[VitalsReading],
) -> tuple[list[Alert], str]:
    """
    Run LLM analysis on current reading + history.
    Returns (alerts, summary_string).
    """
    history_text = _format_history(history, reading)
    prompt = ANALYSIS_PROMPT.format(
        current=reading.summary(),
        history=history_text,
        n_history=len(history),
    )

    try:
        client = _get_client()
        if _provider == "deepseek":
            response = client.chat.completions.create(
                model="deepseek-chat",
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            text = (response.choices[0].message.content or "").strip()
        else:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()

        # Strip any accidental markdown fences
        if text.startswith("```"):
            text = re.sub(r"^```[a-z]*\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        data = json.loads(text)
        alerts = []
        for raw_alert in data.get("alerts", []):
            try:
                alerts.append(Alert(
                    alert_id=str(uuid.uuid4()),
                    patient_id=reading.patient_id,
                    timestamp=datetime.utcnow(),
                    severity=AlertSeverity(raw_alert["severity"]),
                    vital_name=raw_alert["vital_name"],
                    vital_value=float(raw_alert["vital_value"]),
                    message=raw_alert["message"],
                    recommendation=raw_alert["recommendation"],
                    triggered_by="llm_analysis",
                ))
            except Exception as e:
                logger.warning("Skipping malformed LLM alert: %s", e)

        return alerts, data.get("summary", "Analysis complete.")

    except Exception as e:
        logger.error("[LLM ANALYSIS] Failed: %s", e)
        return [], "LLM analysis unavailable: " + str(e)


def _format_history(history: list[VitalsReading], current: VitalsReading) -> str:
    past = [r for r in history if r.timestamp != current.timestamp]
    if not past:
        return "No prior readings available."
    return "\n".join("  - " + r.summary() for r in past[:8])

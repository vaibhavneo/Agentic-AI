from __future__ import annotations
"""
LangGraph-powered health monitoring orchestrator.

Pipeline: ingest -> threshold_check -> llm_analysis -> alert_dispatch -> done
"""
import logging
import uuid
from datetime import datetime
from typing import List, Optional

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel

from models.vitals import VitalsReading
from models.alerts import Alert, AlertSeverity
from config.thresholds import DEFAULT_THRESHOLDS
from agents.threshold_checker import check_thresholds
from agents.llm_analyzer import analyze_vitals_with_llm
from tools.alert_tools import dispatch_alerts
from tools.memory_tools import store_reading, get_patient_history

logger = logging.getLogger(__name__)


class HealthAgentState(BaseModel):
    """Shared state flowing through all agent nodes."""
    raw_input: dict = {}
    input_source: str = "manual"

    reading: Optional[VitalsReading] = None
    patient_history: List[VitalsReading] = []

    threshold_alerts: List[Alert] = []
    llm_alerts: List[Alert] = []
    llm_summary: str = ""

    all_alerts: List[Alert] = []
    dispatched_alerts: List[Alert] = []
    status: str = "pending"
    error: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True


def ingest_node(state: HealthAgentState) -> dict:
    """Convert raw_input dict -> structured VitalsReading, load history."""
    logger.info("[INGEST] source=%s", state.input_source)
    try:
        raw = state.raw_input
        patient_id = str(raw.get("patient_id", "UNKNOWN"))

        ts_raw = raw.get("timestamp")
        if isinstance(ts_raw, str):
            try:
                ts = datetime.fromisoformat(ts_raw)
            except ValueError:
                ts = datetime.utcnow()
        elif isinstance(ts_raw, datetime):
            ts = ts_raw
        else:
            ts = datetime.utcnow()

        reading = VitalsReading(
            patient_id=patient_id,
            timestamp=ts,
            heart_rate=_safe_float(raw.get("heart_rate")),
            systolic_bp=_safe_float(raw.get("systolic_bp")),
            diastolic_bp=_safe_float(raw.get("diastolic_bp")),
            spo2=_safe_float(raw.get("spo2")),
            temperature=_safe_float(raw.get("temperature")),
            respiratory_rate=_safe_float(raw.get("respiratory_rate")),
            glucose=_safe_float(raw.get("glucose")),
            weight=_safe_float(raw.get("weight")),
        )

        store_reading(reading)
        history = get_patient_history(patient_id, last_n=10)
        logger.info("[INGEST] %s", reading.summary())
        return {"reading": reading, "patient_history": history, "status": "analyzing"}

    except Exception as e:
        logger.error("[INGEST] Failed: %s", e)
        return {"status": "error", "error": str(e)}


def threshold_node(state: HealthAgentState) -> dict:
    if state.reading is None:
        return {"threshold_alerts": []}
    alerts = check_thresholds(state.reading, DEFAULT_THRESHOLDS)
    for a in alerts:
        logger.info("[THRESHOLD] %s - %s: %s", a.severity, a.vital_name, a.vital_value)
    return {"threshold_alerts": alerts}


def llm_analysis_node(state: HealthAgentState) -> dict:
    """LLM catches trends, multi-vital patterns, and subtle risks."""
    if state.reading is None:
        return {"llm_alerts": [], "llm_summary": "No reading available."}

    critical = [a for a in state.threshold_alerts if a.severity == AlertSeverity.CRITICAL]
    if len(critical) >= 2:
        logger.info("[LLM] Skipping - multiple critical threshold alerts.")
        return {"llm_alerts": [], "llm_summary": "Multiple critical thresholds triggered. Immediate intervention required."}

    alerts, summary = analyze_vitals_with_llm(state.reading, state.patient_history)
    logger.info("[LLM] %d alerts. Summary: %s", len(alerts), summary[:80])
    return {"llm_alerts": alerts, "llm_summary": summary}


def alert_dispatch_node(state: HealthAgentState) -> dict:
    all_alerts = _deduplicate(state.threshold_alerts + state.llm_alerts)
    priority = {AlertSeverity.CRITICAL: 0, AlertSeverity.WARNING: 1, AlertSeverity.INFO: 2}
    all_alerts.sort(key=lambda a: priority.get(a.severity, 3))
    dispatched = dispatch_alerts(all_alerts)
    logger.info("[DISPATCH] Sent %d/%d alerts.", len(dispatched), len(all_alerts))
    return {"all_alerts": all_alerts, "dispatched_alerts": dispatched, "status": "done"}


def route_after_ingest(state: HealthAgentState) -> str:
    return "threshold" if state.status != "error" else END


def build_health_agent(checkpointer=None):
    """Build and compile the health monitoring LangGraph pipeline."""
    graph = StateGraph(HealthAgentState)
    graph.add_node("ingest", ingest_node)
    graph.add_node("threshold", threshold_node)
    graph.add_node("llm_analysis", llm_analysis_node)
    graph.add_node("alert_dispatch", alert_dispatch_node)

    graph.set_entry_point("ingest")
    graph.add_conditional_edges("ingest", route_after_ingest, {"threshold": "threshold", END: END})
    graph.add_edge("threshold", "llm_analysis")
    graph.add_edge("llm_analysis", "alert_dispatch")
    graph.add_edge("alert_dispatch", END)

    return graph.compile(checkpointer=checkpointer or MemorySaver())


def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _deduplicate(alerts: List[Alert]) -> List[Alert]:
    seen: dict = {}
    priority = {AlertSeverity.CRITICAL: 0, AlertSeverity.WARNING: 1, AlertSeverity.INFO: 2}
    for alert in alerts:
        key = alert.vital_name
        if key not in seen or priority[alert.severity] < priority[seen[key].severity]:
            seen[key] = alert
    return list(seen.values())

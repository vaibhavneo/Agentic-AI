from __future__ import annotations
"""
Rule-based threshold checker — fast, deterministic, no LLM cost.
Catches clear out-of-range vitals immediately.
"""
import uuid
from datetime import datetime
from models.vitals import VitalsReading
from models.alerts import Alert, AlertSeverity
from config.thresholds import VitalThresholds, DEFAULT_THRESHOLDS


def check_thresholds(
    reading: VitalsReading,
    thresholds: VitalThresholds = DEFAULT_THRESHOLDS,
) -> list[Alert]:
    alerts: list[Alert] = []

    checks = [
        ("heart_rate", reading.heart_rate),
        ("systolic_bp", reading.systolic_bp),
        ("diastolic_bp", reading.diastolic_bp),
        ("spo2", reading.spo2),
        ("temperature", reading.temperature),
        ("respiratory_rate", reading.respiratory_rate),
        ("glucose", reading.glucose),
    ]

    for field_name, value in checks:
        if value is None:
            continue
        vital_range = getattr(thresholds, field_name)
        severity = vital_range.check(value)
        if severity is not None:
            alerts.append(Alert(
                alert_id=str(uuid.uuid4()),
                patient_id=reading.patient_id,
                timestamp=datetime.utcnow(),
                severity=severity,
                vital_name=vital_range.name,
                vital_value=value,
                message=vital_range.describe_violation(value),
                recommendation=_recommend(field_name, severity),
                triggered_by="threshold",
            ))

    return alerts


def _recommend(field: str, severity: AlertSeverity) -> str:
    recs = {
        "heart_rate": {
            AlertSeverity.CRITICAL: "Immediate cardiac evaluation. Check for arrhythmia or hemodynamic instability.",
            AlertSeverity.WARNING: "Monitor continuously. Consider 12-lead ECG if sustained.",
        },
        "systolic_bp": {
            AlertSeverity.CRITICAL: "Emergency: assess for hypertensive crisis or cardiogenic shock.",
            AlertSeverity.WARNING: "Recheck in 15 min. Review antihypertensives and recent activity.",
        },
        "diastolic_bp": {
            AlertSeverity.CRITICAL: "Emergency BP management required.",
            AlertSeverity.WARNING: "Monitor trend. Consult physician if persistent.",
        },
        "spo2": {
            AlertSeverity.CRITICAL: "Administer supplemental O2 immediately. Assess airway and breathing.",
            AlertSeverity.WARNING: "Encourage deep breathing. Recheck in 5 min. Consider supplemental O2.",
        },
        "temperature": {
            AlertSeverity.CRITICAL: "Active cooling/warming required. Assess for infection or environmental exposure.",
            AlertSeverity.WARNING: "Monitor trend. Assess for infection source. Antipyretics if indicated.",
        },
        "respiratory_rate": {
            AlertSeverity.CRITICAL: "Assess airway. Prepare for potential respiratory support.",
            AlertSeverity.WARNING: "Monitor effort and SpO2. Investigate underlying cause.",
        },
        "glucose": {
            AlertSeverity.CRITICAL: "Immediate glucose management. Assess for hypoglycemia/DKA/HHS.",
            AlertSeverity.WARNING: "Recheck in 30 min. Adjust insulin or nutritional intake.",
        },
    }
    return recs.get(field, {}).get(severity, "Consult healthcare provider.")

from __future__ import annotations
from pydantic import BaseModel
from enum import Enum
from datetime import datetime
from typing import Optional


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertChannel(str, Enum):
    CONSOLE = "console"
    WEBHOOK = "webhook"
    EMAIL = "email"


class Alert(BaseModel):
    alert_id: str
    patient_id: str
    timestamp: datetime
    severity: AlertSeverity
    vital_name: str
    vital_value: float
    message: str
    recommendation: str
    triggered_by: str       # "threshold" | "llm_analysis"
    acknowledged: bool = False

    def display(self) -> str:
        icon = {"INFO": "[INFO]", "WARNING": "[WARN]", "CRITICAL": "[CRIT]"}
        prefix = icon.get(self.severity, "[    ]")
        lines = [
            prefix + " " + self.patient_id + " - " + self.vital_name + ": " + str(self.vital_value),
            "   " + self.message,
            "   -> " + self.recommendation,
        ]
        return "\n".join(lines)

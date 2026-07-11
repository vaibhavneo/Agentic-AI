from __future__ import annotations
from pydantic import BaseModel
from typing import Optional
from models.alerts import AlertSeverity


class VitalRange(BaseModel):
    name: str = ""
    unit: str = ""
    min: Optional[float] = None
    max: Optional[float] = None
    critical_min: Optional[float] = None
    critical_max: Optional[float] = None

    def check(self, value: float) -> Optional[AlertSeverity]:
        if self.critical_min is not None and value < self.critical_min:
            return AlertSeverity.CRITICAL
        if self.critical_max is not None and value > self.critical_max:
            return AlertSeverity.CRITICAL
        if self.min is not None and value < self.min:
            return AlertSeverity.WARNING
        if self.max is not None and value > self.max:
            return AlertSeverity.WARNING
        return None

    def describe_violation(self, value: float) -> str:
        if self.critical_min is not None and value < self.critical_min:
            return self.name + " critically low: " + str(value) + self.unit + " (threshold: <" + str(self.critical_min) + self.unit + ")"
        if self.critical_max is not None and value > self.critical_max:
            return self.name + " critically high: " + str(value) + self.unit + " (threshold: >" + str(self.critical_max) + self.unit + ")"
        if self.min is not None and value < self.min:
            return self.name + " low: " + str(value) + self.unit + " (normal min: " + str(self.min) + self.unit + ")"
        if self.max is not None and value > self.max:
            return self.name + " high: " + str(value) + self.unit + " (normal max: " + str(self.max) + self.unit + ")"
        return self.name + " normal: " + str(value) + self.unit


class VitalThresholds(BaseModel):
    heart_rate: VitalRange = VitalRange(name="Heart Rate", unit=" bpm", critical_min=40, min=60, max=100, critical_max=150)
    systolic_bp: VitalRange = VitalRange(name="Systolic BP", unit=" mmHg", critical_min=80, min=90, max=140, critical_max=180)
    diastolic_bp: VitalRange = VitalRange(name="Diastolic BP", unit=" mmHg", critical_min=50, min=60, max=90, critical_max=120)
    spo2: VitalRange = VitalRange(name="SpO2", unit="%", critical_min=90, min=95, max=100)
    temperature: VitalRange = VitalRange(name="Temperature", unit="C", critical_min=35.0, min=36.1, max=37.2, critical_max=39.5)
    respiratory_rate: VitalRange = VitalRange(name="Respiratory Rate", unit="/min", critical_min=8, min=12, max=20, critical_max=30)
    glucose: VitalRange = VitalRange(name="Blood Glucose", unit=" mg/dL", critical_min=54, min=70, max=140, critical_max=400)


DEFAULT_THRESHOLDS = VitalThresholds()

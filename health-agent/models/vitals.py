from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class VitalsReading(BaseModel):
    patient_id: str
    timestamp: datetime
    heart_rate: Optional[float] = None
    systolic_bp: Optional[float] = None
    diastolic_bp: Optional[float] = None
    spo2: Optional[float] = None
    temperature: Optional[float] = None
    respiratory_rate: Optional[float] = None
    glucose: Optional[float] = None
    weight: Optional[float] = None

    def summary(self) -> str:
        parts = ["Patient: " + self.patient_id + " @ " + self.timestamp.strftime("%Y-%m-%d %H:%M:%S")]
        if self.heart_rate is not None:
            parts.append("HR=" + str(self.heart_rate) + "bpm")
        if self.systolic_bp is not None and self.diastolic_bp is not None:
            parts.append("BP=" + str(self.systolic_bp) + "/" + str(self.diastolic_bp) + "mmHg")
        if self.spo2 is not None:
            parts.append("SpO2=" + str(self.spo2) + "%")
        if self.temperature is not None:
            parts.append("Temp=" + str(self.temperature) + "C")
        if self.respiratory_rate is not None:
            parts.append("RR=" + str(self.respiratory_rate) + "/min")
        if self.glucose is not None:
            parts.append("Glucose=" + str(self.glucose) + "mg/dL")
        return " | ".join(parts)


class PatientRecord(BaseModel):
    patient_id: str
    name: str
    age: int
    conditions: List[str] = Field(default_factory=list)
    medications: List[str] = Field(default_factory=list)
    history: List[VitalsReading] = Field(default_factory=list)

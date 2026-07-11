from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime
from models.vitals import VitalsReading, PatientRecord


def load_patient_data(path: str) -> PatientRecord:
    data = json.loads(Path(path).read_text())
    # Parse history readings
    history = [
        VitalsReading(**{**r, "timestamp": datetime.fromisoformat(r["timestamp"])})
        for r in data.get("history", [])
    ]
    return PatientRecord(**{**data, "history": history})


def load_vitals_batch(path: str) -> list[VitalsReading]:
    """Load a batch of vitals readings (e.g. a day's worth of sensor data)."""
    data = json.loads(Path(path).read_text())
    return [
        VitalsReading(**{**r, "timestamp": datetime.fromisoformat(r["timestamp"])})
        for r in data
    ]

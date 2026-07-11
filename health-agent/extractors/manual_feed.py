from __future__ import annotations
"""
Manual data feed — accepts dict, JSON string, or keyword=value text.
Examples:
  {"heart_rate": 88, "spo2": 94, "patient_id": "P001"}
  "HR=88 BP=145/92 SpO2=94 Temp=37.8 patient=P001"
"""
import json
import re


FIELD_ALIASES = {
    # heart rate
    "hr": "heart_rate", "heart_rate": "heart_rate", "pulse": "heart_rate",
    # blood pressure
    "sbp": "systolic_bp", "systolic": "systolic_bp", "systolic_bp": "systolic_bp",
    "dbp": "diastolic_bp", "diastolic": "diastolic_bp", "diastolic_bp": "diastolic_bp",
    # spo2
    "spo2": "spo2", "o2sat": "spo2", "o2": "spo2", "oxygen": "spo2",
    # temperature
    "temp": "temperature", "temperature": "temperature", "t": "temperature",
    # respiratory rate
    "rr": "respiratory_rate", "resp": "respiratory_rate", "respiratory_rate": "respiratory_rate",
    # glucose
    "glucose": "glucose", "bg": "glucose", "bgl": "glucose", "sugar": "glucose",
    # patient
    "patient": "patient_id", "patient_id": "patient_id", "id": "patient_id", "pid": "patient_id",
    # timestamp
    "time": "timestamp", "timestamp": "timestamp", "date": "timestamp",
    # weight
    "weight": "weight", "wt": "weight",
}


def parse_manual_input(data: dict | str) -> dict:
    """
    Parse manual vitals input into a normalized dict.
    Handles:
    - dict: {"HR": 88, "SpO2": 94}
    - JSON string: '{"heart_rate": 88}'
    - key=value text: "HR=88 BP=145/92 SpO2=94"
    - BP expressed as "145/92" gets split into systolic/diastolic
    """
    if isinstance(data, str):
        data = data.strip()
        # Try JSON first
        if data.startswith("{"):
            raw = json.loads(data)
        else:
            raw = _parse_kv_text(data)
    else:
        raw = data

    result = {}
    for key, value in raw.items():
        normalized_key = FIELD_ALIASES.get(key.lower().strip(), key.lower().strip())

        # Handle "BP=145/92" → split into systolic/diastolic
        if normalized_key in ("systolic_bp", "bp", "blood_pressure") and isinstance(value, str) and "/" in value:
            parts = value.split("/")
            result["systolic_bp"] = float(parts[0])
            result["diastolic_bp"] = float(parts[1])
            continue

        # Coerce numeric strings
        if isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                pass

        result[normalized_key] = value

    return result


def _parse_kv_text(text: str) -> dict:
    """Parse 'HR=88 BP=145/92 SpO2=94 patient=P001' format."""
    result = {}
    # Match KEY=VALUE pairs (value can include /)
    for match in re.finditer(r"(\w+)=([^\s]+)", text):
        result[match.group(1)] = match.group(2)
    return result

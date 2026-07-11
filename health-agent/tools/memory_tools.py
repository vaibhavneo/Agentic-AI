from __future__ import annotations
"""
In-process patient history store.
Production upgrade path: swap _store for Redis/DynamoDB/PostgreSQL.
"""
from models.vitals import VitalsReading

_store: dict[str, list[VitalsReading]] = {}


def store_reading(reading: VitalsReading) -> None:
    _store.setdefault(reading.patient_id, []).append(reading)


def get_patient_history(patient_id: str, last_n: int = 10) -> list[VitalsReading]:
    history = _store.get(patient_id, [])
    return sorted(history, key=lambda r: r.timestamp, reverse=True)[:last_n]


def clear_history(patient_id: str | None = None) -> None:
    if patient_id:
        _store.pop(patient_id, None)
    else:
        _store.clear()

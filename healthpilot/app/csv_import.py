"""CSV import for BP, weight, sleep, and exercise (which also carries steps).
Each row is validated through the SAME deterministic service functions used
by the UI (vitals.bp_service.record_bp, etc.) — so a CSV can't sneak in a
value the manual-entry forms would reject. Processed entirely in memory from
the upload stream; nothing is ever written to disk under a client-supplied
name, so there is no filesystem path built from user input at all (the
simplest possible path-traversal defense: don't take a path from the user).
A bad row is skipped and reported, not silently dropped or allowed to abort
the whole import.
"""
from __future__ import annotations

import csv
import io

from exercise.activity_service import ActivityValidationError, log_workout
from vitals.bp_service import BPValidationError, record_bp
from vitals.sleep_service import SleepValidationError, record_sleep
from vitals.weight_service import WeightValidationError, record_weight


class CsvImportError(ValueError):
    pass


def _read_rows(file_stream) -> list[dict]:
    raw = file_stream.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    if reader.fieldnames is None:
        raise CsvImportError("empty or unreadable CSV file")
    return list(reader)


def _blank_to_none(value):
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def import_bp_csv(profile_id: str, file_stream) -> dict:
    rows = _read_rows(file_stream)
    imported, errors = 0, []
    for i, row in enumerate(rows, start=2):  # row 1 is the header
        try:
            symptoms_raw = _blank_to_none(row.get("symptoms"))
            symptoms = [s.strip() for s in symptoms_raw.split("|") if s.strip()] if symptoms_raw else []
            record_bp(
                profile_id,
                systolic_1=int(row["systolic_1"]),
                diastolic_1=int(row["diastolic_1"]),
                pulse_1=int(row["pulse_1"]) if _blank_to_none(row.get("pulse_1")) else None,
                systolic_2=int(row["systolic_2"]) if _blank_to_none(row.get("systolic_2")) else None,
                diastolic_2=int(row["diastolic_2"]) if _blank_to_none(row.get("diastolic_2")) else None,
                pulse_2=int(row["pulse_2"]) if _blank_to_none(row.get("pulse_2")) else None,
                symptoms=symptoms,
                reading_date=_blank_to_none(row.get("date")),
                reading_time=_blank_to_none(row.get("time")),
                notes=_blank_to_none(row.get("notes")),
            )
            imported += 1
        except (BPValidationError, KeyError, ValueError) as e:
            errors.append({"row": i, "error": str(e)})
    return {"imported": imported, "errors": errors, "total_rows": len(rows)}


def import_weight_csv(profile_id: str, file_stream) -> dict:
    rows = _read_rows(file_stream)
    imported, errors = 0, []
    for i, row in enumerate(rows, start=2):
        try:
            record_weight(
                profile_id,
                weight_kg=float(row["weight_kg"]),
                log_date=_blank_to_none(row.get("date")),
                notes=_blank_to_none(row.get("notes")),
            )
            imported += 1
        except (WeightValidationError, KeyError, ValueError) as e:
            errors.append({"row": i, "error": str(e)})
    return {"imported": imported, "errors": errors, "total_rows": len(rows)}


def import_sleep_csv(profile_id: str, file_stream) -> dict:
    rows = _read_rows(file_stream)
    imported, errors = 0, []
    for i, row in enumerate(rows, start=2):
        try:
            record_sleep(
                profile_id,
                hours=float(row["hours"]),
                quality=int(row["quality"]) if _blank_to_none(row.get("quality")) else None,
                log_date=_blank_to_none(row.get("date")),
                notes=_blank_to_none(row.get("notes")),
            )
            imported += 1
        except (SleepValidationError, KeyError, ValueError) as e:
            errors.append({"row": i, "error": str(e)})
    return {"imported": imported, "errors": errors, "total_rows": len(rows)}


def import_exercise_csv(profile_id: str, file_stream) -> dict:
    rows = _read_rows(file_stream)
    imported, errors = 0, []
    for i, row in enumerate(rows, start=2):
        try:
            log_workout(
                profile_id,
                workout_type=row["workout_type"],
                activity=row["activity"],
                workout_date=_blank_to_none(row.get("date")),
                duration_min=float(row["duration_min"]) if _blank_to_none(row.get("duration_min")) else None,
                distance_km=float(row["distance_km"]) if _blank_to_none(row.get("distance_km")) else None,
                steps=int(row["steps"]) if _blank_to_none(row.get("steps")) else None,
                avg_hr=int(row["avg_hr"]) if _blank_to_none(row.get("avg_hr")) else None,
                max_hr=int(row["max_hr"]) if _blank_to_none(row.get("max_hr")) else None,
                rpe=int(row["rpe"]) if _blank_to_none(row.get("rpe")) else None,
                intensity=_blank_to_none(row.get("intensity")),
                wearable_calories=float(row["wearable_calories"]) if _blank_to_none(row.get("wearable_calories")) else None,
                notes=_blank_to_none(row.get("notes")),
            )
            imported += 1
        except (ActivityValidationError, KeyError, ValueError) as e:
            errors.append({"row": i, "error": str(e)})
    return {"imported": imported, "errors": errors, "total_rows": len(rows)}


IMPORTERS = {
    "bp": import_bp_csv,
    "weight": import_weight_csv,
    "sleep": import_sleep_csv,
    "exercise": import_exercise_csv,
}

CSV_TEMPLATES = {
    "bp": "date,time,systolic_1,diastolic_1,pulse_1,systolic_2,diastolic_2,pulse_2,symptoms,notes\n2026-01-15,07:30,122,80,68,124,81,70,,\n",
    "weight": "date,weight_kg,notes\n2026-01-15,72.4,\n",
    "sleep": "date,hours,quality,notes\n2026-01-15,7.5,4,\n",
    "exercise": "date,workout_type,activity,duration_min,distance_km,steps,avg_hr,max_hr,rpe,intensity,wearable_calories,notes\n2026-01-15,cardio,running,30,5.0,6200,142,158,6,vigorous,320,\n",
}

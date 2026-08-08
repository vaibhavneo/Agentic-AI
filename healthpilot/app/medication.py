"""Medication model: CRUD + daily taken/not-taken logs. No dose-change logic
anywhere in this module or anywhere else in the app — that's a clinician
decision, never an app one."""
from __future__ import annotations

import datetime as dt

from database.db import get_connection
from safety.potassium_safety import classify_medication_potassium_risk


class ValidationError(ValueError):
    pass


def _validate(data: dict) -> dict:
    out = dict(data)
    if not out.get("name") or not str(out["name"]).strip():
        raise ValidationError("medication name is required")
    out["name"] = str(out["name"]).strip()
    out["dose"] = (out.get("dose") or "").strip() or None
    out["frequency"] = (out.get("frequency") or "").strip() or None
    out["scheduled_time"] = (out.get("scheduled_time") or "").strip() or None
    out["notes"] = (out.get("notes") or "").strip() or None
    return out


def create_medication(profile_id: str, data: dict) -> dict:
    v = _validate(data)
    manual_flag = data.get("potassium_risk_manual")  # True/False/None
    if manual_flag is not None:
        risk = bool(manual_flag)
        source = "manual"
    else:
        risk = classify_medication_potassium_risk(v["name"])
        source = "auto" if risk else "none"

    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO medications
            (profile_id, name, dose, frequency, scheduled_time, notes,
             potassium_risk, potassium_risk_source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (profile_id, v["name"], v["dose"], v["frequency"], v["scheduled_time"],
         v["notes"], int(risk), source),
    )
    conn.commit()
    return get_medication(cur.lastrowid, profile_id)


def get_medication(medication_id: int, profile_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM medications WHERE id = ? AND profile_id = ?",
        (medication_id, profile_id),
    ).fetchone()
    return dict(row) if row else None


def list_medications(profile_id: str, active_only: bool = True) -> list[dict]:
    conn = get_connection()
    if active_only:
        rows = conn.execute(
            "SELECT * FROM medications WHERE profile_id = ? AND active = 1 ORDER BY name",
            (profile_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM medications WHERE profile_id = ? ORDER BY name",
            (profile_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_medication(medication_id: int, profile_id: str, data: dict) -> dict:
    existing = get_medication(medication_id, profile_id)
    if existing is None:
        raise ValidationError("no such medication for this profile")
    merged = {**existing, **data}
    v = _validate(merged)

    manual_flag = data.get("potassium_risk_manual")
    if manual_flag is not None:
        risk, source = bool(manual_flag), "manual"
    elif existing["potassium_risk_source"] == "manual":
        risk, source = existing["potassium_risk"], "manual"
    else:
        risk = classify_medication_potassium_risk(v["name"])
        source = "auto" if risk else "none"

    conn = get_connection()
    conn.execute(
        """UPDATE medications SET name=?, dose=?, frequency=?, scheduled_time=?,
               notes=?, potassium_risk=?, potassium_risk_source=?, active=?,
               updated_at=datetime('now')
           WHERE id=? AND profile_id=?""",
        (v["name"], v["dose"], v["frequency"], v["scheduled_time"], v["notes"],
         int(risk), source, int(merged.get("active", 1)), medication_id, profile_id),
    )
    conn.commit()
    return get_medication(medication_id, profile_id)


def delete_medication(medication_id: int, profile_id: str) -> None:
    conn = get_connection()
    conn.execute(
        "DELETE FROM medications WHERE id = ? AND profile_id = ?",
        (medication_id, profile_id),
    )
    conn.commit()


def log_dose(medication_id: int, profile_id: str, taken: bool, log_date: str | None = None, notes: str | None = None) -> dict:
    if get_medication(medication_id, profile_id) is None:
        raise ValidationError("no such medication for this profile")
    log_date = log_date or dt.date.today().isoformat()
    taken_at = dt.datetime.now().isoformat() if taken else None
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO medication_logs (medication_id, profile_id, log_date, taken, taken_at, notes)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (medication_id, profile_id, log_date, int(taken), taken_at, notes),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM medication_logs WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def get_today_medication_status(profile_id: str) -> list[dict]:
    """Informational taken/not-taken status per active medication for today
    — never a dosing recommendation, just whether today's log has a 'taken'
    entry. Used by the Today page's Medication section."""
    today = dt.date.today().isoformat()
    conn = get_connection()
    meds = list_medications(profile_id, active_only=True)
    status = []
    for m in meds:
        row = conn.execute(
            "SELECT taken FROM medication_logs WHERE medication_id = ? AND profile_id = ? AND log_date = ? ORDER BY id DESC LIMIT 1",
            (m["id"], profile_id, today),
        ).fetchone()
        status.append({**m, "taken_today": bool(row["taken"]) if row else None})
    return status


def get_medication_context(profile_id: str) -> dict:
    """Read-only summary used by the safety engine and by the future Vitals
    Agent — never a dosing recommendation, just current-state context."""
    meds = list_medications(profile_id, active_only=True)
    potassium_risk = any(m["potassium_risk"] for m in meds)
    return {
        "active_medications": meds,
        "has_potassium_risk_medication": potassium_risk,
    }

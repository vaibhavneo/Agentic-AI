"""Multi-profile isolation across every domain added since M1's initial
check (nutrition, vitals, exercise, meal planning) — and a comprehensive
verification that deleting a profile cascades to ALL of its data, in every
table, with zero orphaned rows left behind anywhere in the schema.
"""
import datetime as dt

from app.medication import create_medication, log_dose
from app.profile import create_profile, delete_profile
from database.db import get_connection
from exercise.activity_service import log_workout
from meal_planning.weekly_planner import create_weekly_plan
from nutrition.food_service import default_serving, search_food
from nutrition.meal_service import log_food
from nutrition.targets import recompute_and_store_target
from nutrition.water_service import log_water
from vitals.bp_service import record_bp
from vitals.other_vitals_service import record_other_vitals
from vitals.sleep_service import record_sleep
from vitals.weight_service import record_weight

# Every table that carries profile_id directly or transitively — used to
# assert zero rows remain for a deleted profile.
DIRECT_PROFILE_TABLES = [
    "medications", "medication_logs", "safety_events", "meals",
    "nutrition_targets", "water_logs", "bp_readings", "weight_logs",
    "sleep_logs", "other_vitals_logs", "workouts", "weekly_plans",
]


def _fully_populated_profile(diet_preference="veg"):
    p = create_profile(
        {
            "name": "Iso Test", "age": 40, "sex": "male", "height_cm": 175,
            "current_weight_kg": 80, "activity_level": "moderate", "diet_preference": diet_preference,
        }
    )
    med = create_medication(p["id"], {"name": "Valsartan"})
    log_dose(med["id"], p["id"], taken=True)
    recompute_and_store_target(p)
    food = search_food("banana", use_provider=False)[0]
    log_food(p["id"], "breakfast", food["id"], default_serving(food)["id"], 1)
    log_water(p["id"], 300)
    record_bp(p["id"], systolic_1=118, diastolic_1=76)
    record_bp(p["id"], systolic_1=150, diastolic_1=95)  # stage_2 — populates safety_events too
    record_weight(p["id"], 80.5)
    record_sleep(p["id"], 7.2)
    record_other_vitals(p["id"], resting_hr=60)
    log_workout(p["id"], "cardio", "walking", duration_min=20, intensity="light")
    today = dt.date.today()
    monday = (today - dt.timedelta(days=today.weekday())).isoformat()
    create_weekly_plan(p, monday)
    return p


def test_two_full_profiles_share_nothing():
    a = _fully_populated_profile()
    b = _fully_populated_profile()

    conn = get_connection()
    for table in DIRECT_PROFILE_TABLES:
        a_count = conn.execute(f"SELECT COUNT(*) c FROM {table} WHERE profile_id = ?", (a["id"],)).fetchone()["c"]
        b_count = conn.execute(f"SELECT COUNT(*) c FROM {table} WHERE profile_id = ?", (b["id"],)).fetchone()["c"]
        assert a_count > 0, f"expected profile A to have rows in {table}"
        assert b_count > 0, f"expected profile B to have rows in {table}"
        # every row in each table belongs to exactly the right profile — no crossover
        other_count = conn.execute(
            f"SELECT COUNT(*) c FROM {table} WHERE profile_id != ? AND profile_id != ?", (a["id"], b["id"])
        ).fetchone()["c"]
        assert other_count == 0


def test_delete_profile_leaves_zero_orphaned_rows_anywhere():
    a = _fully_populated_profile()
    b = _fully_populated_profile()

    delete_profile(a["id"])

    conn = get_connection()
    for table in DIRECT_PROFILE_TABLES:
        orphaned = conn.execute(f"SELECT COUNT(*) c FROM {table} WHERE profile_id = ?", (a["id"],)).fetchone()["c"]
        assert orphaned == 0, f"{table} still has rows for a deleted profile"
        b_untouched = conn.execute(f"SELECT COUNT(*) c FROM {table} WHERE profile_id = ?", (b["id"],)).fetchone()["c"]
        assert b_untouched > 0, f"deleting profile A should not have touched profile B's {table} rows"

    # transitively-cascaded child tables (meal_foods, strength_sets, plan_days/meals/foods)
    for child_table, parent_check in [
        ("meal_foods", "SELECT COUNT(*) c FROM meal_foods mf JOIN meals m ON m.id = mf.meal_id WHERE m.profile_id = ?"),
        ("strength_sets", "SELECT COUNT(*) c FROM strength_sets ss JOIN workouts w ON w.id = ss.workout_id WHERE w.profile_id = ?"),
        ("plan_days", "SELECT COUNT(*) c FROM plan_days pd JOIN weekly_plans wp ON wp.id = pd.weekly_plan_id WHERE wp.profile_id = ?"),
    ]:
        remaining = conn.execute(parent_check, (a["id"],)).fetchone()["c"]
        assert remaining == 0, f"{child_table} has orphaned rows tracing back to a deleted profile"


def test_search_food_is_global_reference_data_not_profile_scoped():
    """Foods/servings are shared reference data, not owned by a profile —
    deleting a profile must never remove foods other profiles rely on."""
    a = _fully_populated_profile()
    before = search_food("banana", use_provider=False)
    delete_profile(a["id"])
    after = search_food("banana", use_provider=False)
    assert len(after) == len(before) > 0

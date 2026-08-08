"""Flask app factory + routes. Renders server-side templates for pages that
exist; the nav only links to pages that are actually built (see NAV_ITEMS) —
no dead UI controls.
"""
from __future__ import annotations

import datetime as dt

from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for

from app import config
from app.medication import (
    ValidationError as MedValidationError,
    create_medication,
    delete_medication,
    get_today_medication_status,
    list_medications,
    log_dose,
    update_medication,
)
from app.profile import (
    ValidationError as ProfileValidationError,
    create_profile,
    delete_profile,
    get_profile,
    list_profiles,
    update_profile,
)
from database.db import close_connection, init_db
from nutrition.daily_service import calculate_daily_nutrition, get_today_nutrition
from nutrition.food_service import FoodValidationError, create_manual_food, search_food
from nutrition.meal_service import (
    MealValidationError,
    delete_meal,
    list_meals,
    log_food,
)
from nutrition.nl_logging import log_food_from_text
from nutrition.targets import get_remaining_nutrition_targets, get_active_target, recompute_and_store_target
from nutrition.water_service import WaterValidationError, get_today_water, log_water
from safety.bp_safety import BPSafetyError
from safety.constants import BP_EMERGENCY_SYMPTOMS
from vitals.bp_service import (
    BPValidationError,
    calculate_bp_average,
    calculate_bp_trend,
    get_bp_history,
    get_latest_bp_reading,
    get_today_bp_average,
    record_bp,
)
from vitals.other_vitals_service import (
    OtherVitalsValidationError,
    get_other_vitals_history,
    record_other_vitals,
)
from vitals.sleep_service import (
    SleepValidationError,
    get_sleep_history,
    record_sleep,
)
from vitals.weight_service import (
    WeightValidationError,
    calculate_weight_trend,
    get_weight_history,
    record_weight,
)
from exercise.activity_service import (
    ActivityValidationError,
    delete_workout,
    get_today_activity,
    get_weekly_activity,
    list_workouts,
    log_workout,
)
from meal_planning.daily_planner import MealPlanValidationError, generate_remaining_daily_plan
from meal_planning.grocery import build_grocery_list
from meal_planning.weekly_planner import (
    PlanNotFoundError,
    add_custom_meal,
    copy_meal,
    create_weekly_plan,
    get_weekly_plan,
    mark_meal_source,
    regenerate_day,
    set_meal_locked,
    swap_meal,
)
from insights.pattern_engine import analyze_health_patterns
from insights.health_score import compute_health_score
from insights.today_insight import get_today_insight
from insights.weekly_summary import get_weekly_summary
from agents.orchestrator import answer_question
from vitals.other_vitals_service import get_other_vitals_history as _get_other_vitals_history
from app.csv_import import CSV_TEMPLATES, CsvImportError, IMPORTERS
from app.data_export import export_profile_data

# Pages that are actually wired up end-to-end. Extended as each milestone
# lands — keeps the nav honest instead of linking to stub pages.
NAV_ITEMS = [
    {"slug": "today", "label": "Today", "href": "/today"},
    {"slug": "meals", "label": "Meals", "href": "/meals"},
    {"slug": "weekly-plan", "label": "Weekly Plan", "href": "/weekly-plan"},
    {"slug": "activity", "label": "Activity", "href": "/activity"},
    {"slug": "vitals", "label": "Vitals", "href": "/vitals"},
    {"slug": "insights", "label": "Insights", "href": "/insights"},
    {"slug": "coach", "label": "AI Health Coach", "href": "/coach"},
    {"slug": "profile", "label": "Profile & Targets", "href": "/profile"},
]


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.SECRET_KEY
    app.config["JSON_SORT_KEYS"] = False

    with app.app_context():
        init_db()

    app.teardown_appcontext(close_connection)

    @app.context_processor
    def inject_nav():
        return {"nav_items": NAV_ITEMS, "active_profile_id": session.get("active_profile_id")}

    @app.errorhandler(ProfileValidationError)
    @app.errorhandler(MedValidationError)
    @app.errorhandler(FoodValidationError)
    @app.errorhandler(MealValidationError)
    @app.errorhandler(WaterValidationError)
    @app.errorhandler(BPValidationError)
    @app.errorhandler(BPSafetyError)
    @app.errorhandler(WeightValidationError)
    @app.errorhandler(SleepValidationError)
    @app.errorhandler(OtherVitalsValidationError)
    @app.errorhandler(ActivityValidationError)
    @app.errorhandler(MealPlanValidationError)
    @app.errorhandler(CsvImportError)
    def handle_validation_error(e):
        return jsonify({"error": str(e)}), 400

    @app.errorhandler(PlanNotFoundError)
    def handle_plan_not_found(e):
        return jsonify({"error": str(e)}), 404

    # --- Pages -------------------------------------------------------------

    @app.get("/")
    def index():
        active_id = session.get("active_profile_id")
        if active_id and get_profile(active_id) is not None:
            return redirect(url_for("today_page"))
        return redirect(url_for("profile_page"))

    @app.get("/today")
    def today_page():
        active_id = session.get("active_profile_id")
        if not active_id or get_profile(active_id) is None:
            return redirect(url_for("profile_page"))

        nutrition = get_today_nutrition(active_id)
        target = get_active_target(active_id)
        remaining = get_remaining_nutrition_targets(active_id, nutrition)
        activity = get_today_activity(active_id)
        latest_bp = get_latest_bp_reading(active_id)
        bp_avg_today = get_today_bp_average(active_id)
        bp_avg_7 = calculate_bp_average(active_id, days=7)
        weight_history = get_weight_history(active_id, days=1)
        latest_weight = weight_history[0] if weight_history else None
        other_vitals = _get_other_vitals_history(active_id, days=1)
        latest_resting_hr = other_vitals[0]["resting_hr"] if other_vitals and other_vitals[0]["resting_hr"] else None
        today_meals = list_meals(active_id, dt.date.today().isoformat())
        insight = get_today_insight(active_id)
        weekly = get_weekly_summary(active_id)
        health_score = compute_health_score(active_id)
        medication_status = get_today_medication_status(active_id)

        return render_template(
            "today.html",
            nutrition=nutrition, target=target, remaining=remaining, activity=activity,
            latest_bp=latest_bp, bp_avg_today=bp_avg_today, bp_avg_7=bp_avg_7, latest_weight=latest_weight,
            latest_resting_hr=latest_resting_hr, today_meals=today_meals, insight=insight,
            medication_status=medication_status,
            weekly=weekly, health_score=health_score,
        )

    @app.get("/profile")
    def profile_page():
        profiles = list_profiles()
        active_id = session.get("active_profile_id")
        active = get_profile(active_id) if active_id else None
        medications = list_medications(active_id, active_only=False) if active_id else []
        return render_template(
            "profile.html", profiles=profiles, active=active, medications=medications
        )

    @app.get("/meals")
    def meals_page():
        active_id = session.get("active_profile_id")
        if not active_id or get_profile(active_id) is None:
            return redirect(url_for("profile_page"))

        today = calculate_daily_nutrition(active_id)
        target = get_active_target(active_id)
        remaining = get_remaining_nutrition_targets(active_id, today)
        water_today = get_today_water(active_id)

        full_meals = list_meals(active_id, dt.date.today().isoformat())
        meals_by_type = {"breakfast": [], "lunch": [], "dinner": [], "snack": []}
        for m in full_meals:
            m["nutrition"] = next((bm for bm in today["meals"] if bm["meal_id"] == m["id"]), None)
            meals_by_type.setdefault(m["meal_type"], []).append(m)
        return render_template(
            "meals.html",
            today=today,
            target=target,
            remaining=remaining,
            water_today=water_today,
            meals_by_type=meals_by_type,
        )

    @app.get("/vitals")
    def vitals_page():
        active_id = session.get("active_profile_id")
        if not active_id or get_profile(active_id) is None:
            return redirect(url_for("profile_page"))

        bp_history = get_bp_history(active_id, days=30)
        bp_avg_7 = calculate_bp_average(active_id, days=7)
        bp_avg_30 = calculate_bp_average(active_id, days=30)
        bp_trend = calculate_bp_trend(active_id, days=30)
        weight_history = get_weight_history(active_id, days=90)
        weight_trend = calculate_weight_trend(active_id, days=30)
        sleep_history = get_sleep_history(active_id, days=14)
        return render_template(
            "vitals.html",
            bp_history=bp_history,
            bp_avg_7=bp_avg_7,
            bp_avg_30=bp_avg_30,
            bp_trend=bp_trend,
            weight_history=weight_history,
            weight_trend=weight_trend,
            sleep_history=sleep_history,
            bp_emergency_symptoms=sorted(BP_EMERGENCY_SYMPTOMS),
        )

    @app.get("/activity")
    def activity_page():
        active_id = session.get("active_profile_id")
        if not active_id or get_profile(active_id) is None:
            return redirect(url_for("profile_page"))

        today_activity = get_today_activity(active_id)
        weekly_activity = get_weekly_activity(active_id)
        recent_workouts = list_workouts(
            active_id, (dt.date.today() - dt.timedelta(days=13)).isoformat()
        )
        return render_template(
            "activity.html",
            today_activity=today_activity,
            weekly_activity=weekly_activity,
            recent_workouts=recent_workouts,
        )

    @app.get("/weekly-plan")
    def weekly_plan_page():
        active_id = session.get("active_profile_id")
        if not active_id or get_profile(active_id) is None:
            return redirect(url_for("profile_page"))

        requested_week = request.args.get("week_start")
        today = dt.date.today()
        default_week = (today - dt.timedelta(days=today.weekday())).isoformat()
        try:
            week_start_date = dt.date.fromisoformat(requested_week) if requested_week else dt.date.fromisoformat(default_week)
        except ValueError:
            return redirect(url_for("weekly_plan_page"))  # malformed ?week_start= — fall back to the current week rather than 500ing
        week_start = week_start_date.isoformat()

        try:
            plan = get_weekly_plan(active_id, week_start)
            grocery_list = build_grocery_list(plan)
        except PlanNotFoundError:
            plan = None
            grocery_list = None

        prev_week = (week_start_date - dt.timedelta(days=7)).isoformat()
        next_week = (week_start_date + dt.timedelta(days=7)).isoformat()

        return render_template(
            "weekly_plan.html",
            plan=plan,
            grocery_list=grocery_list,
            week_start=week_start,
            prev_week=prev_week,
            next_week=next_week,
        )

    @app.get("/insights")
    def insights_page():
        active_id = session.get("active_profile_id")
        if not active_id or get_profile(active_id) is None:
            return redirect(url_for("profile_page"))
        patterns = analyze_health_patterns(active_id)
        return render_template("insights.html", patterns=patterns)

    @app.get("/coach")
    def coach_page():
        active_id = session.get("active_profile_id")
        if not active_id or get_profile(active_id) is None:
            return redirect(url_for("profile_page"))
        return render_template("coach.html", ai_configured=config.ai_configured())

    # --- Profile API ---------------------------------------------------

    @app.get("/api/profiles")
    def api_list_profiles():
        return jsonify(list_profiles())

    @app.post("/api/profiles")
    def api_create_profile():
        profile = create_profile(request.get_json(force=True))
        session["active_profile_id"] = profile["id"]
        return jsonify(profile), 201

    @app.get("/api/profiles/<profile_id>")
    def api_get_profile(profile_id):
        profile = get_profile(profile_id)
        if profile is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(profile)

    @app.put("/api/profiles/<profile_id>")
    def api_update_profile(profile_id):
        if get_profile(profile_id) is None:
            return jsonify({"error": "not found"}), 404
        profile = update_profile(profile_id, request.get_json(force=True))
        return jsonify(profile)

    @app.delete("/api/profiles/<profile_id>")
    def api_delete_profile(profile_id):
        delete_profile(profile_id)
        if session.get("active_profile_id") == profile_id:
            session.pop("active_profile_id", None)
        return jsonify({"ok": True})

    @app.post("/api/profiles/<profile_id>/select")
    def api_select_profile(profile_id):
        if get_profile(profile_id) is None:
            return jsonify({"error": "not found"}), 404
        session["active_profile_id"] = profile_id
        return jsonify({"ok": True})

    # --- Medication API --------------------------------------------------

    def _require_profile(profile_id):
        if get_profile(profile_id) is None:
            return jsonify({"error": "no such profile"}), 404
        return None

    @app.get("/api/profiles/<profile_id>/medications")
    def api_list_medications(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        return jsonify(list_medications(profile_id, active_only=False))

    @app.post("/api/profiles/<profile_id>/medications")
    def api_create_medication(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        med = create_medication(profile_id, request.get_json(force=True))
        return jsonify(med), 201

    @app.put("/api/profiles/<profile_id>/medications/<int:medication_id>")
    def api_update_medication(profile_id, medication_id):
        err = _require_profile(profile_id)
        if err:
            return err
        med = update_medication(medication_id, profile_id, request.get_json(force=True))
        return jsonify(med)

    @app.delete("/api/profiles/<profile_id>/medications/<int:medication_id>")
    def api_delete_medication(profile_id, medication_id):
        err = _require_profile(profile_id)
        if err:
            return err
        delete_medication(medication_id, profile_id)
        return jsonify({"ok": True})

    @app.post("/api/profiles/<profile_id>/medications/<int:medication_id>/log")
    def api_log_dose(profile_id, medication_id):
        err = _require_profile(profile_id)
        if err:
            return err
        body = request.get_json(force=True) or {}
        log = log_dose(medication_id, profile_id, bool(body.get("taken", True)), notes=body.get("notes"))
        return jsonify(log), 201

    # --- Nutrition API -----------------------------------------------------

    @app.get("/api/foods/search")
    def api_search_food():
        q = request.args.get("q", "")
        return jsonify(search_food(q, limit=int(request.args.get("limit", 10))))

    @app.post("/api/foods")
    def api_create_manual_food():
        food = create_manual_food(request.get_json(force=True))
        return jsonify(food), 201

    @app.post("/api/profiles/<profile_id>/meals/log")
    def api_log_food(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        body = request.get_json(force=True)
        meal = log_food(
            profile_id,
            body["meal_type"],
            int(body["food_id"]),
            body.get("serving_id"),
            float(body["quantity"]),
            meal_date=body.get("meal_date"),
        )
        return jsonify(meal), 201

    @app.post("/api/profiles/<profile_id>/meals/log_text")
    def api_log_food_text(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        body = request.get_json(force=True)
        result = log_food_from_text(
            profile_id, body["meal_type"], body["text"], meal_date=body.get("meal_date")
        )
        return jsonify(result), 201

    @app.delete("/api/profiles/<profile_id>/meals/<int:meal_id>")
    def api_delete_meal(profile_id, meal_id):
        err = _require_profile(profile_id)
        if err:
            return err
        delete_meal(meal_id, profile_id)
        return jsonify({"ok": True})

    @app.get("/api/profiles/<profile_id>/nutrition/daily")
    def api_daily_nutrition(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        return jsonify(calculate_daily_nutrition(profile_id, request.args.get("date")))

    @app.get("/api/profiles/<profile_id>/nutrition/today")
    def api_today_nutrition(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        return jsonify(get_today_nutrition(profile_id))

    @app.get("/api/profiles/<profile_id>/nutrition/targets")
    def api_get_target(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        target = get_active_target(profile_id)
        return jsonify(target or {})

    @app.post("/api/profiles/<profile_id>/nutrition/targets/recompute")
    def api_recompute_target(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        target = recompute_and_store_target(get_profile(profile_id))
        return jsonify(target), 201

    @app.get("/api/profiles/<profile_id>/nutrition/remaining")
    def api_remaining_targets(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        totals = calculate_daily_nutrition(profile_id, request.args.get("date"))
        return jsonify(get_remaining_nutrition_targets(profile_id, totals, request.args.get("date")))

    @app.post("/api/profiles/<profile_id>/nutrition/generate-remaining-plan")
    def api_generate_remaining_plan(profile_id):
        profile = get_profile(profile_id)
        if profile is None:
            return jsonify({"error": "no such profile"}), 404
        return jsonify(generate_remaining_daily_plan(profile))

    @app.post("/api/profiles/<profile_id>/water")
    def api_log_water(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        body = request.get_json(force=True)
        return jsonify(log_water(profile_id, int(body["amount_ml"]), body.get("log_date"))), 201

    @app.get("/api/profiles/<profile_id>/water/today")
    def api_water_today(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        return jsonify({"amount_ml": get_today_water(profile_id)})

    # --- Vitals API ----------------------------------------------------

    @app.post("/api/profiles/<profile_id>/vitals/bp")
    def api_record_bp(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        body = request.get_json(force=True)
        reading = record_bp(
            profile_id,
            systolic_1=body["systolic_1"],
            diastolic_1=body["diastolic_1"],
            pulse_1=body.get("pulse_1"),
            systolic_2=body.get("systolic_2"),
            diastolic_2=body.get("diastolic_2"),
            pulse_2=body.get("pulse_2"),
            symptoms=body.get("symptoms"),
            reading_date=body.get("reading_date"),
            reading_time=body.get("reading_time"),
            notes=body.get("notes"),
        )
        return jsonify(reading), 201

    @app.get("/api/profiles/<profile_id>/vitals/bp")
    def api_bp_history(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        return jsonify(get_bp_history(profile_id, int(request.args.get("days", 30))))

    @app.get("/api/profiles/<profile_id>/vitals/bp/average")
    def api_bp_average(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        return jsonify(calculate_bp_average(profile_id, int(request.args.get("days", 7))))

    @app.get("/api/profiles/<profile_id>/vitals/bp/trend")
    def api_bp_trend(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        return jsonify(calculate_bp_trend(profile_id, int(request.args.get("days", 30))))

    @app.post("/api/profiles/<profile_id>/vitals/weight")
    def api_record_weight(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        body = request.get_json(force=True)
        return jsonify(record_weight(profile_id, body["weight_kg"], log_date=body.get("log_date"), notes=body.get("notes"))), 201

    @app.get("/api/profiles/<profile_id>/vitals/weight")
    def api_weight_history(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        return jsonify(get_weight_history(profile_id, int(request.args.get("days", 90))))

    @app.post("/api/profiles/<profile_id>/vitals/sleep")
    def api_record_sleep(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        body = request.get_json(force=True)
        return jsonify(
            record_sleep(
                profile_id, body["hours"], quality=body.get("quality"),
                log_date=body.get("log_date"), notes=body.get("notes"),
            )
        ), 201

    @app.get("/api/profiles/<profile_id>/vitals/sleep")
    def api_sleep_history(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        return jsonify(get_sleep_history(profile_id, int(request.args.get("days", 30))))

    @app.post("/api/profiles/<profile_id>/vitals/other")
    def api_record_other_vitals(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        body = request.get_json(force=True)
        return jsonify(
            record_other_vitals(
                profile_id,
                resting_hr=body.get("resting_hr"), waist_cm=body.get("waist_cm"),
                hrv_ms=body.get("hrv_ms"), spo2_pct=body.get("spo2_pct"),
                log_date=body.get("log_date"), notes=body.get("notes"),
            )
        ), 201

    @app.get("/api/profiles/<profile_id>/vitals/other")
    def api_other_vitals_history(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        return jsonify(get_other_vitals_history(profile_id, int(request.args.get("days", 30))))

    # --- Exercise API ----------------------------------------------------

    @app.post("/api/profiles/<profile_id>/workouts")
    def api_log_workout(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        body = request.get_json(force=True)
        workout = log_workout(
            profile_id,
            workout_type=body["workout_type"],
            activity=body["activity"],
            workout_date=body.get("workout_date"),
            start_time=body.get("start_time"),
            duration_min=body.get("duration_min"),
            distance_km=body.get("distance_km"),
            steps=body.get("steps"),
            avg_hr=body.get("avg_hr"),
            max_hr=body.get("max_hr"),
            rpe=body.get("rpe"),
            intensity=body.get("intensity"),
            wearable_calories=body.get("wearable_calories"),
            notes=body.get("notes"),
            strength_sets=body.get("strength_sets"),
        )
        return jsonify(workout), 201

    @app.delete("/api/profiles/<profile_id>/workouts/<int:workout_id>")
    def api_delete_workout(profile_id, workout_id):
        err = _require_profile(profile_id)
        if err:
            return err
        delete_workout(workout_id, profile_id)
        return jsonify({"ok": True})

    @app.get("/api/profiles/<profile_id>/activity/today")
    def api_today_activity(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        return jsonify(get_today_activity(profile_id))

    @app.get("/api/profiles/<profile_id>/activity/weekly")
    def api_weekly_activity(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        return jsonify(get_weekly_activity(profile_id, request.args.get("week_start")))

    # --- Meal planning API -------------------------------------------------

    @app.post("/api/profiles/<profile_id>/weekly-plan")
    def api_create_weekly_plan(profile_id):
        profile = get_profile(profile_id)
        if profile is None:
            return jsonify({"error": "no such profile"}), 404
        body = request.get_json(silent=True) or {}
        plan = create_weekly_plan(profile, body.get("week_start"))
        return jsonify(plan), 201

    @app.get("/api/profiles/<profile_id>/weekly-plan")
    def api_get_weekly_plan(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        week_start = request.args.get("week_start")
        if not week_start:
            return jsonify({"error": "week_start query param is required"}), 400
        return jsonify(get_weekly_plan(profile_id, week_start))

    @app.post("/api/profiles/<profile_id>/plan-meals/<int:plan_meal_id>/swap")
    def api_swap_meal(profile_id, plan_meal_id):
        profile = get_profile(profile_id)
        if profile is None:
            return jsonify({"error": "no such profile"}), 404
        return jsonify(swap_meal(plan_meal_id, profile_id, profile))

    @app.post("/api/profiles/<profile_id>/plan-meals/<int:plan_meal_id>/lock")
    def api_lock_meal(profile_id, plan_meal_id):
        err = _require_profile(profile_id)
        if err:
            return err
        body = request.get_json(force=True)
        return jsonify(set_meal_locked(plan_meal_id, profile_id, bool(body.get("locked", True))))

    @app.post("/api/profiles/<profile_id>/plan-meals/<int:plan_meal_id>/source")
    def api_mark_meal_source(profile_id, plan_meal_id):
        err = _require_profile(profile_id)
        if err:
            return err
        body = request.get_json(force=True)
        return jsonify(mark_meal_source(plan_meal_id, profile_id, body["source"], body.get("notes")))

    @app.post("/api/profiles/<profile_id>/plan-meals/<int:plan_meal_id>/copy")
    def api_copy_meal(profile_id, plan_meal_id):
        err = _require_profile(profile_id)
        if err:
            return err
        body = request.get_json(force=True)
        return jsonify(
            copy_meal(plan_meal_id, int(body["target_plan_day_id"]), profile_id, body.get("target_meal_type") or "snack")
        ), 201

    @app.post("/api/profiles/<profile_id>/plan-days/<int:plan_day_id>/custom-meal")
    def api_add_custom_meal(profile_id, plan_day_id):
        err = _require_profile(profile_id)
        if err:
            return err
        body = request.get_json(force=True)
        return jsonify(add_custom_meal(plan_day_id, profile_id, body["meal_type"], body["food_items"])), 201

    @app.post("/api/profiles/<profile_id>/plan-days/<int:plan_day_id>/regenerate")
    def api_regenerate_day(profile_id, plan_day_id):
        profile = get_profile(profile_id)
        if profile is None:
            return jsonify({"error": "no such profile"}), 404
        return jsonify(regenerate_day(plan_day_id, profile_id, profile))

    @app.get("/api/profiles/<profile_id>/grocery-list")
    def api_grocery_list(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        week_start = request.args.get("week_start")
        if not week_start:
            return jsonify({"error": "week_start query param is required"}), 400
        plan = get_weekly_plan(profile_id, week_start)
        return jsonify(build_grocery_list(plan))

    # --- Insights / AI Coach API --------------------------------------

    @app.get("/api/profiles/<profile_id>/insights")
    def api_insights(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        return jsonify(analyze_health_patterns(profile_id))

    @app.post("/api/profiles/<profile_id>/coach/ask")
    def api_coach_ask(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        body = request.get_json(force=True)
        message = (body.get("message") or "").strip()
        if not message:
            return jsonify({"error": "message is required"}), 400
        history = body.get("history")  # [{role, content}, ...] from the client's own transcript
        # specialist/model are optional, aios_core-retrofit-only overrides (see
        # agents/orchestrator.py::answer_question) — omitted by the Coach UI's
        # own JS, so the live app's request shape and behavior are unchanged.
        result = answer_question(
            profile_id, message, history,
            specialist_override=body.get("specialist"),
            model_override=body.get("model"),
        )
        return jsonify(result)

    # --- CSV import / export / delete -----------------------------------

    @app.get("/api/csv-templates/<kind>")
    def api_csv_template(kind):
        if kind not in CSV_TEMPLATES:
            return jsonify({"error": f"no template for '{kind}'"}), 404
        return Response(
            CSV_TEMPLATES[kind], mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={kind}_template.csv"},
        )

    @app.post("/api/profiles/<profile_id>/import/<kind>")
    def api_csv_import(profile_id, kind):
        err = _require_profile(profile_id)
        if err:
            return err
        importer = IMPORTERS.get(kind)
        if importer is None:
            return jsonify({"error": f"unknown import kind '{kind}'"}), 404
        if "file" not in request.files:
            return jsonify({"error": "no file uploaded"}), 400
        result = importer(profile_id, request.files["file"].stream)
        return jsonify(result), 201

    @app.get("/api/profiles/<profile_id>/export")
    def api_export_profile(profile_id):
        err = _require_profile(profile_id)
        if err:
            return err
        data = export_profile_data(profile_id)
        return Response(
            jsonify(data).get_data(),
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename=healthpilot_export_{profile_id}.json"},
        )

    return app

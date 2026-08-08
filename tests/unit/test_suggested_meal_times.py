from app.profile import create_profile
from meal_planning.daily_planner import generate_daily_plan, suggested_meal_times
from nutrition.targets import recompute_and_store_target


def test_no_wake_or_bed_time_returns_none_for_every_slot():
    times = suggested_meal_times(["breakfast", "lunch", "dinner"], None, None)
    assert times == [None, None, None]


def test_suggested_times_are_ordered_and_within_wake_bed_window():
    times = suggested_meal_times(["breakfast", "lunch", "dinner"], "07:00", "22:00")
    assert all(t is not None for t in times)
    minutes = [int(h) * 60 + int(m) for h, m in (t.split(":") for t in times)]
    assert minutes == sorted(minutes)  # breakfast before lunch before dinner
    assert minutes[0] >= 7 * 60
    assert minutes[-1] <= 22 * 60


def test_suggested_times_handle_bedtime_past_midnight():
    times = suggested_meal_times(["breakfast", "lunch", "dinner"], "06:00", "01:00")
    assert all(t is not None for t in times)


def test_daily_plan_attaches_suggested_time_when_wake_and_bed_set():
    p = create_profile(
        {
            "name": "Wake Test", "age": 30, "sex": "male", "height_cm": 175,
            "current_weight_kg": 75, "activity_level": "moderate", "diet_preference": "veg",
            "meals_per_day": 3, "wake_time": "06:30", "bed_time": "22:30",
        }
    )
    recompute_and_store_target(p)
    plan = generate_daily_plan(p)
    assert all(m["suggested_time"] is not None for m in plan["meals"])


def test_daily_plan_suggested_time_is_none_without_wake_bed_time():
    p = create_profile(
        {
            "name": "No Wake Test", "age": 30, "sex": "male", "height_cm": 175,
            "current_weight_kg": 75, "activity_level": "moderate", "diet_preference": "veg",
            "meals_per_day": 3,
        }
    )
    recompute_and_store_target(p)
    plan = generate_daily_plan(p)
    assert all(m["suggested_time"] is None for m in plan["meals"])

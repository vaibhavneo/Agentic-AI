"""
Tests for vedic_astro_reading — hermetic, no model, no network. Stub
geocode/reading callables injected via context["_geocode_post"] /
context["_reading_sse"] stand in for the real HTTP/SSE calls, per
execution_contract.md's documented test seam.

Run: python3 brain/skills/vedic_astro_reading/tests/test_skill.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ROOT = SKILL_DIR.parents[2]
sys.path.insert(0, str(ROOT))

from aios_core import skill  # noqa: E402

FAILURES: list[str] = []


def check(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}  {detail}")
    if not cond:
        FAILURES.append(name)


GEO_OK = (200, {"lat": 21.6417, "lon": 69.6293, "timezone_offset_hours": 5.5})


def _geocoder(status_body):
    calls = []

    def fn(url, payload):
        calls.append((url, payload))
        return status_body
    fn.calls = calls
    return fn


def _reading(events):
    calls = []

    def fn(url, payload):
        calls.append((url, payload))
        for e in events:
            yield e
    fn.calls = calls
    return fn


BASE_INPUTS = {"place": "Porbandar, India", "date": "1869-10-02", "time": "07:45"}


def test_e1_happy_path():
    print("=== E1: happy path assembles birth_info + sections ===")
    geocoder = _geocoder(GEO_OK)
    reader = _reading([
        ("status", {"msg": "..."}),
        ("section", {"key": "career", "title": "Career", "content": "..."}),
        ("section", {"key": "synthesis", "title": "Synthesis", "content": "final"}),
        ("done", {"msg": "done"}),
    ])
    r = skill.run("vedic_astro_reading", BASE_INPUTS,
                  {"_geocode_post": geocoder, "_reading_sse": reader})
    check("dispatch ok", r.ok, r.failure_detail)
    check("app == vedic_astro", r.output.get("app") == "vedic_astro")
    check("birth_info carries geocoded coordinates",
          r.output["birth_info"]["lat"] == 21.6417 and r.output["birth_info"]["tz_offset"] == 5.5)
    check("sections has both keys",
          set(r.output["sections"]) == {"career", "synthesis"})
    check("section content unchanged", r.output["sections"]["synthesis"]["content"] == "final")


def test_e2_negative_missing_place():
    print("=== E2: missing 'place' -> INPUT_INVALID, never dispatched ===")
    geocoder = _geocoder(GEO_OK)
    r = skill.run("vedic_astro_reading", {"date": "1869-10-02", "time": "07:45"},
                  {"_geocode_post": geocoder})
    check("missing place -> INPUT_INVALID", r.failure == "INPUT_INVALID", str(r.failure))
    check("geocoder never invoked", geocoder.calls == [])


def test_e3_geocode_failure_not_swallowed():
    print("=== E3: a geocode error surfaces, reading is never called ===")
    geocoder = _geocoder((404, {"error": "Could not geocode 'Nowhere'"}))
    reader = _reading([("section", {"key": "x", "title": "x", "content": "x"}), ("done", {})])
    r = skill.run("vedic_astro_reading", {**BASE_INPUTS, "place": "Nowhere"},
                  {"_geocode_post": geocoder, "_reading_sse": reader})
    check("geocode failure -> EXECUTION_ERROR", r.failure == "EXECUTION_ERROR", str(r.failure))
    check("reading step never called", reader.calls == [])


def test_e4_reading_error_event_not_swallowed():
    print("=== E4: an upstream reading 'error' event surfaces ===")
    geocoder = _geocoder(GEO_OK)
    reader = _reading([("error", {"msg": "No API key"})])
    r = skill.run("vedic_astro_reading", BASE_INPUTS,
                  {"_geocode_post": geocoder, "_reading_sse": reader})
    check("reading error -> EXECUTION_ERROR", r.failure == "EXECUTION_ERROR", str(r.failure))


def test_e4b_no_sections_not_swallowed():
    print("=== E4b: a 'done' with zero sections surfaces as a failure ===")
    geocoder = _geocoder(GEO_OK)
    reader = _reading([("status", {"msg": "..."}), ("done", {})])
    r = skill.run("vedic_astro_reading", BASE_INPUTS,
                  {"_geocode_post": geocoder, "_reading_sse": reader})
    check("zero sections -> EXECUTION_ERROR", r.failure == "EXECUTION_ERROR", str(r.failure))


def test_stateless_no_memory_changes():
    print("=== stateless: no memory_changes recorded ===")
    geocoder = _geocoder(GEO_OK)
    reader = _reading([("section", {"key": "x", "title": "x", "content": "x"}), ("done", {})])
    r = skill.run("vedic_astro_reading", BASE_INPUTS,
                  {"_geocode_post": geocoder, "_reading_sse": reader})
    check("dispatch ok", r.ok, r.failure_detail)
    check("memory_changes empty", not getattr(r, "memory_changes", []))


if __name__ == "__main__":
    test_e1_happy_path()
    test_e2_negative_missing_place()
    test_e3_geocode_failure_not_swallowed()
    test_e4_reading_error_event_not_swallowed()
    test_e4b_no_sections_not_swallowed()
    test_stateless_no_memory_changes()
    print("=" * 60)
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("ALL PASS — vedic_astro_reading: HTTP 2-step glue, failures surface, stateless")

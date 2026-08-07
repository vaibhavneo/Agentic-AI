"""
Tests for Phase 10's orchestrator.py — the Critic/Validator self-correction
loop and the agents_consulted transparency list. Uses a scripted fake
chat_fn (no real LLM calls) so the correction logic is fully deterministic.
"""
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chart.calculator import Chart, PlanetPosition
from chart_bundle import build_chart_bundle
import orchestrator

SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio",
         "Sagittarius", "Capricorn", "Aquarius", "Pisces"]

BIRTH_INFO = {"date": "1990-05-15", "time": "10:30", "place": "Delhi, India",
              "lat": 28.6139, "lon": 77.2090, "tz_offset": 5.5}


def _fake_planet(name, sign_index, degrees, house):
    return PlanetPosition(
        name=name, longitude=sign_index * 30 + degrees, sign_index=sign_index,
        sign=SIGNS[sign_index], degrees=degrees, minutes=0.0, nakshatra="Ashwini",
        nakshatra_lord="Ketu", pada=1, retrograde=False, dignity="neutral", house=house,
    )


def _build_test_bundle():
    d1 = Chart(
        label="D-1", ascendant_longitude=0.0, ascendant_sign="Aries", ascendant_sign_index=0,
        ascendant_degrees=0.0, planets={"Sun": _fake_planet("Sun", 4, 15.0, house=5)},
        houses=list(range(1, 13)),
    )
    dashas = [{"lord": "Venus", "years": 20, "start": "1990-05", "end": "2010-05"}]
    return build_chart_bundle(BIRTH_INFO, datetime(1990, 5, 15, 5, 0), d1, {},
                               dashas, {"vargottama": {}, "vimshopaka_bala": {}})


class TestRunCriticAndMaybeCorrect(unittest.TestCase):
    def setUp(self):
        self.bundle = _build_test_bundle()

    def test_no_bundle_returns_draft_unchanged(self):
        result = orchestrator.run_critic_and_maybe_correct(
            lambda s: "should never be called", "system", "The Sun is in Scorpio.", None, "D1")
        self.assertEqual(result["answer"], "The Sun is in Scorpio.")
        self.assertIsNone(result["validation"])
        self.assertFalse(result["corrected"])

    def test_valid_draft_is_not_corrected(self):
        calls = []
        def chat_fn(s):
            calls.append(s)
            return "should not be called"
        result = orchestrator.run_critic_and_maybe_correct(
            chat_fn, "system", "The Sun is in Leo.", self.bundle, "D1")
        self.assertFalse(result["corrected"])
        self.assertTrue(result["validation"]["all_valid"])
        self.assertEqual(calls, [])  # never made a correction call

    def test_wrong_draft_triggers_one_correction_call_that_fixes_it(self):
        def chat_fn(system):
            self.assertIn("CRITIC NOTE", system)
            self.assertIn("Scorpio", system)
            return "The Sun is in Leo, as the chart shows."
        result = orchestrator.run_critic_and_maybe_correct(
            chat_fn, "system", "The Sun is in Scorpio.", self.bundle, "D1")
        self.assertTrue(result["corrected"])
        self.assertEqual(result["answer"], "The Sun is in Leo, as the chart shows.")
        self.assertTrue(result["validation"]["all_valid"])

    def test_correction_that_does_not_improve_keeps_original(self):
        def chat_fn(system):
            return "The Sun is in Scorpio, definitely."  # still wrong
        result = orchestrator.run_critic_and_maybe_correct(
            chat_fn, "system", "The Sun is in Scorpio.", self.bundle, "D1")
        self.assertFalse(result["corrected"])
        self.assertEqual(result["answer"], "The Sun is in Scorpio.")
        self.assertFalse(result["validation"]["all_valid"])

    def test_correction_is_bounded_to_a_single_retry(self):
        call_count = [0]
        def chat_fn(system):
            call_count[0] += 1
            return "Still wrong: Sun in Scorpio."
        orchestrator.run_critic_and_maybe_correct(
            chat_fn, "system", "The Sun is in Scorpio.", self.bundle, "D1")
        self.assertEqual(call_count[0], 1)


class TestAgentsConsulted(unittest.TestCase):
    def setUp(self):
        self.bundle = _build_test_bundle()

    def test_no_bundle_no_transit_no_book_only_parashari(self):
        agents = orchestrator.agents_consulted(None, "D1", "", "")
        self.assertEqual(agents, [orchestrator.PARASHARI_AGENT])

    def test_bundle_present_includes_chart_facts_and_critic(self):
        agents = orchestrator.agents_consulted(self.bundle, "D1", "", "")
        self.assertIn(orchestrator.CHART_FACTS_AGENT, agents)
        self.assertIn(orchestrator.CRITIC_VALIDATOR_AGENT, agents)
        self.assertNotIn(orchestrator.DIVISIONAL_CHART_AGENT, agents)  # D1 is not "divisional"

    def test_non_d1_division_includes_divisional_chart_agent(self):
        agents = orchestrator.agents_consulted(self.bundle, "D9", "", "")
        self.assertIn(orchestrator.DIVISIONAL_CHART_AGENT, agents)

    def test_book_context_includes_classical_sources_agent(self):
        agents = orchestrator.agents_consulted(self.bundle, "D1", "", "some retrieved passage")
        self.assertIn(orchestrator.CLASSICAL_SOURCES_AGENT, agents)

    def test_transit_without_bundle_still_includes_timing_agent(self):
        agents = orchestrator.agents_consulted(None, "D1", "some transit context", "")
        self.assertIn(orchestrator.DASHA_TIMING_AGENT, agents)


if __name__ == "__main__":
    unittest.main()

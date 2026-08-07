"""
Tests for Phase 6 (chart_validation), Phase 7 (context_pack), and Phase 8
(conversations). Follows the same hand-built Chart/PlanetPosition pattern as
tests/test_chart_bundle.py — fast, deterministic, no live ephemeris calls.
"""
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chart.calculator import Chart, PlanetPosition
from chart_bundle import build_chart_bundle
import chart_validation as validation
import context_pack
import conversations

SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio",
         "Sagittarius", "Capricorn", "Aquarius", "Pisces"]

BIRTH_INFO = {"date": "1990-05-15", "time": "10:30", "place": "Delhi, India",
              "lat": 28.6139, "lon": 77.2090, "tz_offset": 5.5}


def _fake_planet(name, sign_index, degrees, house, dignity="neutral", longitude=None, retrograde=False):
    return PlanetPosition(
        name=name, longitude=longitude if longitude is not None else sign_index * 30 + degrees,
        sign_index=sign_index, sign=SIGNS[sign_index], degrees=degrees, minutes=0.0,
        nakshatra="Ashwini", nakshatra_lord="Ketu", pada=1,
        retrograde=retrograde, dignity=dignity, house=house,
    )


def _fake_chart(label, asc_sign_index=0, planets=None):
    return Chart(
        label=label, ascendant_longitude=asc_sign_index * 30.0,
        ascendant_sign=SIGNS[asc_sign_index], ascendant_sign_index=asc_sign_index,
        ascendant_degrees=0.0, planets=planets or {}, houses=list(range(1, 13)),
    )


def _build_test_bundle():
    # Aries ascendant (index 0) -> D-1 house_lords = [Mars, Venus, Mercury, Moon,
    # Sun, Mercury, Venus, Mars, Jupiter, Saturn, Saturn, Jupiter] (SIGN_LORDS as-is).
    d1 = _fake_chart("D-1", asc_sign_index=0, planets={
        "Sun": _fake_planet("Sun", 4, 15.0, house=5),        # Leo, house 5
        "Mars": _fake_planet("Mars", 6, 10.0, house=7),      # Libra, house 7
        "Saturn": _fake_planet("Saturn", 9, 2.0, house=10, retrograde=True),  # Capricorn
    })
    divs = {"D9": _fake_chart("D-9", asc_sign_index=1, planets={
        "Sun": _fake_planet("Sun", 0, 3.0, house=1),
    })}
    dashas = [{"lord": "Venus", "years": 20, "start": "1990-05", "end": "2010-05"}]
    strength = {"vargottama": {}, "vimshopaka_bala": {}}
    return build_chart_bundle(BIRTH_INFO, datetime(1990, 5, 15, 5, 0), d1, divs, dashas, strength)


class TestChartValidation(unittest.TestCase):
    def setUp(self):
        self.bundle = _build_test_bundle()

    def test_extract_planet_sign_claim_basic(self):
        claims = validation.extract_planet_sign_claims("Sun is in Leo this lifetime.")
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["planet"], "Sun")
        self.assertEqual(claims[0]["claimed_sign"], "Leo")

    def test_extract_planet_sign_claim_variants(self):
        text = "Mars is placed in Libra, while Saturn sits retrograde in Capricorn."
        claims = validation.extract_planet_sign_claims(text)
        planets = {c["planet"]: c["claimed_sign"] for c in claims}
        self.assertEqual(planets.get("Mars"), "Libra")
        self.assertEqual(planets.get("Saturn"), "Capricorn")

    def test_validate_text_correct_claim(self):
        result = validation.validate_text("The Sun is in Leo.", self.bundle, "D1")
        self.assertTrue(result["all_valid"])
        self.assertEqual(len(result["confirmed"]), 1)
        self.assertEqual(len(result["issues"]), 0)

    def test_validate_text_catches_wrong_claim(self):
        result = validation.validate_text("The Sun is in Scorpio.", self.bundle, "D1")
        self.assertFalse(result["all_valid"])
        self.assertEqual(len(result["issues"]), 1)
        issue = result["issues"][0]
        self.assertEqual(issue["planet"], "Sun")
        self.assertEqual(issue["claimed_sign"], "Scorpio")
        self.assertEqual(issue["actual_sign"], "Leo")

    def test_validate_text_catches_wrong_claim_with_adverb(self):
        # Regression: "is beautifully placed in" was missed before the \w+ly
        # allowance was added to PLANET_SIGN_RE — found via live LLM testing.
        result = validation.validate_text(
            "Your Sun is beautifully placed in Aries.", self.bundle, "D1")
        self.assertFalse(result["all_valid"])
        self.assertEqual(result["issues"][0]["claimed_sign"], "Aries")

    def test_validate_text_mixed_claims(self):
        text = "The Sun is in Leo, but Mars is in Pisces."
        result = validation.validate_text(text, self.bundle, "D1")
        self.assertFalse(result["all_valid"])
        self.assertEqual(len(result["confirmed"]), 1)
        self.assertEqual(len(result["issues"]), 1)

    def test_house_lord_claim_correct(self):
        # D-1 Aries ascendant -> house 1 lord is Mars.
        result = validation.validate_text("Mars is the 1st lord of this chart.", self.bundle, "D1")
        self.assertTrue(result["all_valid"])
        self.assertEqual(result["confirmed"][0]["type"], "house_lord")

    def test_house_lord_claim_wrong(self):
        result = validation.validate_text("Venus is the 1st lord of this chart.", self.bundle, "D1")
        self.assertFalse(result["all_valid"])
        issue = result["issues"][0]
        self.assertEqual(issue["actual_lord"], "Mars")

    def test_house_lord_claim_alt_phrasing(self):
        result = validation.validate_text("The 10th lord is Saturn.", self.bundle, "D1")
        self.assertTrue(result["all_valid"])

    def test_no_claims_found_is_trivially_valid(self):
        result = validation.validate_text("You are a warm and insightful person.", self.bundle, "D1")
        self.assertTrue(result["all_valid"])
        self.assertEqual(result["claims_checked"], 0)


class TestContextPack(unittest.TestCase):
    def setUp(self):
        self.bundle = _build_test_bundle()

    def test_detect_topics_career(self):
        self.assertIn("career", context_pack.detect_topics("What does my career look like?"))

    def test_detect_topics_multiple(self):
        topics = context_pack.detect_topics("Will I get married and become wealthy?")
        self.assertIn("marriage", topics)
        self.assertIn("wealth", topics)

    def test_detect_topics_none(self):
        self.assertEqual(context_pack.detect_topics("Hello there, how are you?"), [])

    def test_build_context_pack_career_includes_house_10(self):
        pack = context_pack.build_context_pack("Tell me about my career", self.bundle, "D1")
        self.assertIn("career", pack["topics"])
        self.assertIn("House 10", pack["context"])

    def test_build_context_pack_empty_for_generic_question(self):
        pack = context_pack.build_context_pack("Hi Jyoti", self.bundle, "D1")
        self.assertEqual(pack["topics"], [])
        self.assertEqual(pack["context"], "")


class TestConversations(unittest.TestCase):
    def setUp(self):
        self.chart_id = "chart_convtest0000001"
        self.conv_id = conversations.derive_conversation_id(self.chart_id)

    def tearDown(self):
        p = conversations._safe_path(self.conv_id)
        if p and p.exists():
            p.unlink()

    def test_derive_conversation_id(self):
        self.assertEqual(self.conv_id, "conv_convtest0000001")

    def test_derive_conversation_id_rejects_malformed_chart_id(self):
        self.assertIsNone(conversations.derive_conversation_id("not_a_chart_id"))
        self.assertIsNone(conversations.derive_conversation_id(""))

    def test_append_turn_persists_and_loads(self):
        conversations.append_turn(self.conv_id, self.chart_id, "What is my ascendant?", "Aries.")
        loaded = conversations.load_conversation(self.conv_id)
        self.assertEqual(len(loaded["messages"]), 2)
        self.assertEqual(loaded["messages"][0]["content"], "What is my ascendant?")
        self.assertEqual(loaded["messages"][1]["content"], "Aries.")

    def test_append_turn_accumulates_across_calls(self):
        conversations.append_turn(self.conv_id, self.chart_id, "Q1", "A1")
        messages = conversations.append_turn(self.conv_id, self.chart_id, "Q2", "A2")
        self.assertEqual(len(messages), 4)

    def test_append_turn_trims_to_max_stored(self):
        for i in range(conversations.MAX_STORED_MESSAGES):
            conversations.append_turn(self.conv_id, self.chart_id, f"Q{i}", f"A{i}")
        loaded = conversations.load_conversation(self.conv_id)
        self.assertLessEqual(len(loaded["messages"]), conversations.MAX_STORED_MESSAGES)

    def test_path_traversal_blocked(self):
        self.assertIsNone(conversations.load_conversation("../../etc/passwd"))
        self.assertIsNone(conversations.load_conversation("chart_notaconv"))


if __name__ == "__main__":
    unittest.main()

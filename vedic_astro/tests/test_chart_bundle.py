"""
Milestone 1 tests: Chart Bundle schema, persistence, deterministic tools,
and the /api/chat no-chart guard. Uses hand-built Chart/PlanetPosition
objects (not live Swiss Ephemeris calls) so these are fast, deterministic
unit tests independent of any specific birth data.
"""
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chart.calculator import Chart, PlanetPosition
from chart_bundle import build_chart_bundle, make_chart_id, compute_dasha_tree, current_dasha_period
import persistence

SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio",
         "Sagittarius", "Capricorn", "Aquarius", "Pisces"]

BIRTH_INFO_1 = {"date": "1990-05-15", "time": "10:30", "place": "Delhi, India",
                "lat": 28.6139, "lon": 77.2090, "tz_offset": 5.5}
BIRTH_INFO_2 = {"date": "1985-11-02", "time": "22:15", "place": "Mumbai, India",
                "lat": 19.0760, "lon": 72.8777, "tz_offset": 5.5}
BIRTH_INFO_3 = {"date": "2000-01-01", "time": "00:00", "place": "London, UK",
                "lat": 51.5074, "lon": -0.1278, "tz_offset": 0.0}


def _fake_planet(name, sign_index, degrees, house, dignity="neutral", longitude=None):
    return PlanetPosition(
        name=name, longitude=longitude if longitude is not None else sign_index * 30 + degrees,
        sign_index=sign_index, sign=SIGNS[sign_index], degrees=degrees, minutes=0.0,
        nakshatra="Ashwini", nakshatra_lord="Ketu", pada=1,
        retrograde=False, dignity=dignity, house=house,
    )


def _fake_chart(label, asc_sign_index=0, planets=None):
    return Chart(
        label=label, ascendant_longitude=asc_sign_index * 30.0,
        ascendant_sign=SIGNS[asc_sign_index], ascendant_sign_index=asc_sign_index,
        ascendant_degrees=0.0, planets=planets or {}, houses=list(range(1, 13)),
    )


class TestChartId(unittest.TestCase):
    def test_stable_fingerprint(self):
        self.assertEqual(make_chart_id(BIRTH_INFO_1), make_chart_id(dict(BIRTH_INFO_1)))

    def test_different_birth_data_different_id(self):
        self.assertNotEqual(make_chart_id(BIRTH_INFO_1), make_chart_id(BIRTH_INFO_2))

    def test_id_format(self):
        cid = make_chart_id(BIRTH_INFO_1)
        self.assertTrue(cid.startswith("chart_"))
        self.assertEqual(len(cid), len("chart_") + 16)


class TestDashaTree(unittest.TestCase):
    def test_tree_has_nine_mahadashas_each_nine_antardashas(self):
        tree = compute_dasha_tree(datetime(1990, 5, 15, 5, 0), 45.0)
        self.assertEqual(len(tree), 9)
        for md in tree:
            self.assertEqual(len(md["antardashas"]), 9)
            self.assertLess(md["start"], md["end"])

    def test_current_period_found_for_a_real_date(self):
        tree = compute_dasha_tree(datetime(1990, 5, 15, 5, 0), 45.0)
        current = current_dasha_period(tree, as_of=datetime(2026, 1, 1))
        self.assertIsNotNone(current["mahadasha"])
        self.assertIn(current["mahadasha"]["lord"],
                       ["Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury"])
        self.assertIsNotNone(current["antardasha"])
        self.assertIsNotNone(current["pratyantardasha"])

    def test_no_current_period_far_in_the_past(self):
        tree = compute_dasha_tree(datetime(1990, 5, 15, 5, 0), 45.0)
        current = current_dasha_period(tree, as_of=datetime(1800, 1, 1))
        self.assertIsNone(current["mahadasha"])


class TestChartBundle(unittest.TestCase):
    def setUp(self):
        self.d1 = _fake_chart("D-1 (Rasi)", asc_sign_index=0, planets={
            "Sun": _fake_planet("Sun", 4, 15.0, house=5),
            "Moon": _fake_planet("Moon", 3, 20.0, house=4, longitude=110.0),
            "Mercury": _fake_planet("Mercury", 8, 5.0, house=9),
        })
        self.divs = {"D9": _fake_chart("D-9 (Navamsa)", asc_sign_index=1, planets={
            "Sun": _fake_planet("Sun", 0, 3.0, house=1),
            "Mercury": _fake_planet("Mercury", 8, 12.0, house=9),
        })}
        self.dashas = [{"lord": "Venus", "years": 20, "start": "1990-05", "end": "2010-05"}]
        self.strength = {"vargottama": {"Sun": []}, "vimshopaka_bala": {}}
        self.birth_dt = datetime(1990, 5, 15, 5, 0)

    def _build(self, birth_info=BIRTH_INFO_1):
        return build_chart_bundle(birth_info, self.birth_dt, self.d1, self.divs, self.dashas, self.strength)

    def test_bundle_is_json_serializable(self):
        json.dumps(self._build())

    def test_bundle_has_expected_top_level_keys(self):
        bundle = self._build()
        for key in ["chart_id", "schema_version", "birth_data", "calculation_config",
                    "divisional_charts", "timing", "derived"]:
            self.assertIn(key, bundle)

    def test_bundle_chart_id_matches_fingerprint(self):
        bundle = self._build()
        self.assertEqual(bundle["chart_id"], make_chart_id(BIRTH_INFO_1))

    def test_d1_and_d9_both_present_with_correct_planets(self):
        bundle = self._build()
        self.assertEqual(bundle["divisional_charts"]["D1"]["planets"]["Sun"]["sign"], "Leo")
        self.assertEqual(bundle["divisional_charts"]["D9"]["planets"]["Sun"]["sign"], "Aries")

    def test_calculation_config_is_lahiri_whole_sign(self):
        bundle = self._build()
        self.assertIn("Lahiri", bundle["calculation_config"]["ayanamsa"])
        self.assertEqual(bundle["calculation_config"]["house_system"], "Whole Sign")

    def test_two_different_profiles_get_different_bundles(self):
        b1 = self._build(BIRTH_INFO_1)
        b2 = self._build(BIRTH_INFO_2)
        self.assertNotEqual(b1["chart_id"], b2["chart_id"])


class TestChartTools(unittest.TestCase):
    def setUp(self):
        import chart_tools as tools
        self.tools = tools
        d1 = _fake_chart("D-1", asc_sign_index=0, planets={
            "Mercury": _fake_planet("Mercury", 8, 5.0, house=9, dignity="own"),
        })
        divs = {"D9": _fake_chart("D-9", asc_sign_index=1, planets={
            "Mercury": _fake_planet("Mercury", 8, 12.0, house=8, dignity="own"),
        })}
        self.bundle = build_chart_bundle(
            BIRTH_INFO_1, datetime(1990, 5, 15, 5, 0), d1, divs,
            [{"lord": "Venus", "years": 20, "start": "1990-05", "end": "2010-05"}],
            {"vargottama": {}, "vimshopaka_bala": {}},
        )

    def test_get_planet_position_d1(self):
        p = self.tools.get_planet_position(self.bundle, "Mercury", "D1")
        self.assertEqual(p["sign"], "Sagittarius")
        self.assertEqual(p["house"], 9)

    def test_get_planet_position_d9_differs_from_d1(self):
        p9 = self.tools.get_planet_position(self.bundle, "Mercury", "D9")
        self.assertEqual(p9["house"], 8)

    def test_get_divisional_chart_unknown_division_returns_none(self):
        self.assertIsNone(self.tools.get_divisional_chart(self.bundle, "D99"))

    def test_get_current_dasha_returns_timing_dict(self):
        timing = self.tools.get_current_dasha(self.bundle)
        self.assertIn("current_mahadasha", timing)
        self.assertIn("mahadasha_antardasha_sequence", timing)

    def test_compare_d1_d9_flags_vargottama(self):
        cmp = self.tools.compare_d1_d9(self.bundle)
        self.assertTrue(cmp["Mercury"]["vargottama"])


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.bundle1 = {"chart_id": "chart_test0000000001", "profile_name": "Profile One",
                         "created_at": "2026-01-01T00:00:00Z", "birth_data": {"place": "Delhi"}}
        self.bundle2 = {"chart_id": "chart_test0000000002", "profile_name": "Profile Two",
                         "created_at": "2026-01-01T00:00:00Z", "birth_data": {"place": "Mumbai"}}

    def tearDown(self):
        for cid in ("chart_test0000000001", "chart_test0000000002"):
            p = persistence._safe_path(cid)
            if p and p.exists():
                p.unlink()

    def test_save_and_load_round_trip(self):
        persistence.save_chart(self.bundle1)
        loaded = persistence.load_chart(self.bundle1["chart_id"])
        self.assertEqual(loaded["profile_name"], "Profile One")

    def test_two_profiles_stay_isolated(self):
        persistence.save_chart(self.bundle1)
        persistence.save_chart(self.bundle2)
        loaded1 = persistence.load_chart(self.bundle1["chart_id"])
        loaded2 = persistence.load_chart(self.bundle2["chart_id"])
        self.assertEqual(loaded1["birth_data"]["place"], "Delhi")
        self.assertEqual(loaded2["birth_data"]["place"], "Mumbai")
        self.assertNotEqual(loaded1["chart_id"], loaded2["chart_id"])

    def test_unknown_chart_id_returns_none(self):
        self.assertIsNone(persistence.load_chart("chart_doesnotexist0000"))

    def test_path_traversal_blocked(self):
        self.assertIsNone(persistence.load_chart("../../../etc/passwd"))
        self.assertIsNone(persistence.load_chart("chart_../../etc/passwd"))
        self.assertIsNone(persistence.load_chart(""))


class TestChatEndpointNoChart(unittest.TestCase):
    def test_chat_without_chart_id_or_birth_info_asks_for_a_chart(self):
        import web.app as app_module
        client = app_module.app.test_client()
        r = client.post("/api/chat", json={"question": "What is my ascendant?"})
        body = r.get_json()
        self.assertIn("calculate or select", body.get("answer", "").lower())


if __name__ == "__main__":
    unittest.main()

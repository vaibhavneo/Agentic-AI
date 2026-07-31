"""
Vedic Astrology Chatbot — Main Orchestrator
=============================================
Conversational interface that:
1. Collects birth data (date, time, place)
2. Calculates complete chart (D-1 through D-10)
3. Runs deep multi-agent prediction
4. Answers follow-up questions with chart context
5. Maintains conversation memory
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

import anthropic

from chart.calculator import VedicChartCalculator
from chart.divisional import build_divisional_charts
from chart.formatter import format_full_chart_text, format_south_indian, format_planet_table
from geocoder import geocode, parse_birth_datetime
from knowledge.ingest import get_knowledge_base
from agents.prediction_engine import run_deep_prediction


class VedicAstrologyChatbot:
    """
    The complete Vedic astrology AI.
    Maintains session state: current chart, conversation history.
    """

    SYSTEM_PROMPT = """You are Jyoti — a deeply knowledgeable and compassionate Vedic astrologer.
You have mastered the classical texts (Brihat Parasara Hora Sastra, Jaimini Sutras)
and the modern integrated approach (K.N. Rao, B.V. Raman, Narasimha Rao, Deepanshu Giri).

When a complete chart analysis has been done, you have access to all the planetary
positions and the full reading. Use this context to answer follow-up questions
with precision and depth.

Guidelines:
- Reference specific planets, houses, and signs in your answers
- Be warm, insightful, and non-fatalistic — Vedic astrology shows tendencies, not destiny
- Always suggest that the person has free will and can work with the energies
- For sensitive topics (health, death, major losses), be compassionate and constructive
- If asked about something not clearly shown in the chart, say so honestly
- Recommend spiritual practices or remedies when appropriate (mantras, gemstones, fasting)"""

    INTAKE_PROMPTS = {
        "date":  "📅 Please provide your date of birth (YYYY-MM-DD or DD/MM/YYYY):",
        "time":  "🕐 Please provide your exact time of birth (HH:MM in 24-hour format, e.g. 14:35):\n   Note: If unknown, try 06:00 (sunrise) and we'll note uncertainty.",
        "place": "📍 Please provide your place of birth (city, country):",
    }

    def __init__(self, api_key: str, verbose: bool = True):
        self.client  = anthropic.Anthropic(api_key=api_key)
        self.verbose = verbose
        self.calc    = VedicChartCalculator()
        self.kb      = None      # loaded on first chart analysis
        self.kb_tried = False

        # Session state
        self.current_chart_context: Optional[str]  = None
        self.current_reading: Optional[dict]       = None
        self.birth_info: Optional[dict]            = None
        self.d1                                    = None
        self.conversation: list[dict]              = []

    # ── Knowledge base (lazy load) ────────────────────────────────────────

    def _load_kb(self):
        if not self.kb_tried:
            self.kb_tried = True
            print("\n📚 Loading knowledge base from astrology books...")
            try:
                self.kb = get_knowledge_base()
            except Exception as e:
                print(f"   [warn] Knowledge base unavailable: {e}")
                self.kb = None

    # ── Birth data collection ─────────────────────────────────────────────

    def collect_birth_data(self) -> Optional[dict]:
        """Interactive birth data collection."""
        print("\n" + "═"*60)
        print(" BIRTH DATA — needed for your Vedic chart")
        print("═"*60)

        data = {}
        for field, prompt in self.INTAKE_PROMPTS.items():
            while True:
                print(f"\n{prompt}")
                val = input("  → ").strip()
                if val:
                    data[field] = val
                    break
                print("  (Required — please enter a value)")

        return data

    # ── Chart calculation ─────────────────────────────────────────────────

    def calculate_chart(self, date: str, time_str: str, place: str) -> Optional[dict]:
        """Geocode, calculate chart, build divisional charts."""
        print(f"\n🌍 Geocoding '{place}'...")
        geo = geocode(place)
        if not geo:
            # Fallback: ask for manual coordinates
            print(f"   Could not geocode '{place}'. Please enter coordinates manually.")
            try:
                lat = float(input("  Latitude (e.g. 28.6139): ").strip())
                lon = float(input("  Longitude (e.g. 77.2090): ").strip())
                tz_offset = float(input("  Timezone offset from UTC (e.g. 5.5 for IST): ").strip())
                geo = {"lat": lat, "lon": lon, "timezone_offset_hours": tz_offset,
                       "display_name": place, "timezone_name": "Manual"}
            except ValueError:
                return None

        print(f"   📌 {geo['display_name']}")
        print(f"   📐 Lat: {geo['lat']:.4f}, Lon: {geo['lon']:.4f}")
        print(f"   🕐 Timezone: {geo['timezone_name']} (UTC{geo['timezone_offset_hours']:+.1f})")

        try:
            utc_dt = parse_birth_datetime(date, time_str, geo["timezone_offset_hours"])
        except ValueError as e:
            print(f"   ❌ {e}")
            return None

        print(f"\n⚡ Calculating sidereal chart (Lahiri Ayanamsa)...")
        jd = self.calc.to_julian_day(utc_dt)

        # D-1 chart
        d1 = self.calc.build_d1(jd, geo["lat"], geo["lon"])
        self.d1 = d1

        # Divisional charts
        divs = build_divisional_charts(d1)

        # Vimshottari Dasha
        moon_lon = d1.planets["Moon"].longitude if "Moon" in d1.planets else 0.0
        dashas = self.calc.calc_vimshottari(jd, moon_lon)

        birth_info = {
            "date":  date,
            "time":  time_str,
            "place": place,
            "lat":   f"{geo['lat']:.4f}",
            "lon":   f"{geo['lon']:.4f}",
            "tz":    geo["timezone_name"],
            "utc_datetime": utc_dt.strftime("%Y-%m-%d %H:%M UTC"),
        }
        self.birth_info = birth_info

        return {
            "d1": d1,
            "divisional": divs,
            "dashas": dashas,
            "birth_info": birth_info,
        }

    # ── Display charts ────────────────────────────────────────────────────

    def display_charts(self, data: dict, show_all: bool = False):
        print("\n" + "═"*60)
        print(" YOUR VEDIC CHARTS")
        print("═"*60)

        # D-1
        print(format_south_indian(data["d1"]))
        print(format_planet_table(data["d1"]))

        if show_all:
            for chart in data["divisional"].values():
                print(format_south_indian(chart))
                print(format_planet_table(chart))

        # Dasha
        print("\n" + "─"*60)
        print(" VIMSHOTTARI DASHA PERIODS")
        print("─"*60)
        for d in data["dashas"][:6]:
            print(f"  {d['lord']:12s} {d['start']} → {d['end']}  ({d['years']} years)")
        print()

    # ── Full prediction ───────────────────────────────────────────────────

    def generate_reading(self, data: dict) -> dict:
        """Run the multi-agent prediction pipeline."""
        self._load_kb()
        results = run_deep_prediction(
            self.client,
            data["d1"],
            data["divisional"],
            data["dashas"],
            data["birth_info"],
            self.kb,
            verbose=self.verbose,
        )
        self.current_reading = results

        # Build context for follow-up conversations
        from chart.formatter import chart_to_analysis_context
        d1_ctx = chart_to_analysis_context(data["d1"], "D-1 Natal Chart")
        d9_ctx = chart_to_analysis_context(data["divisional"].get("D9"), "D-9 Navamsa") if "D9" in data["divisional"] else ""
        d10_ctx = chart_to_analysis_context(data["divisional"].get("D10"), "D-10 Dasamsa") if "D10" in data["divisional"] else ""

        self.current_chart_context = (
            f"BIRTH INFO: {json.dumps(data['birth_info'], indent=2)}\n\n"
            f"{d1_ctx}\n\n{d9_ctx}\n\n{d10_ctx}\n\n"
            f"CAREER ANALYSIS:\n{results['career']}\n\n"
            f"WEALTH ANALYSIS:\n{results['wealth']}\n\n"
            f"RELATIONSHIP & MARRIAGE:\n{results['relationships']}\n\n"
            f"SOUL PURPOSE:\n{results['soul_purpose']}\n\n"
            f"LIFE LESSONS:\n{results['life_lessons']}"
        )
        return results

    # ── Print the full reading ────────────────────────────────────────────

    @staticmethod
    def print_reading(reading: dict):
        sections = [
            ("💼 CAREER & PROFESSION", "career"),
            ("💰 WEALTH & FINANCIAL POTENTIAL", "wealth"),
            ("💝 RELATIONSHIPS & MARRIAGE", "relationships"),
            ("🔮 SOUL PURPOSE & LIFE PURPOSE", "soul_purpose"),
            ("📖 LIFE LESSONS & KARMIC THEMES", "life_lessons"),
            ("🌟 COMPLETE VEDIC READING — SYNTHESIS", "synthesis"),
        ]
        for title, key in sections:
            if key in reading:
                print(f"\n{'═'*64}")
                print(f" {title}")
                print(f"{'═'*64}")
                print(reading[key])

    # ── Follow-up conversation ────────────────────────────────────────────

    def answer_question(self, question: str) -> str:
        """Answer a follow-up question using the chart context."""
        chart_ctx = self.current_chart_context or ""
        system = (
            self.SYSTEM_PROMPT + "\n\n"
            "## Current Chart Context\n"
            + chart_ctx[:6000]
        )
        self.conversation.append({"role": "user", "content": question})
        resp = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            system=system,
            messages=self.conversation[-10:],  # keep last 10 turns
        )
        answer = resp.content[0].text
        self.conversation.append({"role": "assistant", "content": answer})
        return answer

    # ── Check if question is a new birth chart request ────────────────────

    def _is_new_chart_request(self, text: str) -> bool:
        keywords = ["new chart", "another chart", "someone else", "my friend",
                    "analyze", "birth chart for", "horoscope for", "read for"]
        return any(k in text.lower() for k in keywords)

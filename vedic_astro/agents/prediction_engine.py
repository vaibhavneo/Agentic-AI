"""
Vedic Astrology Deep Research Prediction Engine
================================================
Multi-agent architecture:
  1. Chart Analyst Agent   — reads all 6 charts and identifies key patterns
  2. Domain Expert Agents  — 6 specialists (career, wealth, relationships,
                             marriage, life purpose, soul purpose, life lessons)
  3. Synthesis Agent       — weaves all analyses into cohesive prediction
  4. Book Research Layer   — retrieves relevant passages from ingested books

Pattern: Orchestrator-Subagent + Parallel Processing + RAG
Source: Narasimha Rao (Integrated Approach), K.N. Rao (Finer Techniques),
        Deepanshu Giri (Nakshatra Pada), Arjun Pai (Nakshatra Remedies)
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

try:
    from openai import OpenAI as _OpenAI
    _USE_OPENAI = True
except ImportError:
    _USE_OPENAI = False

try:
    import anthropic as _anthropic
except ImportError:
    _anthropic = None

from chart.calculator import Chart, VedicChartCalculator, SIGN_LORDS, VIMSHOTTARI_SEQUENCE
from chart.formatter import chart_to_analysis_context
from chart.divisional import build_divisional_charts
from chart.strength import (
    compute_panchadha_maitri, find_vargottama, find_all_vargottama, strength_summary,
)
from knowledge.vedic_knowledge import (
    HOUSE_MEANINGS, PLANET_KARAKAS, SIGN_CHARACTERISTICS,
    IMPORTANT_YOGAS, DIVISIONAL_MEANINGS, NAKSHATRA_THEMES,
    CAREER_ANALYSIS_FRAMEWORK, WEALTH_ANALYSIS_FRAMEWORK,
    MARRIAGE_ANALYSIS_FRAMEWORK, SOUL_PURPOSE_FRAMEWORK,
    LIFE_LESSONS_FRAMEWORK,
)
from knowledge.varga_authority import get_authority

# Domain -> natural significator planets whose computed strength is worth
# surfacing in that domain's context (in addition to any dynamically-derived
# house lords added in build_strength_context()).
DOMAIN_KEY_PLANETS = {
    "career":   ["Sun", "Saturn", "Mercury"],
    "wealth":   ["Jupiter", "Venus"],
    "marriage": ["Venus", "Jupiter"],
    "soul":     ["Rahu", "Ketu"],
    "lessons":  ["Saturn"],
}

# Domain -> houses whose lord is a relevant additional significator.
DOMAIN_KEY_HOUSES = {
    "career":   [10],
    "wealth":   [2, 11],
    "marriage": [7],
    "soul":     [],
    "lessons":  [6, 8, 12],
}


def _call(client, system: str, user: str,
          model: str = "", max_tokens: int = 3000) -> str:
    """Unified call — works with both OpenAI-compatible (DeepSeek) and Anthropic clients.
    DeepSeek model name comes from $DEEPSEEK_MODEL (default deepseek-v4-flash);
    the old 'deepseek-chat'/'deepseek-reasoner' names now 400 — only
    deepseek-v4-pro/-flash are valid. Both are actually reasoning-capable
    (confirmed empirically — 'flash' is not exempt), returning chain-of-
    thought in a separate `reasoning_content` field that can consume the
    whole max_tokens budget and leave `content` empty. extra_body's
    thinking:disabled turns this off so `content` is always the direct
    answer (see web/app.py's _chat_with_client for the full investigation);
    the reasoning_content fallback below is now only a last-resort safety
    net, not the normal path. Read at call time (import-order-safe)."""
    model = model or os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
    if _USE_OPENAI and isinstance(client, _OpenAI):
        resp = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            extra_body={"thinking": {"type": "disabled"}},
        )
        msg = resp.choices[0].message
        return (msg.content or "").strip() or (getattr(msg, "reasoning_content", "") or "").strip()
    else:
        # Anthropic fallback
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text


# ══════════════════════════════════════════════════════════════════════════
# CONTEXT BUILDER — assemble all chart data + knowledge for LLM
# ══════════════════════════════════════════════════════════════════════════

class ChartContext:
    """Builds the complete astrological context for AI analysis."""

    def __init__(self, d1: Chart, divisional: dict[str, Chart],
                 dashas: list[dict], birth_info: dict):
        self.d1         = d1
        self.divisional = divisional
        self.dashas     = dashas
        self.birth_info = birth_info

    def _yogas_in_chart(self) -> str:
        """Detect major yogas from D-1."""
        d1 = self.d1
        asc = d1.ascendant_sign_index

        found: list[str] = []

        # Pancha Mahapurusha Yogas
        for planet, positions in [
            ("Jupiter", [3, 8, 11]),   # Cancer, Sagittarius, Pisces in Kendra
            ("Venus",   [1, 6, 11]),   # Taurus, Libra, Pisces in Kendra
            ("Mars",    [0, 7, 9]),    # Aries, Scorpio, Capricorn in Kendra
            ("Saturn",  [6, 9, 10]),   # Libra, Capricorn, Aquarius in Kendra
            ("Mercury", [2, 5]),       # Gemini, Virgo in Kendra
        ]:
            if planet in d1.planets:
                p = d1.planets[planet]
                if p.house in (1, 4, 7, 10) and p.sign_index in positions:
                    names = {"Jupiter": "Hamsa", "Venus": "Malavya",
                             "Mars": "Ruchaka", "Saturn": "Sasha", "Mercury": "Bhadra"}
                    found.append(f"{names[planet]} Yoga ({planet} in {p.sign}, House {p.house})")

        # Gajakesari
        if "Jupiter" in d1.planets and "Moon" in d1.planets:
            jup_house = d1.planets["Jupiter"].house
            moon_house = d1.planets["Moon"].house
            if (jup_house - moon_house) % 3 == 0:
                found.append(f"Gajakesari Yoga (Jupiter H{jup_house}, Moon H{moon_house})")

        # Budhaditya
        if "Sun" in d1.planets and "Mercury" in d1.planets:
            if d1.planets["Sun"].sign == d1.planets["Mercury"].sign:
                found.append(f"Budhaditya Yoga (Sun-Mercury in {d1.planets['Sun'].sign})")

        # Kaal Sarp check (rough)
        rahu_lon = d1.planets.get("Rahu", None)
        ketu_lon = d1.planets.get("Ketu", None)
        if rahu_lon and ketu_lon:
            # Check if all planets fall between Rahu and Ketu
            rahu_l = rahu_lon.longitude
            ketu_l = ketu_lon.longitude
            all_planets = [p.longitude for n, p in d1.planets.items()
                           if n not in ("Rahu", "Ketu")]
            # Simple check
            min_l = min(rahu_l, ketu_l)
            max_l = max(rahu_l, ketu_l)
            enclosed = all(min_l <= pl <= max_l for pl in all_planets)
            if enclosed:
                found.append("Kaal Sarp Yoga (all planets between Rahu-Ketu axis)")

        # Vargottama (D-1/D-9, the classical named case) + generalized same-sign
        # strength across the rest of the Shodasavarga (find_all_vargottama
        # covers all 16 charts; only D9 gets the "Vargottama" name itself).
        all_matches = find_all_vargottama(d1, self.divisional)
        for name in all_matches.get("D9", []):
            sign = d1.planets[name].sign
            found.append(f"Vargottama: {name} in {sign} (same sign D-1 and D-9 — very powerful)")
        for key, names in all_matches.items():
            if key == "D9" or not names:
                continue
            sign_list = ", ".join(f"{n} ({d1.planets[n].sign})" for n in names)
            found.append(f"Same-sign strength D-1/{key}: {sign_list}")

        return "\n".join(f"✦ {y}" for y in found) if found else "No major standard yogas detected (check for minor yogas)"

    def _amatyakaraka(self) -> str:
        """Find Amatyakaraka (planet with 2nd highest degrees within sign)."""
        scored = sorted(
            [(p.degrees + p.minutes/60, name)
             for name, p in self.d1.planets.items()
             if name not in ("Rahu", "Ketu")],
            reverse=True,
        )
        if len(scored) >= 2:
            ak_val, ak_name = scored[0]
            amk_val, amk_name = scored[1]
            return (f"Atmakaraka (AK): {ak_name} at {ak_val:.2f}° — the soul's primary lesson\n"
                    f"Amatyakaraka (AmK): {amk_name} at {amk_val:.2f}° — career and achievement significator")
        return ""

    def _current_dasha(self) -> str:
        """Find the current operating dasha."""
        if not self.dashas:
            return "Dasha periods not calculated"
        now = datetime.now()
        now_str = f"{now.year}-{now.month:02d}"
        current = self.dashas[0]
        for d in self.dashas:
            if d["start"] <= now_str <= d["end"]:
                current = d
                break
        return (f"Current Mahadasha: {current['lord']} ({current['start']} to {current['end']})\n"
                f"  {PLANET_KARAKAS.get(current['lord'], {}).get('soul_purpose', '')}")

    def build_strength_context(self, topic: str) -> str:
        """Computed cross-chart strength summary for the planets most relevant
        to `topic` — the concrete mechanism for feeding the LLM structured
        strength data instead of raw undifferentiated chart data alone."""
        planets = list(DOMAIN_KEY_PLANETS.get(topic, []))
        for house in DOMAIN_KEY_HOUSES.get(topic, []):
            if 1 <= house <= 12:
                sign_idx = self.d1.houses[house - 1]
                lord = SIGN_LORDS[sign_idx]
                if lord not in planets:
                    planets.append(lord)

        lines = [strength_summary(p, self.d1, self.divisional, topic) for p in planets]
        return "\n".join(f"- {line}" for line in lines) if lines else "No strength data computed for this topic."

    def build_full_context(self, topic: str = "all") -> str:
        """Build complete context string for the AI prediction engine.
        `topic` selects which divisional charts get emphasis, per the
        classical varga-authority mapping (knowledge/varga_authority.py) —
        each domain gets the charts that actually govern it, not every
        domain getting the same undifferentiated set."""
        parts = []

        # Birth info
        bi = self.birth_info
        parts.append(f"## Birth Data\n"
                     f"Date: {bi.get('date', 'Unknown')}\n"
                     f"Time: {bi.get('time', 'Unknown')}\n"
                     f"Place: {bi.get('place', 'Unknown')}\n"
                     f"Lat/Lon: {bi.get('lat', '?')}/{bi.get('lon', '?')}")

        # D-1 Chart
        parts.append(chart_to_analysis_context(self.d1, "D-1 (Rasi — Natal Chart)"))

        # Lordship convention — the single most-misused fact in AI chart reading.
        parts.append(
            "\n## IMPORTANT — House Lordship Convention\n"
            "Functional house lordships ('my 1st lord', 'my 7th lord', etc.) are "
            "ALWAYS defined by the D-1 (natal) lagna and are listed in the D-1 "
            "'House Lords' block above. They DO NOT change from one divisional "
            "chart to another. Each divisional chart below also shows its own "
            "house layout for reference, but when referring to 'the Nth lord' of "
            "the native, use the D-1 lords only."
        )

        # Divisional charts — domain-authoritative ones get full detail;
        # 'all' (default) falls back to the original 5-chart set.
        if topic == "all":
            chart_keys = ["D9", "D10", "D2", "D3", "D7"]
        else:
            authority = get_authority(topic)
            chart_keys = [k for k in authority["primary"] + authority["secondary"] if k != "D1"]
        for key in chart_keys:
            if key in self.divisional:
                # Divisional charts show placements only — no per-varga lord
                # table (functional lordships are D-1-only; see formatter docs).
                parts.append(chart_to_analysis_context(self.divisional[key], include_house_lords=False))

        # Karakas
        parts.append(f"\n## Atmakaraka & Amatyakaraka\n{self._amatyakaraka()}")

        # Yogas
        parts.append(f"\n## Key Yogas Detected\n{self._yogas_in_chart()}")

        # Computed cross-chart strength (Vimshopaka Bala, Vargottama) for the
        # planets most relevant to this topic
        if topic != "all":
            parts.append(f"\n## Computed Chart Strength ({topic})\n{self.build_strength_context(topic)}")

        # Moon Nakshatra
        if "Moon" in self.d1.planets:
            moon = self.d1.planets["Moon"]
            nak_theme = NAKSHATRA_THEMES.get(moon.nakshatra, "")
            parts.append(f"\n## Moon Nakshatra\n"
                         f"{moon.nakshatra} Pada {moon.pada} (Lord: {moon.nakshatra_lord})\n"
                         f"Theme: {nak_theme}")

        # Ascendant Nakshatra
        from chart.calculator import VedicChartCalculator
        calc = VedicChartCalculator()
        nak, nak_lord, pada = calc.nakshatra_from_longitude(self.d1.ascendant_longitude)
        nak_theme = NAKSHATRA_THEMES.get(nak, "")
        parts.append(f"\n## Ascendant Nakshatra\n{nak} Pada {pada} (Lord: {nak_lord})\nTheme: {nak_theme}")

        # Dasha
        parts.append(f"\n## Vimshottari Dasha\n{self._current_dasha()}")
        if self.dashas:
            dasha_list = "\n".join(
                f"  {d['lord']:12s} {d['start']} → {d['end']} ({d['years']}yr)"
                for d in self.dashas[:6]
            )
            parts.append(f"Dasha sequence:\n{dasha_list}")

        # Relevant vedic knowledge
        parts.append(f"\n## Classic House Meanings (selected)")
        for h in [1, 2, 4, 5, 7, 9, 10, 11]:
            hm = HOUSE_MEANINGS[h]
            parts.append(f"H{h} — {hm['name']}: {hm['primary'][:100]}")

        return "\n\n".join(parts)


# ══════════════════════════════════════════════════════════════════════════
# PREDICTION AGENTS
# ══════════════════════════════════════════════════════════════════════════

BASE_SYSTEM = """You are a master Vedic astrologer with 30+ years of experience,
trained in the classical traditions of Parasara, Jaimini, B.V. Raman, K.N. Rao,
and Deepanshu Giri. You have studied the complete Brihat Parasara Hora Sastra
and applied it to thousands of charts.

IMPORTANT RULES:
- Base ALL predictions on the specific planetary positions in the chart data provided
- Reference specific planets, houses, signs, and dignities in your analysis
- Integrate D-1 with divisional charts (especially D-9 for soul/marriage, D-10 for career)
- Acknowledge both strengths AND challenges honestly
- Give time-based predictions using Dasha periods when relevant
- Write in clear, insightful English accessible to a modern reader
- Avoid vague generalities — be specific to THIS chart
- If you reference RELEVANT BOOK PASSAGES, cite them exactly as shown in their
  [Book Title, page N] tag. Never invent a book title, author, or page number
  that is not shown in the passages given to you."""


def analyze_career(client: anthropic.Anthropic, ctx: ChartContext,
                   book_passages: str, verbose: bool = False) -> str:
    if verbose: print("   💼 Career analyst running...")
    system = BASE_SYSTEM + f"\n\n{CAREER_ANALYSIS_FRAMEWORK}"
    user = f"""Analyze the CAREER potential for this chart.

{ctx.build_full_context('career')}

RELEVANT BOOK PASSAGES:
{book_passages}

Provide a comprehensive career analysis covering:
1. Most suitable professions based on D-1 + D-10 + Amatyakaraka
2. Career trajectory — when does success peak? (Dasha timing)
3. Natural talents and working style
4. Potential career challenges and how to navigate them
5. Best environments to work in (corporate/creative/service/independent)
Be specific to the actual planetary positions. 300-400 words."""

    return _call(client, system, user)


def analyze_wealth(client: anthropic.Anthropic, ctx: ChartContext,
                   book_passages: str, verbose: bool = False) -> str:
    if verbose: print("   💰 Wealth analyst running...")
    system = BASE_SYSTEM + f"\n\n{WEALTH_ANALYSIS_FRAMEWORK}"
    user = f"""Analyze the WEALTH and FINANCIAL POTENTIAL for this chart.

{ctx.build_full_context('wealth')}

RELEVANT BOOK PASSAGES:
{book_passages}

Cover:
1. Natural wealth potential — early vs late bloomer financially
2. Primary sources of income and wealth accumulation
3. D-2 (Hora) analysis — Sun hora or Moon hora dominant?
4. Dhana yogas present (or absent)
5. Periods of financial peak and challenge
6. Financial mindset and relationship with money
Be specific to actual planetary positions. 250-350 words."""

    return _call(client, system, user)


def analyze_relationships(client: anthropic.Anthropic, ctx: ChartContext,
                          book_passages: str, verbose: bool = False) -> str:
    if verbose: print("   💝 Relationship analyst running...")
    system = BASE_SYSTEM + f"\n\n{MARRIAGE_ANALYSIS_FRAMEWORK}"
    user = f"""Analyze RELATIONSHIPS and MARRIAGE for this chart.

{ctx.build_full_context('marriage')}

RELEVANT BOOK PASSAGES:
{book_passages}

Analyze:
1. General relationship patterns — how they love and are loved
2. Spouse/partner characteristics from D-9 7th house
3. Marriage timing and indicators (favorable dasha periods)
4. Challenges in relationships and karmic lessons
5. Venus analysis — relating style and values in partnership
6. 7th house condition in D-1 and D-9
7. Whether this chart indicates a harmonious or challenging marriage journey
Be specific. 300-400 words."""

    return _call(client, system, user)


def analyze_soul_purpose(client: anthropic.Anthropic, ctx: ChartContext,
                          book_passages: str, verbose: bool = False) -> str:
    if verbose: print("   🔮 Soul purpose analyst running...")
    system = BASE_SYSTEM + f"\n\n{SOUL_PURPOSE_FRAMEWORK}"
    user = f"""Analyze the SOUL PURPOSE and LIFE PURPOSE of this chart.

{ctx.build_full_context('soul')}

RELEVANT BOOK PASSAGES:
{book_passages}

This is the most important analysis. Cover deeply:
1. RAHU (North Node) — the soul's current evolutionary direction and mission
2. KETU (South Node) — past life mastery and what must be released/balanced
3. Atmakaraka — the soul's primary lesson in this lifetime
4. D-9 Navamsa Lagna — the soul's dharmic nature
5. 9th house (Dharma) — higher purpose, guiding philosophy
6. 5th house (Purva Punya) — what gifts were brought from past lives
7. The central karmic axis of this life
Write with depth and insight. 400-500 words."""

    return _call(client, system, user, max_tokens=3000)


def analyze_life_lessons(client: anthropic.Anthropic, ctx: ChartContext,
                          book_passages: str, verbose: bool = False) -> str:
    if verbose: print("   📖 Life lessons analyst running...")
    system = BASE_SYSTEM + f"\n\n{LIFE_LESSONS_FRAMEWORK}"
    user = f"""Analyze the LIFE LESSONS and KARMIC THEMES for this chart.

{ctx.build_full_context('lessons')}

RELEVANT BOOK PASSAGES:
{book_passages}

Cover:
1. Saturn's placement — primary karmic lesson and areas of disciplined growth
2. Challenges indicated in 6th, 8th, 12th houses
3. Retrograde planets — internalized energies and past-life over-development
4. Debilitated planets — what needs conscious healing
5. The biggest growth edge in this lifetime
6. Spiritual path indicated (devotion / knowledge / service / practice)
7. The lesson the soul came specifically to learn in this incarnation
Be honest about challenges while offering constructive guidance. 350-450 words."""

    return _call(client, system, user)


def synthesize_full_reading(
    client: anthropic.Anthropic,
    ctx: ChartContext,
    career: str,
    wealth: str,
    relationships: str,
    soul_purpose: str,
    life_lessons: str,
    verbose: bool = False,
) -> str:
    if verbose: print("   🌟 Synthesis agent weaving final reading...")

    system = f"""{BASE_SYSTEM}

You are now the master synthesizer. You have received specialist analyses from
5 different expert astrologers. Your job is to weave them into ONE coherent,
flowing, deeply insightful Vedic reading that:
- Identifies the central themes that run through ALL areas
- Highlights the most important 3-5 chart factors
- Shows how career, wealth, relationships, and purpose interconnect
- Gives 3-5 specific, actionable guidance points
- Speaks to the person's whole life journey"""

    user = f"""Synthesize this complete Vedic reading.

BIRTH INFO: {ctx.birth_info}
D-1 ASCENDANT: {ctx.d1.ascendant_sign} with key planets {', '.join(f'{n} in H{p.house} {p.sign}({p.dignity})' for n, p in ctx.d1.planets.items() if p.dignity != 'neutral')[:300]}

CAREER ANALYSIS:
{career}

WEALTH ANALYSIS:
{wealth}

RELATIONSHIP & MARRIAGE ANALYSIS:
{relationships}

SOUL PURPOSE:
{soul_purpose}

LIFE LESSONS:
{life_lessons}

Write the COMPLETE VEDIC READING as a flowing, personal, insightful document.
Format it with clear sections but write in warm, direct language as if speaking
to the person. Include specific remedies or guidance at the end. 600-800 words."""

    return _call(client, system, user, max_tokens=4000)


# ══════════════════════════════════════════════════════════════════════════
# MASTER PREDICTION RUNNER
# ══════════════════════════════════════════════════════════════════════════

def run_deep_prediction(
    client: anthropic.Anthropic,
    d1: Chart,
    divisional: dict[str, Chart],
    dashas: list[dict],
    birth_info: dict,
    knowledge_base,
    verbose: bool = True,
) -> dict[str, str]:
    """
    Run the full multi-agent deep prediction pipeline.
    Returns dict with all domain analyses + synthesis.
    """
    ctx = ChartContext(d1, divisional, dashas, birth_info)

    # Build topic-specific book research queries
    def get_book_ctx(query: str) -> str:
        if knowledge_base:
            return knowledge_base.format_context(query, top_k=4, max_chars=2000)
        return ""

    asc_sign = d1.ascendant_sign
    moon_nak = d1.planets.get("Moon", None)
    moon_nak_name = moon_nak.nakshatra if moon_nak else ""

    if verbose:
        print("\n🔭 Running deep multi-agent Vedic analysis...")
        print(f"   Chart: {asc_sign} Ascendant, Moon in {moon_nak_name}")

    # ── Parallel-style: run each domain analysis
    results: dict[str, str] = {}

    results["career"] = analyze_career(
        client, ctx,
        get_book_ctx(f"{asc_sign} ascendant career 10th house profession D-10 Dasamsa Amatyakaraka {moon_nak_name}"),
        verbose,
    )

    results["wealth"] = analyze_wealth(
        client, ctx,
        get_book_ctx(f"{asc_sign} wealth 2nd 11th house financial prosperity dhana yoga D-2 Hora"),
        verbose,
    )

    results["relationships"] = analyze_relationships(
        client, ctx,
        get_book_ctx(f"marriage 7th house D-9 navamsa spouse {asc_sign} ascendant relationship"),
        verbose,
    )

    results["soul_purpose"] = analyze_soul_purpose(
        client, ctx,
        get_book_ctx(f"rahu ketu north south node soul purpose {moon_nak_name} nakshatra dharma 9th house D-20 vimsamsa D-24 chaturvimsamsa"),
        verbose,
    )

    results["life_lessons"] = analyze_life_lessons(
        client, ctx,
        get_book_ctx(f"saturn karma 8th house 12th house life lessons spiritual growth {asc_sign} D-30 trimsamsa misfortune"),
        verbose,
    )

    results["synthesis"] = synthesize_full_reading(
        client, ctx,
        results["career"],
        results["wealth"],
        results["relationships"],
        results["soul_purpose"],
        results["life_lessons"],
        verbose,
    )

    return results

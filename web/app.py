"""
Vedic Astrology Brain — Flask Web Server
=========================================
Serves the Jyotish AI on http://localhost:5050
Powered by DeepSeek LLM (falls back to Anthropic if ANTHROPIC_API_KEY is set)
"""
from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Load .env from vedic_astro/ or stock_agent/ (shared key)
for _env_path in [
    Path(__file__).parent.parent / ".env",          # vedic_astro/.env
    Path(__file__).parent.parent.parent / "stock_agent" / ".env",  # stock_agent/.env
]:
    if _env_path.exists():
        for line in _env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())
        break

sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, Response, jsonify, request, stream_with_context

from chart.calculator import VedicChartCalculator
from chart.divisional import build_divisional_charts
from chart.transits import (
    build_transit_context,
    build_dasha_bhukti_context,
    extract_target_times,
)
from chart.formatter import (
    format_south_indian,
    format_planet_table,
    chart_to_analysis_context,
)
from chart.strength import compute_panchadha_maitri, find_all_vargottama, vimshopaka_bala
from geocoder import geocode, parse_birth_datetime
from knowledge.ingest import get_knowledge_base
from agents.prediction_engine import (
    ChartContext,
    analyze_career,
    analyze_wealth,
    analyze_relationships,
    analyze_soul_purpose,
    analyze_life_lessons,
    synthesize_full_reading,
)

app = Flask(__name__, static_folder="static")
app.config["JSON_SORT_KEYS"] = False

# DeepSeek retired deepseek-chat AND deepseek-reasoner; the only valid names are
# now deepseek-v4-pro and deepseek-v4-flash. Default is FLASH, not pro: pro is a
# reasoning model that spends the whole max_tokens budget on hidden reasoning
# before emitting any answer, so a normal chat budget comes back with an EMPTY
# message.content ("No response"). flash returns the answer directly. Single
# source of truth, overridable: set DEEPSEEK_MODEL in vedic_astro/.env.
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

_client = None
_calc   = VedicChartCalculator()
_kb     = None
_kb_lock = threading.Lock()


def _get_api_key() -> tuple[str, str]:
    """Returns (key, provider) — prefers DeepSeek, falls back to Anthropic."""
    dk = os.getenv("DEEPSEEK_API_KEY", "")
    if dk:
        return dk, "deepseek"
    ak = os.getenv("ANTHROPIC_API_KEY", "")
    if ak:
        return ak, "anthropic"
    return "", "none"


def get_client():
    global _client
    if _client is None:
        key, provider = _get_api_key()
        if not key:
            raise ValueError(
                "No API key found. Create vedic_astro/.env with DEEPSEEK_API_KEY=sk-..."
            )
        if provider == "deepseek":
            from openai import OpenAI
            _client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
        else:
            import anthropic
            _client = anthropic.Anthropic(api_key=key)
    return _client


def get_kb():
    global _kb
    with _kb_lock:
        if _kb is None:
            _kb = get_knowledge_base()
    return _kb


def _chat_with_client(client, system: str, messages: list, max_tokens: int = 3000) -> str:
    """Send a chat message — works with both DeepSeek (OpenAI) and Anthropic clients.

    max_tokens is generous because deepseek-v4-pro is a reasoning model that
    consumes the budget on hidden reasoning first; too small a cap returns an
    empty content with finish_reason='length'. If content still comes back
    empty (reasoning ate the whole budget), fall back to reasoning_content so
    the user sees something rather than a blank 'No response'.
    """
    try:
        from openai import OpenAI
        if isinstance(client, OpenAI):
            msgs = [{"role": "system", "content": system}] + messages
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                max_tokens=max_tokens,
                messages=msgs,
            )
            msg = resp.choices[0].message
            content = (msg.content or "").strip()
            if not content:
                content = (getattr(msg, "reasoning_content", "") or "").strip()
            if not content:
                content = ("The model returned an empty response (finish_reason="
                           f"{resp.choices[0].finish_reason}). Try DEEPSEEK_MODEL="
                           "deepseek-v4-flash for direct answers.")
            return content
    except ImportError:
        pass
    # Anthropic
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    )
    return resp.content[0].text


# ── Routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return (Path(__file__).parent / "static" / "index.html").read_text()


@app.route("/api/status")
def api_status():
    key, provider = _get_api_key()
    return jsonify({"ok": bool(key), "provider": provider, "key_set": bool(key)})


@app.route("/api/geocode", methods=["POST"])
def api_geocode():
    place = (request.json or {}).get("place", "")
    if not place:
        return jsonify({"error": "No place provided"}), 400
    result = geocode(place)
    if not result:
        return jsonify({"error": f"Could not geocode '{place}'"}), 404
    return jsonify(result)


@app.route("/api/chart", methods=["POST"])
def api_chart():
    data = request.json or {}
    try:
        date      = data["date"]
        time_str  = data["time"]
        place     = data["place"]
        lat       = float(data.get("lat", 0))
        lon       = float(data.get("lon", 0))
        tz_offset = float(data.get("tz_offset", 0))
    except (KeyError, ValueError) as e:
        return jsonify({"error": str(e)}), 400

    try:
        utc_dt = parse_birth_datetime(date, time_str, tz_offset)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    jd   = _calc.to_julian_day(utc_dt)
    d1   = _calc.build_d1(jd, lat, lon)
    divs = build_divisional_charts(d1)
    moon_lon = d1.planets.get("Moon").longitude if "Moon" in d1.planets else 0.0
    dashas   = _calc.calc_vimshottari(jd, moon_lon)

    def planet_dict(p):
        return {
            "sign": p.sign, "degrees": p.degrees, "minutes": p.minutes,
            "house": p.house, "dignity": p.dignity,
            "nakshatra": p.nakshatra, "nakshatra_lord": p.nakshatra_lord,
            "pada": p.pada, "retrograde": p.retrograde,
        }

    def chart_dict(chart):
        return {
            "label": chart.label,
            "ascendant": {
                "sign": chart.ascendant_sign,
                "degrees": round(chart.ascendant_degrees, 2),
                "sign_index": chart.ascendant_sign_index,
            },
            "planets": {name: planet_dict(p) for name, p in chart.planets.items()},
            "houses": chart.houses,
            "grid_ascii": format_south_indian(chart),
            "table_ascii": format_planet_table(chart),
        }

    # Full Shodasavarga — dynamic, so newly-added vargas show up automatically
    charts_payload = {"d1": chart_dict(d1)}
    charts_payload.update({key.lower(): chart_dict(chart) for key, chart in divs.items()})

    # Computed strength: Vargottama/same-sign findings + Vimshopaka Bala for the
    # 9 classical planets across the full 16-varga set
    maitri = compute_panchadha_maitri(d1)
    vargottama = find_all_vargottama(d1, divs)
    strength = {
        "vargottama": vargottama,
        "vimshopaka_bala": {
            name: vimshopaka_bala(name, d1, divs, panchadha_maitri=maitri)
            for name in d1.planets
        },
    }

    return jsonify({
        "birth_info": {
            "date": date, "time": time_str, "place": place,
            "lat": lat, "lon": lon, "tz_offset": tz_offset,
            "utc": utc_dt.strftime("%Y-%m-%d %H:%M UTC"),
        },
        **charts_payload,
        "dashas": dashas,
        "strength": strength,
    })


@app.route("/api/reading/stream", methods=["POST"])
def api_reading_stream():
    data       = request.json or {}
    birth_info = data.get("birth_info", {})
    date       = birth_info.get("date")
    time_str   = birth_info.get("time")
    lat        = float(birth_info.get("lat", 0))
    lon        = float(birth_info.get("lon", 0))
    tz_offset  = float(birth_info.get("tz_offset", 0))

    try:
        utc_dt = parse_birth_datetime(date, time_str, tz_offset)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    # Check API key before starting stream
    key, provider = _get_api_key()
    if not key:
        def err_gen():
            yield 'event: error\ndata: {"msg": "No API key. Create vedic_astro/.env with DEEPSEEK_API_KEY=sk-..."}\n\n'
            yield 'event: done\ndata: {"msg": "done"}\n\n'
        return Response(stream_with_context(err_gen()), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache"})

    jd   = _calc.to_julian_day(utc_dt)
    d1   = _calc.build_d1(jd, lat, lon)
    divs = build_divisional_charts(d1)
    moon_lon = d1.planets.get("Moon").longitude if "Moon" in d1.planets else 0.0
    dashas   = _calc.calc_vimshottari(jd, moon_lon)
    ctx      = ChartContext(d1, divs, dashas, birth_info)
    client   = get_client()
    kb       = get_kb()

    def generate():
        def send(event: str, data_obj: dict):
            payload = json.dumps(data_obj, ensure_ascii=False)
            yield f"event: {event}\ndata: {payload}\n\n"

        def book_ctx(query: str) -> str:
            return kb.format_context(query, top_k=4, max_chars=2000) if kb else ""

        asc = d1.ascendant_sign
        moon_planet = d1.planets.get("Moon")
        moon_nak = moon_planet.nakshatra if moon_planet else ""

        yield from send("status", {"msg": "💼 Career agent analyzing..."})
        career = analyze_career(client, ctx, book_ctx(f"{asc} career 10th house {moon_nak}"))
        yield from send("section", {"key": "career", "title": "Career & Profession", "content": career})

        yield from send("status", {"msg": "💰 Wealth agent analyzing..."})
        wealth = analyze_wealth(client, ctx, book_ctx(f"{asc} wealth 2nd 11th dhana yoga"))
        yield from send("section", {"key": "wealth", "title": "Wealth & Financial Potential", "content": wealth})

        yield from send("status", {"msg": "💝 Relationship agent analyzing..."})
        relationships = analyze_relationships(client, ctx, book_ctx(f"7th house marriage navamsa spouse {asc}"))
        yield from send("section", {"key": "relationships", "title": "Relationships & Marriage", "content": relationships})

        yield from send("status", {"msg": "🔮 Soul purpose agent analyzing..."})
        soul = analyze_soul_purpose(client, ctx, book_ctx(f"rahu ketu soul purpose nakshatra {moon_nak} dharma"))
        yield from send("section", {"key": "soul_purpose", "title": "Soul Purpose & Dharma", "content": soul})

        yield from send("status", {"msg": "📖 Life lessons agent analyzing..."})
        lessons = analyze_life_lessons(client, ctx, book_ctx(f"saturn karma 8th 12th house life lessons {asc}"))
        yield from send("section", {"key": "life_lessons", "title": "Life Lessons & Karmic Themes", "content": lessons})

        yield from send("status", {"msg": "🌟 Synthesizing complete reading..."})
        synthesis = synthesize_full_reading(client, ctx, career, wealth, relationships, soul, lessons)
        yield from send("section", {"key": "synthesis", "title": "Complete Vedic Reading", "content": synthesis})

        yield from send("done", {"msg": "Reading complete"})

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _chart_context_from_birth(birth_info: dict) -> str:
    """Recompute the chart on the server from birth data and build the SAME
    authoritative context string the reading engine uses. This is the single
    source of truth for the chat — the browser no longer hand-assembles a
    partial summary that the LLM then hallucinates around."""
    date      = birth_info.get("date")
    time_str  = birth_info.get("time")
    lat       = float(birth_info.get("lat", 0))
    lon       = float(birth_info.get("lon", 0))
    tz_offset = float(birth_info.get("tz_offset", 0))

    utc_dt   = parse_birth_datetime(date, time_str, tz_offset)
    jd       = _calc.to_julian_day(utc_dt)
    d1       = _calc.build_d1(jd, lat, lon)
    divs     = build_divisional_charts(d1)
    moon_lon = d1.planets.get("Moon").longitude if "Moon" in d1.planets else 0.0
    dashas   = _calc.calc_vimshottari(jd, moon_lon)
    ctx      = ChartContext(d1, divs, dashas, birth_info)
    return ctx.build_full_context("all")


def _transit_context_from_birth(birth_info: dict, question: str) -> str:
    """Build the live gochara (transit) block: the natal D-1 plus current
    planetary positions — and positions for any date named in the question —
    mapped onto the natal houses. Transits are judged from the natal Moon and
    Lagna, so no birth place is needed beyond the natal chart already computed."""
    date      = birth_info.get("date")
    time_str  = birth_info.get("time")
    lat       = float(birth_info.get("lat", 0))
    lon       = float(birth_info.get("lon", 0))
    tz_offset = float(birth_info.get("tz_offset", 0))

    utc_dt = parse_birth_datetime(date, time_str, tz_offset)
    jd     = _calc.to_julian_day(utc_dt)
    d1     = _calc.build_d1(jd, lat, lon)

    now      = datetime.utcnow()
    targets  = extract_target_times(question, now)
    blocks   = [build_transit_context(_calc, d1, when, label)
                for label, when in targets]

    # Grounded dasha→bhukti timeline covering now through any year asked about.
    moon_lon   = d1.planets["Moon"].longitude if "Moon" in d1.planets else 0.0
    until_year = max([now.year] + [w.year for _, w in targets])
    blocks.append(build_dasha_bhukti_context(_calc, jd, moon_lon, now, until_year))
    return "\n\n".join(blocks)


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data       = request.json or {}
    question   = data.get("question", "")
    history    = data.get("history", [])
    birth_info = data.get("birth_info") or {}
    reading    = data.get("reading", "")          # optional full-reading prose
    ctx_str    = data.get("chart_context", "")     # legacy fallback

    if not question:
        return jsonify({"error": "No question"}), 400

    key, _ = _get_api_key()
    if not key:
        return jsonify({"error": "No API key. Create vedic_astro/.env with DEEPSEEK_API_KEY=sk-..."}), 503

    # Authoritative chart context: recompute server-side from birth data so the
    # LLM sees the EXACT chart that was rendered — full planetary placements,
    # divisionals, karakas, yogas, strength, and the live dasha timeline.
    chart_ctx = ""
    transit_ctx = ""
    if birth_info.get("date") and birth_info.get("time"):
        try:
            chart_ctx = _chart_context_from_birth(birth_info)
        except Exception as e:
            chart_ctx = ""   # fall through to legacy context below
            print(f"   ⚠️  chat chart recompute failed: {e}")
        # Live gochara (transits): current planetary positions relative to the
        # natal chart, plus positions for any date the user names in the
        # question. This is what lets the agent answer timing questions.
        try:
            transit_ctx = _transit_context_from_birth(birth_info, question)
        except Exception as e:
            transit_ctx = ""
            print(f"   ⚠️  chat transit compute failed: {e}")
    if not chart_ctx:
        chart_ctx = ctx_str   # legacy path if no birth_info supplied

    today = datetime.now()
    system_parts = [
        "You are Jyoti — a deeply knowledgeable and compassionate Vedic astrologer "
        "trained in Parasara, Jaimini, K.N. Rao, Deepanshu Giri, and Narasimha Rao traditions.",
        f"TODAY'S DATE is {today.strftime('%A, %d %B %Y')}. Use this as 'now' for any "
        "question about the present, the future, age, or timing. Never say you don't "
        "know the current date.",
        "The person's COMPLETE, AUTHORITATIVE chart is given below. It is computed "
        "directly from Swiss Ephemeris for this exact birth data. Treat it as ground "
        "truth. When answering, cite the specific planets, signs, houses, nakshatras, "
        "and dasha periods AS GIVEN — never guess or invent a placement. If a detail "
        "isn't in the data below, say so rather than assuming it.",
        "CRITICAL — House lordships: the chart data includes an explicit 'House Lords' "
        "table for each chart. NEVER derive lordships yourself from memory. When the "
        "user asks about 'the Nth lord' or which house a planet rules, read it "
        "verbatim from the D-1 'House Lords' table. Functional lordships come from the "
        "D-1 lagna only and stay fixed across all divisional charts (D-9, D-10, etc.). "
        "For example, do not call a planet 'the 5th lord' unless the D-1 table says so.",
        "Be warm, insightful, and non-fatalistic.",
        "Address the person directly as 'you'. Do NOT narrate your reasoning "
        "process, restate the question, or write phrases like 'We need to "
        "analyze' — give the reading itself, directly and gracefully.",
        "\n## AUTHORITATIVE CHART DATA\n" + chart_ctx,
    ]
    if transit_ctx:
        system_parts.append(
            "TIMING METHOD — For any question about WHEN something happens, or "
            "about a specific date/year, reason from BOTH (a) the Vimshottari "
            "Dasha timeline in the chart data above, and (b) the live TRANSITS "
            "(gochara) below, which are computed from Swiss Ephemeris for the "
            "current date and for any date named in the question. Combine dasha "
            "(the active planetary period) with transit (where the planets "
            "actually are) — that is the classical way to time an event. Cite "
            "the specific transiting planets, their houses from the Moon and "
            "Lagna, Sade Sati status, and Jupiter/Saturn positions AS GIVEN.")
        system_parts.append(
            "\n## LIVE TRANSITS / GOCHARA (computed — treat as ground truth)\n"
            + transit_ctx)
    if reading:
        # Secondary context, clearly subordinate to the chart data above.
        system_parts.append(
            "\n## Prior Full Reading (narrative context — the chart data above "
            "always takes precedence if anything conflicts)\n" + reading[:4000]
        )
    system = "\n\n".join(system_parts)

    try:
        client = get_client()
        messages = history[-10:] + [{"role": "user", "content": question}]
        answer = _chat_with_client(client, system, messages)
        return jsonify({"answer": answer})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    key, provider = _get_api_key()
    print("\n🪐 Jyotish Vedic Astrology AI")
    print(f"   LLM: {'DeepSeek ' + DEEPSEEK_MODEL if provider == 'deepseek' else 'Anthropic claude-sonnet-4-6' if provider == 'anthropic' else 'NOT SET'}")
    print(f"   Key: {'SET (' + key[:8] + '...)' if key else 'NOT SET — create vedic_astro/.env with DEEPSEEK_API_KEY=sk-...'}")
    print("   Loading knowledge base...")
    try:
        get_kb()
        print("   ✅ Knowledge base ready")
    except Exception as e:
        print(f"   ⚠️  KB warning: {e}")
    print("\n   ✨ Server at http://localhost:5050")
    print("   Press Ctrl+C to stop\n")
    port = int(os.getenv("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)

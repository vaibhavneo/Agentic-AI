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

    Both deepseek-v4-flash AND deepseek-v4-pro are actually reasoning-capable
    (confirmed empirically - flash is not "non-reasoning", it just reasons by
    default unless told not to): the API returns chain-of-thought in a
    separate `reasoning_content` field, at the same level as `content`. Under
    a tight max_tokens budget the model can spend the whole budget on
    reasoning and return finish_reason='length' with an EMPTY `content` - a
    previous version of this code fell back to displaying `reasoning_content`
    in that case, which is how raw internal narration ("I need to check...",
    "wait, that's not right") ended up shown to the user as if it were the
    final answer. Fix: explicitly disable thinking mode via
    extra_body={"thinking": {"type": "disabled"}} (DeepSeek V4 API, see
    api-docs.deepseek.com/guides/thinking_mode) so `content` is always the
    direct answer and `reasoning_content` is never populated. The
    reasoning_content fallback stays only as a last-resort safety net for a
    genuinely empty response (e.g. a future model or a real max_tokens cutoff
    on a very long answer) - normal operation should never reach it now.
    """
    try:
        from openai import OpenAI
        if isinstance(client, OpenAI):
            msgs = [{"role": "system", "content": system}] + messages
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                max_tokens=max_tokens,
                messages=msgs,
                extra_body={"thinking": {"type": "disabled"}},
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

    from chart_bundle import build_chart_bundle
    from persistence import save_chart
    bundle = build_chart_bundle(
        birth_info={"date": date, "time": time_str, "place": place,
                    "lat": lat, "lon": lon, "tz_offset": tz_offset},
        birth_dt=utc_dt, d1=d1, divs=divs, dashas=dashas, strength=strength,
    )
    save_chart(bundle)

    return jsonify({
        "chart_id": bundle["chart_id"],
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


def _build_grounded_context(bundle, division):
    """Formats an already-built Chart Bundle into text for the system
    prompt. Reads only bundle fields - no recalculation."""
    lines = []
    d1 = bundle["divisional_charts"].get("D1")
    bd = bundle["birth_data"]
    lines.append("Birth data: %s %s at %s (lat %s, lon %s, UTC %s)" % (
        bd['date'], bd['time'], bd['place'], bd['lat'], bd['lon'], bd['utc']))
    lines.append("")
    lines.append("D-1 (Rasi) Ascendant: %s at %s degrees" % (
        d1['ascendant']['sign'], d1['ascendant']['degrees']))
    lines.append("D-1 Planetary Positions:")
    for name, p in d1["planets"].items():
        retro = "(Retrograde) " if p["retrograde"] else ""
        lines.append("  %s: %s %sd%s' House %s Nakshatra %s Pada %s %sDignity: %s" % (
            name, p['sign'], p['degrees'], p['minutes'], p['house'],
            p['nakshatra'], p['pada'], retro, p['dignity']))
    lines.append("D-1 House Lords (lordships ALWAYS derive from D-1, fixed across "
                  "all divisional charts): %s" % d1['house_lords'])

    if division != "D1" and division in bundle["divisional_charts"]:
        dv = bundle["divisional_charts"][division]
        lines.append("")
        lines.append("%s Ascendant: %s" % (division, dv['ascendant']['sign']))
        lines.append("%s Planetary Positions:" % division)
        for name, p in dv["planets"].items():
            lines.append("  %s: %s House %s Dignity: %s" % (
                name, p['sign'], p['house'], p['dignity']))

    timing = bundle["timing"]
    md = timing.get("current_mahadasha")
    ad = timing.get("current_antardasha")
    pd = timing.get("current_pratyantardasha")
    lines.append("")
    lines.append("Current Vimshottari Mahadasha: %s (%s to %s)" % (
        md['lord'] if md else 'unknown',
        md['start'] if md else '?', md['end'] if md else '?'))
    if ad:
        lines.append("Current Antardasha: %s (%s to %s)" % (ad['lord'], ad['start'], ad['end']))
    if pd:
        lines.append("Current Pratyantardasha: %s (%s to %s)" % (pd['lord'], pd['start'], pd['end']))

    vargottama = bundle["derived"].get("vargottama", {})
    if vargottama:
        lines.append("")
        lines.append("Vargottama planets: %s" % vargottama)

    return "\n".join(lines)


@app.route("/api/chat", methods=["POST"])
def api_chat():
    from persistence import load_chart
    import chart_tools as _tools
    import chart_validation as _validation
    import context_pack as _context_pack
    import conversations as _conversations
    import book_grounding as _book_grounding
    import orchestrator as _orchestrator

    data       = request.json or {}
    question   = data.get("question", "")
    history    = data.get("history", [])
    chart_id   = data.get("chart_id", "")
    division   = (data.get("division") or "D1").upper()
    birth_info = data.get("birth_info") or {}
    reading    = data.get("reading", "")          # optional full-reading prose
    ctx_str    = data.get("chart_context", "")     # legacy fallback

    if division not in {"D1", "D2", "D3", "D7", "D9", "D10"}:
        division = "D1"

    if not question:
        return jsonify({"error": "No question"}), 400

    bundle = load_chart(chart_id) if chart_id else None
    if bundle and not birth_info.get("date"):
        bd = bundle.get("birth_data", {})
        birth_info = {"date": bd.get("date"), "time": bd.get("time"),
                      "lat": bd.get("lat"), "lon": bd.get("lon"),
                      "tz_offset": bd.get("tz_offset"), "place": bd.get("place")}

    # Conversation memory: conversation_id is ALWAYS re-derived here from the
    # resolved chart_id (a pure function, see conversations.derive_conversation_id)
    # rather than trusted from whatever the client sends — this guarantees the
    # id can never drift from the chart it's tied to and removes a whole class
    # of client bugs, while still satisfying "derived from chart_id" client-side
    # too (the frontend mirrors the same derivation for its own display use).
    conversation_id = _conversations.derive_conversation_id(bundle["chart_id"]) if bundle else None
    persisted_convo = _conversations.load_conversation(conversation_id) if conversation_id else None
    convo_history = persisted_convo["messages"] if persisted_convo else history

    # Authoritative chart context: prefer the persisted Chart Bundle for the
    # active chart_id (the exact chart that was calculated and saved) over
    # recomputing from whatever birth_info the client happens to send.
    chart_ctx = ""
    transit_ctx = ""
    facts_used = None
    pack = {"topics": [], "context": ""}
    if bundle:
        div_chart = _tools.get_divisional_chart(bundle, division) or bundle["divisional_charts"].get("D1")
        timing = _tools.get_current_dasha(bundle)
        pack = _context_pack.build_context_pack(question, bundle, division)
        facts_used = {
            "chart_id": bundle["chart_id"],
            "profile_name": bundle["profile_name"],
            "division": division,
            "ascendant": div_chart.get("ascendant") if div_chart else None,
            "current_mahadasha": timing.get("current_mahadasha"),
            "current_antardasha": timing.get("current_antardasha"),
            "current_pratyantardasha": timing.get("current_pratyantardasha"),
            "context_pack_topics": pack["topics"],
            "context_pack_divisions": pack.get("divisions_detected", []),
            "context_pack_facts": pack["context"],
        }
        chart_ctx = _build_grounded_context(bundle, division)

    book_pack = {"passages": [], "context": ""}
    try:
        book_pack = _book_grounding.build_book_context(get_kb(), question, pack["topics"], bundle, division)
    except Exception as e:
        print("   chat book-grounding failed: %s" % e)
    if facts_used is not None:
        facts_used["book_sources"] = book_pack["passages"]
    if birth_info.get("date") and birth_info.get("time"):
        if not chart_ctx:
            try:
                chart_ctx = _chart_context_from_birth(birth_info)
            except Exception as e:
                chart_ctx = ""   # fall through to legacy context below
                print("   chat chart recompute failed: %s" % e)
        # Live gochara (transits): current planetary positions relative to the
        # natal chart, plus positions for any date the user names in the
        # question. This is what lets the agent answer timing questions.
        try:
            transit_ctx = _transit_context_from_birth(birth_info, question)
        except Exception as e:
            transit_ctx = ""
            print("   chat transit compute failed: %s" % e)
    if not chart_ctx:
        chart_ctx = ctx_str   # legacy path if no birth_info supplied

    if not chart_ctx:
        return jsonify({
            "answer": "Please calculate or select a birth chart before asking a chart-specific question.",
            "chart_facts_used": None,
        })

    key, _ = _get_api_key()
    if not key:
        return jsonify({"error": "No API key. Create vedic_astro/.env with DEEPSEEK_API_KEY=sk-..."}), 503

    today = datetime.now()
    system_parts = [
        "You are Jyoti - a deeply knowledgeable and compassionate Vedic astrologer "
        "trained in Parasara, Jaimini, K.N. Rao, Deepanshu Giri, and Narasimha Rao traditions.",
        "TODAY'S DATE is %s. Use this as 'now' for any "
        "question about the present, the future, age, or timing. Never say you don't "
        "know the current date." % today.strftime('%A, %d %B %Y'),
        "The person's COMPLETE, AUTHORITATIVE chart is given below. It is computed "
        "directly from Swiss Ephemeris for this exact birth data. Treat it as ground "
        "truth. When answering, cite the specific planets, signs, houses, nakshatras, "
        "and dasha periods AS GIVEN - never guess or invent a placement. If a detail "
        "isn't in the data below, say so rather than assuming it.",
        "CRITICAL - House lordships: the chart data includes an explicit 'House Lords' "
        "table for each chart. NEVER derive lordships yourself from memory. When the "
        "user asks about 'the Nth lord' or which house a planet rules, read it "
        "verbatim from the D-1 'House Lords' table. Functional lordships come from the "
        "D-1 lagna only and stay fixed across all divisional charts (D-9, D-10, etc.). "
        "For example, do not call a planet 'the 5th lord' unless the D-1 table says so.",
        "Be warm, insightful, and non-fatalistic.",
        "Address the person directly as 'you'. Do NOT narrate your reasoning "
        "process, restate the question, or write phrases like 'We need to "
        "analyze' - give the reading itself, directly and gracefully.",
        "\n## AUTHORITATIVE CHART DATA\n" + chart_ctx,
    ]
    if transit_ctx:
        system_parts.append(
            "TIMING METHOD - For any question about WHEN something happens, or "
            "about a specific date/year, reason from BOTH (a) the Vimshottari "
            "Dasha timeline in the chart data above, and (b) the live TRANSITS "
            "(gochara) below, which are computed from Swiss Ephemeris for the "
            "current date and for any date named in the question. Combine dasha "
            "(the active planetary period) with transit (where the planets "
            "actually are) - that is the classical way to time an event. Cite "
            "the specific transiting planets, their houses from the Moon and "
            "Lagna, Sade Sati status, and Jupiter/Saturn positions AS GIVEN.")
        system_parts.append(
            "\n## LIVE TRANSITS / GOCHARA (computed - treat as ground truth)\n"
            + transit_ctx)
    if pack["context"]:
        system_parts.append(
            "\n## TOPIC-SPECIFIC FACTS (detected from the question - read these "
            "verbatim, do not recompute or contradict them)\n" + pack["context"]
        )
    if book_pack["context"]:
        system_parts.append(
            "CLASSICAL SOURCES - the passages below are real excerpts retrieved "
            "from the ingested library of classical Vedic astrology texts. If you "
            "reference or quote one, cite it EXACTLY as shown in its [Book Title, "
            "page N] tag. Never invent a book title, author, or page number that "
            "is not shown below. If nothing below is relevant to the question, "
            "do not fabricate a citation - just don't cite one.")
        system_parts.append(
            "\n## RETRIEVED CLASSICAL SOURCE PASSAGES\n" + book_pack["context"])
    if reading:
        # Secondary context, clearly subordinate to the chart data above.
        system_parts.append(
            "\n## Prior Full Reading (narrative context - the chart data above "
            "always takes precedence if anything conflicts)\n" + reading[:4000]
        )
    system = "\n\n".join(system_parts)

    try:
        client = get_client()
        messages = convo_history[-10:] + [{"role": "user", "content": question}]
        chat_fn = lambda sys_prompt: _chat_with_client(client, sys_prompt, messages)  # noqa: E731

        # Parashari Agent (draft) -> Critic/Validator Agent (verify, and
        # bounded-retry-correct if the draft contradicts the chart data).
        draft = chat_fn(system)
        result = _orchestrator.run_critic_and_maybe_correct(chat_fn, system, draft, bundle, division)
        answer = result["answer"]
        validation_result = result["validation"]
        if validation_result and not validation_result["all_valid"]:
            print("   ⚠️  chat_validation caught %d unsupported claim(s) (corrected=%s): %s"
                  % (len(validation_result["issues"]), result["corrected"], validation_result["issues"]))
        if conversation_id:
            _conversations.append_turn(conversation_id, bundle["chart_id"], question, answer)

        return jsonify({
            "answer": answer,
            "chart_facts_used": facts_used,
            "validation": validation_result,
            "corrected": result["corrected"],
            "agents_consulted": _orchestrator.agents_consulted(
                bundle, division, transit_ctx, book_pack["context"], pack.get("divisions_detected", [])),
            "conversation_id": conversation_id,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/charts", methods=["GET"])
def api_charts_list():
    from persistence import list_charts
    return jsonify({"charts": list_charts()})


@app.route("/api/charts/<chart_id>", methods=["GET"])
def api_charts_get(chart_id):
    from persistence import load_chart
    bundle = load_chart(chart_id)
    if bundle is None:
        return jsonify({"error": "chart not found"}), 404
    return jsonify(bundle)


@app.route("/api/charts/<chart_id>/summary", methods=["GET"])
def api_charts_summary(chart_id):
    from persistence import load_chart
    import chart_tools as _tools
    bundle = load_chart(chart_id)
    if bundle is None:
        return jsonify({"error": "chart not found"}), 404
    return jsonify(_tools.get_chart_summary(bundle))


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

#!/usr/bin/env python3
"""
Vedic Astrology Brain — Interactive CLI
=========================================
Complete Vedic astrology chatbot with deep research agent architecture.
Trained on 30+ classical Vedic astrology books.

Usage:
  python3 cli.py                    # Interactive mode
  python3 cli.py --ingest           # Rebuild knowledge base from books
  python3 cli.py --demo             # Demo with a sample chart
"""
from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

BANNER = r"""
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║     ✦  J Y O T I S H  ✦   V E D I C   A S T R O L O G Y       ║
║                                                                  ║
║   🪐  Complete Chart Analysis  ·  AI Deep Research Agent        ║
║   Full Shodasavarga (D-1 to D-60, 16 charts) · Dasha · Nakshatra ║
║                                                                  ║
║   Career · Wealth · Marriage · Soul Purpose · Life Lessons       ║
║   Trained on 30+ Classical Vedic Astrology Books                 ║
╚══════════════════════════════════════════════════════════════════╝
"""

HELP = """
COMMANDS (after chart is loaded):
  /charts      — Show all 16 divisional charts (Shodasavarga)
  /d9          — Show D-9 (Navamsa) chart
  /d10         — Show D-10 (Dasamsa/Career) chart
  /d30         — Show D-30 (Trimsamsa/Character-Misfortune) chart
  /d60         — Show D-60 (Shashtiamsa/Overall Life Results) chart
  /dasha       — Show full Vimshottari Dasha timeline
  /career      — Career & profession analysis
  /wealth      — Wealth & financial potential
  /marriage    — Marriage & relationship analysis
  /soul        — Soul purpose & dharma
  /lessons     — Life lessons & karmic themes
  /reading     — Full synthesized reading
  /new         — Start a new chart
  /quit        — Exit

Or just type any question about your chart!
"""

def _wrap(text: str, width: int = 76) -> str:
    result = []
    for para in text.split("\n"):
        if not para.strip():
            result.append("")
        elif para.startswith(("  ", "##", "**", "-", "*", ">", "|", "✦", "🌟", "💼", "💰", "📖")):
            result.append(para)
        else:
            result.extend(textwrap.wrap(para, width=width))
    return "\n".join(result)


def run():
    print(BANNER)

    # ── CLI args
    if "--ingest" in sys.argv:
        from knowledge.ingest import KnowledgeBase
        print("🔄 Rebuilding knowledge base from books...")
        kb = KnowledgeBase()
        kb.load_or_build(force_rebuild=True)
        print("✅ Knowledge base rebuilt. Run cli.py normally to use it.")
        return

    if "--demo" in sys.argv:
        # Demo mode: famous chart (Mahatma Gandhi)
        demo_date  = "1869-10-02"
        demo_time  = "07:11"
        demo_place = "Porbandar, India"
        print(f"🎭 Demo Mode: Mahatma Gandhi's chart")
        print(f"   Born: {demo_date} at {demo_time} in {demo_place}")
    else:
        demo_date = demo_time = demo_place = None

    # ── API key
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("❌  ANTHROPIC_API_KEY not set.")
        print("    export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    # ── Init chatbot
    print("⚡ Initializing Jyoti — Vedic Astrology AI...")
    from chatbot import VedicAstrologyChatbot
    bot = VedicAstrologyChatbot(api_key=api_key, verbose=True)
    print("   Jyoti is ready. Namaste! 🙏\n")

    # ── Collect / use demo birth data
    if demo_date:
        birth_data = {"date": demo_date, "time": demo_time, "place": demo_place}
    else:
        birth_data = bot.collect_birth_data()

    if not birth_data:
        print("❌ No birth data provided.")
        return

    # ── Calculate chart
    chart_data = bot.calculate_chart(
        birth_data["date"],
        birth_data["time"],
        birth_data["place"],
    )
    if not chart_data:
        print("❌ Chart calculation failed.")
        return

    # ── Display charts
    bot.display_charts(chart_data, show_all=False)

    # ── Run full prediction
    print("\n" + "═"*64)
    print(" RUNNING DEEP MULTI-AGENT VEDIC ANALYSIS")
    print(" (This uses 6 AI specialist agents + book knowledge)")
    print("═"*64)

    reading = bot.generate_reading(chart_data)
    bot.print_reading(reading)

    # ── Interactive follow-up conversation
    print("\n" + "═"*64)
    print(" ASK JYOTI ANYTHING ABOUT YOUR CHART")
    print(" Type /help for commands or just ask a question")
    print("═"*64)

    while True:
        try:
            user_input = input("\n🙏 You → ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nNamaste! May the stars guide you. 🙏")
            break

        if not user_input:
            continue

        cmd = user_input.lower().strip()

        if cmd in ("/quit", "/exit", "/q"):
            print("\nNamaste! May the stars guide you. 🙏")
            break
        elif cmd == "/help":
            print(HELP)
        elif cmd == "/charts":
            bot.display_charts(chart_data, show_all=True)
        elif cmd == "/d9":
            from chart.formatter import format_south_indian, format_planet_table
            if "D9" in chart_data["divisional"]:
                print(format_south_indian(chart_data["divisional"]["D9"]))
                print(format_planet_table(chart_data["divisional"]["D9"]))
        elif cmd == "/d10":
            from chart.formatter import format_south_indian, format_planet_table
            if "D10" in chart_data["divisional"]:
                print(format_south_indian(chart_data["divisional"]["D10"]))
                print(format_planet_table(chart_data["divisional"]["D10"]))
        elif cmd == "/d30":
            from chart.formatter import format_south_indian, format_planet_table
            if "D30" in chart_data["divisional"]:
                print(format_south_indian(chart_data["divisional"]["D30"]))
                print(format_planet_table(chart_data["divisional"]["D30"]))
        elif cmd == "/d60":
            from chart.formatter import format_south_indian, format_planet_table
            if "D60" in chart_data["divisional"]:
                print(format_south_indian(chart_data["divisional"]["D60"]))
                print(format_planet_table(chart_data["divisional"]["D60"]))
        elif cmd == "/dasha":
            print("\n── FULL VIMSHOTTARI DASHA TIMELINE ─────────────")
            for d in chart_data["dashas"]:
                print(f"  {d['lord']:12s} {d['start']} → {d['end']}  ({d['years']} years)")
        elif cmd in ("/career", "/wealth", "/marriage", "/soul", "/lessons", "/reading"):
            key_map = {
                "/career": "career", "/wealth": "wealth",
                "/marriage": "relationships", "/soul": "soul_purpose",
                "/lessons": "life_lessons", "/reading": "synthesis",
            }
            key = key_map[cmd]
            if reading and key in reading:
                print("\n" + "═"*64)
                print(_wrap(reading[key]))
        elif cmd == "/new":
            print("\n── New Chart ──────────────────────────────────")
            new_data = bot.collect_birth_data()
            if new_data:
                chart_data = bot.calculate_chart(
                    new_data["date"], new_data["time"], new_data["place"]
                )
                if chart_data:
                    bot.display_charts(chart_data)
                    reading = bot.generate_reading(chart_data)
                    bot.print_reading(reading)
        elif cmd.startswith("/"):
            print(f"Unknown command: {user_input}. Type /help.")
        else:
            # Follow-up question
            print("\n🪐 Jyoti →")
            answer = bot.answer_question(user_input)
            print(_wrap(answer))


if __name__ == "__main__":
    run()

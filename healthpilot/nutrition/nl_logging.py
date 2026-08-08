"""Natural-language food logging pipeline:
    text -> candidate foods (AI proposes) -> serving-size resolution ->
    nutrition lookup -> structured meal -> deterministic totals (all code).

The LLM's only job is turning "two rotis and a bowl of dal" into structured
guesses like [{"query": "roti", "quantity": 2}, {"query": "dal", "quantity": 1}].
It never sees or invents a nutrient value — food_service.search_food and
meal_service.log_food do that lookup and arithmetic deterministically. If no
AI provider is configured, a simple heuristic splitter is used instead so
logging still works offline.
"""
from __future__ import annotations

from app import config
from nutrition.food_service import default_serving, search_food
from nutrition.meal_service import log_food

_PARSE_SYSTEM_PROMPT = """You extract food items from a natural-language meal description.
Return ONLY a JSON object: {"candidates": [{"query": string, "quantity": number}]}.
- "query" is a short, generic food search term (e.g. "roti", "grilled chicken breast", "banana") — no brand names, no adjectives that aren't part of the food identity.
- "quantity" is how many of that food's typical serving the user described (e.g. "two rotis" -> quantity 2; "a bowl of dal" -> quantity 1; if unclear, use 1).
- One candidate per distinct food mentioned. Do not invent foods that weren't mentioned."""


def _heuristic_parse(text: str) -> list[dict]:
    """No-AI fallback: split on common separators, quantity always 1. Cruder
    than the LLM path but keeps logging functional with no API key set."""
    import re

    parts = re.split(r",|\band\b|\+", text, flags=re.IGNORECASE)
    return [{"query": p.strip(), "quantity": 1} for p in parts if p.strip()]


def parse_food_text(text: str) -> list[dict]:
    if not text or not text.strip():
        return []

    if config.ai_configured():
        try:
            from agents.llm_client import chat_json

            result = chat_json(_PARSE_SYSTEM_PROMPT, text, max_tokens=500)
            candidates = result.get("candidates", []) if isinstance(result, dict) else []
            cleaned = []
            for c in candidates:
                query = str(c.get("query", "")).strip()
                if not query:
                    continue
                try:
                    quantity = float(c.get("quantity", 1))
                except (TypeError, ValueError):
                    quantity = 1
                cleaned.append({"query": query, "quantity": quantity if quantity > 0 else 1})
            if cleaned:
                return cleaned
        except Exception:
            pass  # fall through to heuristic — logging must not hard-fail because the AI call did

    return _heuristic_parse(text)


def log_food_from_text(profile_id: str, meal_type: str, text: str, meal_date: str | None = None) -> dict:
    """Returns {"logged": [...], "unresolved": [...]}. Unresolved candidates
    (no local/provider match found) are surfaced for manual resolution —
    never silently dropped or guessed."""
    candidates = parse_food_text(text)
    logged, unresolved = [], []

    for candidate in candidates:
        matches = search_food(candidate["query"], limit=1)
        if not matches:
            unresolved.append(candidate)
            continue

        food = matches[0]
        serving = default_serving(food)
        if serving is None:
            unresolved.append({**candidate, "reason": "no serving size on file"})
            continue

        meal = log_food(
            profile_id, meal_type, food["id"], serving["id"], candidate["quantity"],
            meal_date=meal_date, source="nl",
        )
        logged.append({
            "candidate": candidate,
            "food_id": food["id"],
            "food_name": food["name"],
            "serving": serving["description"],
            "quantity": candidate["quantity"],
            "meal_id": meal["id"],
            "nutrition": meal["nutrition"],
        })

    return {"logged": logged, "unresolved": unresolved}

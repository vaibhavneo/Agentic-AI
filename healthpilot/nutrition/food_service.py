"""Food lookup + manual entry. search_food is the one deterministic entry
point everything else (NL logging, meal building, the future Food Logging
Agent) goes through — it never fabricates a nutrient value: local seed/
manually-entered data or a live USDA lookup only.
"""
from __future__ import annotations

from database.db import get_connection
from nutrition.providers.base import NutritionProvider
from nutrition.providers.usda import USDAProvider

NUTRIENT_FIELDS = (
    "calories_kcal", "protein_g", "carbs_g", "fiber_g", "total_fat_g",
    "saturated_fat_g", "sodium_mg", "potassium_mg", "calcium_mg",
    "magnesium_mg", "added_sugar_g",
)


class FoodValidationError(ValueError):
    pass


def _default_provider() -> NutritionProvider:
    return USDAProvider()


def _food_with_servings(row) -> dict:
    conn = get_connection()
    servings = conn.execute(
        "SELECT * FROM servings WHERE food_id = ? ORDER BY is_default DESC, id", (row["id"],)
    ).fetchall()
    d = dict(row)
    d["servings"] = [dict(s) for s in servings]
    return d


def get_food_by_external_id(external_id: str, source: str = "manual") -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM foods WHERE source = ? AND external_id = ?", (source, external_id)
    ).fetchone()
    return _food_with_servings(row) if row else None


def get_food(food_id: int) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM foods WHERE id = ?", (food_id,)).fetchone()
    return _food_with_servings(row) if row else None


def _search_local(query: str, limit: int) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM foods WHERE name LIKE ? ORDER BY name LIMIT ?",
        (f"%{query}%", limit),
    ).fetchall()
    return [_food_with_servings(r) for r in rows]


def _upsert_provider_food(provider: NutritionProvider, pf) -> dict:
    conn = get_connection()
    existing = conn.execute(
        "SELECT id FROM foods WHERE source = ? AND external_id = ?", (provider.name, pf.external_id)
    ).fetchone()
    if existing:
        return get_food(existing["id"])

    cur = conn.execute(
        """INSERT INTO foods (source, external_id, name, brand, calories_kcal, protein_g, carbs_g,
               fiber_g, total_fat_g, saturated_fat_g, sodium_mg, potassium_mg, calcium_mg,
               magnesium_mg, added_sugar_g)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (provider.name, pf.external_id, pf.name, pf.brand, pf.calories_kcal, pf.protein_g,
         pf.carbs_g, pf.fiber_g, pf.total_fat_g, pf.saturated_fat_g, pf.sodium_mg,
         pf.potassium_mg, pf.calcium_mg, pf.magnesium_mg, pf.added_sugar_g),
    )
    food_id = cur.lastrowid
    for s in pf.servings:
        conn.execute(
            "INSERT INTO servings (food_id, description, grams, is_default) VALUES (?, ?, ?, ?)",
            (food_id, s.description, s.grams, int(s.is_default)),
        )
    conn.commit()
    return get_food(food_id)


def search_food(query: str, limit: int = 10, use_provider: bool = True) -> list[dict]:
    """Local seed/manual/previously-cached foods first; if a live provider is
    configured and local results are thin, supplement with a provider search
    and cache any new hits locally for next time."""
    query = (query or "").strip()
    if not query:
        return []

    local = _search_local(query, limit)
    if not use_provider or len(local) >= limit:
        return local

    provider = _default_provider()
    if not provider.is_configured():
        return local

    try:
        provider_results = provider.search(query, limit=limit - len(local))
    except Exception:
        return local  # network/auth failure — degrade to local results, don't crash logging

    seen_external_ids = {f["external_id"] for f in local if f.get("source") == provider.name}
    merged = list(local)
    for pf in provider_results:
        if pf.external_id in seen_external_ids:
            continue
        merged.append(_upsert_provider_food(provider, pf))
    return merged


def create_manual_food(data: dict) -> dict:
    """Manual label entry fallback — the user types in the numbers straight
    off a nutrition label. All macro fields must be non-negative numbers."""
    if not data.get("name") or not str(data["name"]).strip():
        raise FoodValidationError("name is required")

    values = {}
    for field in NUTRIENT_FIELDS:
        raw = data.get(field, 0)
        try:
            v = float(raw)
        except (TypeError, ValueError):
            raise FoodValidationError(f"{field} must be a number")
        if v < 0:
            raise FoodValidationError(f"{field} cannot be negative")
        values[field] = v

    if values["calories_kcal"] == 0:
        raise FoodValidationError("calories_kcal is required and must be > 0")

    servings = data.get("servings") or [{"description": "100g", "grams": 100, "is_default": True}]
    for s in servings:
        if not s.get("grams") or float(s["grams"]) <= 0:
            raise FoodValidationError("every serving needs grams > 0")

    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO foods (source, external_id, name, brand, calories_kcal, protein_g, carbs_g,
               fiber_g, total_fat_g, saturated_fat_g, sodium_mg, potassium_mg, calcium_mg,
               magnesium_mg, added_sugar_g)
           VALUES ('manual', NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            str(data["name"]).strip(), data.get("brand"),
            values["calories_kcal"], values["protein_g"], values["carbs_g"], values["fiber_g"],
            values["total_fat_g"], values["saturated_fat_g"], values["sodium_mg"],
            values["potassium_mg"], values["calcium_mg"], values["magnesium_mg"], values["added_sugar_g"],
        ),
    )
    food_id = cur.lastrowid
    for s in servings:
        conn.execute(
            "INSERT INTO servings (food_id, description, grams, is_default) VALUES (?, ?, ?, ?)",
            (food_id, s.get("description", "serving"), float(s["grams"]), int(bool(s.get("is_default")))),
        )
    conn.commit()
    return get_food(food_id)


def resolve_serving_grams(food: dict, serving_id: int | None, quantity: float) -> float:
    """quantity is 'number of servings' when serving_id is given, else grams directly."""
    if serving_id is None:
        if quantity <= 0:
            raise FoodValidationError("grams must be > 0")
        return quantity
    serving = next((s for s in food["servings"] if s["id"] == serving_id), None)
    if serving is None:
        raise FoodValidationError(f"no such serving {serving_id} for food {food['id']}")
    if quantity <= 0:
        raise FoodValidationError("quantity must be > 0")
    return serving["grams"] * quantity


def default_serving(food: dict) -> dict | None:
    if not food["servings"]:
        return None
    return next((s for s in food["servings"] if s["is_default"]), food["servings"][0])

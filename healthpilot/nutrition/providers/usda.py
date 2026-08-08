"""USDA FoodData Central provider. Optional — only activates when
USDA_FDC_API_KEY is set (app.config.USDA_FDC_API_KEY). Without it, the app
falls back to the local manual/seed food database (nutrition/food_service.py).
"""
from __future__ import annotations

import requests

from app import config
from nutrition.providers.base import NutritionProvider, ProviderFood, ProviderServing

SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"

# USDA nutrient names vary slightly by dataset (Foundation / SR Legacy /
# Branded) but are consistent enough to match by name substring rather than
# nutrientNumber, which is more fragile across datasets.
_NUTRIENT_NAME_MAP = {
    "energy": "calories_kcal",
    "protein": "protein_g",
    "carbohydrate, by difference": "carbs_g",
    "fiber, total dietary": "fiber_g",
    "total lipid (fat)": "total_fat_g",
    "fatty acids, total saturated": "saturated_fat_g",
    "sodium, na": "sodium_mg",
    "potassium, k": "potassium_mg",
    "calcium, ca": "calcium_mg",
    "magnesium, mg": "magnesium_mg",
    "sugars, added": "added_sugar_g",
}


class USDAProvider(NutritionProvider):
    name = "usda"

    def is_configured(self) -> bool:
        return bool(config.USDA_FDC_API_KEY)

    def search(self, query: str, limit: int = 10) -> list[ProviderFood]:
        if not self.is_configured():
            return []
        resp = requests.get(
            SEARCH_URL,
            params={
                "api_key": config.USDA_FDC_API_KEY,
                "query": query,
                "pageSize": limit,
                "dataType": ["Foundation", "SR Legacy"],
            },
            timeout=10,
        )
        resp.raise_for_status()
        results = []
        for item in resp.json().get("foods", []):
            food = self._parse_food(item)
            if food is not None:
                results.append(food)
        return results

    def _parse_food(self, item: dict) -> ProviderFood | None:
        fields = {}
        for nutrient in item.get("foodNutrients", []):
            key = (nutrient.get("nutrientName") or "").strip().lower()
            mapped = _NUTRIENT_NAME_MAP.get(key)
            if mapped:
                fields[mapped] = nutrient.get("value", 0) or 0

        if "calories_kcal" not in fields:
            return None  # no usable energy value — don't fabricate one

        serving_grams = item.get("servingSize") if item.get("servingSizeUnit") == "g" else None
        servings = [ProviderServing(description="100g", grams=100, is_default=serving_grams is None)]
        if serving_grams:
            servings.append(
                ProviderServing(
                    description=f"1 serving ({serving_grams}g)", grams=serving_grams, is_default=True
                )
            )

        return ProviderFood(
            external_id=str(item.get("fdcId")),
            name=item.get("description", "").title(),
            brand=item.get("brandOwner"),
            servings=servings,
            **fields,
        )

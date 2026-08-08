"""Nutrition provider interface. Any structured nutrition data source (USDA
FoodData Central today; a branded-food database or a barcode scanner API
tomorrow) implements this so nutrition/food_service.py never has to know
which source a result came from.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ProviderServing:
    description: str
    grams: float
    is_default: bool = False


@dataclass
class ProviderFood:
    external_id: str
    name: str
    calories_kcal: float
    protein_g: float = 0
    carbs_g: float = 0
    fiber_g: float = 0
    total_fat_g: float = 0
    saturated_fat_g: float = 0
    sodium_mg: float = 0
    potassium_mg: float = 0
    calcium_mg: float = 0
    magnesium_mg: float = 0
    added_sugar_g: float = 0
    brand: str | None = None
    servings: list[ProviderServing] = field(default_factory=list)


class NutritionProvider(ABC):
    name: str = "base"

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[ProviderFood]:
        """Returns candidate foods for a free-text query. Never raises on
        'no results' — returns an empty list. May raise on network/auth
        failure; callers should catch and fall back to local search."""

    @abstractmethod
    def is_configured(self) -> bool:
        """Whether this provider has what it needs (e.g. an API key) to run."""

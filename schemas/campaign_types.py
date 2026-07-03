from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, Field


class SpotlightsVars(BaseModel):
    name: str
    description: str
    # Real campaign payloads send this as "type"; the field is named
    # spotlight_type internally to avoid shadowing Python builtins/keywords.
    spotlight_type: str | None = Field(
        default=None, validation_alias=AliasChoices("type", "spotlight_type")
    )


class MenuItemsVars(BaseModel):
    name: str
    description: str
    price: str | None = None
    item_category: list[str] | str = []
    item_menu: str | None = None


class DealsVars(BaseModel):
    name: str
    description: str | None = None
    deal_type: str
    deal_type_vars: dict[str, Any]
    platforms: list[str] = []
    start_date: str | None = None
    end_date: str | None = None
    promo_code: str | None = None


CAMPAIGN_REGISTRY: dict[str, type[BaseModel]] = {
    "Spotlights": SpotlightsVars,
    "Menu Items": MenuItemsVars,
    "Deals": DealsVars,
}

ALLERGEN_SET: frozenset[str] = frozenset(
    {
        "milk",
        "eggs",
        "wheat",
        "sesame",
        "shellfish",
        "tree nuts",
        "peanuts",
        "soy",
        "fish",
    }
)

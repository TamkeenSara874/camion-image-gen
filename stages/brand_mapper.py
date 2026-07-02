from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from schemas.internal import RestaurantBrand

BRANDS_PATH = str(Path(__file__).parent.parent / "config" / "restaurant_brands.json")


@lru_cache
def _load_brands() -> dict[str, dict]:
    with open(BRANDS_PATH, encoding="utf-8") as f:
        return json.load(f)


def map_brand(restaurant_id: int) -> RestaurantBrand:
    brands = _load_brands()
    data = brands.get(str(restaurant_id))
    if data is None:
        raise ValueError(f"restaurantId {restaurant_id} not found in restaurant brand map")
    return RestaurantBrand(
        restaurant_id=restaurant_id,
        restaurant_name=data["restaurant_name"],
        cuisine_type=data["cuisine_type"],
        brand_theme=data["brand_theme"],
        visual_style=data["visual_style"],
        website_url=data["website_url"],
        brand_colors=data["brand_colors"],
        currency_symbol=data.get("currency_symbol", "$"),
    )

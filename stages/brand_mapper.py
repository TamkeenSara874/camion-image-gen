from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from schemas.internal import RestaurantBrand

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent
BRANDS_PATH = str(_REPO_ROOT / "config" / "restaurant_brands.json")


def _resolve_logo_path(logo_path: str | None, restaurant_id: int) -> str | None:
    """logo_path in restaurant_brands.json is relative to the repo root. A missing
    or unreadable logo file must never crash image generation -- it degrades to
    the compositor's text-only fallback (see stages/text_compositor.py) rather
    than blocking the whole request over a cosmetic branding element."""
    if not logo_path:
        return None
    resolved = _REPO_ROOT / logo_path
    if not resolved.is_file():
        logger.warning(
            "logo_missing", extra={"restaurant_id": restaurant_id, "logo_path": logo_path}
        )
        return None
    return str(resolved)


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
        logo_path=_resolve_logo_path(data.get("logo_path"), restaurant_id),
    )

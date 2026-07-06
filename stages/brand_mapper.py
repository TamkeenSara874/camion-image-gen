from __future__ import annotations

import asyncio
import json
import logging
import time
from functools import lru_cache
from pathlib import Path

from schemas.internal import RestaurantBrand
from services.logo_fetcher import download_logo, fetch_logo_url

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent
BRANDS_PATH = str(_REPO_ROOT / "config" / "restaurant_brands.json")

_LOGO_FETCH_COOLDOWN_S = 300.0
_last_fetch_attempt: dict[int, float] = {}


def _resolve_logo_path(logo_path: str | None, restaurant_id: int) -> str | None:
    """logo_path in restaurant_brands.json is relative to the repo root. If the
    config doesn't declare one at all, fall back to the conventional
    config/logos/{id}.png location -- that's where ensure_logo() saves a
    logo it auto-fetched for a restaurant on a previous request, so this is
    how later requests find it without needing the JSON updated. A missing
    or unreadable file must never crash image generation -- it degrades to
    the compositor's text-only fallback (see stages/text_compositor.py) rather
    than blocking the whole request over a cosmetic branding element."""
    if logo_path:
        resolved = _REPO_ROOT / logo_path
        if not resolved.is_file():
            logger.warning(
                "logo_missing", extra={"restaurant_id": restaurant_id, "logo_path": logo_path}
            )
            return None
        return str(resolved)

    conventional = _REPO_ROOT / "config" / "logos" / f"{restaurant_id}.png"
    return str(conventional) if conventional.is_file() else None


async def ensure_logo(brand: RestaurantBrand) -> RestaurantBrand:
    """Lazily scrapes and caches a restaurant's real logo the first time it's
    needed, instead of requiring every restaurant's logo to be pre-fetched and
    committed ahead of time. Mutates and returns the same RestaurantBrand
    instance in place, which is also the object referenced by CampaignContext
    -- callers just need to await this before Stage 6 reads ctx.restaurant.logo_path.

    Designed to run concurrently with Stage 4 (prompt) + Stage 5 (image
    synthesis) rather than blocking the pipeline: see pipeline/image_pipeline.py,
    where this is kicked off right after Stage 2 via asyncio.create_task() and
    only awaited immediately before Stage 6 needs the result. Those two stages
    alone typically take 15-90s, versus ~1-2s for a logo fetch, so in the
    common case this adds zero wall-clock latency.

    Never raises -- a failed fetch just leaves logo_path=None, which the
    compositor already handles by degrading to a typed-name badge. A cooldown
    prevents re-attempting on every single request for a restaurant whose
    site is down or has no discoverable logo.
    """
    if brand.logo_path is not None or not brand.website_url:
        return brand

    now = time.monotonic()
    last_attempt = _last_fetch_attempt.get(brand.restaurant_id)
    if last_attempt is not None and (now - last_attempt) < _LOGO_FETCH_COOLDOWN_S:
        return brand
    _last_fetch_attempt[brand.restaurant_id] = now

    try:
        logo_url, source = await asyncio.to_thread(fetch_logo_url, brand.website_url)
        path = await asyncio.to_thread(download_logo, logo_url, brand.restaurant_id)
        brand.logo_path = str(path)
        logger.info(
            "logo_auto_fetched",
            extra={"restaurant_id": brand.restaurant_id, "source": source, "logo_path": brand.logo_path},
        )
    except Exception as exc:
        logger.warning(
            "logo_auto_fetch_failed", extra={"restaurant_id": brand.restaurant_id, "error": str(exc)}
        )
    return brand


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

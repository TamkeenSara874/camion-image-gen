from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from schemas.campaign_types import (
    ALLERGEN_SET,
    CAMPAIGN_REGISTRY,
    DealsVars,
    MenuItemsVars,
    SpotlightsVars,
)
from schemas.internal import CampaignContext, RestaurantBrand
from schemas.request import CampaignPayload

_INJECTION_PATTERNS: tuple[str, ...] = (
    r"ignore\s+(previous|above|all)\s+instructions?",
    r"forget\s+(everything|your\s+instructions?)",
    r"you\s+are\s+now",
    r"act\s+as",
    r"jailbreak",
    r"<[^>]+>",
)

_ORIENTATION_SIZE: dict[str, tuple[str, str]] = {
    "Landscape": ("1536x1024", "16:9"),
    "Portrait": ("1024x1536", "9:16"),
    "Square": ("1024x1024", "1:1"),
}

_CHANNEL_SIZE: dict[str, tuple[str, str]] = {
    "Email": ("1536x1024", "16:9"),
    "SMS": ("1024x1024", "1:1"),
    "Social": ("1024x1024", "1:1"),
    "Website": ("1536x1024", "16:9"),
}


def sanitize_user_text(text: str) -> str:
    for pattern in _INJECTION_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    return text.replace("{", "{{").replace("}", "}}")


def parse(payload: CampaignPayload, brand: RestaurantBrand) -> CampaignContext:
    if payload.orientation:
        image_size, aspect_ratio = _ORIENTATION_SIZE[payload.orientation]
    else:
        channel_key = (payload.channels or ["Email"])[0]
        image_size, aspect_ratio = _CHANNEL_SIZE.get(channel_key, ("1536x1024", "16:9"))

    guest_context_tags = [
        tag for tag in payload.campaign_guest_tags if tag.lower() not in ALLERGEN_SET
    ]

    schema_cls = CAMPAIGN_REGISTRY[payload.campaign_type]
    vars_obj = schema_cls.model_validate(payload.campaign_vars)
    main_offer, price, extra_vars = _extract_fields(vars_obj, brand)

    channel = (payload.channels or ["Email"])[0]
    custom_prompt = sanitize_user_text(payload.custom_prompt) if payload.custom_prompt else None

    return CampaignContext(
        restaurant=brand,
        campaign_type=payload.campaign_type,
        campaign_goal=sanitize_user_text(payload.campaign_goals),
        main_title=sanitize_user_text(vars_obj.name),  # type: ignore[attr-defined]
        main_offer=main_offer,
        price=price,
        cta=payload.cta,
        cta_text="Order Now" if payload.cta else None,
        audience=payload.campaign_audiences,
        guest_context_tags=guest_context_tags,
        channel=channel,
        brand_voice=sanitize_user_text(payload.campaign_brand_voices),
        image_size=image_size,
        aspect_ratio=aspect_ratio,
        custom_prompt=custom_prompt,
        extra_vars=extra_vars,
    )


def _extract_fields(
    vars_obj: BaseModel, brand: RestaurantBrand
) -> tuple[str, str | None, dict[str, Any]]:
    if isinstance(vars_obj, SpotlightsVars):
        return (
            sanitize_user_text(vars_obj.description),
            None,
            {"spotlight_type": vars_obj.spotlight_type},
        )
    if isinstance(vars_obj, MenuItemsVars):
        price = f"{brand.currency_symbol}{vars_obj.price}" if vars_obj.price else None
        return (
            sanitize_user_text(vars_obj.description),
            price,
            {"item_category": vars_obj.item_category},
        )
    if isinstance(vars_obj, DealsVars):
        return (
            sanitize_user_text(vars_obj.description or ""),
            None,
            {
                "deal_type": vars_obj.deal_type,
                "deal_type_vars": vars_obj.deal_type_vars,
                "promo_code": vars_obj.promo_code,
                "platforms": vars_obj.platforms,
            },
        )
    return "", None, {}

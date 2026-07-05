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

# campaign_goals -> visual composition directive, per the task spec's explicit
# mapping (e.g. "Increase Online Orders -> food should look orderable and
# action-driven"). Fed to the LLM as an explicit instruction instead of relying
# on it to infer the right composition from the raw goal label alone.
_GOAL_DIRECTIVES: dict[str, str] = {
    "Increase Online Orders": (
        "Make the food look immediately orderable and craveable: an action-driven, "
        "takeout/delivery-ready shot that sells the food itself."
    ),
    "Increase Item Sales": (
        "Focus tightly on the item as the unmistakable hero subject: a clean, "
        "high-detail product shot with nothing competing for attention."
    ),
    "Increase Deal Sales": (
        "Make the value of the offer visually obvious: generous portions or an "
        "abundant spread that reads as a great deal at a glance."
    ),
    "Increase Guest Visits": (
        "Emphasize the in-restaurant experience and atmosphere over any single "
        "dish, so the scene makes viewers want to visit in person."
    ),
}
_DEFAULT_GOAL_DIRECTIVE = "Create an appetizing, on-brand scene that supports this campaign's goal."

# campaign_audiences -> tone directive, per the task spec (e.g. "Lost ->
# reactivation-focused and persuasive"). Checked in priority order when a
# payload lists multiple audiences, favoring the segment with the most
# distinct campaign treatment.
_AUDIENCE_TONE_PRIORITY: tuple[str, ...] = ("Lost", "Occasional", "Regular", "New", "Potential")
_AUDIENCE_TONES: dict[str, str] = {
    "New": "Welcoming and introductory: make a great first impression.",
    "Potential": "Welcoming and introductory: make a great first impression.",
    "Occasional": "Friendly reminder tone: warm, familiar, low-pressure.",
    "Lost": "Reactivation-focused and persuasive: give them a clear reason to come back.",
    "Regular": "Loyalty and familiarity: warm and appreciative of the relationship.",
}
_DEFAULT_AUDIENCE_TONE = "Friendly and inclusive, suitable for a general audience."


def _goal_direction(campaign_goal: str) -> str:
    return _GOAL_DIRECTIVES.get(campaign_goal, _DEFAULT_GOAL_DIRECTIVE)


def _audience_tone(audiences: list[str]) -> str:
    for key in _AUDIENCE_TONE_PRIORITY:
        if key in audiences:
            return _AUDIENCE_TONES[key]
    return _DEFAULT_AUDIENCE_TONE


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
        goal_direction=_goal_direction(payload.campaign_goals),
        audience_tone=_audience_tone(payload.campaign_audiences),
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

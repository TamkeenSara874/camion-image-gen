from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.config import Settings
from schemas.internal import CampaignContext, ImagePromptResponse
from services.openai_client import get_openai_client

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_CAMPAIGN_TYPE_TO_TEMPLATE: dict[str, str] = {
    "Spotlights": "prompt_spotlights.yaml",
    "Menu Items": "prompt_menu_items.yaml",
    "Deals": "prompt_deals.yaml",
}

_NO_TEXT_SUFFIX = (
    "Professional food photography background only. "
    "No text, no signage, no labels, no numbers, no watermarks, no logos anywhere in the scene."
)


@lru_cache
def _load_template(campaign_type: str) -> dict[str, str]:
    filename = _CAMPAIGN_TYPE_TO_TEMPLATE.get(campaign_type)
    if filename is None:
        raise ValueError(f"No prompt template for campaign_type: {campaign_type!r}")
    path = PROMPTS_DIR / filename
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_user_message(template: str, ctx: CampaignContext, retry_suffix: str) -> str:
    custom_prompt_block = (
        f"Additional creative direction: {ctx.custom_prompt}" if ctx.custom_prompt else ""
    )
    audience_str = ", ".join(ctx.audience) if ctx.audience else "General"
    guest_tags_str = ", ".join(ctx.guest_context_tags) if ctx.guest_context_tags else "None"
    item_category = ctx.extra_vars.get("item_category", [])
    item_category_str = (
        ", ".join(item_category) if isinstance(item_category, list) else str(item_category)
    )
    deal_type = ctx.extra_vars.get("deal_type", "")
    platforms = ctx.extra_vars.get("platforms") or []
    platforms_str = ", ".join(platforms) if platforms else "all channels"
    spotlight_type = ctx.extra_vars.get("spotlight_type") or "general"

    filled = template.format(
        restaurant_name=ctx.restaurant.restaurant_name,
        cuisine_type=ctx.restaurant.cuisine_type,
        brand_theme=ctx.restaurant.brand_theme,
        visual_style=ctx.restaurant.visual_style,
        main_title=ctx.main_title,
        main_offer=ctx.main_offer,
        campaign_goal=ctx.campaign_goal,
        audience=audience_str,
        brand_voice=ctx.brand_voice,
        aspect_ratio=ctx.aspect_ratio,
        image_size=ctx.image_size,
        primary_hex=ctx.restaurant.brand_colors.get("primary", "#333333"),
        accent_hex=ctx.restaurant.brand_colors.get("accent", "#888888"),
        guest_context_tags=guest_tags_str,
        custom_prompt_block=custom_prompt_block,
        item_category=item_category_str,
        deal_type=deal_type,
        platforms=platforms_str,
        spotlight_type=spotlight_type,
    )

    if retry_suffix:
        filled = filled + f"\n\n{retry_suffix}"

    return filled


def _parse_llm_response(raw: str, ctx: CampaignContext) -> ImagePromptResponse:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Prompt generator returned invalid JSON: {exc}\nRaw: {raw[:300]}") from exc

    prompt = data.get("final_image_prompt", "")
    if not prompt.endswith(_NO_TEXT_SUFFIX):
        prompt = prompt.rstrip() + " " + _NO_TEXT_SUFFIX

    alt = data.get("alt_text", "").replace("—", " - ").replace("–", " - ")

    return ImagePromptResponse(
        final_image_prompt=prompt,
        alt_text=alt,
        metadata={
            "campaign_type": ctx.campaign_type,
            "aspect_ratio": ctx.aspect_ratio,
        },
    )


async def generate_prompt(
    ctx: CampaignContext,
    settings: Settings,
    retry_suffix: str = "",
) -> ImagePromptResponse:
    template_data = _load_template(ctx.campaign_type)
    user_message = _build_user_message(template_data["user"], ctx, retry_suffix)

    client = get_openai_client()
    response = await client.chat.completions.create(
        model=settings.openai_concept_model,
        max_tokens=700,
        temperature=0.7,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": template_data["system"]},
            {"role": "user", "content": user_message},
        ],
        timeout=settings.llm_timeout,
    )

    raw = response.choices[0].message.content or ""
    result = _parse_llm_response(raw, ctx)

    # Attach token usage to allow cost estimation by the caller
    usage = response.usage
    result.metadata["input_tokens"] = str(usage.prompt_tokens if usage else 0)
    result.metadata["output_tokens"] = str(usage.completion_tokens if usage else 0)

    return result

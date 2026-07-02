from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from schemas.internal import CampaignContext, ImagePromptResponse, RestaurantBrand
from stages.prompt_generator import _build_user_message, _load_template, _parse_llm_response


@pytest.fixture
def mijos_brand() -> RestaurantBrand:
    return RestaurantBrand(
        restaurant_id=2,
        restaurant_name="Mijo's Taqueria",
        cuisine_type="Mexican",
        brand_theme="vibrant, festive",
        visual_style="rustic wood textures, terracotta tones",
        website_url="https://mijostaqueria.com",
        brand_colors={"primary": "#C8410A", "accent": "#F5A623", "text_on_primary": "#FFFFFF"},
        currency_symbol="$",
    )


@pytest.fixture
def spotlights_ctx(mijos_brand) -> CampaignContext:
    return CampaignContext(
        restaurant=mijos_brand,
        campaign_type="Spotlights",
        campaign_goal="Increase Restaurant Visits",
        main_title="Weekend Fiesta",
        main_offer="Live music, fresh margaritas, and chef's special tacos.",
        price=None,
        cta=False,
        cta_text=None,
        audience=["Regulars", "New"],
        guest_context_tags=["Cocktail", "Mexican Food Lovers"],
        channel="Email",
        brand_voice="Vibrant, Festive",
        image_size="1536x1024",
        aspect_ratio="16:9",
        custom_prompt=None,
        extra_vars={},
    )


@pytest.fixture
def menu_items_ctx(mijos_brand) -> CampaignContext:
    return CampaignContext(
        restaurant=mijos_brand,
        campaign_type="Menu Items",
        campaign_goal="Increase Item Sales",
        main_title="Baja Fish Taco",
        main_offer="Crispy beer-battered fish, fresh pico, avocado crema.",
        price="$12",
        cta=False,
        cta_text=None,
        audience=["Potential", "New"],
        guest_context_tags=["Seafood Lovers"],
        channel="Email",
        brand_voice="Casual, Friendly",
        image_size="1024x1024",
        aspect_ratio="1:1",
        custom_prompt=None,
        extra_vars={"item_category": ["Tacos"]},
    )


@pytest.fixture
def deals_ctx(mijos_brand) -> CampaignContext:
    return CampaignContext(
        restaurant=mijos_brand,
        campaign_type="Deals",
        campaign_goal="Increase Item Sales",
        main_title="Taco Tuesday BOGO",
        main_offer="Buy one Baja Fish Taco, get one free every Tuesday.",
        price=None,
        cta=False,
        cta_text=None,
        audience=["All Guests"],
        guest_context_tags=[],
        channel="Email",
        brand_voice="Exciting, Fun",
        image_size="1536x1024",
        aspect_ratio="16:9",
        custom_prompt=None,
        extra_vars={"deal_type": "BOGO", "deal_type_vars": {}, "promo_code": None},
    )


def test_load_spotlights_template_has_system_and_user():
    tmpl = _load_template("Spotlights")
    assert "system" in tmpl
    assert "user" in tmpl
    assert len(tmpl["system"]) > 20
    assert "{main_title}" in tmpl["user"]


def test_load_menu_items_template():
    tmpl = _load_template("Menu Items")
    assert "{main_title}" in tmpl["user"]
    assert "{item_category}" in tmpl["user"]


def test_load_deals_template():
    tmpl = _load_template("Deals")
    assert "{deal_type}" in tmpl["user"]


def test_load_unknown_template_raises():
    from stages.prompt_generator import _load_template as lt

    with pytest.raises(ValueError, match="No prompt template"):
        lt("Flash Sale")
        lt.cache_clear()


def test_build_user_message_injects_restaurant_name(spotlights_ctx):
    tmpl = _load_template("Spotlights")
    msg = _build_user_message(tmpl["user"], spotlights_ctx, "")
    assert "Mijo's Taqueria" in msg
    assert "Weekend Fiesta" in msg
    assert "#C8410A" in msg


def test_build_user_message_includes_retry_suffix(spotlights_ctx):
    tmpl = _load_template("Spotlights")
    msg = _build_user_message(tmpl["user"], spotlights_ctx, "CRITICAL: regenerate without any text")
    assert "CRITICAL: regenerate without any text" in msg


def test_build_user_message_includes_custom_prompt(mijos_brand):
    ctx = CampaignContext(
        restaurant=mijos_brand,
        campaign_type="Spotlights",
        campaign_goal="",
        main_title="T",
        main_offer="D",
        price=None,
        cta=False,
        cta_text=None,
        audience=[],
        guest_context_tags=[],
        channel="Email",
        brand_voice="",
        image_size="1536x1024",
        aspect_ratio="16:9",
        custom_prompt="Use a sunset rooftop setting",
        extra_vars={},
    )
    tmpl = _load_template("Spotlights")
    msg = _build_user_message(tmpl["user"], ctx, "")
    assert "sunset rooftop setting" in msg


def test_build_user_message_no_custom_prompt_block_when_none(spotlights_ctx):
    tmpl = _load_template("Spotlights")
    msg = _build_user_message(tmpl["user"], spotlights_ctx, "")
    assert "Additional creative direction" not in msg


def test_parse_llm_response_valid_json(spotlights_ctx):
    raw = json.dumps({
        "final_image_prompt": "A festive table with tacos and margaritas.",
        "alt_text": "Mijo's Taqueria — Weekend Fiesta: festive table.",
    })
    result = _parse_llm_response(raw, spotlights_ctx)
    assert isinstance(result, ImagePromptResponse)
    assert "Mijo" in result.alt_text


def test_parse_llm_response_appends_no_text_suffix(spotlights_ctx):
    raw = json.dumps({
        "final_image_prompt": "A festive table with tacos.",
        "alt_text": "Alt text here.",
    })
    result = _parse_llm_response(raw, spotlights_ctx)
    assert result.final_image_prompt.endswith(
        "Professional food photography background only. "
        "No text, no signage, no labels, no numbers, no watermarks, no logos anywhere in the scene."
    )


def test_parse_llm_response_does_not_duplicate_suffix(spotlights_ctx):
    suffix = (
        "Professional food photography background only. "
        "No text, no signage, no labels, no numbers, no watermarks, no logos anywhere in the scene."
    )
    raw = json.dumps({
        "final_image_prompt": f"A festive table. {suffix}",
        "alt_text": "Alt.",
    })
    result = _parse_llm_response(raw, spotlights_ctx)
    assert result.final_image_prompt.count("Professional food photography background only.") == 1


def test_parse_llm_response_strips_markdown_fences(spotlights_ctx):
    raw = "```json\n" + json.dumps({"final_image_prompt": "Scene.", "alt_text": "Alt."}) + "\n```"
    result = _parse_llm_response(raw, spotlights_ctx)
    assert result.final_image_prompt.startswith("Scene.")


def test_parse_llm_response_invalid_json_raises(spotlights_ctx):
    with pytest.raises(ValueError, match="invalid JSON"):
        _parse_llm_response("not json at all", spotlights_ctx)


async def test_generate_prompt_calls_openai_and_returns_response(spotlights_ctx):
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 400
    mock_usage.completion_tokens = 160

    mock_message = MagicMock()
    mock_message.content = json.dumps({
        "final_image_prompt": "Vibrant tacos on rustic wood table, warm festive lighting.",
        "alt_text": "Mijo's Taqueria — Weekend Fiesta: vibrant taco spread.",
    })

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage

    mock_settings = MagicMock()
    mock_settings.openai_concept_model = "gpt-4o-mini"
    mock_settings.llm_timeout = 60
    mock_settings.openai_api_key = "test-key"

    with patch("stages.prompt_generator.get_openai_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        from stages.prompt_generator import generate_prompt

        result = await generate_prompt(spotlights_ctx, mock_settings)

    assert "tacos" in result.final_image_prompt.lower()
    assert result.alt_text
    assert result.metadata["input_tokens"] == "400"
    assert result.metadata["output_tokens"] == "160"


async def test_generate_prompt_retry_suffix_passed_to_llm(spotlights_ctx):
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 420
    mock_usage.completion_tokens = 170

    mock_message = MagicMock()
    mock_message.content = json.dumps({
        "final_image_prompt": "Clean festive scene, absolutely no text anywhere.",
        "alt_text": "Alt.",
    })

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage

    mock_settings = MagicMock()
    mock_settings.openai_concept_model = "gpt-4o-mini"
    mock_settings.llm_timeout = 60
    mock_settings.openai_api_key = "test-key"

    captured_messages = []

    async def capture_create(**kwargs):
        captured_messages.extend(kwargs.get("messages", []))
        return mock_response

    with patch("stages.prompt_generator.get_openai_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create = capture_create
        mock_get_client.return_value = mock_client

        from stages.prompt_generator import generate_prompt

        await generate_prompt(spotlights_ctx, mock_settings, retry_suffix="CRITICAL: no text")

    user_msg = next(m["content"] for m in captured_messages if m["role"] == "user")
    assert "CRITICAL: no text" in user_msg

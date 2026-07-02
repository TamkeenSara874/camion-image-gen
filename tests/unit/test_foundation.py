from __future__ import annotations

import pytest


def test_campaign_registry_has_three_types():
    from schemas.campaign_types import CAMPAIGN_REGISTRY

    assert set(CAMPAIGN_REGISTRY.keys()) == {"Spotlights", "Menu Items", "Deals"}


def test_spotlights_validates():
    from schemas.campaign_types import CAMPAIGN_REGISTRY

    v = CAMPAIGN_REGISTRY["Spotlights"].model_validate(
        {"name": "Summer Grilling", "description": "Weekend BBQ specials."}
    )
    assert v.name == "Summer Grilling"
    assert v.spotlight_type is None


def test_menu_items_validates_with_price():
    from schemas.campaign_types import CAMPAIGN_REGISTRY

    v = CAMPAIGN_REGISTRY["Menu Items"].model_validate(
        {
            "name": "Beer & Wine",
            "description": "All beers, plus house red and white wines.",
            "price": "30",
            "item_category": ["Catering"],
        }
    )
    assert v.price == "30"


def test_deals_validates():
    from schemas.campaign_types import CAMPAIGN_REGISTRY

    v = CAMPAIGN_REGISTRY["Deals"].model_validate(
        {
            "name": "BOGO Taco Tuesday",
            "deal_type": "BOGO",
            "deal_type_vars": {"buy": 1, "get": 1, "item": "Baja Fish Taco"},
        }
    )
    assert v.deal_type == "BOGO"
    assert v.promo_code is None


def test_unknown_campaign_type_not_in_registry():
    from schemas.campaign_types import CAMPAIGN_REGISTRY

    assert "Flash Sale" not in CAMPAIGN_REGISTRY


def test_campaign_payload_validates():
    from schemas.request import CampaignPayload

    p = CampaignPayload.model_validate(
        {
            "campaign_type": "Menu Items",
            "campaign_vars": {
                "name": "Beer & Wine",
                "item_category": ["Catering"],
                "price": "30",
                "description": "All beers, plus house red and white wines.",
                "item_menu": "",
            },
            "cta": False,
            "channels": ["Email"],
            "campaign_brand_voices": "Friendly, Casual, Inclusive",
            "restaurantId": 4,
            "orientation": "Landscape",
            "custom_prompt": None,
        }
    )
    assert p.campaign_type == "Menu Items"
    assert p.restaurantId == 4
    assert p.cta is False
    assert p.orientation == "Landscape"


def test_campaign_payload_rejects_empty_campaign_type():
    from pydantic import ValidationError

    from schemas.request import CampaignPayload

    with pytest.raises(ValidationError):
        CampaignPayload.model_validate(
            {"campaign_type": "  ", "campaign_vars": {}, "restaurantId": 1}
        )


def test_settings_defaults_load():
    from app.config import get_settings

    s = get_settings()
    assert s.openai_concept_model == "gpt-4o-mini"
    assert s.openai_image_model == "gpt-image-2"
    assert s.openai_image_fallback_model == "gpt-image-1.5"
    assert s.openai_image_fallback_model_2 == "gpt-image-1-mini"
    assert s.openai_qa_model == "gpt-4.1"
    assert s.cta_overlay_enabled is False
    assert s.max_images_per_restaurant_per_day == 50
    assert s.qa_brand_fidelity_threshold == 4


def test_cost_estimate_gpt4o_mini():
    from services.cost_table import estimate_token_cost

    cost = estimate_token_cost("gpt-4o-mini", input_tokens=420, output_tokens=180)
    expected = (420 * 0.15 + 180 * 0.60) / 1_000_000
    assert abs(cost - expected) < 1e-10


def test_cost_estimate_image_models():
    from services.cost_table import estimate_image_cost

    assert estimate_image_cost("gpt-image-2", "medium") == pytest.approx(0.042)
    assert estimate_image_cost("gpt-image-1.5", "medium") == pytest.approx(0.030)
    assert estimate_image_cost("gpt-image-1-mini", "low") == pytest.approx(0.005)


def test_cost_estimate_unknown_model_returns_zero():
    from services.cost_table import estimate_token_cost

    assert estimate_token_cost("gpt-4o", 1000, 500) == 0.0


def test_request_metrics_total_cost_sums_stages():
    from schemas.internal import RequestMetrics, StageMetrics

    m = RequestMetrics(request_id="test-001", restaurant_id=2, campaign_type="Deals")
    m.stages = [
        StageMetrics(
            stage="prompt_generator",
            model="gpt-4o-mini",
            latency_ms=1200,
            input_tokens=420,
            output_tokens=180,
            estimated_cost_usd=0.000171,
        ),
        StageMetrics(
            stage="image_synthesizer",
            model="gpt-image-2",
            latency_ms=14800,
            estimated_cost_usd=0.042,
        ),
        StageMetrics(
            stage="qa_validator",
            model="gpt-4.1",
            latency_ms=3200,
            input_tokens=210,
            output_tokens=85,
            estimated_cost_usd=0.001100,
        ),
    ]
    total = sum(s.estimated_cost_usd for s in m.stages)
    assert abs(total - 0.043271) < 1e-6


def test_qa_result_passes_when_all_checks_clear():
    from schemas.internal import QAResult

    qa = QAResult(
        ocr_passed=True,
        stray_model_text=False,
        brand_fidelity_score=4,
        composition_score=4,
    )
    assert qa.qa_passed is True


def test_qa_result_fails_on_stray_text():
    from schemas.internal import QAResult

    qa = QAResult(ocr_passed=True, stray_model_text=True, brand_fidelity_score=5)
    assert qa.qa_passed is False


def test_qa_result_fails_on_low_brand_fidelity():
    from schemas.internal import QAResult

    qa = QAResult(ocr_passed=True, stray_model_text=False, brand_fidelity_score=3)
    assert qa.qa_passed is False


def test_new_campaign_type_registers_without_pipeline_changes():
    from pydantic import BaseModel

    from schemas.campaign_types import CAMPAIGN_REGISTRY

    class HappyHourVars(BaseModel):
        name: str
        discount_percent: int
        hours: str

    CAMPAIGN_REGISTRY["Happy Hour"] = HappyHourVars
    assert "Happy Hour" in CAMPAIGN_REGISTRY
    v = CAMPAIGN_REGISTRY["Happy Hour"].model_validate(
        {"name": "Wednesday Happy Hour", "discount_percent": 50, "hours": "4pm-7pm"}
    )
    assert v.discount_percent == 50
    del CAMPAIGN_REGISTRY["Happy Hour"]
    assert "Happy Hour" not in CAMPAIGN_REGISTRY


def test_internal_schemas_are_dataclasses():
    import dataclasses

    from schemas.internal import (
        CampaignContext,
        CompositeResult,
        ImagePromptResponse,
        QAResult,
        RequestMetrics,
        RestaurantBrand,
        StageMetrics,
        SynthesisResult,
    )

    for cls in (
        RestaurantBrand,
        CampaignContext,
        ImagePromptResponse,
        SynthesisResult,
        CompositeResult,
        QAResult,
        StageMetrics,
        RequestMetrics,
    ):
        assert dataclasses.is_dataclass(cls), f"{cls.__name__} must be a dataclass"


def test_response_schemas_are_pydantic():
    from pydantic import BaseModel

    from schemas.response import ImageGenerationResponse, ResponseMetrics, StageBreakdown

    for cls in (StageBreakdown, ResponseMetrics, ImageGenerationResponse):
        assert issubclass(cls, BaseModel), f"{cls.__name__} must be a Pydantic BaseModel"

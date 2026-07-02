from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest

import pipeline.image_pipeline as pip_mod
from pipeline.image_pipeline import run
from schemas.internal import CompositeResult, ImagePromptResponse, SynthesisResult
from schemas.request import CampaignPayload


@pytest.fixture(autouse=True)
def _reset_state():
    pip_mod._cache.clear()
    pip_mod._daily_counts.clear()
    yield
    pip_mod._cache.clear()
    pip_mod._daily_counts.clear()


@pytest.fixture()
def settings():
    from app.config import Settings
    return Settings(
        openai_api_key="sk-test",
        api_bearer_token="test-token",
        r2_account_id="test-acct",
        r2_access_key_id="test-key",
        r2_secret_access_key="test-secret",
        r2_bucket_name="test-bucket",
        r2_public_url="https://test.r2.dev",
        qa_enabled=True,
        qa_retry_limit=2,
    )


@pytest.fixture()
def menu_payload() -> CampaignPayload:
    return CampaignPayload.model_validate({
        "campaign_type": "Menu Items",
        "campaign_goals": "Increase Item Sales",
        "campaign_audiences": ["Potential", "New"],
        "campaign_guest_tags": ["Seafood Lovers"],
        "campaign_vars": {
            "name": "Baja Fish Taco",
            "description": "Crispy beer-battered fish on corn tortilla.",
            "price": "12",
            "item_category": ["Tacos"],
            "item_menu": "",
        },
        "cta": False,
        "channels": ["Email"],
        "campaign_brand_voices": "Casual",
        "restaurantId": 2,
        "orientation": "Landscape",
        "custom_prompt": None,
    })


FAKE_PROMPT = ImagePromptResponse(
    final_image_prompt="Vibrant taco scene. No text.",
    alt_text="Mijo's Baja Fish Taco",
    metadata={"input_tokens": "120", "output_tokens": "70"},
)

FAKE_SYNTHESIS = SynthesisResult(
    image_bytes=b"\xff\xd8\xff" + b"\x00" * 50,
    model_used="gpt-image-2",
    attempt_number=1,
    orientation_preserved=True,
)

FAKE_COMPOSITE = CompositeResult(
    image_bytes=b"\xff\xd8\xff" + b"\x00" * 80,
    mime_type="image/jpeg",
    text_was_truncated=False,
)

FAKE_URL = "https://test.r2.dev/2/abc123.jpg"


def _as_async_mock(val):
    return val if isinstance(val, AsyncMock) else AsyncMock(return_value=val)


@contextmanager
def _mocked_pipeline(
    *,
    prompt=None,
    synthesis=None,
    composite_result=None,
    upload_url=FAKE_URL,
    vision_result=(False, 5, 5, []),
    clip_score=0.28,
    ocr_result=(True, []),
):
    mocks = {
        "gp": AsyncMock(return_value=prompt or FAKE_PROMPT),
        "synth": AsyncMock(return_value=synthesis or FAKE_SYNTHESIS),
        "comp": _as_async_mock(composite_result or FAKE_COMPOSITE),
        "upload": AsyncMock(return_value=upload_url),
        "vision": _as_async_mock(vision_result),
        "clip": AsyncMock(return_value=clip_score),
        "ocr": AsyncMock(return_value=ocr_result),
    }
    with (
        patch("pipeline.image_pipeline.generate_prompt", mocks["gp"]),
        patch("pipeline.image_pipeline.synthesize", mocks["synth"]),
        patch("pipeline.image_pipeline.composite", mocks["comp"]),
        patch("pipeline.image_pipeline.upload_image", mocks["upload"]),
        patch("pipeline.image_pipeline._vision_check_async", mocks["vision"]),
        patch("pipeline.image_pipeline._clip_check_async", mocks["clip"]),
        patch("pipeline.image_pipeline._ocr_check_async", mocks["ocr"]),
    ):
        yield mocks


class TestHappyPath:
    async def test_response_structure(self, menu_payload, settings):
        with _mocked_pipeline() as mocks:
            response = await run(menu_payload, settings)

        assert response.image_url == FAKE_URL
        assert response.model_used == "gpt-image-2"
        assert response.attempt_number == 1
        assert response.orientation_preserved is True
        assert response.restaurant_name == "Mijo's Taqueria"
        assert response.campaign_type == "Menu Items"
        assert response.qa_passed is True
        assert response.qa_retries == 0
        assert response.clip_score == pytest.approx(0.28)
        assert response.alt_text == "Mijo's Baja Fish Taco"
        assert response.metrics.total_cost_usd >= 0.0
        assert len(response.metrics.stage_breakdown) > 0

    async def test_all_stages_called_once(self, menu_payload, settings):
        with _mocked_pipeline() as mocks:
            await run(menu_payload, settings)

        mocks["gp"].assert_called_once()
        mocks["synth"].assert_called_once()
        mocks["comp"].assert_called_once()
        mocks["upload"].assert_called_once()
        mocks["vision"].assert_called_once()

    async def test_r2_url_prefix(self, menu_payload, settings):
        with _mocked_pipeline(upload_url="https://test.r2.dev/2/img.jpg"):
            response = await run(menu_payload, settings)

        assert response.image_url.startswith("https://test.r2.dev")

    async def test_orientation_preserved_flag(self, menu_payload, settings):
        hf_synthesis = SynthesisResult(
            image_bytes=b"\xff\xd8\xff" + b"\x00" * 50,
            model_used="FLUX.1-schnell",
            attempt_number=5,
            orientation_preserved=False,
        )
        with _mocked_pipeline(synthesis=hf_synthesis):
            response = await run(menu_payload, settings)

        assert response.orientation_preserved is False
        assert response.model_used == "FLUX.1-schnell"
        assert response.attempt_number == 5


class TestCaching:
    async def test_cache_hit_skips_synthesis(self, menu_payload, settings):
        with _mocked_pipeline() as mocks:
            r1 = await run(menu_payload, settings)
            r2 = await run(menu_payload, settings)

        assert mocks["synth"].call_count == 1
        assert r1 is r2

    async def test_cache_key_differs_by_payload(self, menu_payload, settings):
        different_payload = CampaignPayload.model_validate({
            "campaign_type": "Spotlights",
            "campaign_goals": "Brand Awareness",
            "campaign_audiences": ["All"],
            "campaign_guest_tags": [],
            "campaign_vars": {"name": "Weekend Fiesta", "description": "Live music."},
            "cta": False,
            "channels": ["Email"],
            "campaign_brand_voices": "Vibrant",
            "restaurantId": 2,
            "orientation": "Landscape",
            "custom_prompt": None,
        })
        with _mocked_pipeline() as mocks:
            await run(menu_payload, settings)
            await run(different_payload, settings)

        assert mocks["synth"].call_count == 2


class TestLimitsAndValidation:
    async def test_daily_limit_raises(self, menu_payload, settings):
        settings_limited = Settings_with_limit(settings, limit=0)
        with pytest.raises(RuntimeError, match="Daily image limit"):
            with _mocked_pipeline():
                await run(menu_payload, settings_limited)

    async def test_invalid_restaurant_raises_value_error(self, settings):
        bad_payload = CampaignPayload.model_validate({
            "campaign_type": "Menu Items",
            "campaign_goals": "Sales",
            "campaign_audiences": ["All"],
            "campaign_guest_tags": [],
            "campaign_vars": {
                "name": "Burger",
                "description": "A beef burger.",
                "price": "15",
                "item_category": ["Burgers"],
                "item_menu": "",
            },
            "cta": False,
            "channels": ["Email"],
            "campaign_brand_voices": "Casual",
            "restaurantId": 999,
            "orientation": "Landscape",
            "custom_prompt": None,
        })
        with pytest.raises(ValueError, match="999"):
            with _mocked_pipeline():
                await run(bad_payload, settings)

    async def test_invalid_campaign_type_raises_value_error(self, settings):
        bad_payload = CampaignPayload.model_validate({
            "campaign_type": "Flash Sale",
            "campaign_goals": "Sales",
            "campaign_audiences": ["All"],
            "campaign_guest_tags": [],
            "campaign_vars": {"name": "Sale", "description": "50% off"},
            "cta": False,
            "channels": ["Email"],
            "campaign_brand_voices": "Urgent",
            "restaurantId": 2,
            "orientation": "Landscape",
            "custom_prompt": None,
        })
        with pytest.raises(ValueError, match="Flash Sale"):
            with _mocked_pipeline():
                await run(bad_payload, settings)


def Settings_with_limit(base_settings, limit: int):
    from app.config import Settings
    return Settings(
        openai_api_key=base_settings.openai_api_key,
        api_bearer_token=base_settings.api_bearer_token,
        r2_account_id=base_settings.r2_account_id,
        r2_access_key_id=base_settings.r2_access_key_id,
        r2_secret_access_key=base_settings.r2_secret_access_key,
        r2_bucket_name=base_settings.r2_bucket_name,
        r2_public_url=base_settings.r2_public_url,
        max_images_per_restaurant_per_day=limit,
        qa_enabled=base_settings.qa_enabled,
    )


class TestQARetries:
    async def test_synthesis_retry_on_stray_text(self, menu_payload, settings):
        vision_calls = [
            (True, 4, 4, ["stray text found"]),
            (False, 5, 5, []),
        ]
        with _mocked_pipeline(vision_result=AsyncMock(side_effect=vision_calls)) as mocks:
            response = await run(menu_payload, settings)

        assert mocks["synth"].call_count == 2
        assert mocks["gp"].call_count == 2
        assert response.qa_passed is True
        assert response.qa_retries == 1

    async def test_compositor_retry_no_resynthesis(self, menu_payload, settings):
        from app.config import Settings as S
        s = S(
            openai_api_key="sk-test",
            api_bearer_token="test-token",
            r2_account_id="test-acct",
            r2_access_key_id="test-key",
            r2_secret_access_key="test-secret",
            r2_bucket_name="test-bucket",
            r2_public_url="https://test.r2.dev",
            qa_enabled=True,
            qa_retry_limit=1,
        )
        composite_calls = [
            CompositeResult(image_bytes=b"\xff\xd8\xff" + b"\x00" * 40, text_was_truncated=True),
            CompositeResult(image_bytes=b"\xff\xd8\xff" + b"\x00" * 40, text_was_truncated=False),
        ]
        # Vision: brand=3 so qa_passed=False; no stray text so synthesis_fail=False
        # → failure classified as COMPOSITOR (text_overflow=True, no synthesis fail)
        with _mocked_pipeline(
            composite_result=AsyncMock(side_effect=composite_calls),
            vision_result=(False, 3, 4, ["brand score low"]),
        ) as mocks:
            response = await run(menu_payload, s)

        # Synthesize called exactly once (no re-synthesis for compositor failure)
        assert mocks["synth"].call_count == 1
        assert mocks["comp"].call_count == 2
        assert response.qa_retries == 1

    async def test_qa_fails_after_retry_limit_returns_response(self, menu_payload, settings):
        from app.config import Settings as S
        s = S(
            openai_api_key="sk-test",
            api_bearer_token="test-token",
            r2_account_id="test-acct",
            r2_access_key_id="test-key",
            r2_secret_access_key="test-secret",
            r2_bucket_name="test-bucket",
            r2_public_url="https://test.r2.dev",
            qa_enabled=True,
            qa_retry_limit=1,
        )
        with _mocked_pipeline(vision_result=(True, 2, 2, ["bad image"])):
            response = await run(menu_payload, s)

        assert response.qa_passed is False
        assert response.qa_retries == 1

    async def test_qa_disabled_skips_retry(self, menu_payload, settings):
        from app.config import Settings as S
        s = S(
            openai_api_key="sk-test",
            api_bearer_token="test-token",
            r2_account_id="test-acct",
            r2_access_key_id="test-key",
            r2_secret_access_key="test-secret",
            r2_bucket_name="test-bucket",
            r2_public_url="https://test.r2.dev",
            qa_enabled=False,
        )
        with _mocked_pipeline(vision_result=(True, 1, 1, ["very bad"])) as mocks:
            response = await run(menu_payload, s)

        # With QA disabled, vision should still be called but retry loop should not trigger
        assert response.qa_retries == 0
        assert mocks["synth"].call_count == 1

    async def test_retry_suffix_passed_to_prompt_generator(self, menu_payload, settings):
        from app.config import Settings as S
        s = S(
            openai_api_key="sk-test",
            api_bearer_token="test-token",
            r2_account_id="test-acct",
            r2_access_key_id="test-key",
            r2_secret_access_key="test-secret",
            r2_bucket_name="test-bucket",
            r2_public_url="https://test.r2.dev",
            qa_enabled=True,
            qa_retry_limit=1,
        )
        vision_calls = [(True, 4, 4, ["stray text"]), (False, 5, 5, [])]
        with _mocked_pipeline(vision_result=AsyncMock(side_effect=vision_calls)) as mocks:
            await run(menu_payload, s)

        # Second call to generate_prompt should have retry_suffix keyword argument
        assert mocks["gp"].call_count == 2
        second_call_kwargs = mocks["gp"].call_args_list[1].kwargs
        assert "retry_suffix" in second_call_kwargs
        assert len(second_call_kwargs["retry_suffix"]) > 0


class TestMetrics:
    async def test_stage_breakdown_present(self, menu_payload, settings):
        with _mocked_pipeline():
            response = await run(menu_payload, settings)

        stages = [s.stage for s in response.metrics.stage_breakdown]
        assert "validator" in stages
        assert "brand_mapper" in stages
        assert "campaign_parser" in stages
        assert "prompt_generator" in stages
        assert "image_synthesizer" in stages
        assert "text_compositor" in stages
        assert "qa_validator" in stages

    async def test_total_latency_ms_positive(self, menu_payload, settings):
        with _mocked_pipeline():
            response = await run(menu_payload, settings)

        assert response.metrics.total_latency_ms >= 0

    async def test_qa_scores_in_response(self, menu_payload, settings):
        with _mocked_pipeline(vision_result=(False, 4, 5, [])):
            response = await run(menu_payload, settings)

        assert response.qa_scores["brand_fidelity"] == 4
        assert response.qa_scores["composition"] == 5

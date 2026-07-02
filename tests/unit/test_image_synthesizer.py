from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from schemas.internal import CampaignContext, ImagePromptResponse, RestaurantBrand, SynthesisResult
from stages.image_synthesizer import _breaker, synthesize


def _fake_settings(
    image_model: str = "gpt-image-2",
    fallback_model: str = "gpt-image-1.5",
    fallback_model_2: str = "gpt-image-1-mini",
    image_quality: str = "medium",
    image_timeout: int = 30,
    hf_token: str = "",
) -> MagicMock:
    s = MagicMock()
    s.openai_image_model = image_model
    s.openai_image_fallback_model = fallback_model
    s.openai_image_fallback_model_2 = fallback_model_2
    s.openai_image_quality = image_quality
    s.image_timeout = image_timeout
    s.hf_token = hf_token
    return s


def _make_brand() -> RestaurantBrand:
    return RestaurantBrand(
        restaurant_id=2,
        restaurant_name="Mijo's Taqueria",
        cuisine_type="Mexican",
        brand_theme="vibrant",
        visual_style="rustic",
        website_url="https://mijostaqueria.com",
        brand_colors={"primary": "#C8410A", "accent": "#F5A623", "text_on_primary": "#FFFFFF"},
    )


def _make_ctx(image_size: str = "1536x1024") -> CampaignContext:
    return CampaignContext(
        restaurant=_make_brand(),
        campaign_type="Menu Items",
        campaign_goal="Increase Sales",
        main_title="Baja Fish Taco",
        main_offer="Crispy fish taco",
        price="$12",
        cta=False,
        cta_text=None,
        audience=["All Guests"],
        guest_context_tags=[],
        channel="Email",
        brand_voice="Casual",
        image_size=image_size,
        aspect_ratio="16:9",
        custom_prompt=None,
    )


def _make_prompt_response() -> ImagePromptResponse:
    return ImagePromptResponse(
        final_image_prompt="Vibrant taco scene. No text no signage.",
        negative_prompt="text, watermark, logo, blurry",
        alt_text="Mijo's Taqueria - Baja Fish Taco",
    )


@pytest.fixture(autouse=True)
def reset_breaker():
    _breaker.reset()
    yield
    _breaker.reset()


@pytest.mark.asyncio
async def test_attempt1_success():
    ctx = _make_ctx()
    settings = _fake_settings()
    fake_bytes = b"PNG_IMAGE_BYTES"

    with patch("stages.image_synthesizer._openai_attempt", new=AsyncMock(return_value=fake_bytes)):
        result = await synthesize(_make_prompt_response(), ctx, settings)

    assert isinstance(result, SynthesisResult)
    assert result.image_bytes == fake_bytes
    assert result.model_used == "gpt-image-2"
    assert result.attempt_number == 1
    assert result.orientation_preserved is True


@pytest.mark.asyncio
async def test_attempt1_content_rejection_falls_to_attempt2():
    from openai import BadRequestError as OAIBadRequest

    ctx = _make_ctx()
    settings = _fake_settings()
    fake_bytes = b"SAFE_IMAGE"

    def side_effect(prompt, model, size, quality, timeout):
        if "FLUX" not in prompt and "safe content" not in prompt:
            raise OAIBadRequest("content_policy", response=MagicMock(status_code=400), body={})
        return asyncio.coroutine(lambda: fake_bytes)()

    call_count = {"n": 0}

    async def mock_attempt(prompt, model, size, quality, timeout):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise OAIBadRequest("content_policy", response=MagicMock(status_code=400), body={})
        return fake_bytes

    with patch("stages.image_synthesizer._openai_attempt", new=mock_attempt):
        result = await synthesize(_make_prompt_response(), ctx, settings)

    assert result.attempt_number == 2
    assert result.model_used == "gpt-image-2"
    assert result.image_bytes == fake_bytes


@pytest.mark.asyncio
async def test_attempt1_timeout_falls_to_fallback_model():
    ctx = _make_ctx()
    settings = _fake_settings()
    fake_bytes = b"FALLBACK_IMAGE"
    call_count = {"n": 0}

    async def mock_attempt(prompt, model, size, quality, timeout):
        call_count["n"] += 1
        if call_count["n"] <= 2:
            raise TimeoutError("timed out")
        return fake_bytes

    with patch("stages.image_synthesizer._openai_attempt", new=mock_attempt):
        result = await synthesize(_make_prompt_response(), ctx, settings)

    assert result.model_used == "gpt-image-1.5"
    assert result.attempt_number == 3


@pytest.mark.asyncio
async def test_all_openai_fail_hf_called_when_token_set():
    ctx = _make_ctx()
    settings = _fake_settings(hf_token="hf_test")
    fake_hf_bytes = b"HF_IMAGE"

    async def always_timeout(prompt, model, size, quality, timeout):
        raise TimeoutError("timed out")

    mock_resp = MagicMock()
    mock_resp.content = fake_hf_bytes
    mock_resp.raise_for_status = MagicMock()

    with patch("stages.image_synthesizer._openai_attempt", new=always_timeout):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_http

            result = await synthesize(_make_prompt_response(), ctx, settings)

    assert result.model_used == "FLUX.1-schnell"
    assert result.attempt_number == 5
    assert result.image_bytes == fake_hf_bytes


@pytest.mark.asyncio
async def test_all_openai_fail_no_hf_token_raises():
    ctx = _make_ctx()
    settings = _fake_settings(hf_token="")

    async def always_fail(prompt, model, size, quality, timeout):
        raise TimeoutError("timed out")

    with patch("stages.image_synthesizer._openai_attempt", new=always_fail):
        with pytest.raises(RuntimeError, match="HF_TOKEN"):
            await synthesize(_make_prompt_response(), ctx, settings)


@pytest.mark.asyncio
async def test_hf_orientation_preserved_false_for_landscape():
    ctx = _make_ctx(image_size="1536x1024")
    settings = _fake_settings(hf_token="hf_test")

    async def always_fail(prompt, model, size, quality, timeout):
        raise TimeoutError()

    mock_resp = MagicMock()
    mock_resp.content = b"HF"
    mock_resp.raise_for_status = MagicMock()

    with patch("stages.image_synthesizer._openai_attempt", new=always_fail):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_http
            result = await synthesize(_make_prompt_response(), ctx, settings)

    assert result.orientation_preserved is False


@pytest.mark.asyncio
async def test_hf_orientation_preserved_true_for_square():
    ctx = _make_ctx(image_size="1024x1024")
    settings = _fake_settings(hf_token="hf_test")

    async def always_fail(prompt, model, size, quality, timeout):
        raise TimeoutError()

    mock_resp = MagicMock()
    mock_resp.content = b"HF"
    mock_resp.raise_for_status = MagicMock()

    with patch("stages.image_synthesizer._openai_attempt", new=always_fail):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_http
            result = await synthesize(_make_prompt_response(), ctx, settings)

    assert result.orientation_preserved is True


@pytest.mark.asyncio
async def test_breaker_opens_after_5_failures_skips_to_hf():
    ctx = _make_ctx()
    settings = _fake_settings(hf_token="hf_test")
    fake_hf_bytes = b"HF_IMAGE"

    # Open the breaker manually
    for _ in range(5):
        _breaker.record_failure()
    assert _breaker.is_open

    mock_attempt = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.content = fake_hf_bytes
    mock_resp.raise_for_status = MagicMock()

    with patch("stages.image_synthesizer._openai_attempt", new=mock_attempt):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_http
            result = await synthesize(_make_prompt_response(), ctx, settings)

    mock_attempt.assert_not_called()
    assert result.model_used == "FLUX.1-schnell"


@pytest.mark.asyncio
async def test_synthesize_returns_synthesis_result_type():
    ctx = _make_ctx()
    settings = _fake_settings()

    with patch("stages.image_synthesizer._openai_attempt", new=AsyncMock(return_value=b"IMG")):
        result = await synthesize(_make_prompt_response(), ctx, settings)

    assert isinstance(result, SynthesisResult)


@pytest.mark.asyncio
async def test_content_rejection_both_primary_attempts_falls_to_3a():
    from openai import BadRequestError as OAIBadRequest

    ctx = _make_ctx()
    settings = _fake_settings()
    fake_bytes = b"3A_IMAGE"
    call_count = {"n": 0}

    async def mock_attempt(prompt, model, size, quality, timeout):
        call_count["n"] += 1
        if model == "gpt-image-2":
            raise OAIBadRequest("rejected", response=MagicMock(status_code=400), body={})
        return fake_bytes

    with patch("stages.image_synthesizer._openai_attempt", new=mock_attempt):
        result = await synthesize(_make_prompt_response(), ctx, settings)

    assert result.model_used == "gpt-image-1.5"
    assert result.attempt_number == 3


@pytest.mark.asyncio
async def test_breaker_resets_on_success():
    ctx = _make_ctx()
    settings = _fake_settings()
    for _ in range(3):
        _breaker.record_failure()
    assert not _breaker.is_open

    with patch("stages.image_synthesizer._openai_attempt", new=AsyncMock(return_value=b"OK")):
        await synthesize(_make_prompt_response(), ctx, settings)

    assert _breaker._failures == 0

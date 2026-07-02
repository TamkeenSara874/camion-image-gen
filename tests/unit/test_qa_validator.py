from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import stages.qa_validator as qav
from schemas.internal import CampaignContext, QAResult, RestaurantBrand
from stages.qa_validator import (
    _ocr_check_async,
    _run_ocr_sync,
    validate,
)

_RAW = b"RAW_IMAGE_BYTES"
_FINAL = b"FINAL_IMAGE_BYTES"


def _make_brand() -> RestaurantBrand:
    return RestaurantBrand(
        restaurant_id=2,
        restaurant_name="Mijo's Taqueria",
        cuisine_type="Mexican",
        brand_theme="vibrant, festive",
        visual_style="rustic wood",
        website_url="https://mijostaqueria.com",
        brand_colors={"primary": "#C8410A", "accent": "#F5A623", "text_on_primary": "#FFFFFF"},
    )


def _make_ctx() -> CampaignContext:
    return CampaignContext(
        restaurant=_make_brand(),
        campaign_type="Menu Items",
        campaign_goal="Increase Sales",
        main_title="Baja Fish Taco",
        main_offer="Crispy beer-battered fish taco",
        price="$12",
        cta=False,
        cta_text=None,
        audience=["All Guests"],
        guest_context_tags=[],
        channel="Email",
        brand_voice="Casual",
        image_size="1536x1024",
        aspect_ratio="16:9",
        custom_prompt=None,
    )


def _fake_settings(qa_enabled: bool = True) -> MagicMock:
    s = MagicMock()
    s.qa_enabled = qa_enabled
    s.openai_qa_model = "gpt-4.1"
    s.llm_timeout = 60
    return s


@pytest.fixture(autouse=True)
def reset_clip_globals():
    qav._clip_model = None
    qav._clip_preprocess = None
    qav._clip_tokenizer = None
    yield
    qav._clip_model = None
    qav._clip_preprocess = None
    qav._clip_tokenizer = None


@pytest.mark.asyncio
async def test_qa_disabled_returns_default_passing_result():
    ctx = _make_ctx()
    result = await validate(_RAW, _FINAL, ctx, _fake_settings(qa_enabled=False))
    assert isinstance(result, QAResult)
    assert result.qa_passed is True
    assert result.clip_score is None


@pytest.mark.asyncio
async def test_validate_clip_and_ocr_run_in_parallel():
    ctx = _make_ctx()
    call_order = []

    async def mock_clip(image_bytes, ctx):
        call_order.append("clip")
        return 0.30

    async def mock_ocr(image_bytes):
        call_order.append("ocr")
        return True, []

    async def mock_vision(image_bytes, ctx, settings):
        return False, 5, 5, []

    with patch.object(qav, "_clip_check_async", mock_clip):
        with patch.object(qav, "_ocr_check_async", mock_ocr):
            with patch.object(qav, "_vision_check_async", mock_vision):
                result = await validate(_RAW, _FINAL, ctx, _fake_settings())

    assert set(call_order) == {"clip", "ocr"}
    assert result.clip_score == 0.30


@pytest.mark.asyncio
async def test_validate_ocr_fails_on_allergen_word():
    ctx = _make_ctx()

    with patch.object(qav, "_clip_check_async", AsyncMock(return_value=0.30)):
        with patch.object(qav, "_ocr_check_async", AsyncMock(return_value=(False, ["wheat"]))):
            with patch.object(qav, "_vision_check_async", AsyncMock(return_value=(False, 5, 5, []))):
                result = await validate(_RAW, _FINAL, ctx, _fake_settings())

    assert result.ocr_passed is False
    assert "wheat" in result.allergen_words_found
    assert result.qa_passed is False


@pytest.mark.asyncio
async def test_validate_ocr_passes_on_clean_image():
    ctx = _make_ctx()

    with patch.object(qav, "_clip_check_async", AsyncMock(return_value=0.28)):
        with patch.object(qav, "_ocr_check_async", AsyncMock(return_value=(True, []))):
            with patch.object(qav, "_vision_check_async", AsyncMock(return_value=(False, 5, 5, []))):
                result = await validate(_RAW, _FINAL, ctx, _fake_settings())

    assert result.ocr_passed is True
    assert result.allergen_words_found == []


@pytest.mark.asyncio
async def test_validate_clip_score_stored_in_result():
    ctx = _make_ctx()

    with patch.object(qav, "_clip_check_async", AsyncMock(return_value=0.24)):
        with patch.object(qav, "_ocr_check_async", AsyncMock(return_value=(True, []))):
            with patch.object(qav, "_vision_check_async", AsyncMock(return_value=(False, 4, 4, []))):
                result = await validate(_RAW, _FINAL, ctx, _fake_settings())

    assert result.clip_score == pytest.approx(0.24)


@pytest.mark.asyncio
async def test_validate_clip_unavailable_returns_none_score():
    ctx = _make_ctx()

    with patch.object(qav, "_clip_check_async", AsyncMock(return_value=None)):
        with patch.object(qav, "_ocr_check_async", AsyncMock(return_value=(True, []))):
            with patch.object(qav, "_vision_check_async", AsyncMock(return_value=(False, 5, 5, []))):
                result = await validate(_RAW, _FINAL, ctx, _fake_settings())

    assert result.clip_score is None
    assert result.qa_passed is True


@pytest.mark.asyncio
async def test_validate_vision_stray_text_fails_qa():
    ctx = _make_ctx()

    with patch.object(qav, "_clip_check_async", AsyncMock(return_value=0.30)):
        with patch.object(qav, "_ocr_check_async", AsyncMock(return_value=(True, []))):
            with patch.object(qav, "_vision_check_async", AsyncMock(return_value=(True, 4, 4, ["stray text in background"]))):
                result = await validate(_RAW, _FINAL, ctx, _fake_settings())

    assert result.stray_model_text is True
    assert result.qa_passed is False


@pytest.mark.asyncio
async def test_validate_vision_low_brand_fidelity_fails_qa():
    ctx = _make_ctx()

    with patch.object(qav, "_clip_check_async", AsyncMock(return_value=0.30)):
        with patch.object(qav, "_ocr_check_async", AsyncMock(return_value=(True, []))):
            with patch.object(qav, "_vision_check_async", AsyncMock(return_value=(False, 2, 4, ["wrong food subject"]))):
                result = await validate(_RAW, _FINAL, ctx, _fake_settings())

    assert result.brand_fidelity_score == 2
    assert result.qa_passed is False


@pytest.mark.asyncio
async def test_validate_vision_exception_does_not_crash():
    ctx = _make_ctx()

    async def failing_vision(image_bytes, ctx, settings):
        raise TimeoutError("network timeout")

    with patch.object(qav, "_clip_check_async", AsyncMock(return_value=0.30)):
        with patch.object(qav, "_ocr_check_async", AsyncMock(return_value=(True, []))):
            with patch.object(qav, "_vision_check_async", failing_vision):
                result = await validate(_RAW, _FINAL, ctx, _fake_settings())

    assert isinstance(result, QAResult)
    assert result.brand_fidelity_score == 5


@pytest.mark.asyncio
async def test_validate_text_truncated_flag_propagated():
    ctx = _make_ctx()

    with patch.object(qav, "_clip_check_async", AsyncMock(return_value=0.30)):
        with patch.object(qav, "_ocr_check_async", AsyncMock(return_value=(True, []))):
            with patch.object(qav, "_vision_check_async", AsyncMock(return_value=(False, 5, 5, []))):
                result = await validate(_RAW, _FINAL, ctx, _fake_settings(), text_was_truncated=True)

    assert result.text_overflow_detected is True


@pytest.mark.asyncio
async def test_validate_all_checks_pass_qa_passed_true():
    ctx = _make_ctx()

    with patch.object(qav, "_clip_check_async", AsyncMock(return_value=0.30)):
        with patch.object(qav, "_ocr_check_async", AsyncMock(return_value=(True, []))):
            with patch.object(qav, "_vision_check_async", AsyncMock(return_value=(False, 4, 4, []))):
                result = await validate(_RAW, _FINAL, ctx, _fake_settings())

    assert result.qa_passed is True


def _blank_png() -> bytes:
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (100, 100)).save(buf, format="PNG")
    return buf.getvalue()


def _mock_pytesseract(return_value: str | None = None, side_effect=None) -> MagicMock:
    mock = MagicMock()
    if side_effect is not None:
        mock.image_to_string.side_effect = side_effect
    else:
        mock.image_to_string.return_value = return_value
    return mock


def test_run_ocr_sync_finds_allergen():
    with patch.dict(sys.modules, {"pytesseract": _mock_pytesseract("Contains wheat and milk")}):
        passed, found = _run_ocr_sync(_blank_png())

    assert passed is False
    assert "wheat" in found
    assert "milk" in found


def test_run_ocr_sync_clean_image_passes():
    with patch.dict(sys.modules, {"pytesseract": _mock_pytesseract("Delicious tacos with fresh salsa")}):
        passed, found = _run_ocr_sync(_blank_png())

    assert passed is True
    assert found == []


def test_run_ocr_sync_exception_returns_safe_default():
    with patch.dict(sys.modules, {"pytesseract": _mock_pytesseract(side_effect=OSError("not installed"))}):
        passed, found = _run_ocr_sync(_blank_png())

    assert passed is True
    assert found == []

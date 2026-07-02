from __future__ import annotations

import asyncio
import base64
import json
import logging

from app.config import Settings
from schemas.internal import CampaignContext, QAResult
from services.openai_client import get_openai_client

logger = logging.getLogger(__name__)

ALLERGEN_SET = {
    "milk", "eggs", "wheat", "sesame", "shellfish",
    "tree nuts", "peanuts", "soy", "fish", "gluten",
}

_clip_model = None
_clip_preprocess = None
_clip_tokenizer = None
_clip_lock = asyncio.Lock()

CLIP_THRESHOLD = 0.20

_VISION_SYSTEM = (
    "You are a quality assurance system for restaurant marketing images. "
    "Inspect the image and return ONLY valid JSON with these exact keys:\n"
    '{"stray_model_text": bool, "brand_fidelity_score": int, "composition_score": int, "issues": [str]}\n'
    "stray_model_text: true if the AI model rendered text, numbers, labels, or signage in the food scene "
    "background. Ignore text strips at the image edges (those are programmatic overlays, not model output).\n"
    "brand_fidelity_score: 1-5. 5=food subject clearly matches campaign, atmosphere strongly matches brand.\n"
    "composition_score: 1-5. 5=strong focal element, professional editorial quality, correct orientation.\n"
    "issues: list of specific problems observed, empty list if none."
)


async def _ensure_clip_loaded() -> bool:
    global _clip_model, _clip_preprocess, _clip_tokenizer
    if _clip_model is not None:
        return True
    async with _clip_lock:
        if _clip_model is not None:
            return True
        try:
            import open_clip
            model, _, preprocess = await asyncio.to_thread(
                open_clip.create_model_and_transforms,
                "ViT-B-32",
                pretrained="openai",
            )
            model.eval()
            _clip_model = model
            _clip_preprocess = preprocess
            _clip_tokenizer = open_clip.get_tokenizer("ViT-B-32")
            return True
        except Exception as exc:
            logger.warning("CLIP not available, skipping alignment check: %s", exc)
            return False


def _run_clip_sync(image_bytes: bytes, item_text: str) -> float:
    import torch
    from io import BytesIO
    from PIL import Image
    img = _clip_preprocess(Image.open(BytesIO(image_bytes)).convert("RGB")).unsqueeze(0)
    tokens = _clip_tokenizer([f"a photo of {item_text}"])
    with torch.no_grad():
        img_feat = _clip_model.encode_image(img)
        txt_feat = _clip_model.encode_text(tokens)
        img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)
        txt_feat = txt_feat / txt_feat.norm(dim=-1, keepdim=True)
        return float((img_feat @ txt_feat.T).squeeze())


def _run_ocr_sync(image_bytes: bytes) -> tuple[bool, list[str]]:
    try:
        import pytesseract
        from io import BytesIO
        from PIL import Image
        text = pytesseract.image_to_string(Image.open(BytesIO(image_bytes))).lower()
        found = [w for w in ALLERGEN_SET if w in text]
        return len(found) == 0, found
    except Exception as exc:
        logger.warning("OCR check skipped: %s", exc)
        return True, []


async def _clip_check_async(image_bytes: bytes, ctx: CampaignContext) -> float | None:
    if not await _ensure_clip_loaded():
        return None
    item_text = f"{ctx.main_title} {ctx.main_offer}"
    try:
        return await asyncio.to_thread(_run_clip_sync, image_bytes, item_text)
    except Exception as exc:
        logger.warning("CLIP score computation failed: %s", exc)
        return None


async def _ocr_check_async(image_bytes: bytes) -> tuple[bool, list[str]]:
    return await asyncio.to_thread(_run_ocr_sync, image_bytes)


async def _vision_check_async(
    image_bytes: bytes,
    ctx: CampaignContext,
    settings: Settings,
) -> tuple[bool, int, int, list[str]]:
    b64 = base64.b64encode(image_bytes).decode()
    user_content = [
        {
            "type": "text",
            "text": (
                f"Campaign: {ctx.campaign_type} for {ctx.restaurant.restaurant_name}. "
                f"Brand theme: {ctx.restaurant.brand_theme}. "
                f"Hero subject: {ctx.main_title}, {ctx.main_offer}. "
                f"Target aspect ratio: {ctx.aspect_ratio}."
            ),
        },
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"},
        },
    ]
    client = get_openai_client()
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=settings.openai_qa_model,
                max_tokens=300,
                temperature=0.0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _VISION_SYSTEM},
                    {"role": "user", "content": user_content},
                ],
            ),
            timeout=settings.llm_timeout,
        )
        data = json.loads(response.choices[0].message.content or "{}")
        return (
            bool(data.get("stray_model_text", False)),
            int(data.get("brand_fidelity_score", 5)),
            int(data.get("composition_score", 5)),
            list(data.get("issues", [])),
        )
    except Exception as exc:
        logger.warning("Vision QA check failed, proceeding without score: %s", exc)
        return False, 5, 5, []


async def validate(
    raw_image_bytes: bytes,
    final_image_bytes: bytes,
    ctx: CampaignContext,
    settings: Settings,
    text_was_truncated: bool = False,
) -> QAResult:
    if not settings.qa_enabled:
        return QAResult()

    # Tier 0 + Tier 1: CLIP and OCR run in parallel on raw synthesis bytes
    clip_score, (ocr_passed, allergen_words) = await asyncio.gather(
        _clip_check_async(raw_image_bytes, ctx),
        _ocr_check_async(raw_image_bytes),
    )

    # Tier 2: gpt-4.1 vision scoring on final composite image
    try:
        stray_text, brand_score, comp_score, issues = await _vision_check_async(
            final_image_bytes, ctx, settings
        )
    except Exception as exc:
        logger.warning("Vision QA stage failed, proceeding with defaults: %s", exc)
        stray_text, brand_score, comp_score, issues = False, 5, 5, []

    return QAResult(
        ocr_passed=ocr_passed,
        allergen_words_found=allergen_words,
        clip_score=clip_score,
        stray_model_text=stray_text,
        brand_fidelity_score=brand_score,
        composition_score=comp_score,
        text_overflow_detected=text_was_truncated,
        issues=issues,
    )

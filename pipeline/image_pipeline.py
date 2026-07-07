from __future__ import annotations

import asyncio
import collections
import hashlib
import logging
import time
import uuid
from datetime import date
from enum import Enum

import structlog

from app.config import Settings
from schemas.internal import (
    CampaignContext,
    CompositeResult,
    QAResult,
    RequestMetrics,
    StageMetrics,
)
from schemas.request import CampaignPayload
from schemas.response import ImageGenerationResponse, ResponseMetrics, StageBreakdown
from services.cost_table import estimate_image_cost, estimate_token_cost
from services.storage import upload_image
from stages.brand_mapper import ensure_logo, map_brand
from stages.campaign_parser import parse
from stages.image_synthesizer import synthesize
from stages.prompt_generator import generate_prompt
from stages.qa_validator import (
    CLIP_THRESHOLD,
    _clip_check_async,
    _ocr_check_async,
    _vision_check_async,
)
from stages.text_compositor import composite
from stages.validator import validate as validate_payload
from utils.metrics import (
    CLIP_SCORE_HISTOGRAM,
    IMAGE_GENERATION_COST,
    IMAGE_GENERATION_LATENCY,
    IMAGE_GENERATION_REQUESTS_TOTAL,
    QA_RETRY_TOTAL,
    STAGE_LATENCY,
    SYNTHESIS_FALLBACK_TOTAL,
)

logger = structlog.get_logger()

_cache: dict[str, ImageGenerationResponse] = {}
_daily_counts: dict[tuple[int, date], int] = collections.defaultdict(int)


class _FailureCategory(str, Enum):
    SYNTHESIS = "synthesis"
    COMPOSITOR = "compositor"
    BOTH = "both"


def _payload_hash(payload: CampaignPayload) -> str:
    return hashlib.sha256(payload.model_dump_json().encode()).hexdigest()[:16]


def _classify_failure(qa_result: QAResult) -> _FailureCategory:
    synthesis_fail = (
        qa_result.stray_model_text
        or not qa_result.ocr_passed
        or (qa_result.clip_score is not None and qa_result.clip_score < CLIP_THRESHOLD)
    )
    if qa_result.text_overflow_detected and not synthesis_fail:
        return _FailureCategory.COMPOSITOR
    if qa_result.text_overflow_detected and synthesis_fail:
        return _FailureCategory.BOTH
    return _FailureCategory.SYNTHESIS


def _build_retry_suffix(qa_result: QAResult, ctx: CampaignContext) -> str:
    parts: list[str] = []
    if qa_result.stray_model_text:
        parts.append(
            "CRITICAL FAILURE: Previous attempt rendered text or labels in the background. "
            "Regenerate with absolute zero tolerance for any text in the scene."
        )
    if not qa_result.ocr_passed:
        words = ", ".join(qa_result.allergen_words_found)
        parts.append(
            f"ALLERGEN TERMS ({words}) detected in the previous image. "
            "Generate clean food and atmosphere visuals only."
        )
    if qa_result.brand_fidelity_score is not None and qa_result.brand_fidelity_score < 4:
        parts.append(
            f"BRAND FIDELITY SCORE: {qa_result.brand_fidelity_score}/5 — too low. "
            f"Emphasize the restaurant atmosphere ({ctx.restaurant.brand_theme}) more strongly. "
            f"Hero subject must clearly be: {ctx.main_offer}."
        )
    return "\n\n".join(parts)


async def _parallel_clip_ocr(
    raw_bytes: bytes,
    ctx: CampaignContext,
) -> tuple[float | None, tuple[bool, list[str]]]:
    clip_score, ocr_result = await asyncio.gather(
        _clip_check_async(raw_bytes, ctx),
        _ocr_check_async(raw_bytes),
    )
    return clip_score, ocr_result


async def _composite_and_check(
    raw_bytes: bytes,
    ctx: CampaignContext,
    settings: Settings,
) -> tuple[CompositeResult, float | None, tuple[bool, list[str]]]:
    composite_result, (clip_score, ocr_result) = await asyncio.gather(
        composite(raw_bytes, ctx, settings),
        _parallel_clip_ocr(raw_bytes, ctx),
    )
    return composite_result, clip_score, ocr_result


async def run(payload: CampaignPayload, settings: Settings) -> ImageGenerationResponse:
    request_id = uuid.uuid4().hex[:12]
    log = logger.bind(request_id=request_id, restaurant_id=payload.restaurantId)

    cache_key = _payload_hash(payload)
    if cache_key in _cache:
        log.info("cache_hit")
        return _cache[cache_key]

    today = date.today()
    count_key = (payload.restaurantId, today)
    if _daily_counts[count_key] >= settings.max_images_per_restaurant_per_day:
        raise RuntimeError(
            f"Daily image limit ({settings.max_images_per_restaurant_per_day}) reached "
            f"for restaurant {payload.restaurantId}."
        )

    metrics = RequestMetrics(
        request_id=request_id,
        restaurant_id=payload.restaurantId,
        campaign_type=payload.campaign_type,
    )
    t_start = time.perf_counter()

    # Stage 1
    t0 = time.perf_counter()
    validate_payload(payload)
    metrics.stages.append(StageMetrics("validator", None, int((time.perf_counter() - t0) * 1000)))

    # Stage 2
    t0 = time.perf_counter()
    brand = map_brand(payload.restaurantId)
    metrics.stages.append(StageMetrics("brand_mapper", None, int((time.perf_counter() - t0) * 1000)))

    # Kick off logo resolution now, in the background. Only Stage 6 (compositor)
    # needs it, and Stage 4 (prompt) + Stage 5 (image synthesis) below take
    # 15-90s combined versus ~1-2s for a logo fetch, so awaiting this right
    # before Stage 6 needs it adds ~zero wall-clock latency in the common case.
    # ensure_logo() mutates `brand` in place, and ctx.restaurant (set in Stage 3
    # below) holds a reference to this same object, so no reassignment is needed.
    t0_logo = time.perf_counter()
    logo_task = asyncio.create_task(ensure_logo(brand))

    # Stage 3
    t0 = time.perf_counter()
    ctx = parse(payload, brand)
    metrics.stages.append(StageMetrics("campaign_parser", None, int((time.perf_counter() - t0) * 1000)))

    # Stage 4: initial prompt
    t0 = time.perf_counter()
    prompt_response = await generate_prompt(ctx, settings)
    in_t = int(prompt_response.metadata.get("input_tokens", 0))
    out_t = int(prompt_response.metadata.get("output_tokens", 0))
    metrics.stages.append(StageMetrics(
        "prompt_generator", settings.openai_concept_model,
        int((time.perf_counter() - t0) * 1000), in_t, out_t,
        estimate_token_cost(settings.openai_concept_model, in_t, out_t),
    ))

    # Stage 5-7 loop with retry
    synthesis = None
    stray_text, brand_score, comp_score, issues = False, 5, 5, []
    clip_score: float | None = None
    ocr_result: tuple[bool, list[str]] = (True, [])
    image_url = ""
    qa_result = QAResult()
    qa_retries = 0
    need_synthesis = True
    run_vision = True
    last_failure_category: _FailureCategory | None = None

    # Only blocks if the fetch (kicked off right after Stage 2) is somehow
    # still running -- normally a no-op since Stage 4 above already took longer.
    await logo_task
    metrics.stages.append(StageMetrics("logo_fetch", None, int((time.perf_counter() - t0_logo) * 1000)))

    while True:
        if qa_retries > 0 and need_synthesis:
            # Stage 4 retry with failure feedback injected
            retry_suffix = _build_retry_suffix(qa_result, ctx)
            t0 = time.perf_counter()
            prompt_response = await generate_prompt(ctx, settings, retry_suffix=retry_suffix)
            in_t = int(prompt_response.metadata.get("input_tokens", 0))
            out_t = int(prompt_response.metadata.get("output_tokens", 0))
            metrics.stages.append(StageMetrics(
                "prompt_generator_retry", settings.openai_concept_model,
                int((time.perf_counter() - t0) * 1000), in_t, out_t,
                estimate_token_cost(settings.openai_concept_model, in_t, out_t),
            ))

        if need_synthesis:
            # Stage 5
            t0 = time.perf_counter()
            synthesis = await synthesize(prompt_response, ctx, settings)
            synth_cost = estimate_image_cost(synthesis.model_used, settings.openai_image_quality)
            metrics.stages.append(StageMetrics(
                "image_synthesizer", synthesis.model_used,
                int((time.perf_counter() - t0) * 1000),
                estimated_cost_usd=synth_cost,
            ))
            metrics.synthesis_attempt = synthesis.attempt_number
            metrics.synthesis_model = synthesis.model_used
            metrics.orientation_preserved = synthesis.orientation_preserved
            run_vision = True

        # Stage 6 || CLIP+OCR in parallel
        t0 = time.perf_counter()
        composite_result, clip_score, ocr_result = await _composite_and_check(
            synthesis.image_bytes, ctx, settings
        )
        metrics.stages.append(StageMetrics(
            "text_compositor", None, int((time.perf_counter() - t0) * 1000)
        ))

        if run_vision:
            # Stage 7 Tier 2 || R2 upload in parallel
            t0 = time.perf_counter()
            image_url, vision_result = await asyncio.gather(
                upload_image(
                    composite_result.image_bytes, payload.restaurantId, settings,
                    prompt_response.alt_text
                ),
                _vision_check_async(composite_result.image_bytes, ctx, settings),
            )
            stray_text, brand_score, comp_score, issues = vision_result
            qa_cost = estimate_token_cost(settings.openai_qa_model, 210, 85)
            metrics.stages.append(StageMetrics(
                "qa_validator", settings.openai_qa_model,
                int((time.perf_counter() - t0) * 1000), estimated_cost_usd=qa_cost,
            ))
        else:
            # Compositor-only retry: upload new composite, reuse previous vision scores
            t0 = time.perf_counter()
            image_url = await upload_image(
                composite_result.image_bytes, payload.restaurantId, settings,
                prompt_response.alt_text
            )
            metrics.stages.append(StageMetrics(
                "qa_validator_recheck", None, int((time.perf_counter() - t0) * 1000)
            ))

        metrics.clip_score = clip_score
        metrics.ocr_passed = ocr_result[0]
        metrics.allergen_words_found = ocr_result[1]
        metrics.stray_model_text = stray_text
        metrics.brand_fidelity_score = brand_score
        metrics.composition_score = comp_score

        qa_result = QAResult(
            ocr_passed=ocr_result[0],
            allergen_words_found=ocr_result[1],
            clip_score=clip_score,
            stray_model_text=stray_text,
            brand_fidelity_score=brand_score,
            composition_score=comp_score,
            text_overflow_detected=composite_result.text_was_truncated,
            issues=issues,
        )

        if not qa_result.qa_passed and settings.qa_enabled and qa_retries < settings.qa_retry_limit:
            failure_cat = _classify_failure(qa_result)
            last_failure_category = failure_cat
            need_synthesis = failure_cat != _FailureCategory.COMPOSITOR
            run_vision = need_synthesis
            qa_retries += 1
            log.warning("qa_retry", attempt=qa_retries, category=failure_cat, issues=issues)
        else:
            if not qa_result.qa_passed:
                log.warning("qa_failed_after_retries", retries=qa_retries)
            break

    metrics.qa_retries = qa_retries
    metrics.qa_passed = qa_result.qa_passed
    metrics.alt_text = prompt_response.alt_text
    metrics.total_latency_ms = int((time.perf_counter() - t_start) * 1000)
    metrics.total_cost_usd = sum(s.estimated_cost_usd for s in metrics.stages)

    _daily_counts[count_key] += 1

    IMAGE_GENERATION_REQUESTS_TOTAL.labels(
        campaign_type=metrics.campaign_type,
        model=metrics.synthesis_model or "unknown",
        qa_passed=str(metrics.qa_passed).lower(),
    ).inc()
    IMAGE_GENERATION_LATENCY.observe(metrics.total_latency_ms / 1000)
    IMAGE_GENERATION_COST.observe(metrics.total_cost_usd)
    if qa_retries and last_failure_category is not None:
        QA_RETRY_TOTAL.labels(reason=last_failure_category.value).inc(qa_retries)
    if clip_score is not None:
        CLIP_SCORE_HISTOGRAM.observe(clip_score)
    for s in metrics.stages:
        STAGE_LATENCY.labels(stage=s.stage).observe(s.latency_ms / 1000)
    if synthesis.attempt_number > 1:
        SYNTHESIS_FALLBACK_TOTAL.labels(
            from_model=settings.openai_image_model, to_model=synthesis.model_used
        ).inc()

    log.info(
        "request_complete",
        total_latency_ms=metrics.total_latency_ms,
        total_cost_usd=round(metrics.total_cost_usd, 6),
        synthesis_model=metrics.synthesis_model,
        clip_score=metrics.clip_score,
        ocr_passed=metrics.ocr_passed,
        brand_fidelity_score=metrics.brand_fidelity_score,
        qa_retries=metrics.qa_retries,
        qa_passed=metrics.qa_passed,
    )

    response = ImageGenerationResponse(
        image_url=image_url,
        model_used=synthesis.model_used,
        attempt_number=synthesis.attempt_number,
        orientation_preserved=synthesis.orientation_preserved,
        restaurant_name=brand.restaurant_name,
        campaign_type=ctx.campaign_type,
        aspect_ratio=ctx.aspect_ratio,
        generated_prompt=prompt_response.final_image_prompt,
        alt_text=prompt_response.alt_text,
        qa_passed=qa_result.qa_passed,
        qa_retries=qa_retries,
        clip_score=clip_score,
        qa_scores={"brand_fidelity": brand_score, "composition": comp_score},
        metrics=ResponseMetrics(
            total_latency_ms=metrics.total_latency_ms,
            total_cost_usd=round(metrics.total_cost_usd, 6),
            stage_breakdown=[
                StageBreakdown(stage=s.stage, latency_ms=s.latency_ms, cost_usd=s.estimated_cost_usd)
                for s in metrics.stages
            ],
        ),
    )

    _cache[cache_key] = response
    return response

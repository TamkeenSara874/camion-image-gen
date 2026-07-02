from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog

from schemas.internal import RequestMetrics, StageMetrics
from services.cost_table import estimate_stage_cost
from utils.metrics import (
    CLIP_SCORE_HISTOGRAM,
    IMAGE_GENERATION_COST,
    IMAGE_GENERATION_LATENCY,
    IMAGE_GENERATION_REQUESTS_TOTAL,
    STAGE_LATENCY,
)

logger = structlog.get_logger()


def new_request_metrics(restaurant_id: int, campaign_type: str) -> RequestMetrics:
    return RequestMetrics(
        request_id=str(uuid.uuid4()).replace("-", "")[:16],
        restaurant_id=restaurant_id,
        campaign_type=campaign_type,
    )


@asynccontextmanager
async def stage_timer(
    name: str,
    metrics: RequestMetrics,
    model: str | None = None,
) -> AsyncIterator[StageMetrics]:
    # Image synthesizer must set stage.estimated_cost_usd directly; token-only stages get it auto-estimated.
    t0 = time.perf_counter()
    stage = StageMetrics(stage=name, model=model, latency_ms=0)
    failed = False
    try:
        yield stage
    except Exception:
        failed = True
        raise
    finally:
        stage.latency_ms = int((time.perf_counter() - t0) * 1000)
        if stage.estimated_cost_usd == 0.0:
            stage.estimated_cost_usd = estimate_stage_cost(stage)
        metrics.stages.append(stage)
        STAGE_LATENCY.labels(stage=name).observe(stage.latency_ms / 1000)
        logger.info(
            "stage_complete",
            stage=name,
            model=model,
            latency_ms=stage.latency_ms,
            input_tokens=stage.input_tokens,
            output_tokens=stage.output_tokens,
            cost_usd=round(stage.estimated_cost_usd, 6),
            failed=failed,
            request_id=metrics.request_id,
        )


def emit(metrics: RequestMetrics) -> None:
    # Call in try/finally so partial metrics are logged even when the pipeline raises mid-run.
    metrics.total_latency_ms = sum(s.latency_ms for s in metrics.stages)
    metrics.total_cost_usd = sum(s.estimated_cost_usd for s in metrics.stages)

    logger.info(
        "request_complete",
        request_id=metrics.request_id,
        restaurant_id=metrics.restaurant_id,
        campaign_type=metrics.campaign_type,
        total_latency_ms=metrics.total_latency_ms,
        total_cost_usd=round(metrics.total_cost_usd, 6),
        synthesis_attempt=metrics.synthesis_attempt,
        synthesis_model=metrics.synthesis_model,
        orientation_preserved=metrics.orientation_preserved,
        clip_score=metrics.clip_score,
        ocr_passed=metrics.ocr_passed,
        allergen_words_found=metrics.allergen_words_found,
        stray_model_text=metrics.stray_model_text,
        brand_fidelity_score=metrics.brand_fidelity_score,
        composition_score=metrics.composition_score,
        qa_retries=metrics.qa_retries,
        qa_passed=metrics.qa_passed,
        alt_text=metrics.alt_text,
        stages=[
            {
                "stage": s.stage,
                "model": s.model,
                "latency_ms": s.latency_ms,
                "input_tokens": s.input_tokens,
                "output_tokens": s.output_tokens,
                "cost_usd": round(s.estimated_cost_usd, 6),
            }
            for s in metrics.stages
        ],
    )

    IMAGE_GENERATION_REQUESTS_TOTAL.labels(
        campaign_type=metrics.campaign_type,
        model=metrics.synthesis_model or "unknown",
        qa_passed=str(metrics.qa_passed).lower(),
    ).inc()
    IMAGE_GENERATION_LATENCY.observe(metrics.total_latency_ms / 1000)
    IMAGE_GENERATION_COST.observe(metrics.total_cost_usd)
    if metrics.clip_score is not None:
        CLIP_SCORE_HISTOGRAM.observe(metrics.clip_score)

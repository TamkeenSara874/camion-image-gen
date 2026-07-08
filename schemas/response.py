from __future__ import annotations

from pydantic import BaseModel


class StageBreakdown(BaseModel):
    stage: str
    latency_ms: int
    cost_usd: float


class ResponseMetrics(BaseModel):
    total_latency_ms: int
    total_cost_usd: float
    stage_breakdown: list[StageBreakdown]


class ImageGenerationResponse(BaseModel):
    image_url: str
    model_used: str
    attempt_number: int
    orientation_preserved: bool
    restaurant_name: str
    campaign_type: str
    aspect_ratio: str
    generated_prompt: str
    alt_text: str
    qa_passed: bool
    qa_retries: int
    clip_score: float | None
    qa_scores: dict[str, int | None]
    metrics: ResponseMetrics


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: int
    stage: str
    result: ImageGenerationResponse | None = None
    error: str | None = None

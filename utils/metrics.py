from __future__ import annotations

from prometheus_client import Counter, Histogram

IMAGE_GENERATION_REQUESTS_TOTAL = Counter(
    "image_generation_requests_total",
    "Total image generation requests",
    ["campaign_type", "model", "qa_passed"],
)

STAGE_LATENCY = Histogram(
    "stage_latency_seconds",
    "Per-stage wall-clock latency in seconds",
    ["stage"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0],
)

IMAGE_GENERATION_LATENCY = Histogram(
    "image_generation_latency_seconds",
    "End-to-end latency per image generation request",
    buckets=[1, 5, 10, 15, 20, 30, 45, 60, 90, 120],
)

IMAGE_GENERATION_COST = Histogram(
    "image_generation_cost_usd",
    "Estimated cost per request in USD",
    buckets=[0.001, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5],
)

CLIP_SCORE_HISTOGRAM = Histogram(
    "clip_score",
    "CLIP item-alignment cosine similarity score",
    buckets=[0.0, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7, 1.0],
)

SYNTHESIS_FALLBACK_TOTAL = Counter(
    "synthesis_fallback_total",
    "Times image synthesis fell back to a secondary model",
    ["from_model", "to_model"],
)

QA_RETRY_TOTAL = Counter(
    "qa_retry_total",
    "QA-triggered regenerations",
    ["reason"],
)

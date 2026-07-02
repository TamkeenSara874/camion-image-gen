from __future__ import annotations

from schemas.internal import StageMetrics

MODEL_COSTS_USD_PER_1M_TOKENS: dict[str, tuple[float, float]] = {
    # (input_cost_per_1M, output_cost_per_1M)
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-5-mini": (0.50, 2.00),
}

IMAGE_COSTS_USD: dict[str, dict[str, float]] = {
    # {model: {quality: cost_per_image}}
    "gpt-image-2": {"low": 0.011, "medium": 0.042, "high": 0.167},
    "gpt-image-1.5": {"low": 0.008, "medium": 0.030, "high": 0.120},
    "gpt-image-1-mini": {"low": 0.005, "medium": 0.015, "high": 0.060},
}


def estimate_token_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    if model not in MODEL_COSTS_USD_PER_1M_TOKENS:
        return 0.0
    input_rate, output_rate = MODEL_COSTS_USD_PER_1M_TOKENS[model]
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


def estimate_image_cost(model: str, quality: str = "medium") -> float:
    return IMAGE_COSTS_USD.get(model, {}).get(quality, 0.0)


def estimate_stage_cost(stage: StageMetrics) -> float:
    if stage.model is None:
        return 0.0
    if stage.input_tokens > 0 or stage.output_tokens > 0:
        return estimate_token_cost(stage.model, stage.input_tokens, stage.output_tokens)
    return 0.0

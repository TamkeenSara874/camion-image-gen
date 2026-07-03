from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any

import httpx
from openai import BadRequestError

from app.config import Settings
from schemas.internal import CampaignContext, ImagePromptResponse, SynthesisResult
from services.openai_client import get_openai_client

logger = logging.getLogger(__name__)

_HF_URL = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"

_SAFETY_SUFFIX = (
    " Clean professional food photography only. No people, no text, no watermarks, safe content."
)


class _CircuitBreaker:
    def __init__(self, fail_max: int = 5, reset_timeout: float = 60.0) -> None:
        self._fail_max = fail_max
        self._reset_timeout = reset_timeout
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self._reset_timeout:
            self._failures = 0
            self._opened_at = None
            return False
        return True

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._fail_max:
            self._opened_at = time.monotonic()

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def reset(self) -> None:
        self._failures = 0
        self._opened_at = None


_breaker = _CircuitBreaker(fail_max=5, reset_timeout=60.0)


async def _openai_attempt(
    prompt: str,
    model: str,
    size: str,
    quality: str,
    timeout: int,
) -> bytes:
    client = get_openai_client()
    response = await asyncio.wait_for(
        client.images.generate(
            model=model,
            prompt=prompt,
            size=size,
            quality=quality,
            n=1,
        ),
        timeout=timeout,
    )
    b64 = response.data[0].b64_json
    return base64.b64decode(b64)


async def _try_openai(
    prompt: str,
    model: str,
    size: str,
    quality: str,
    settings: Settings,
) -> bytes | None:
    """Returns image bytes, None on content rejection, or raises on service errors."""
    try:
        result = await _openai_attempt(prompt, model, size, quality, settings.image_timeout)
        _breaker.record_success()
        return result
    except BadRequestError:
        return None
    except Exception:
        _breaker.record_failure()
        raise


async def synthesize(
    prompt_response: ImagePromptResponse,
    ctx: CampaignContext,
    settings: Settings,
) -> SynthesisResult:
    prompt = prompt_response.final_image_prompt
    size = ctx.image_size
    quality = settings.openai_image_quality

    if not _breaker.is_open:
        try:
            result = await _try_openai(prompt, settings.openai_image_model, size, quality, settings)
            if result is not None:
                return SynthesisResult(
                    image_bytes=result,
                    model_used=settings.openai_image_model,
                    attempt_number=1,
                )
        except Exception as exc:
            logger.warning(
                "Attempt 1 (%s) failed: %s: %s", settings.openai_image_model, type(exc).__name__, exc
            )

    if not _breaker.is_open:
        sanitized = prompt.rstrip() + _SAFETY_SUFFIX
        try:
            result = await _try_openai(
                sanitized, settings.openai_image_model, size, quality, settings
            )
            if result is not None:
                return SynthesisResult(
                    image_bytes=result,
                    model_used=settings.openai_image_model,
                    attempt_number=2,
                )
        except Exception as exc:
            logger.warning(
                "Attempt 2 (%s, sanitized) failed: %s: %s",
                settings.openai_image_model, type(exc).__name__, exc,
            )

    if not _breaker.is_open:
        try:
            result = await _try_openai(
                prompt, settings.openai_image_fallback_model, size, "medium", settings
            )
            if result is not None:
                return SynthesisResult(
                    image_bytes=result,
                    model_used=settings.openai_image_fallback_model,
                    attempt_number=3,
                )
        except Exception as exc:
            logger.warning(
                "Attempt 3 (%s) failed: %s: %s",
                settings.openai_image_fallback_model, type(exc).__name__, exc,
            )

    if not _breaker.is_open:
        try:
            result = await _try_openai(
                prompt, settings.openai_image_fallback_model_2, size, "low", settings
            )
            if result is not None:
                return SynthesisResult(
                    image_bytes=result,
                    model_used=settings.openai_image_fallback_model_2,
                    attempt_number=4,
                )
        except Exception as exc:
            logger.warning(
                "Attempt 4 (%s) failed: %s: %s",
                settings.openai_image_fallback_model_2, type(exc).__name__, exc,
            )

    if _breaker.is_open:
        logger.warning("Circuit breaker open, skipped all OpenAI attempts this request")

    if settings.hf_token:
        payload: dict[str, Any] = {
            "inputs": prompt,
            "parameters": {
                "num_inference_steps": 4,
                "negative_prompt": prompt_response.negative_prompt,
            },
        }
        async with httpx.AsyncClient(timeout=settings.image_timeout) as http:
            resp = await http.post(
                _HF_URL,
                headers={"Authorization": f"Bearer {settings.hf_token}"},
                json=payload,
            )
            resp.raise_for_status()
        return SynthesisResult(
            image_bytes=resp.content,
            model_used="FLUX.1-schnell",
            attempt_number=5,
            orientation_preserved=(size == "1024x1024"),
        )

    logger.error("All image synthesis attempts failed and no HF_TOKEN is configured")
    raise RuntimeError(
        "All image synthesis attempts failed. "
        "Set HF_TOKEN in .env to enable the free FLUX fallback."
    )

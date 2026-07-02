from __future__ import annotations

from functools import lru_cache

from openai import AsyncOpenAI

from app.config import Settings, get_settings


@lru_cache
def get_openai_client(settings: Settings | None = None) -> AsyncOpenAI:
    if settings is None:
        settings = get_settings()
    return AsyncOpenAI(api_key=settings.openai_api_key)

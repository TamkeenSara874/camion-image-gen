from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    port: int = 8000
    log_level: str = "INFO"
    api_bearer_token: str

    openai_api_key: str
    openai_concept_model: str = "gpt-4o-mini"
    openai_image_model: str = "gpt-image-2"
    openai_image_fallback_model: str = "gpt-image-1.5"
    openai_image_fallback_model_2: str = "gpt-image-1-mini"
    openai_qa_model: str = "gpt-4.1"
    openai_image_quality: Literal["low", "medium", "high"] = "medium"

    hf_token: str = ""

    r2_account_id: str
    r2_access_key_id: str
    r2_secret_access_key: str
    r2_bucket_name: str
    r2_public_url: str

    qa_enabled: bool = True
    qa_retry_limit: int = 2
    qa_brand_fidelity_threshold: int = 4
    image_timeout: int = 120
    llm_timeout: int = 60

    cta_overlay_enabled: bool = False
    max_images_per_restaurant_per_day: int = 50

    model_config = {"env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_startup(settings: Settings) -> None:
    required = {
        "OPENAI_API_KEY": settings.openai_api_key,
        "API_BEARER_TOKEN": settings.api_bearer_token,
        "R2_ACCOUNT_ID": settings.r2_account_id,
        "R2_ACCESS_KEY_ID": settings.r2_access_key_id,
        "R2_SECRET_ACCESS_KEY": settings.r2_secret_access_key,
        "R2_BUCKET_NAME": settings.r2_bucket_name,
        "R2_PUBLIC_URL": settings.r2_public_url,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RestaurantBrand:
    restaurant_id: int
    restaurant_name: str
    cuisine_type: str
    brand_theme: str
    visual_style: str
    website_url: str
    brand_colors: dict[str, str]
    currency_symbol: str = "$"
    logo_path: str | None = None
    style_profile: str = "festive_organic"


@dataclass
class CampaignContext:
    restaurant: RestaurantBrand
    campaign_type: str
    campaign_goal: str
    main_title: str
    main_offer: str
    price: str | None
    cta: bool
    cta_text: str | None
    audience: list[str]
    guest_context_tags: list[str]
    channel: str
    brand_voice: str
    image_size: str
    aspect_ratio: str
    custom_prompt: str | None
    extra_vars: dict[str, Any] = field(default_factory=dict)
    goal_direction: str = ""
    audience_tone: str = ""
    occasion_mood: str = ""


@dataclass
class ImagePromptResponse:
    final_image_prompt: str
    negative_prompt: str = "text, watermark, logo, signage, letters, numbers, blurry"
    alt_text: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class SynthesisResult:
    image_bytes: bytes
    model_used: str
    attempt_number: int
    orientation_preserved: bool = True


@dataclass
class CompositeResult:
    image_bytes: bytes
    mime_type: str = "image/jpeg"
    text_was_truncated: bool = False


@dataclass
class QAResult:
    ocr_passed: bool = True
    allergen_words_found: list[str] = field(default_factory=list)
    clip_score: float | None = None
    stray_model_text: bool = False
    brand_fidelity_score: int | None = None
    composition_score: int | None = None
    text_overflow_detected: bool = False
    issues: list[str] = field(default_factory=list)

    @property
    def qa_passed(self) -> bool:
        return (
            self.ocr_passed
            and not self.stray_model_text
            and (self.brand_fidelity_score is None or self.brand_fidelity_score >= 4)
        )


@dataclass
class StageMetrics:
    stage: str
    model: str | None
    latency_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0


@dataclass
class RequestMetrics:
    request_id: str
    restaurant_id: int
    campaign_type: str
    stages: list[StageMetrics] = field(default_factory=list)
    synthesis_attempt: int = 1
    synthesis_model: str = ""
    orientation_preserved: bool = True
    clip_score: float | None = None
    ocr_passed: bool | None = None
    allergen_words_found: list[str] = field(default_factory=list)
    stray_model_text: bool | None = None
    brand_fidelity_score: int | None = None
    composition_score: int | None = None
    qa_retries: int = 0
    qa_passed: bool = True
    alt_text: str = ""
    total_latency_ms: int = 0
    total_cost_usd: float = 0.0

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, field_validator


class CampaignPayload(BaseModel):
    campaign_type: str
    campaign_goals: str = ""
    campaign_audiences: list[str] = []
    campaign_guest_tags: list[str] = []
    campaign_vars: dict[str, Any]
    cta: bool = False
    channels: list[str] = ["Email"]
    campaign_brand_voices: str = ""
    restaurantId: int  # noqa: N815
    orientation: Literal["Landscape", "Portrait", "Square"] | None = None
    custom_prompt: str | None = None

    @field_validator("campaign_type")
    @classmethod
    def campaign_type_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("campaign_type must not be empty")
        return v

    @field_validator("campaign_guest_tags", mode="before")
    @classmethod
    def coerce_guest_tags(cls, v: Any) -> Any:
        # Upstream sends "" instead of [] when there are no tags (seen in real
        # campaign payloads); Pydantic won't coerce a bare string into a list.
        if v == "" or v is None:
            return []
        if isinstance(v, str):
            return [v]
        return v

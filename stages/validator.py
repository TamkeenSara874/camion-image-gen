from __future__ import annotations

from pydantic import ValidationError

from schemas.campaign_types import CAMPAIGN_REGISTRY
from schemas.request import CampaignPayload


def validate(payload: CampaignPayload) -> None:
    schema_cls = CAMPAIGN_REGISTRY.get(payload.campaign_type)
    if schema_cls is None:
        raise ValueError(
            f"Unknown campaign_type: {payload.campaign_type!r}. Known: {list(CAMPAIGN_REGISTRY)}"
        )
    try:
        schema_cls.model_validate(payload.campaign_vars)
    except ValidationError as exc:
        raise ValueError(
            f"campaign_vars validation failed for {payload.campaign_type}: {exc}"
        ) from exc

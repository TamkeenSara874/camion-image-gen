from __future__ import annotations

import pytest
from pydantic import BaseModel

from schemas.campaign_types import CAMPAIGN_REGISTRY
from schemas.request import CampaignPayload
from stages.validator import validate


class HappyHourVars(BaseModel):
    name: str
    description: str
    discount_percent: int
    hours: str


@pytest.fixture
def happy_hour_registered():
    CAMPAIGN_REGISTRY["Happy Hour"] = HappyHourVars
    yield
    del CAMPAIGN_REGISTRY["Happy Hour"]


def test_new_campaign_type_registers_without_pipeline_changes(happy_hour_registered):
    """A brand-new campaign type is usable via CAMPAIGN_REGISTRY alone -- no
    changes to stages/validator.py or any other pipeline code."""
    assert "Happy Hour" in CAMPAIGN_REGISTRY

    validated = CAMPAIGN_REGISTRY["Happy Hour"].model_validate(
        {
            "name": "Wednesday Happy Hour",
            "description": "Half price cocktails",
            "discount_percent": 50,
            "hours": "4pm-7pm",
        }
    )
    assert validated.discount_percent == 50


def test_new_campaign_type_flows_through_stage1_validator(happy_hour_registered):
    payload = CampaignPayload.model_validate(
        {
            "campaign_type": "Happy Hour",
            "campaign_vars": {
                "name": "Wednesday Happy Hour",
                "description": "Half price cocktails",
                "discount_percent": 50,
                "hours": "4pm-7pm",
            },
            "restaurantId": 2,
        }
    )
    # Should not raise -- Stage 1 resolves the schema purely from the registry.
    validate(payload)


def test_new_campaign_type_missing_required_field_still_rejected(happy_hour_registered):
    payload = CampaignPayload.model_validate(
        {
            "campaign_type": "Happy Hour",
            "campaign_vars": {"name": "Wednesday Happy Hour", "description": "Half price"},
            "restaurantId": 2,
        }
    )
    with pytest.raises(ValueError, match="campaign_vars validation failed"):
        validate(payload)


def test_unregistering_removes_type_cleanly():
    CAMPAIGN_REGISTRY["Temp Type"] = HappyHourVars
    del CAMPAIGN_REGISTRY["Temp Type"]
    assert "Temp Type" not in CAMPAIGN_REGISTRY

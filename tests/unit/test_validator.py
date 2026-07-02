from __future__ import annotations

import pytest

from schemas.request import CampaignPayload
from stages.validator import validate


def _make(campaign_type: str, campaign_vars: dict, **extra) -> CampaignPayload:
    return CampaignPayload.model_validate(
        {"campaign_type": campaign_type, "campaign_vars": campaign_vars, "restaurantId": 2, **extra}
    )


def test_valid_spotlights_passes():
    validate(_make("Spotlights", {"name": "Weekend Fiesta", "description": "Live music and tacos"}))


def test_valid_menu_items_passes():
    validate(
        _make(
            "Menu Items", {"name": "Baja Fish Taco", "description": "Crispy fish on corn tortilla"}
        )
    )


def test_valid_deals_passes():
    validate(
        _make(
            "Deals",
            {"name": "BOGO Tuesday", "deal_type": "BOGO", "deal_type_vars": {"buy": 1, "get": 1}},
        )
    )


def test_unknown_campaign_type_raises():
    with pytest.raises(ValueError, match="Unknown campaign_type"):
        validate(_make("Flash Sale", {"name": "Sale"}))


def test_unknown_type_error_lists_known_types():
    with pytest.raises(ValueError, match="Spotlights"):
        validate(_make("Unknown", {"name": "X"}))


def test_spotlights_missing_name_raises():
    with pytest.raises(ValueError, match="campaign_vars validation failed"):
        validate(_make("Spotlights", {"description": "No name field here"}))


def test_spotlights_missing_description_raises():
    with pytest.raises(ValueError, match="campaign_vars validation failed"):
        validate(_make("Spotlights", {"name": "Weekend Fiesta"}))


def test_menu_items_missing_name_raises():
    with pytest.raises(ValueError, match="campaign_vars validation failed"):
        validate(_make("Menu Items", {"description": "A dish with no name"}))


def test_deals_missing_deal_type_raises():
    with pytest.raises(ValueError, match="campaign_vars validation failed"):
        validate(_make("Deals", {"name": "BOGO", "deal_type_vars": {"buy": 1, "get": 1}}))


def test_deals_missing_deal_type_vars_raises():
    with pytest.raises(ValueError, match="campaign_vars validation failed"):
        validate(_make("Deals", {"name": "BOGO", "deal_type": "BOGO"}))


def test_empty_campaign_type_raises():
    with pytest.raises(ValueError):
        CampaignPayload.model_validate(
            {"campaign_type": "", "campaign_vars": {"name": "X"}, "restaurantId": 2}
        )

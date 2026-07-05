from __future__ import annotations

import json

import pytest

from schemas.internal import RestaurantBrand
from stages.brand_mapper import _load_brands, map_brand


def test_mijos_brand_maps_correctly():
    brand = map_brand(2)
    assert isinstance(brand, RestaurantBrand)
    assert brand.restaurant_name == "Mijo's Taqueria"
    assert brand.cuisine_type == "Mexican"
    assert brand.brand_colors["primary"] == "#4D6D22"
    assert brand.brand_colors["accent"] == "#DCCEC4"
    assert brand.currency_symbol == "$"
    assert brand.restaurant_id == 2


def test_flights_brand_maps_correctly():
    brand = map_brand(4)
    assert brand.restaurant_name == "Flights Restaurant"
    assert brand.brand_colors["primary"] == "#1A2744"
    assert brand.brand_colors["accent"] == "#C9A96E"
    assert brand.restaurant_id == 4


def test_unknown_restaurant_raises():
    with pytest.raises(ValueError, match="restaurantId 999 not found"):
        map_brand(999)


def test_brands_json_loaded_once():
    _load_brands.cache_clear()
    map_brand(2)
    map_brand(4)
    info = _load_brands.cache_info()
    assert info.misses == 1
    assert info.hits == 1
    _load_brands.cache_clear()


def test_new_restaurant_via_config_only(tmp_path, monkeypatch):
    brands_data = {
        "99": {
            "restaurant_name": "TestCafe",
            "cuisine_type": "Fusion",
            "brand_theme": "modern, minimalist",
            "visual_style": "clean whites, muted tones",
            "website_url": "https://testcafe.example.com",
            "brand_colors": {
                "primary": "#2D2D2D",
                "accent": "#F0F0F0",
                "text_on_primary": "#FFFFFF",
            },
            "currency_symbol": "$",
        }
    }
    brands_file = tmp_path / "restaurant_brands.json"
    brands_file.write_text(json.dumps(brands_data))

    import stages.brand_mapper as bm

    monkeypatch.setattr(bm, "BRANDS_PATH", str(brands_file))
    bm._load_brands.cache_clear()

    brand = bm.map_brand(99)
    assert brand.restaurant_name == "TestCafe"
    assert brand.brand_colors["primary"] == "#2D2D2D"
    assert brand.currency_symbol == "$"

    bm._load_brands.cache_clear()


def test_brand_has_all_required_fields():
    brand = map_brand(2)
    assert brand.brand_theme
    assert brand.visual_style
    assert brand.website_url
    assert "primary" in brand.brand_colors
    assert "accent" in brand.brand_colors


def test_mijos_and_flights_resolve_to_real_logo_files():
    import os

    mijos = map_brand(2)
    flights = map_brand(4)
    assert mijos.logo_path is not None and os.path.isfile(mijos.logo_path)
    assert flights.logo_path is not None and os.path.isfile(flights.logo_path)


def test_missing_logo_file_degrades_to_none_instead_of_crashing(tmp_path, monkeypatch):
    """A restaurant config can reference a logo_path that doesn't exist on disk
    (e.g. not yet sourced for a brand-new restaurant). This must never crash
    image generation -- it degrades to the compositor's text fallback."""
    brands_data = {
        "100": {
            "restaurant_name": "NoLogoYet",
            "cuisine_type": "Fusion",
            "brand_theme": "modern",
            "visual_style": "clean",
            "website_url": "https://nologoyet.example.com",
            "logo_path": "config/logos/does-not-exist.png",
            "brand_colors": {"primary": "#111111", "accent": "#EEEEEE", "text_on_primary": "#FFFFFF"},
        }
    }
    brands_file = tmp_path / "restaurant_brands.json"
    brands_file.write_text(json.dumps(brands_data))

    import stages.brand_mapper as bm

    monkeypatch.setattr(bm, "BRANDS_PATH", str(brands_file))
    bm._load_brands.cache_clear()

    brand = bm.map_brand(100)
    assert brand.logo_path is None

    bm._load_brands.cache_clear()


def test_absent_logo_path_key_resolves_to_none(tmp_path, monkeypatch):
    brands_data = {
        "101": {
            "restaurant_name": "NoLogoKey",
            "cuisine_type": "Fusion",
            "brand_theme": "modern",
            "visual_style": "clean",
            "website_url": "https://nologokey.example.com",
            "brand_colors": {"primary": "#111111", "accent": "#EEEEEE", "text_on_primary": "#FFFFFF"},
        }
    }
    brands_file = tmp_path / "restaurant_brands.json"
    brands_file.write_text(json.dumps(brands_data))

    import stages.brand_mapper as bm

    monkeypatch.setattr(bm, "BRANDS_PATH", str(brands_file))
    bm._load_brands.cache_clear()

    brand = bm.map_brand(101)
    assert brand.logo_path is None

    bm._load_brands.cache_clear()

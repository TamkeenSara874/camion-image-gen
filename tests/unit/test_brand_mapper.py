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
    assert brand.brand_colors["primary"] == "#C8410A"
    assert brand.brand_colors["accent"] == "#F5A623"
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

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from schemas.internal import RestaurantBrand
from stages.brand_mapper import _load_brands, ensure_logo, map_brand


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


def test_mijos_and_flights_have_distinct_explicit_style_profiles():
    assert map_brand(2).style_profile == "festive_organic"
    assert map_brand(4).style_profile == "refined_minimal"


def test_missing_style_profile_key_defaults_to_festive_organic(tmp_path, monkeypatch):
    brands_data = {
        "102": {
            "restaurant_name": "NoStyleYet",
            "cuisine_type": "Fusion",
            "brand_theme": "modern",
            "visual_style": "clean",
            "website_url": "https://nostyleyet.example.com",
            "brand_colors": {"primary": "#111111", "accent": "#EEEEEE", "text_on_primary": "#FFFFFF"},
        }
    }
    brands_file = tmp_path / "restaurant_brands.json"
    brands_file.write_text(json.dumps(brands_data))

    import stages.brand_mapper as bm

    monkeypatch.setattr(bm, "BRANDS_PATH", str(brands_file))
    bm._load_brands.cache_clear()

    brand = bm.map_brand(102)
    assert brand.style_profile == "festive_organic"

    bm._load_brands.cache_clear()


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


def _make_test_brand(restaurant_id: int, website_url: str = "https://example.com", logo_path=None):
    return RestaurantBrand(
        restaurant_id=restaurant_id,
        restaurant_name="Test Spot",
        cuisine_type="Fusion",
        brand_theme="modern",
        visual_style="clean",
        website_url=website_url,
        brand_colors={"primary": "#111111", "accent": "#EEEEEE", "text_on_primary": "#FFFFFF"},
        logo_path=logo_path,
    )


def test_resolve_logo_path_falls_back_to_conventional_location(tmp_path, monkeypatch):
    import stages.brand_mapper as bm

    monkeypatch.setattr(bm, "_REPO_ROOT", tmp_path)
    logos_dir = tmp_path / "config" / "logos"
    logos_dir.mkdir(parents=True)
    (logos_dir / "55.png").write_bytes(b"fake-png")

    # No explicit logo_path in config (as if never manually onboarded) -- must
    # still find whatever an earlier ensure_logo() auto-fetch saved there.
    resolved = bm._resolve_logo_path(None, 55)
    assert resolved == str(logos_dir / "55.png")


def test_resolve_logo_path_returns_none_when_conventional_file_absent(tmp_path, monkeypatch):
    import stages.brand_mapper as bm

    monkeypatch.setattr(bm, "_REPO_ROOT", tmp_path)
    assert bm._resolve_logo_path(None, 999) is None


async def test_ensure_logo_skips_fetch_when_logo_already_present():
    brand = _make_test_brand(2, logo_path="config/logos/2.png")
    with patch("stages.brand_mapper.fetch_logo_url") as mock_fetch:
        result = await ensure_logo(brand)
    mock_fetch.assert_not_called()
    assert result.logo_path == "config/logos/2.png"


async def test_ensure_logo_skips_fetch_when_no_website_url():
    brand = _make_test_brand(999, website_url="")
    with patch("stages.brand_mapper.fetch_logo_url") as mock_fetch:
        result = await ensure_logo(brand)
    mock_fetch.assert_not_called()
    assert result.logo_path is None


async def test_ensure_logo_fetches_and_mutates_brand_in_place(tmp_path):
    import stages.brand_mapper as bm

    bm._last_fetch_attempt.clear()
    fake_path = tmp_path / "7.png"
    fake_path.write_bytes(b"fake-png-bytes")
    brand = _make_test_brand(7, website_url="https://newspot.example.com")

    with (
        patch(
            "stages.brand_mapper.fetch_logo_url",
            return_value=("https://newspot.example.com/logo.png", "og_image_or_favicon"),
        ) as mock_fetch,
        patch("stages.brand_mapper.download_logo", return_value=fake_path) as mock_download,
    ):
        result = await ensure_logo(brand)

    mock_fetch.assert_called_once_with("https://newspot.example.com")
    mock_download.assert_called_once_with("https://newspot.example.com/logo.png", 7)
    assert result is brand  # mutated in place, not replaced
    assert result.logo_path == str(fake_path)
    bm._last_fetch_attempt.clear()


async def test_ensure_logo_failed_fetch_leaves_logo_path_none_without_raising():
    import stages.brand_mapper as bm

    bm._last_fetch_attempt.clear()
    brand = _make_test_brand(8, website_url="https://down.example.com")

    with patch("stages.brand_mapper.fetch_logo_url", side_effect=RuntimeError("site unreachable")):
        result = await ensure_logo(brand)  # must not raise

    assert result.logo_path is None
    bm._last_fetch_attempt.clear()


async def test_ensure_logo_respects_cooldown_after_a_failed_attempt():
    import stages.brand_mapper as bm

    bm._last_fetch_attempt.clear()
    brand = _make_test_brand(9, website_url="https://flaky.example.com")

    with patch("stages.brand_mapper.fetch_logo_url", side_effect=RuntimeError("boom")) as mock_fetch:
        await ensure_logo(brand)
        await ensure_logo(brand)  # second attempt in the same burst

    assert mock_fetch.call_count == 1  # cooldown skipped the second attempt
    bm._last_fetch_attempt.clear()

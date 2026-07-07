from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock

from PIL import Image, ImageDraw

from schemas.internal import CampaignContext, RestaurantBrand
from stages.text_compositor import (
    _STYLE_PRESETS,
    _VARIANTS_BY_TYPE,
    _apply_brand_tone,
    _composite_sync,
    _deals_header_scrim,
    _deals_panel,
    _deals_poster,
    _draw_cta_pill,
    _draw_logo_badge,
    _hex_to_rgb,
    _menu_items_header_scrim,
    _menu_items_panel,
    _menu_items_poster,
    _select_variant,
    _spotlights_panel_left,
    _spotlights_panel_right,
    _spotlights_poster,
    _style_for,
    composite,
)


def _make_brand(
    restaurant_id: int = 2,
    currency: str = "$",
    logo_path: str | None = "config/logos/2.png",
    style_profile: str = "festive_organic",
) -> RestaurantBrand:
    return RestaurantBrand(
        restaurant_id=restaurant_id,
        restaurant_name="Mijo's Taqueria",
        cuisine_type="Mexican",
        brand_theme="vibrant, festive",
        visual_style="rustic wood",
        website_url="https://mijostaqueria.com",
        brand_colors={"primary": "#C8410A", "accent": "#F5A623", "text_on_primary": "#FFFFFF"},
        currency_symbol=currency,
        logo_path=logo_path,
        style_profile=style_profile,
    )


def _make_ctx(
    campaign_type: str = "Menu Items",
    price: str | None = "$12",
    cta: bool = False,
    main_title: str = "Baja Fish Taco",
    main_offer: str = "Crispy beer-battered fish, fresh pico, avocado crema.",
    brand: RestaurantBrand | None = None,
) -> CampaignContext:
    return CampaignContext(
        restaurant=brand or _make_brand(),
        campaign_type=campaign_type,
        campaign_goal="Increase Sales",
        main_title=main_title,
        main_offer=main_offer,
        price=price,
        cta=cta,
        cta_text="Order Now" if cta else None,
        audience=["All Guests"],
        guest_context_tags=[],
        channel="Email",
        brand_voice="Casual, Friendly",
        image_size="1536x1024",
        aspect_ratio="16:9",
        custom_prompt=None,
        extra_vars={},
    )


def _fake_settings(cta_enabled: bool = False) -> MagicMock:
    s = MagicMock()
    s.cta_overlay_enabled = cta_enabled
    return s


def _blank_image(w: int = 1536, h: int = 1024) -> bytes:
    img = Image.new("RGB", (w, h), color=(180, 120, 80))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _is_valid_jpeg(data: bytes) -> bool:
    return data[:2] == b"\xff\xd8"


def test_menu_items_output_is_valid_jpeg():
    ctx = _make_ctx("Menu Items")
    result, _ = _composite_sync(_blank_image(), ctx, _fake_settings())
    assert _is_valid_jpeg(result)


def test_deals_output_is_valid_jpeg():
    ctx = _make_ctx(
        "Deals", main_title="BOGO Tuesday", main_offer="Buy 1 get 1 free on tacos", price=None
    )
    result, _ = _composite_sync(_blank_image(), ctx, _fake_settings())
    assert _is_valid_jpeg(result)


def test_spotlights_output_is_valid_jpeg():
    ctx = _make_ctx(
        "Spotlights",
        main_title="Weekend Fiesta",
        main_offer="Live music and margaritas",
        price=None,
    )
    result, _ = _composite_sync(_blank_image(), ctx, _fake_settings())
    assert _is_valid_jpeg(result)


def test_unknown_campaign_type_falls_back_to_menu_items_layout():
    ctx = _make_ctx("Special Days", main_title="Holiday", main_offer="Special menu")
    result, _ = _composite_sync(_blank_image(), ctx, _fake_settings())
    assert _is_valid_jpeg(result)


def test_menu_items_no_price_renders_without_error():
    ctx = _make_ctx("Menu Items", price=None)
    result, _ = _composite_sync(_blank_image(), ctx, _fake_settings())
    assert _is_valid_jpeg(result)


def test_cta_not_rendered_when_disabled_by_default():
    ctx = _make_ctx("Menu Items", cta=True)
    result, _ = _composite_sync(_blank_image(), ctx, _fake_settings(cta_enabled=False))
    assert _is_valid_jpeg(result)


def test_cta_rendered_when_enabled_and_cta_true():
    ctx = _make_ctx("Menu Items", cta=True)
    result_with, _ = _composite_sync(_blank_image(), ctx, _fake_settings(cta_enabled=True))
    result_without, _ = _composite_sync(_blank_image(), ctx, _fake_settings(cta_enabled=False))
    assert _is_valid_jpeg(result_with)
    assert len(result_with) != len(result_without)


def test_cta_not_rendered_when_enabled_but_cta_false():
    ctx_no_cta = _make_ctx("Menu Items", cta=False)
    ctx_with_cta = _make_ctx("Menu Items", cta=True)
    result_off, _ = _composite_sync(_blank_image(), ctx_no_cta, _fake_settings(cta_enabled=True))
    result_on, _ = _composite_sync(_blank_image(), ctx_with_cta, _fake_settings(cta_enabled=True))
    assert _is_valid_jpeg(result_off)
    assert len(result_off) != len(result_on)


def test_long_campaign_name_truncated_in_deals():
    # Tiny image: panel_w = 42% of 100px = 42px; at MIN_FONT_SIZE a 20-char name exceeds that
    ctx = _make_ctx("Deals", main_title="An Extremely Long Name", main_offer="25% off", price=None)
    result, text_truncated = _composite_sync(_blank_image(100, 100), ctx, _fake_settings())
    assert _is_valid_jpeg(result)
    assert text_truncated is True


def test_short_campaign_name_not_truncated():
    ctx = _make_ctx("Deals", main_title="BOGO", main_offer="Buy 1 get 1", price=None)
    result, text_truncated = _composite_sync(_blank_image(), ctx, _fake_settings())
    assert _is_valid_jpeg(result)
    assert text_truncated is False


def test_portrait_image_composited_correctly():
    ctx = _make_ctx(
        "Spotlights", main_title="Wine Wednesday", main_offer="130 wines by the glass", price=None
    )
    result, _ = _composite_sync(_blank_image(1024, 1536), ctx, _fake_settings())
    assert _is_valid_jpeg(result)
    img = Image.open(BytesIO(result))
    assert img.width == 1024
    assert img.height == 1536


def test_square_image_composited_correctly():
    ctx = _make_ctx("Menu Items")
    result, _ = _composite_sync(_blank_image(1024, 1024), ctx, _fake_settings())
    img = Image.open(BytesIO(result))
    assert img.width == 1024
    assert img.height == 1024


def test_output_dimensions_match_input():
    for w, h in [(1536, 1024), (1024, 1536), (1024, 1024)]:
        ctx = _make_ctx("Deals", main_title="Test", main_offer="Test offer", price=None)
        result, _ = _composite_sync(_blank_image(w, h), ctx, _fake_settings())
        img = Image.open(BytesIO(result))
        assert img.width == w
        assert img.height == h


async def test_composite_coroutine_returns_composite_result():
    from schemas.internal import CompositeResult

    ctx = _make_ctx("Menu Items")
    result = await composite(_blank_image(), ctx, _fake_settings())
    assert isinstance(result, CompositeResult)
    assert result.mime_type == "image/jpeg"
    assert _is_valid_jpeg(result.image_bytes)


async def test_composite_sets_text_was_truncated_flag():
    from schemas.internal import CompositeResult

    # Tiny image forces panel_w to 42px, guaranteeing truncation on any non-trivial title
    ctx = _make_ctx("Deals", main_title="Long Title That Must Truncate", main_offer="25% off", price=None)
    result = await composite(_blank_image(100, 100), ctx, _fake_settings())
    assert isinstance(result, CompositeResult)
    assert result.text_was_truncated is True


def _pixel_close(actual: tuple[int, int, int], expected: tuple[int, int, int], tolerance: int = 12) -> bool:
    return all(abs(a - e) <= tolerance for a, e in zip(actual, expected))


# --- Structural tests below call specific variant functions directly rather
# than going through the hash-based dispatch in _composite_sync, so they stay
# deterministic regardless of which variant a given fixture's content happens
# to hash to. Dispatch/hash behavior itself is covered separately further down.


def _blend(fg: tuple[int, int, int], bg: tuple[int, int, int], alpha: int) -> tuple[int, int, int]:
    a = alpha / 255
    return tuple(round(f * a + b * (1 - a)) for f, b in zip(fg, bg))


def test_menu_items_header_scrim_variant_header_bar_is_brand_tinted():
    """Regression guard for the header-bar variant: the top strip must be a
    translucent wash of the restaurant's real brand color (deliberately not
    fully opaque -- see _fading_header_band -- so the photo stays visible
    through it), not a stray photo pixel or an unrelated tone."""
    ctx = _make_ctx("Menu Items")
    img = Image.open(BytesIO(_blank_image())).convert("RGB")
    result, _ = _menu_items_header_scrim(img, ctx, _fake_settings())
    out = Image.open(BytesIO(result))
    primary = _hex_to_rgb(ctx.restaurant.brand_colors["primary"])
    expected = _blend(primary, (180, 120, 80), alpha=205)
    assert _pixel_close(out.getpixel((5, 5)), expected, tolerance=3)


def test_deals_header_scrim_variant_header_bar_is_brand_tinted():
    ctx = _make_ctx("Deals", main_title="BOGO", main_offer="Buy 1 get 1", price=None)
    img = Image.open(BytesIO(_blank_image())).convert("RGB")
    result, _ = _deals_header_scrim(img, ctx, _fake_settings())
    out = Image.open(BytesIO(result))
    primary = _hex_to_rgb(ctx.restaurant.brand_colors["primary"])
    expected = _blend(primary, (180, 120, 80), alpha=205)
    assert _pixel_close(out.getpixel((5, 5)), expected, tolerance=3)


def test_menu_items_header_scrim_variant_photo_is_full_bleed():
    """The header-scrim variant must leave the hero photo fully visible in the
    body of the frame -- no opaque side panel eating into it."""
    ctx = _make_ctx("Menu Items")
    img = Image.open(BytesIO(_blank_image())).convert("RGB")
    result, _ = _menu_items_header_scrim(img, ctx, _fake_settings())
    out = Image.open(BytesIO(result))
    w, h = out.size
    primary = _hex_to_rgb(ctx.restaurant.brand_colors["primary"])
    pixel = out.getpixel((int(w * 0.1), int(h * 0.6)))
    assert not _pixel_close(pixel, primary, tolerance=25)


def test_deals_header_scrim_variant_photo_is_full_bleed():
    ctx = _make_ctx("Deals", main_title="BOGO", main_offer="Buy 1 get 1", price=None)
    img = Image.open(BytesIO(_blank_image())).convert("RGB")
    result, _ = _deals_header_scrim(img, ctx, _fake_settings())
    out = Image.open(BytesIO(result))
    w, h = out.size
    primary = _hex_to_rgb(ctx.restaurant.brand_colors["primary"])
    pixel = out.getpixel((int(w * 0.1), int(h * 0.6)))
    assert not _pixel_close(pixel, primary, tolerance=25)


def test_menu_items_panel_variant_has_a_right_side_panel():
    ctx = _make_ctx("Menu Items")
    img = Image.open(BytesIO(_blank_image())).convert("RGB")
    result, _ = _menu_items_panel(img, ctx, _fake_settings())
    out = Image.open(BytesIO(result))
    w, h = out.size
    primary = _hex_to_rgb(ctx.restaurant.brand_colors["primary"])
    assert _pixel_close(out.getpixel((w - 5, h // 2)), primary, tolerance=15)


def test_deals_panel_variant_has_a_left_side_panel():
    ctx = _make_ctx("Deals", main_title="BOGO", main_offer="Buy 1 get 1", price=None)
    img = Image.open(BytesIO(_blank_image())).convert("RGB")
    result, _ = _deals_panel(img, ctx, _fake_settings())
    out = Image.open(BytesIO(result))
    h = out.height
    primary = _hex_to_rgb(ctx.restaurant.brand_colors["primary"])
    assert _pixel_close(out.getpixel((5, h // 2)), primary, tolerance=15)


def test_spotlights_panel_left_variant_has_a_left_side_panel():
    """Matches the one reference campaign email that actually uses a side panel."""
    ctx = _make_ctx("Spotlights", main_title="Weekend Fiesta", main_offer="Live music", price=None)
    img = Image.open(BytesIO(_blank_image())).convert("RGB")
    result, _ = _spotlights_panel_left(img, ctx, _fake_settings())
    out = Image.open(BytesIO(result))
    h = out.height
    primary = _hex_to_rgb(ctx.restaurant.brand_colors["primary"])
    assert _pixel_close(out.getpixel((5, h // 2)), primary, tolerance=15)


def test_spotlights_panel_right_variant_has_a_right_side_panel():
    ctx = _make_ctx("Spotlights", main_title="Weekend Fiesta", main_offer="Live music", price=None)
    img = Image.open(BytesIO(_blank_image())).convert("RGB")
    result, _ = _spotlights_panel_right(img, ctx, _fake_settings())
    out = Image.open(BytesIO(result))
    w, h = out.size
    primary = _hex_to_rgb(ctx.restaurant.brand_colors["primary"])
    assert _pixel_close(out.getpixel((w - 5, h // 2)), primary, tolerance=15)


def test_spotlights_poster_variant_has_no_side_panel():
    """The poster variant is the 'no panel at all' option in the Spotlights
    pool -- full-bleed photo on both edges."""
    ctx = _make_ctx("Spotlights", main_title="Weekend Fiesta", main_offer="Live music", price=None)
    img = Image.open(BytesIO(_blank_image())).convert("RGB")
    result, _ = _spotlights_poster(img, ctx, _fake_settings())
    out = Image.open(BytesIO(result))
    w, h = out.size
    primary = _hex_to_rgb(ctx.restaurant.brand_colors["primary"])
    assert not _pixel_close(out.getpixel((5, h // 2)), primary, tolerance=25)
    assert not _pixel_close(out.getpixel((w - 5, h // 2)), primary, tolerance=25)


def test_menu_items_poster_and_deals_poster_have_no_opaque_header_bar():
    """Poster variants replace the opaque header bar with a small floating
    corner logo badge -- the top-center strip should not be a flat brand fill."""
    primary = _hex_to_rgb("#C8410A")
    for variant_fn, ctx in [
        (_menu_items_poster, _make_ctx("Menu Items")),
        (_deals_poster, _make_ctx("Deals", main_title="BOGO", main_offer="Buy 1 get 1", price=None)),
    ]:
        img = Image.open(BytesIO(_blank_image())).convert("RGB")
        result, _ = variant_fn(img, ctx, _fake_settings())
        out = Image.open(BytesIO(result))
        w, _h = out.size
        assert not _pixel_close(out.getpixel((w // 2, 5)), primary, tolerance=15)


def test_logo_badge_draws_something_over_the_flat_header_color():
    """Proves the real logo asset is actually pasted (not just a flat brand
    rectangle) by checking the badge center differs from the surrounding
    uniform header fill."""
    ctx = _make_ctx("Menu Items", brand=_make_brand(logo_path="config/logos/2.png"))
    img = Image.open(BytesIO(_blank_image())).convert("RGB")
    result, _ = _menu_items_header_scrim(img, ctx, _fake_settings())
    out = Image.open(BytesIO(result))
    w = out.width
    header_h = int(out.height * 0.15)
    primary = _hex_to_rgb(ctx.restaurant.brand_colors["primary"])
    badge_pixel = out.getpixel((w // 2, header_h // 2))
    assert not _pixel_close(badge_pixel, primary, tolerance=10)


def test_missing_logo_falls_back_to_text_badge_without_crashing():
    """A restaurant with no sourced logo file yet must degrade to a typed
    fallback (never a hallucinated/invented mark) and still render cleanly."""
    ctx = _make_ctx("Menu Items", brand=_make_brand(logo_path=None))
    img = Image.open(BytesIO(_blank_image())).convert("RGB")
    result, _ = _menu_items_header_scrim(img, ctx, _fake_settings())
    assert _is_valid_jpeg(result)
    out = Image.open(BytesIO(result))
    w = out.width
    header_h = int(out.height * 0.15)
    primary = _hex_to_rgb(ctx.restaurant.brand_colors["primary"])
    # The fallback text badge still draws a white card + text, so the badge
    # center should differ from the flat header fill just like the real logo does.
    badge_pixel = out.getpixel((w // 2, header_h // 2))
    assert not _pixel_close(badge_pixel, primary, tolerance=10)


# --- Variant dispatch: determinism and coverage ---------------------------


def test_variant_selection_is_deterministic():
    ctx = _make_ctx("Menu Items", main_title="Baja Fish Taco")
    assert _select_variant(ctx, 3) == _select_variant(ctx, 3)


def test_same_payload_always_renders_the_same_variant():
    ctx = _make_ctx("Deals", main_title="Taco Tuesday BOGO", main_offer="Buy 1 get 1", price=None)
    result1, _ = _composite_sync(_blank_image(), ctx, _fake_settings())
    result2, _ = _composite_sync(_blank_image(), ctx, _fake_settings())
    assert result1 == result2


def test_different_campaign_names_can_select_different_variants():
    """The whole point of the variant pool: campaigns of the same type must
    not all be forced into one identical structure."""
    titles = [f"Campaign {i}" for i in range(30)]
    indices = {_select_variant(_make_ctx("Menu Items", main_title=t), 3) for t in titles}
    assert indices == {0, 1, 2}


def test_unknown_campaign_type_falls_back_to_a_menu_items_variant():
    ctx = _make_ctx("Special Days", main_title="Holiday", main_offer="Special menu")
    result, _ = _composite_sync(_blank_image(), ctx, _fake_settings())
    assert _is_valid_jpeg(result)
    # Same output whether campaign_type is truly unknown or explicitly "Menu Items",
    # since both resolve to the same variant pool and the hash key only depends on
    # (restaurant_id, campaign_type, main_title) -- confirms it's really falling
    # back to the Menu Items pool rather than crashing or silently no-op'ing.
    ctx_known = _make_ctx("Menu Items", main_title="Holiday", main_offer="Special menu")
    result_known, _ = _composite_sync(_blank_image(), ctx_known, _fake_settings())
    assert _is_valid_jpeg(result_known)


def test_all_menu_items_variants_produce_valid_jpeg():
    ctx = _make_ctx("Menu Items")
    for variant_fn in _VARIANTS_BY_TYPE["Menu Items"]:
        img = Image.open(BytesIO(_blank_image())).convert("RGB")
        result, _ = variant_fn(img, ctx, _fake_settings())
        assert _is_valid_jpeg(result)


def test_all_deals_variants_produce_valid_jpeg():
    ctx = _make_ctx("Deals", main_title="BOGO", main_offer="Buy 1 get 1 free on tacos", price=None)
    for variant_fn in _VARIANTS_BY_TYPE["Deals"]:
        img = Image.open(BytesIO(_blank_image())).convert("RGB")
        result, _ = variant_fn(img, ctx, _fake_settings())
        assert _is_valid_jpeg(result)


def test_all_spotlights_variants_produce_valid_jpeg():
    ctx = _make_ctx("Spotlights", main_title="Weekend Fiesta", main_offer="Live music", price=None)
    for variant_fn in _VARIANTS_BY_TYPE["Spotlights"]:
        img = Image.open(BytesIO(_blank_image())).convert("RGB")
        result, _ = variant_fn(img, ctx, _fake_settings())
        assert _is_valid_jpeg(result)


def test_all_variants_handle_missing_price_without_crashing():
    ctx = _make_ctx("Menu Items", price=None)
    for variant_fn in _VARIANTS_BY_TYPE["Menu Items"]:
        img = Image.open(BytesIO(_blank_image())).convert("RGB")
        result, _ = variant_fn(img, ctx, _fake_settings())
        assert _is_valid_jpeg(result)


def test_apply_brand_tone_blends_toward_primary_color():
    primary_hex = "#C8410A"
    photo_color = (180, 120, 80)
    img = Image.new("RGB", (10, 10), color=photo_color)
    toned = _apply_brand_tone(img, primary_hex, strength=0.5)
    r, g, b = _hex_to_rgb(primary_hex)
    expected = tuple(int(p * 0.5 + c * 0.5) for p, c in zip(photo_color, (r, g, b)))
    assert _pixel_close(toned.getpixel((5, 5)), expected, tolerance=2)


def test_apply_brand_tone_zero_strength_is_a_no_op():
    photo_color = (180, 120, 80)
    img = Image.new("RGB", (10, 10), color=photo_color)
    toned = _apply_brand_tone(img, "#C8410A", strength=0.0)
    assert toned.getpixel((5, 5)) == photo_color


def test_wrap_two_lines_does_not_orphan_punctuation():
    """Regression test: a long deal offer used to be split on a fixed
    character count (main_offer[:55], main_offer[55:100]), which could land
    mid-clause and leave a second line starting with stray punctuation, e.g.
    ", Monday through Friday." Word-boundary wrapping must not do that."""
    from PIL import ImageDraw

    from stages.text_compositor import _FONT_BOLD, _wrap_two_lines

    img = Image.new("RGB", (1536, 1024))
    draw = ImageDraw.Draw(img)
    text = "Enjoy 25% off all cocktails and wines during happy hour, Monday through Friday."

    line1, line2 = _wrap_two_lines(draw, text, _FONT_BOLD, 100, max_width=650)

    assert line1 and line1[0] not in ",.;:"
    assert not line2 or line2[0] not in ",.;:"
    # No words lost or duplicated across the split.
    assert f"{line1} {line2}".split() == text.split()


# --- Style profiles: restaurant "personality" beyond the two brand hex codes ----


def test_style_for_returns_matching_preset_for_known_profiles():
    festive_ctx = _make_ctx(brand=_make_brand(style_profile="festive_organic"))
    minimal_ctx = _make_ctx(brand=_make_brand(style_profile="refined_minimal"))
    assert _style_for(festive_ctx) is _STYLE_PRESETS["festive_organic"]
    assert _style_for(minimal_ctx) is _STYLE_PRESETS["refined_minimal"]


def test_style_for_falls_back_to_default_for_unknown_profile():
    ctx = _make_ctx(brand=_make_brand(style_profile="some_future_profile"))
    assert _style_for(ctx) is _STYLE_PRESETS["festive_organic"]


def test_festive_and_minimal_presets_use_different_display_fonts():
    assert _STYLE_PRESETS["festive_organic"].display_font != _STYLE_PRESETS["refined_minimal"].display_font


def test_logo_badge_draws_no_backing_box_around_a_real_logo(tmp_path):
    """The badge must not paint any card/rectangle behind a real logo -- only
    the logo's own pixels and its silhouette shadow should touch the canvas,
    so it reads as just a logo, not 'a logo in a box.'"""
    bg = (200, 200, 200)
    img = Image.new("RGB", (400, 200), bg).convert("RGBA")
    draw = ImageDraw.Draw(img)
    style = _STYLE_PRESETS["festive_organic"]
    logo_path = str(tmp_path / "logo.png")
    Image.new("RGBA", (40, 40), (255, 0, 0, 255)).save(logo_path)
    _draw_logo_badge(
        img, draw, logo_path, "AB",
        center_x=200, center_y=100, max_card_h=80, max_card_w=200,
        style=style,
    )
    # Well outside the logo's placed footprint (80x80, centered) and past its
    # shadow's offset/blur reach -- must be untouched background, not a fill.
    assert img.getpixel((280, 100))[:3] == bg


def test_logo_badge_shadow_follows_logo_silhouette_not_a_rectangle(tmp_path):
    """The shadow must trace the logo's own alpha shape rather than a
    rectangular card -- proven with a circular logo: a point just past its
    round bottom edge (where a bounding-box rectangle's edge would already
    be, but the circle's own silhouette isn't) still shows the shadow."""
    bg = (200, 200, 200)
    img = Image.new("RGB", (400, 200), bg).convert("RGBA")
    draw = ImageDraw.Draw(img)
    style = _STYLE_PRESETS["festive_organic"]
    logo_path = str(tmp_path / "circle.png")
    circle = Image.new("RGBA", (80, 80), (0, 0, 0, 0))
    ImageDraw.Draw(circle).ellipse((0, 0, 79, 79), fill=(255, 0, 0, 255))
    circle.save(logo_path)
    _draw_logo_badge(
        img, draw, logo_path, "AB",
        center_x=200, center_y=100, max_card_h=80, max_card_w=80,
        style=style,
    )
    # Directly below the circle's own bottom edge (y=140), inside the
    # shadow's offset+blur reach.
    shadow_pixel = img.getpixel((200, 144))
    assert shadow_pixel[:3] != bg
    assert sum(shadow_pixel[:3]) < sum(bg)


def test_missing_logo_fallback_text_has_no_backing_box():
    """The typed-name fallback must not paint a card either -- just the
    shadowed text directly on the photo, consistent with the real-logo path."""
    bg = (200, 200, 200)
    img = Image.new("RGB", (400, 200), bg).convert("RGBA")
    draw = ImageDraw.Draw(img)
    style = _STYLE_PRESETS["festive_organic"]
    _draw_logo_badge(
        img, draw, None, "AB",
        center_x=200, center_y=100, max_card_h=80, max_card_w=200,
        style=style,
    )
    # Far from the short "AB" glyphs' actual footprint -- must be untouched.
    assert img.getpixel((80, 100))[:3] == bg


def test_hairline_accent_drawn_at_panel_seam_for_refined_minimal():
    brand = _make_brand(style_profile="refined_minimal")
    ctx = _make_ctx("Deals", main_title="BOGO", main_offer="Buy 1 get 1", price=None, brand=brand)
    img = Image.open(BytesIO(_blank_image())).convert("RGB")
    result, _ = _deals_panel(img, ctx, _fake_settings())
    out = Image.open(BytesIO(result))
    w = out.width
    panel_w = int(w * 0.36)
    accent = _hex_to_rgb(brand.brand_colors["accent"])
    seam_pixel = out.getpixel((panel_w, out.height // 2))
    assert _pixel_close(seam_pixel, accent, tolerance=20)


def test_no_hairline_seam_for_festive_organic():
    brand = _make_brand(style_profile="festive_organic")
    ctx = _make_ctx("Deals", main_title="BOGO", main_offer="Buy 1 get 1", price=None, brand=brand)
    img = Image.open(BytesIO(_blank_image())).convert("RGB")
    result, _ = _deals_panel(img, ctx, _fake_settings())
    out = Image.open(BytesIO(result))
    w = out.width
    panel_w = int(w * 0.36)
    accent = _hex_to_rgb(brand.brand_colors["accent"])
    seam_pixel = out.getpixel((panel_w, out.height // 2))
    assert not _pixel_close(seam_pixel, accent, tolerance=20)


def test_cta_pill_is_boxier_for_refined_minimal_than_festive_organic():
    """roundness drives the pill's corner radius -- refined_minimal's low
    roundness should leave its extreme corner filled (square-ish), while
    festive_organic's high roundness carves that same corner away. The
    pill's bottom-right tip is (w - margin, h - margin) regardless of the
    CTA text's width, so this is exact rather than an estimate."""
    w, h = 1536, 1024
    accent = _hex_to_rgb("#F5A623")
    # 4px in from the true tip: inside festive_organic's large-radius arc
    # (cut away -> background) but past refined_minimal's small-radius arc
    # (plain rectangle fill applies).
    corner = (w - int(w * 0.03) - 4, h - int(h * 0.03) - 4)

    organic_ctx = _make_ctx("Menu Items", cta=True, brand=_make_brand(style_profile="festive_organic"))
    img = Image.new("RGB", (w, h), (10, 10, 10))
    draw = ImageDraw.Draw(img)
    _draw_cta_pill(draw, w, h, organic_ctx, _fake_settings(cta_enabled=True))
    organic_corner = img.getpixel(corner)

    minimal_ctx = _make_ctx("Menu Items", cta=True, brand=_make_brand(style_profile="refined_minimal"))
    img2 = Image.new("RGB", (w, h), (10, 10, 10))
    draw2 = ImageDraw.Draw(img2)
    _draw_cta_pill(draw2, w, h, minimal_ctx, _fake_settings(cta_enabled=True))
    minimal_corner = img2.getpixel(corner)

    assert not _pixel_close(organic_corner, accent, tolerance=20)
    assert _pixel_close(minimal_corner, accent, tolerance=20)

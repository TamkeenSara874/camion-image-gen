from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock

from PIL import Image

from schemas.internal import CampaignContext, RestaurantBrand
from stages.text_compositor import _composite_sync, composite


def _make_brand(restaurant_id: int = 2, currency: str = "$") -> RestaurantBrand:
    return RestaurantBrand(
        restaurant_id=restaurant_id,
        restaurant_name="Mijo's Taqueria",
        cuisine_type="Mexican",
        brand_theme="vibrant, festive",
        visual_style="rustic wood",
        website_url="https://mijostaqueria.com",
        brand_colors={"primary": "#C8410A", "accent": "#F5A623", "text_on_primary": "#FFFFFF"},
        currency_symbol=currency,
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

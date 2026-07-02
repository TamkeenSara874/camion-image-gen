from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.config import Settings
from schemas.internal import CampaignContext, CompositeResult

_FONTS_DIR = Path(__file__).parent.parent / "fonts"
_FONT_BOLD = str(_FONTS_DIR / "Inter-Bold.ttf")
_FONT_REGULAR = str(_FONTS_DIR / "Inter-Regular.ttf")

_MIN_FONT_SIZE = 10
_JPEG_QUALITY = 92

_LAYOUT_DISPATCH: dict[str, Any] = {}


def _get_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size=max(size, _MIN_FONT_SIZE))
    except OSError:
        return ImageFont.load_default(size=max(size, _MIN_FONT_SIZE))


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex_to_rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    r, g, b = _hex_to_rgb(hex_color)
    return r, g, b, alpha


def _apply_brand_tone(img: Image.Image, primary_hex: str, strength: float = 0.08) -> Image.Image:
    overlay = Image.new("RGB", img.size, _hex_to_rgb(primary_hex))
    return Image.blend(img.convert("RGB"), overlay, alpha=strength)


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: str,
    initial_size: int,
    max_width: int,
) -> tuple[str, ImageFont.FreeTypeFont]:
    font = _get_font(font_path, initial_size)
    if draw.textlength(text, font=font) <= max_width:
        return text, font
    scale = max_width / draw.textlength(text, font=font)
    font = _get_font(font_path, max(int(initial_size * scale), _MIN_FONT_SIZE))
    if draw.textlength(text, font=font) <= max_width:
        return text, font
    while len(text) > 1 and draw.textlength(text + "...", font=font) > max_width:
        text = text[:-1]
    return text + "...", font


def _draw_text_center_y(
    draw: ImageDraw.ImageDraw,
    x: int,
    strip_y: int,
    strip_h: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple,
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    text_h = bbox[3] - bbox[1]
    y = strip_y + (strip_h - text_h) // 2
    draw.text((x, y), text, font=font, fill=fill)


def _composite_menu_items(
    img: Image.Image,
    ctx: CampaignContext,
    settings: Settings,
) -> tuple[bytes, bool]:
    """
    Menu Items: left panel (42% width, primary color) with restaurant name, item name large,
    price in accent color. Food photo visible in right 58%.
    """
    w, h = img.size
    panel_w = int(w * 0.42)
    padding = int(w * 0.035)

    img = img.convert("RGBA")
    panel = Image.new(
        "RGBA", (panel_w, h), _hex_to_rgba(ctx.restaurant.brand_colors["primary"], 235)
    )
    img.paste(panel, (0, 0), panel)
    img = img.convert("RGB")
    draw = ImageDraw.Draw(img)

    text_color = tuple(_hex_to_rgb(ctx.restaurant.brand_colors["text_on_primary"]))
    accent_color = tuple(_hex_to_rgb(ctx.restaurant.brand_colors["accent"]))
    max_text_w = panel_w - padding * 2
    text_truncated = False

    # Restaurant name: small, top
    rest_font_size = int(h * 0.033)
    rest_text, rest_font = _fit_text(
        draw, ctx.restaurant.restaurant_name, _FONT_BOLD, rest_font_size, max_text_w
    )
    draw.text((padding, int(h * 0.055)), rest_text, font=rest_font, fill=text_color)

    # Item name: large
    name_font_size = int(h * 0.082)
    name_text, name_font = _fit_text(draw, ctx.main_title, _FONT_BOLD, name_font_size, max_text_w)
    if name_text.endswith("..."):
        text_truncated = True
    draw.text((padding, int(h * 0.22)), name_text, font=name_font, fill=text_color)

    # Price: accent color, prominent, below item name
    if ctx.price:
        price_font_size = int(h * 0.095)
        price_text, price_font = _fit_text(
            draw, ctx.price, _FONT_BOLD, price_font_size, max_text_w
        )
        draw.text((padding, int(h * 0.46)), price_text, font=price_font, fill=accent_color)

    if settings.cta_overlay_enabled and ctx.cta and ctx.cta_text:
        draw = ImageDraw.Draw(img)
        cta_h = int(h * 0.07)
        cta_y = h - cta_h
        draw.rectangle(
            [(0, cta_y), (panel_w, h)],
            fill=_hex_to_rgba(ctx.restaurant.brand_colors["accent"], 255),
        )
        cta_font_size = int(cta_h * 0.45)
        cta_font = _get_font(_FONT_BOLD, cta_font_size)
        cta_w = draw.textlength(ctx.cta_text, font=cta_font)
        draw.text(
            ((panel_w - cta_w) // 2, cta_y + (cta_h - cta_font_size) // 2),
            ctx.cta_text,
            font=cta_font,
            fill=text_color,
        )

    out = BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    return out.getvalue(), text_truncated


def _composite_deals(
    img: Image.Image,
    ctx: CampaignContext,
    settings: Settings,
) -> tuple[bytes, bool]:
    """
    Deals: left panel (42% width, brand primary color) with deal name + offer large.
    Food photo visible in right 58%.
    Matches real Camion deal emails: image (1).png (Mijo's BOGO), image (2).png (Flights % OFF).
    """
    w, h = img.size
    panel_w = int(w * 0.42)
    padding = int(w * 0.035)

    img = img.convert("RGBA")
    panel = Image.new(
        "RGBA", (panel_w, h), _hex_to_rgba(ctx.restaurant.brand_colors["primary"], 235)
    )
    img.paste(panel, (0, 0), panel)
    img = img.convert("RGB")
    draw = ImageDraw.Draw(img)

    text_color = tuple(_hex_to_rgb(ctx.restaurant.brand_colors["text_on_primary"]))
    accent_color = tuple(_hex_to_rgb(ctx.restaurant.brand_colors["accent"]))
    max_text_w = panel_w - padding * 2
    text_truncated = False

    # Restaurant name: small, top
    rest_font_size = int(h * 0.033)
    rest_text, rest_font = _fit_text(
        draw, ctx.restaurant.restaurant_name, _FONT_BOLD, rest_font_size, max_text_w
    )
    draw.text((padding, int(h * 0.055)), rest_text, font=rest_font, fill=text_color)

    # Campaign title: medium
    title_font_size = int(h * 0.058)
    title_text, title_font = _fit_text(
        draw, ctx.main_title, _FONT_BOLD, title_font_size, max_text_w
    )
    if title_text.endswith("..."):
        text_truncated = True
    draw.text((padding, int(h * 0.17)), title_text, font=title_font, fill=text_color)

    # Main offer: large, accent color — the visual centrepiece
    offer_font_size = int(h * 0.10)
    offer_short = ctx.main_offer[:55].rstrip()
    offer_text, offer_font = _fit_text(draw, offer_short, _FONT_BOLD, offer_font_size, max_text_w)
    if offer_text.endswith("..."):
        text_truncated = True
    draw.text((padding, int(h * 0.33)), offer_text, font=offer_font, fill=accent_color)

    # Secondary offer line (remainder of offer, smaller)
    if len(ctx.main_offer) > 55:
        remainder = ctx.main_offer[55:100].strip()
        sec_font_size = int(h * 0.040)
        sec_text, sec_font = _fit_text(
            draw,
            remainder,
            _FONT_REGULAR if Path(_FONT_REGULAR).exists() else _FONT_BOLD,
            sec_font_size,
            max_text_w,
        )
        draw.text((padding, int(h * 0.50)), sec_text, font=sec_font, fill=text_color)

    if settings.cta_overlay_enabled and ctx.cta and ctx.cta_text:
        draw = ImageDraw.Draw(img)
        cta_h = int(h * 0.07)
        cta_y = h - cta_h
        draw.rectangle(
            [(0, cta_y), (panel_w, h)],
            fill=_hex_to_rgba(ctx.restaurant.brand_colors["accent"], 255),
        )
        cta_font_size = int(cta_h * 0.45)
        cta_font = _get_font(_FONT_BOLD, cta_font_size)
        cta_w = draw.textlength(ctx.cta_text, font=cta_font)
        draw.text(
            ((panel_w - cta_w) // 2, cta_y + (cta_h - cta_font_size) // 2),
            ctx.cta_text,
            font=cta_font,
            fill=text_color,
        )

    out = BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    return out.getvalue(), text_truncated


def _composite_spotlights(
    img: Image.Image,
    ctx: CampaignContext,
    settings: Settings,
) -> tuple[bytes, bool]:
    """
    Spotlights: left half dark panel (48% width), right half atmospheric photo.
    Restaurant name top, campaign name large center, offer text below.
    Matches real Camion spotlight layout: Spot light image.png (Mijo's Locals Wednesday).
    """
    w, h = img.size
    panel_w = int(w * 0.48)
    padding = int(w * 0.04)

    img = img.convert("RGBA")
    panel = Image.new(
        "RGBA", (panel_w, h), _hex_to_rgba(ctx.restaurant.brand_colors["primary"], 242)
    )
    img.paste(panel, (0, 0), panel)
    img = img.convert("RGB")
    draw = ImageDraw.Draw(img)

    text_color = tuple(_hex_to_rgb(ctx.restaurant.brand_colors["text_on_primary"]))
    accent_color = tuple(_hex_to_rgb(ctx.restaurant.brand_colors["accent"]))
    max_text_w = panel_w - padding * 2
    text_truncated = False

    # Restaurant name: small, top
    rest_font_size = int(h * 0.036)
    rest_text, rest_font = _fit_text(
        draw, ctx.restaurant.restaurant_name, _FONT_BOLD, rest_font_size, max_text_w
    )
    draw.text((padding, int(h * 0.06)), rest_text, font=rest_font, fill=text_color)

    # Campaign name: large, brand voice centrepiece
    name_font_size = int(h * 0.10)
    name_text, name_font = _fit_text(draw, ctx.main_title, _FONT_BOLD, name_font_size, max_text_w)
    if name_text.endswith("..."):
        text_truncated = True
    draw.text((padding, int(h * 0.26)), name_text, font=name_font, fill=text_color)

    # Offer: medium, accent color
    offer_font_size = int(h * 0.048)
    offer_short = ctx.main_offer[:60].rstrip()
    offer_text, offer_font = _fit_text(draw, offer_short, _FONT_BOLD, offer_font_size, max_text_w)
    if offer_text.endswith("..."):
        text_truncated = True
    draw.text((padding, int(h * 0.50)), offer_text, font=offer_font, fill=accent_color)

    if settings.cta_overlay_enabled and ctx.cta and ctx.cta_text:
        draw = ImageDraw.Draw(img)
        cta_h = int(h * 0.07)
        cta_y = h - cta_h
        draw.rectangle(
            [(0, cta_y), (panel_w, h)],
            fill=_hex_to_rgba(ctx.restaurant.brand_colors["accent"], 255),
        )
        cta_font = _get_font(_FONT_BOLD, int(cta_h * 0.45))
        cta_w = draw.textlength(ctx.cta_text, font=cta_font)
        draw.text(
            ((panel_w - cta_w) // 2, cta_y + int(cta_h * 0.25)),
            ctx.cta_text,
            font=cta_font,
            fill=text_color,
        )

    out = BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    return out.getvalue(), text_truncated


def _add_cta_strip(
    draw: ImageDraw.ImageDraw,
    img: Image.Image,
    w: int,
    above_y: int,
    ctx: CampaignContext,
    settings: Settings,
) -> tuple[Image.Image, bool]:
    cta_h = int(img.height * 0.07)
    cta_y = above_y - cta_h
    draw.rectangle(
        [(0, cta_y), (w, above_y)], fill=_hex_to_rgba(ctx.restaurant.brand_colors["accent"], 230)
    )
    cta_font = _get_font(_FONT_BOLD, int(cta_h * 0.45))
    cta_text = ctx.cta_text or ""
    cta_w = draw.textlength(cta_text, font=cta_font)
    text_color = tuple(_hex_to_rgb(ctx.restaurant.brand_colors["text_on_primary"]))
    draw.text(
        ((w - int(cta_w)) // 2, cta_y + int(cta_h * 0.25)), cta_text, font=cta_font, fill=text_color
    )
    return img, False


_LAYOUT_DISPATCH = {
    "Menu Items": _composite_menu_items,
    "Deals": _composite_deals,
    "Spotlights": _composite_spotlights,
}


def _composite_sync(
    image_bytes: bytes, ctx: CampaignContext, settings: Settings
) -> tuple[bytes, bool]:
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    layout_fn = _LAYOUT_DISPATCH.get(ctx.campaign_type, _composite_menu_items)
    return layout_fn(img, ctx, settings)


async def composite(
    image_bytes: bytes,
    ctx: CampaignContext,
    settings: Settings,
) -> CompositeResult:
    final_bytes, text_truncated = await asyncio.to_thread(
        _composite_sync, image_bytes, ctx, settings
    )
    return CompositeResult(
        image_bytes=final_bytes,
        mime_type="image/jpeg",
        text_was_truncated=text_truncated,
    )

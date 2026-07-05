from __future__ import annotations

import asyncio
import hashlib
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

from app.config import Settings
from schemas.internal import CampaignContext, CompositeResult

_FONTS_DIR = Path(__file__).parent.parent / "fonts"
_FONT_BOLD = str(_FONTS_DIR / "Inter-Bold.ttf")
_FONT_REGULAR = str(_FONTS_DIR / "Inter-Regular.ttf")
_FONT_TEXT = _FONT_REGULAR if Path(_FONT_REGULAR).exists() else _FONT_BOLD

_MIN_FONT_SIZE = 10
_JPEG_QUALITY = 92

LayoutFn = Callable[[Image.Image, CampaignContext, Settings], "tuple[bytes, bool]"]


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


def _apply_brand_tone(img: Image.Image, primary_hex: str, strength: float = 0.06) -> Image.Image:
    """Subtle brand-color wash so images generated independently for the same
    restaurant share a tonal anchor instead of looking like unrelated stock photos.
    See README 'Batch Visual Consistency' trade-off."""
    overlay = Image.new("RGB", img.size, _hex_to_rgb(primary_hex))
    return Image.blend(img.convert("RGB"), overlay, alpha=strength)


@lru_cache(maxsize=16)
def _load_logo(logo_path: str) -> Image.Image:
    return Image.open(logo_path).convert("RGBA")


def _paste_logo_centered(
    img: Image.Image, logo_path: str, center_x: int, center_y: int, max_w: int, max_h: int
) -> None:
    """Pastes the restaurant's REAL logo asset (never model-generated -- see
    stages/prompt_generator.py's explicit 'no logos' instruction to the image
    model, which exists because diffusion models cannot reproduce a specific
    small business's exact mark and would otherwise hallucinate a lookalike)."""
    logo = _load_logo(logo_path)
    lw, lh = logo.size
    scale = min(max_w / lw, max_h / lh)
    new_w, new_h = max(1, int(lw * scale)), max(1, int(lh * scale))
    resized = logo.resize((new_w, new_h), Image.LANCZOS)
    img.paste(resized, (center_x - new_w // 2, center_y - new_h // 2), resized)


def _draw_logo_badge(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    logo_path: str | None,
    fallback_text: str,
    center_x: int,
    center_y: int,
    max_card_h: int,
    max_card_w: int,
) -> None:
    """Draws the brand mark centered at (center_x, center_y) on a snug white
    rounded card so the logo (or, absent a sourced logo, the restaurant name as
    plain text -- an honest degrade, never an invented mark) stays legible
    regardless of the restaurant's brand color."""
    pad = max(int(max_card_h * 0.18), 6)
    content_h = max_card_h - pad * 2

    if logo_path:
        logo = _load_logo(logo_path)
        lw, lh = logo.size
        content_w = min(int(content_h * (lw / lh)), max_card_w - pad * 2)
        content_h = min(content_h, int(content_w * (lh / lw)))
        card_w, card_h = content_w + pad * 2, content_h + pad * 2
    else:
        font = _get_font(_FONT_BOLD, int(max_card_h * 0.42))
        text_w = draw.textlength(fallback_text, font=font)
        while text_w > max_card_w - pad * 2 and font.size > _MIN_FONT_SIZE:
            font = _get_font(_FONT_BOLD, font.size - 2)
            text_w = draw.textlength(fallback_text, font=font)
        card_w, card_h = int(text_w) + pad * 2, max_card_h

    box = (
        center_x - card_w // 2,
        center_y - card_h // 2,
        center_x + card_w // 2,
        center_y + card_h // 2,
    )
    draw.rounded_rectangle(box, radius=max(int(card_h * 0.18), 4), fill=(255, 255, 255, 235))

    if logo_path:
        _paste_logo_centered(img, logo_path, center_x, center_y, content_w, content_h)
    else:
        draw.text(
            (center_x - int(text_w) // 2, center_y - font.size // 2),
            fallback_text,
            font=font,
            fill=(30, 30, 30, 255),
        )


def _draw_corner_logo(
    img: Image.Image, draw: ImageDraw.ImageDraw, ctx: CampaignContext, w: int, h: int, side: str = "left"
) -> None:
    """Small logo badge floating directly over the photo in a top corner --
    used by the 'poster' variants, which have no opaque header bar."""
    badge_h = int(h * 0.11)
    badge_w = int(w * 0.24)
    margin = int(w * 0.035)
    cx = margin + badge_w // 2 if side == "left" else w - margin - badge_w // 2
    cy = margin + badge_h // 2
    _draw_logo_badge(
        img, draw, ctx.restaurant.logo_path, ctx.restaurant.restaurant_name,
        center_x=cx, center_y=cy, max_card_h=badge_h, max_card_w=badge_w,
    )


def _vertical_gradient_scrim(
    w: int, h: int, rgb: tuple[int, int, int], max_alpha: int = 205
) -> Image.Image:
    """Transparent-to-opaque gradient so the hero photo stays fully visible at
    the top of the band and text stays readable at the bottom, instead of an
    opaque block that hides half the photo."""
    gradient = Image.new("L", (1, h))
    for y in range(h):
        gradient.putpixel((0, y), int(max_alpha * (y / max(h - 1, 1))))
    alpha_mask = gradient.resize((w, h))
    overlay = Image.new("RGBA", (w, h), (*rgb, 0))
    overlay.putalpha(alpha_mask)
    return overlay


def _paste_side_panel(
    img: Image.Image, ctx: CampaignContext, panel_frac: float, side: str
) -> tuple[Image.Image, int, int]:
    """Pastes an opaque brand-primary panel on the given side. Returns
    (img, panel_x0, panel_w) so callers know where to place text."""
    w, h = img.size
    panel_w = int(w * panel_frac)
    panel_x0 = 0 if side == "left" else w - panel_w
    panel = Image.new("RGBA", (panel_w, h), _hex_to_rgba(ctx.restaurant.brand_colors["primary"], 242))
    img.paste(panel, (panel_x0, 0), panel)
    return img, panel_x0, panel_w


def _draw_header_bar(
    img: Image.Image, draw: ImageDraw.ImageDraw, w: int, h: int, ctx: CampaignContext
) -> int:
    """Opaque brand-color strip across the top with the real restaurant logo.
    Returns the header height so callers know where the visible photo area begins."""
    header_h = int(h * 0.15)
    draw.rectangle([(0, 0), (w, header_h)], fill=_hex_to_rgba(ctx.restaurant.brand_colors["primary"], 255))
    _draw_logo_badge(
        img, draw, ctx.restaurant.logo_path, ctx.restaurant.restaurant_name,
        center_x=w // 2, center_y=header_h // 2,
        max_card_h=int(header_h * 0.78), max_card_w=int(w * 0.5),
    )
    return header_h


def _draw_cta_pill(
    draw: ImageDraw.ImageDraw, w: int, h: int, ctx: CampaignContext, settings: Settings
) -> None:
    if not (settings.cta_overlay_enabled and ctx.cta and ctx.cta_text):
        return
    pill_h = int(h * 0.06)
    font = _get_font(_FONT_BOLD, int(pill_h * 0.5))
    text_w = draw.textlength(ctx.cta_text, font=font)
    pad_x = int(pill_h * 0.6)
    pill_w = int(text_w) + pad_x * 2
    x1, y1 = w - pill_w - int(w * 0.03), h - pill_h - int(h * 0.03)
    x2, y2 = x1 + pill_w, y1 + pill_h
    draw.rounded_rectangle(
        (x1, y1, x2, y2), radius=pill_h // 2, fill=_hex_to_rgba(ctx.restaurant.brand_colors["accent"], 240)
    )
    text_color = tuple(_hex_to_rgb(ctx.restaurant.brand_colors["text_on_primary"]))
    draw.text((x1 + pad_x, y1 + (pill_h - font.size) // 2), ctx.cta_text, font=font, fill=text_color)


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


def _wrap_two_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: str,
    size: int,
    max_width: int,
) -> tuple[str, str]:
    """Split text into two lines on word boundaries, filling line 1 to
    max_width. Never orphans punctuation the way a raw character-index
    slice does (e.g. splitting "...happy hour, Monday..." at a fixed
    character count can leave a line starting with ", Monday")."""
    font = _get_font(font_path, size)
    words = text.split()
    line1: list[str] = []
    i = 0
    while i < len(words):
        candidate = " ".join([*line1, words[i]])
        if not line1 or draw.textlength(candidate, font=font) <= max_width:
            line1.append(words[i])
            i += 1
        else:
            break
    return " ".join(line1), " ".join(words[i:])


def _finalize(img: Image.Image) -> bytes:
    out = BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    return out.getvalue()


def _select_variant(ctx: CampaignContext, count: int) -> int:
    """Deterministic pick from the campaign type's layout pool: the same
    payload always renders the same way (stable for caching/testing/QA
    re-review), but different campaign names/restaurants land on different
    treatments instead of every campaign of a given type looking identical."""
    key = f"{ctx.restaurant.restaurant_id}:{ctx.campaign_type}:{ctx.main_title}"
    digest = hashlib.sha256(key.encode()).hexdigest()
    return int(digest, 16) % count


# ---------------------------------------------------------------------------
# Menu Items variants
# ---------------------------------------------------------------------------


def _menu_items_header_scrim(img: Image.Image, ctx: CampaignContext, settings: Settings) -> tuple[bytes, bool]:
    """Header bar (real logo) + full-bleed hero photo + bottom gradient caption
    band with item name and price. Matches image.png / image (1).png."""
    w, h = img.size
    img = _apply_brand_tone(img, ctx.restaurant.brand_colors["primary"]).convert("RGBA")
    draw = ImageDraw.Draw(img)
    padding = int(w * 0.035)
    text_truncated = False

    _draw_header_bar(img, draw, w, h, ctx)

    scrim_h = int(h * 0.30)
    scrim = _vertical_gradient_scrim(w, scrim_h, (0, 0, 0))
    img.paste(scrim, (0, h - scrim_h), scrim)

    text_color = (255, 255, 255, 255)
    accent_color = tuple(_hex_to_rgb(ctx.restaurant.brand_colors["accent"])) + (255,)
    price_str = ctx.price or ""
    price_font = _get_font(_FONT_BOLD, int(h * 0.075))
    price_w = draw.textlength(price_str, font=price_font) if price_str else 0
    name_max_w = w - padding * 2 - (int(price_w) + padding if price_str else 0)

    name_text, name_font = _fit_text(draw, ctx.main_title, _FONT_BOLD, int(h * 0.065), name_max_w)
    if name_text.endswith("..."):
        text_truncated = True
    name_y = h - int(scrim_h * 0.62)
    draw.text((padding, name_y), name_text, font=name_font, fill=text_color)

    if price_str:
        draw.text((w - int(price_w) - padding, name_y - int(h * 0.005)), price_str, font=price_font, fill=accent_color)

    offer_text, offer_font = _fit_text(draw, ctx.main_offer, _FONT_TEXT, int(h * 0.032), w - padding * 2)
    if offer_text.endswith("..."):
        text_truncated = True
    draw.text((padding, h - int(scrim_h * 0.28)), offer_text, font=offer_font, fill=text_color)

    _draw_cta_pill(draw, w, h, ctx, settings)
    return _finalize(img), text_truncated


def _menu_items_poster(img: Image.Image, ctx: CampaignContext, settings: Settings) -> tuple[bytes, bool]:
    """No header bar -- logo floats as a corner badge directly on the full-bleed
    photo. Item name is a bold centered headline; price is a separate floating
    accent-color tag in the opposite corner. A 'featured dish' poster feel,
    distinct from the header-bar layout."""
    w, h = img.size
    img = _apply_brand_tone(img, ctx.restaurant.brand_colors["primary"]).convert("RGBA")
    draw = ImageDraw.Draw(img)
    text_truncated = False

    _draw_corner_logo(img, draw, ctx, w, h, side="left")

    if ctx.price:
        badge_d = int(h * 0.13)
        margin = int(w * 0.035)
        cx, cy = w - margin - badge_d // 2, margin + badge_d // 2
        draw.ellipse(
            (cx - badge_d // 2, cy - badge_d // 2, cx + badge_d // 2, cy + badge_d // 2),
            fill=_hex_to_rgba(ctx.restaurant.brand_colors["accent"], 245),
        )
        price_text, price_font = _fit_text(draw, ctx.price, _FONT_BOLD, int(badge_d * 0.32), int(badge_d * 0.82))
        pw = draw.textlength(price_text, font=price_font)
        price_ink = tuple(_hex_to_rgb(ctx.restaurant.brand_colors["primary"])) + (255,)
        draw.text((cx - pw // 2, cy - price_font.size // 2), price_text, font=price_font, fill=price_ink)

    scrim_h = int(h * 0.32)
    scrim = _vertical_gradient_scrim(w, scrim_h, (0, 0, 0))
    img.paste(scrim, (0, h - scrim_h), scrim)

    text_color = (255, 255, 255, 255)
    max_w = int(w * 0.86)

    name_text, name_font = _fit_text(draw, ctx.main_title, _FONT_BOLD, int(h * 0.078), max_w)
    if name_text.endswith("..."):
        text_truncated = True
    nw = draw.textlength(name_text, font=name_font)
    draw.text(((w - nw) // 2, h - int(scrim_h * 0.66)), name_text, font=name_font, fill=text_color)

    offer_text, offer_font = _fit_text(draw, ctx.main_offer, _FONT_TEXT, int(h * 0.032), max_w)
    if offer_text.endswith("..."):
        text_truncated = True
    ow = draw.textlength(offer_text, font=offer_font)
    draw.text(((w - ow) // 2, h - int(scrim_h * 0.28)), offer_text, font=offer_font, fill=text_color)

    _draw_cta_pill(draw, w, h, ctx, settings)
    return _finalize(img), text_truncated


def _menu_items_panel(img: Image.Image, ctx: CampaignContext, settings: Settings) -> tuple[bytes, bool]:
    """Right-side brand-color panel (logo, item name, price, description);
    photo fills the left side. Same panel primitive as Spotlights/Deals panel
    variants but mirrored to the right, so a panel-style Menu Items image
    still reads as visually distinct from a panel-style Spotlights image."""
    w, h = img.size
    img = _apply_brand_tone(img, ctx.restaurant.brand_colors["primary"]).convert("RGBA")
    img, panel_x0, panel_w = _paste_side_panel(img, ctx, 0.44, side="right")
    draw = ImageDraw.Draw(img)
    padding = int(w * 0.035)
    text_x = panel_x0 + padding
    max_text_w = panel_w - padding * 2
    text_truncated = False

    _draw_logo_badge(
        img, draw, ctx.restaurant.logo_path, ctx.restaurant.restaurant_name,
        center_x=panel_x0 + panel_w // 2, center_y=int(h * 0.10),
        max_card_h=int(h * 0.13), max_card_w=panel_w - padding,
    )

    text_color = (255, 255, 255, 255)
    accent_color = tuple(_hex_to_rgb(ctx.restaurant.brand_colors["accent"])) + (255,)

    name_text, name_font = _fit_text(draw, ctx.main_title, _FONT_BOLD, int(h * 0.068), max_text_w)
    if name_text.endswith("..."):
        text_truncated = True
    draw.text((text_x, int(h * 0.28)), name_text, font=name_font, fill=text_color)

    next_y = 0.44
    if ctx.price:
        price_text, price_font = _fit_text(draw, ctx.price, _FONT_BOLD, int(h * 0.085), max_text_w)
        draw.text((text_x, int(h * next_y)), price_text, font=price_font, fill=accent_color)
        next_y += 0.15

    offer_font_size = int(h * 0.034)
    offer_line, offer_remainder = _wrap_two_lines(draw, ctx.main_offer, _FONT_TEXT, offer_font_size, max_text_w)
    offer_text, offer_font = _fit_text(draw, offer_line, _FONT_TEXT, offer_font_size, max_text_w)
    if offer_text.endswith("...") or (offer_remainder and offer_text != offer_line):
        text_truncated = True
    draw.text((text_x, int(h * next_y)), offer_text, font=offer_font, fill=text_color)
    if offer_remainder:
        sec_text, sec_font = _fit_text(draw, offer_remainder, _FONT_TEXT, offer_font_size, max_text_w)
        if sec_text.endswith("..."):
            text_truncated = True
        draw.text((text_x, int(h * (next_y + 0.055))), sec_text, font=sec_font, fill=text_color)

    _draw_cta_pill(draw, w, h, ctx, settings)
    return _finalize(img), text_truncated


# ---------------------------------------------------------------------------
# Deals variants
# ---------------------------------------------------------------------------


def _deals_header_scrim(img: Image.Image, ctx: CampaignContext, settings: Settings) -> tuple[bytes, bool]:
    """Header bar (real logo) + full-bleed hero photo + bottom gradient band
    with a large accent-colored offer callout. Matches image (2).png / image (3).png."""
    w, h = img.size
    img = _apply_brand_tone(img, ctx.restaurant.brand_colors["primary"]).convert("RGBA")
    draw = ImageDraw.Draw(img)
    padding = int(w * 0.035)
    text_truncated = False

    _draw_header_bar(img, draw, w, h, ctx)

    scrim_h = int(h * 0.36)
    scrim = _vertical_gradient_scrim(w, scrim_h, (0, 0, 0))
    img.paste(scrim, (0, h - scrim_h), scrim)

    text_color = (255, 255, 255, 255)
    accent_color = tuple(_hex_to_rgb(ctx.restaurant.brand_colors["accent"])) + (255,)
    max_text_w = w - padding * 2

    title_text, title_font = _fit_text(draw, ctx.main_title, _FONT_BOLD, int(h * 0.042), max_text_w)
    if title_text.endswith("..."):
        text_truncated = True
    draw.text((padding, h - int(scrim_h * 0.86)), title_text, font=title_font, fill=text_color)

    offer_font_size = int(h * 0.085)
    offer_line, offer_remainder = _wrap_two_lines(draw, ctx.main_offer, _FONT_BOLD, offer_font_size, max_text_w)
    offer_text, offer_font = _fit_text(draw, offer_line, _FONT_BOLD, offer_font_size, max_text_w)
    if offer_text.endswith("...") or (offer_remainder and offer_text != offer_line):
        text_truncated = True
    draw.text((padding, h - int(scrim_h * 0.62)), offer_text, font=offer_font, fill=accent_color)

    if offer_remainder:
        sec_text, sec_font = _fit_text(draw, offer_remainder, _FONT_TEXT, int(h * 0.034), max_text_w)
        if sec_text.endswith("..."):
            text_truncated = True
        draw.text((padding, h - int(scrim_h * 0.24)), sec_text, font=sec_font, fill=text_color)

    _draw_cta_pill(draw, w, h, ctx, settings)
    return _finalize(img), text_truncated


def _deals_poster(img: Image.Image, ctx: CampaignContext, settings: Settings) -> tuple[bytes, bool]:
    """No header bar -- corner logo badge, full-bleed photo, and the offer
    rendered as a huge centered stamp-style callout (the 'BIG DISCOUNT'
    poster treatment), with the deal name as a small centered label above it."""
    w, h = img.size
    img = _apply_brand_tone(img, ctx.restaurant.brand_colors["primary"]).convert("RGBA")
    draw = ImageDraw.Draw(img)
    text_truncated = False

    _draw_corner_logo(img, draw, ctx, w, h, side="right")

    scrim_h = int(h * 0.40)
    scrim = _vertical_gradient_scrim(w, scrim_h, (0, 0, 0))
    img.paste(scrim, (0, h - scrim_h), scrim)

    text_color = (255, 255, 255, 255)
    accent_color = tuple(_hex_to_rgb(ctx.restaurant.brand_colors["accent"])) + (255,)
    max_w = int(w * 0.88)

    title_text, title_font = _fit_text(draw, ctx.main_title, _FONT_BOLD, int(h * 0.036), max_w)
    if title_text.endswith("..."):
        text_truncated = True
    tw = draw.textlength(title_text, font=title_font)
    draw.text(((w - tw) // 2, h - int(scrim_h * 0.92)), title_text, font=title_font, fill=text_color)

    offer_font_size = int(h * 0.10)
    offer_line, offer_remainder = _wrap_two_lines(draw, ctx.main_offer, _FONT_BOLD, offer_font_size, max_w)
    offer_text, offer_font = _fit_text(draw, offer_line, _FONT_BOLD, offer_font_size, max_w)
    if offer_text.endswith("...") or (offer_remainder and offer_text != offer_line):
        text_truncated = True
    ow = draw.textlength(offer_text, font=offer_font)
    draw.text(((w - ow) // 2, h - int(scrim_h * 0.68)), offer_text, font=offer_font, fill=accent_color)

    if offer_remainder:
        sec_text, sec_font = _fit_text(draw, offer_remainder, _FONT_TEXT, int(h * 0.032), max_w)
        if sec_text.endswith("..."):
            text_truncated = True
        sw = draw.textlength(sec_text, font=sec_font)
        draw.text(((w - sw) // 2, h - int(scrim_h * 0.24)), sec_text, font=sec_font, fill=text_color)

    _draw_cta_pill(draw, w, h, ctx, settings)
    return _finalize(img), text_truncated


def _deals_panel(img: Image.Image, ctx: CampaignContext, settings: Settings) -> tuple[bytes, bool]:
    """Left brand-color panel with logo, deal name, and offer; photo fills the
    right side. Panel-on-the-left convention (vs. Menu Items' panel-on-the-right)
    so the two panel variants don't read identically at a glance."""
    w, h = img.size
    img = _apply_brand_tone(img, ctx.restaurant.brand_colors["primary"]).convert("RGBA")
    img, panel_x0, panel_w = _paste_side_panel(img, ctx, 0.44, side="left")
    draw = ImageDraw.Draw(img)
    padding = int(w * 0.035)
    text_x = panel_x0 + padding
    max_text_w = panel_w - padding * 2
    text_truncated = False

    _draw_logo_badge(
        img, draw, ctx.restaurant.logo_path, ctx.restaurant.restaurant_name,
        center_x=panel_x0 + panel_w // 2, center_y=int(h * 0.10),
        max_card_h=int(h * 0.13), max_card_w=panel_w - padding,
    )

    text_color = (255, 255, 255, 255)
    accent_color = tuple(_hex_to_rgb(ctx.restaurant.brand_colors["accent"])) + (255,)

    title_text, title_font = _fit_text(draw, ctx.main_title, _FONT_BOLD, int(h * 0.055), max_text_w)
    if title_text.endswith("..."):
        text_truncated = True
    draw.text((text_x, int(h * 0.26)), title_text, font=title_font, fill=text_color)

    offer_font_size = int(h * 0.09)
    offer_line, offer_remainder = _wrap_two_lines(draw, ctx.main_offer, _FONT_BOLD, offer_font_size, max_text_w)
    offer_text, offer_font = _fit_text(draw, offer_line, _FONT_BOLD, offer_font_size, max_text_w)
    if offer_text.endswith("...") or (offer_remainder and offer_text != offer_line):
        text_truncated = True
    draw.text((text_x, int(h * 0.42)), offer_text, font=offer_font, fill=accent_color)

    if offer_remainder:
        sec_text, sec_font = _fit_text(draw, offer_remainder, _FONT_TEXT, int(h * 0.038), max_text_w)
        if sec_text.endswith("..."):
            text_truncated = True
        draw.text((text_x, int(h * 0.58)), sec_text, font=sec_font, fill=text_color)

    _draw_cta_pill(draw, w, h, ctx, settings)
    return _finalize(img), text_truncated


# ---------------------------------------------------------------------------
# Spotlights variants
# ---------------------------------------------------------------------------


def _spotlights_panel_left(img: Image.Image, ctx: CampaignContext, settings: Settings) -> tuple[bytes, bool]:
    """Left brand-color panel with logo badge, headline, and offer; atmospheric
    photo fills the right side. Matches Spot light image.png."""
    return _spotlights_panel(img, ctx, settings, side="left")


def _spotlights_panel_right(img: Image.Image, ctx: CampaignContext, settings: Settings) -> tuple[bytes, bool]:
    """Mirror of the left-panel treatment, panel on the right instead."""
    return _spotlights_panel(img, ctx, settings, side="right")


def _spotlights_panel(
    img: Image.Image, ctx: CampaignContext, settings: Settings, side: str
) -> tuple[bytes, bool]:
    w, h = img.size
    img = _apply_brand_tone(img, ctx.restaurant.brand_colors["primary"]).convert("RGBA")
    img, panel_x0, panel_w = _paste_side_panel(img, ctx, 0.45, side=side)
    draw = ImageDraw.Draw(img)
    padding = int(w * 0.04)
    text_x = panel_x0 + padding
    max_text_w = panel_w - padding * 2
    text_truncated = False

    _draw_logo_badge(
        img, draw, ctx.restaurant.logo_path, ctx.restaurant.restaurant_name,
        center_x=panel_x0 + panel_w // 2, center_y=int(h * 0.12),
        max_card_h=int(h * 0.15), max_card_w=panel_w - padding,
    )

    text_color = (255, 255, 255, 255)
    accent_color = tuple(_hex_to_rgb(ctx.restaurant.brand_colors["accent"])) + (255,)

    name_text, name_font = _fit_text(draw, ctx.main_title, _FONT_BOLD, int(h * 0.10), max_text_w)
    if name_text.endswith("..."):
        text_truncated = True
    draw.text((text_x, int(h * 0.34)), name_text, font=name_font, fill=text_color)

    offer_font_size = int(h * 0.040)
    offer_line, offer_remainder = _wrap_two_lines(draw, ctx.main_offer, _FONT_BOLD, offer_font_size, max_text_w)
    offer_text, offer_font = _fit_text(draw, offer_line, _FONT_BOLD, offer_font_size, max_text_w)
    if offer_text.endswith("...") or (offer_remainder and offer_text != offer_line):
        text_truncated = True
    draw.text((text_x, int(h * 0.53)), offer_text, font=offer_font, fill=accent_color)

    if offer_remainder:
        sec_text, sec_font = _fit_text(draw, offer_remainder, _FONT_BOLD, offer_font_size, max_text_w)
        if sec_text.endswith("..."):
            text_truncated = True
        draw.text((text_x, int(h * 0.585)), sec_text, font=sec_font, fill=accent_color)

    _draw_cta_pill(draw, w, h, ctx, settings)
    return _finalize(img), text_truncated


def _spotlights_poster(img: Image.Image, ctx: CampaignContext, settings: Settings) -> tuple[bytes, bool]:
    """No side panel -- full-bleed atmospheric photo with a corner logo badge
    and a centered, event-poster-style headline in a bottom gradient band.
    The 'no panel at all' option in the Spotlights pool."""
    w, h = img.size
    img = _apply_brand_tone(img, ctx.restaurant.brand_colors["primary"]).convert("RGBA")
    draw = ImageDraw.Draw(img)
    text_truncated = False

    _draw_corner_logo(img, draw, ctx, w, h, side="left")

    scrim_h = int(h * 0.34)
    scrim = _vertical_gradient_scrim(w, scrim_h, (0, 0, 0))
    img.paste(scrim, (0, h - scrim_h), scrim)

    text_color = (255, 255, 255, 255)
    accent_color = tuple(_hex_to_rgb(ctx.restaurant.brand_colors["accent"])) + (255,)
    max_w = int(w * 0.86)

    name_text, name_font = _fit_text(draw, ctx.main_title, _FONT_BOLD, int(h * 0.09), max_w)
    if name_text.endswith("..."):
        text_truncated = True
    nw = draw.textlength(name_text, font=name_font)
    draw.text(((w - nw) // 2, h - int(scrim_h * 0.70)), name_text, font=name_font, fill=text_color)

    offer_short = ctx.main_offer[:80].rstrip()
    offer_text, offer_font = _fit_text(draw, offer_short, _FONT_TEXT, int(h * 0.034), max_w)
    if offer_text.endswith("..."):
        text_truncated = True
    ow = draw.textlength(offer_text, font=offer_font)
    draw.text(((w - ow) // 2, h - int(scrim_h * 0.28)), offer_text, font=offer_font, fill=accent_color)

    _draw_cta_pill(draw, w, h, ctx, settings)
    return _finalize(img), text_truncated


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_VARIANTS_BY_TYPE: dict[str, list[LayoutFn]] = {
    "Menu Items": [_menu_items_header_scrim, _menu_items_poster, _menu_items_panel],
    "Deals": [_deals_header_scrim, _deals_poster, _deals_panel],
    "Spotlights": [_spotlights_panel_left, _spotlights_panel_right, _spotlights_poster],
}


def _composite_sync(
    image_bytes: bytes, ctx: CampaignContext, settings: Settings
) -> tuple[bytes, bool]:
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    variants = _VARIANTS_BY_TYPE.get(ctx.campaign_type, _VARIANTS_BY_TYPE["Menu Items"])
    variant_fn = variants[_select_variant(ctx, len(variants))]
    return variant_fn(img, ctx, settings)


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

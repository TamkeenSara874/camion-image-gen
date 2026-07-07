from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.config import Settings
from schemas.internal import CampaignContext, CompositeResult

_FONTS_DIR = Path(__file__).parent.parent / "fonts"
_FONT_BOLD = str(_FONTS_DIR / "Inter-Bold.ttf")
_FONT_REGULAR = str(_FONTS_DIR / "Inter-Regular.ttf")
_FONT_TEXT = _FONT_REGULAR if Path(_FONT_REGULAR).exists() else _FONT_BOLD

# Headline/display faces for the restaurant "personality" style presets below.
# Fall back to the neutral Inter-Bold if a font asset is somehow missing
# rather than crashing image generation over a cosmetic typography choice.
_FONT_DISPLAY_ORGANIC = str(_FONTS_DIR / "Righteous-Regular.ttf")
_FONT_DISPLAY_MINIMAL = str(_FONTS_DIR / "Marcellus-Regular.ttf")
if not Path(_FONT_DISPLAY_ORGANIC).exists():
    _FONT_DISPLAY_ORGANIC = _FONT_BOLD
if not Path(_FONT_DISPLAY_MINIMAL).exists():
    _FONT_DISPLAY_MINIMAL = _FONT_BOLD

_MIN_FONT_SIZE = 10
_JPEG_QUALITY = 92

LayoutFn = Callable[[Image.Image, CampaignContext, Settings], "tuple[bytes, bool]"]


@dataclass(frozen=True)
class _StylePreset:
    """A restaurant's visual "personality" beyond its two brand hex codes --
    see RestaurantBrand.style_profile, an explicit per-restaurant config
    choice (config/restaurant_brands.json) rather than something guessed from
    brand_theme text, so two restaurants with a similarly-worded brand_theme
    can still land on deliberately different personalities."""

    display_font: str
    roundness: float  # 0-1: fraction of half-height used as corner radius on CTA pills
    hairline_accent: bool  # thin accent-color edge line, the "crisp minimal lines" cue


_STYLE_PRESETS: dict[str, _StylePreset] = {
    "festive_organic": _StylePreset(
        display_font=_FONT_DISPLAY_ORGANIC,
        roundness=0.9,
        hairline_accent=False,
    ),
    "refined_minimal": _StylePreset(
        display_font=_FONT_DISPLAY_MINIMAL,
        roundness=0.22,
        hairline_accent=True,
    ),
}
_DEFAULT_STYLE_NAME = "festive_organic"


def _style_for(ctx: CampaignContext) -> _StylePreset:
    return _STYLE_PRESETS.get(ctx.restaurant.style_profile, _STYLE_PRESETS[_DEFAULT_STYLE_NAME])


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


def _drop_shadow_from_alpha(img: Image.Image, glyph: Image.Image, x0: int, y0: int) -> None:
    """Soft blurred shadow that follows the pasted content's own silhouette
    (its alpha channel) instead of a rectangular card -- so a real logo floats
    on the photo the way a genuine printed logo would, with no visible frame
    around it. `glyph` is the exact RGBA image about to be pasted at (x0, y0)."""
    gw, gh = glyph.size
    alpha = glyph.split()[-1] if glyph.mode == "RGBA" else Image.new("L", glyph.size, 255)
    offset = max(int(max(gw, gh) * 0.05), 2)
    blur = max(int(max(gw, gh) * 0.05), 3)
    margin = blur * 3

    canvas = Image.new("L", (gw + margin * 2, gh + margin * 2), 0)
    canvas.paste(alpha, (margin + offset, margin + offset))
    canvas = canvas.filter(ImageFilter.GaussianBlur(radius=blur))
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow.putalpha(canvas.point(lambda a: int(a * 0.60)))

    px, py = x0 - margin, y0 - margin
    cx0, cy0 = max(px, 0), max(py, 0)
    cx1, cy1 = min(px + shadow.width, img.width), min(py + shadow.height, img.height)
    if cx1 <= cx0 or cy1 <= cy0:
        return
    crop = shadow.crop((cx0 - px, cy0 - py, cx1 - px, cy1 - py))
    img.paste(crop, (cx0, cy0), crop)


def _draw_logo_badge(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    logo_path: str | None,
    fallback_text: str,
    center_x: int,
    center_y: int,
    max_card_h: int,
    max_card_w: int,
    style: _StylePreset,
) -> None:
    """Draws the brand mark centered at (center_x, center_y) directly on the
    photo -- no backing card or border. This is the restaurant's REAL logo
    asset, never model-generated (see stages/prompt_generator.py's explicit
    'no logos' instruction to the image model, which exists because diffusion
    models cannot reproduce a specific small business's exact mark and would
    otherwise hallucinate a lookalike). It gets a soft shadow that follows its
    own silhouette (see _drop_shadow_from_alpha), the same way a genuine
    printed logo would cast one, instead of a rectangular card that reads as
    "a logo in a box" rather than just a logo. Absent a sourced logo,
    degrades to the restaurant name as plain text with a soft dark shadow for
    legibility -- an honest degrade, never an invented mark."""
    if logo_path:
        logo = _load_logo(logo_path)
        lw, lh = logo.size
        scale = min(max_card_w / lw, max_card_h / lh)
        new_w, new_h = max(1, int(lw * scale)), max(1, int(lh * scale))
        resized = logo.resize((new_w, new_h), Image.LANCZOS)
        x0, y0 = center_x - new_w // 2, center_y - new_h // 2
        _drop_shadow_from_alpha(img, resized, x0, y0)
        img.paste(resized, (x0, y0), resized)
    else:
        font = _get_font(style.display_font, int(max_card_h * 0.55))
        text_w = draw.textlength(fallback_text, font=font)
        while text_w > max_card_w and font.size > _MIN_FONT_SIZE:
            font = _get_font(style.display_font, font.size - 2)
            text_w = draw.textlength(fallback_text, font=font)
        tx, ty = center_x - int(text_w) // 2, center_y - font.size // 2
        shadow_offset = max(int(font.size * 0.05), 1)
        draw.text(
            (tx + shadow_offset, ty + shadow_offset), fallback_text, font=font, fill=(0, 0, 0, 150)
        )
        draw.text((tx, ty), fallback_text, font=font, fill=(255, 255, 255, 255))


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
        style=_style_for(ctx),
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


def _fading_side_panel(
    panel_w: int, h: int, rgb: tuple[int, int, int], side: str,
    max_alpha: int = 215, opaque_frac: float = 0.55,
) -> Image.Image:
    """A translucent brand-color wash on one side -- opaque (but never fully
    solid) near the image's outer edge, fading to fully transparent toward
    the panel's inner seam so it blends into the photo instead of ending in
    a hard vertical line. Horizontal mirror of _fading_header_band."""
    opaque_w = int(panel_w * opaque_frac)
    fade_span = max(panel_w - opaque_w - 1, 1)
    gradient = Image.new("L", (panel_w, 1))
    for x in range(panel_w):
        local_x = x if side == "left" else (panel_w - 1 - x)
        alpha = max_alpha if local_x <= opaque_w else int(max_alpha * (1 - (local_x - opaque_w) / fade_span))
        gradient.putpixel((x, 0), max(alpha, 0))
    alpha_mask = gradient.resize((panel_w, h))
    overlay = Image.new("RGBA", (panel_w, h), (*rgb, 0))
    overlay.putalpha(alpha_mask)
    return overlay


def _paste_side_panel(
    img: Image.Image, ctx: CampaignContext, panel_frac: float, side: str
) -> tuple[Image.Image, int, int]:
    """Pastes a translucent brand-color wash on the given side (see
    _fading_side_panel) that fades into the photo at its inner seam instead
    of a hard vertical line. Returns (img, panel_x0, panel_w) so callers know
    where to place text. A "refined minimal" style profile adds a thin
    accent-color hairline at that seam -- the "crisp lines" cue from that
    personality's shape language; an "organic" profile leaves it plain."""
    w, h = img.size
    panel_w = int(w * panel_frac)
    panel_x0 = 0 if side == "left" else w - panel_w
    primary_rgb = _hex_to_rgb(ctx.restaurant.brand_colors["primary"])
    panel = _fading_side_panel(panel_w, h, primary_rgb, side)
    img.paste(panel, (panel_x0, 0), panel)

    style = _style_for(ctx)
    if style.hairline_accent:
        seam_x = panel_x0 + panel_w if side == "left" else panel_x0
        draw = ImageDraw.Draw(img)
        line_w = max(int(w * 0.003), 1)
        draw.rectangle(
            (seam_x - line_w // 2, 0, seam_x + line_w // 2, h),
            fill=_hex_to_rgba(ctx.restaurant.brand_colors["accent"], 255),
        )
    return img, panel_x0, panel_w


def _fading_header_band(
    w: int, h: int, rgb: tuple[int, int, int], max_alpha: int = 205, opaque_frac: float = 0.45
) -> Image.Image:
    """A translucent brand-color wash -- never fully opaque, so the photo
    stays visibly present through the whole band instead of the header
    reading as a solid strip laid over (and blocking) the scene -- that
    fades further to fully transparent by the bottom edge, blending into the
    photo the way the bottom caption scrim already does."""
    opaque_h = int(h * opaque_frac)
    gradient = Image.new("L", (1, h))
    fade_span = max(h - opaque_h - 1, 1)
    for y in range(h):
        alpha = max_alpha if y <= opaque_h else int(max_alpha * (1 - (y - opaque_h) / fade_span))
        gradient.putpixel((0, y), max(alpha, 0))
    alpha_mask = gradient.resize((w, h))
    overlay = Image.new("RGBA", (w, h), (*rgb, 0))
    overlay.putalpha(alpha_mask)
    return overlay


def _radial_glow(
    img: Image.Image, center_x: int, center_y: int, radius: int, rgb: tuple[int, int, int], alpha: int
) -> None:
    """Soft blurred glow behind a badge so it reads as lit within the scene
    rather than a flat shape pasted on top -- a lighting cue distinct from
    the drop shadow's grounding cue, aimed at exactly the 'logo looks
    external' complaint on the opaque header bar."""
    x0, y0 = max(center_x - radius, 0), max(center_y - radius, 0)
    x1, y1 = min(center_x + radius, img.width), min(center_y + radius, img.height)
    if x1 <= x0 or y1 <= y0:
        return
    glow = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        (center_x - x0 - radius, center_y - y0 - radius, center_x - x0 + radius, center_y - y0 + radius),
        fill=(*rgb, alpha),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=max(int(radius * 0.5), 4)))
    img.paste(glow, (x0, y0), glow)


def _draw_header_bar(
    img: Image.Image, draw: ImageDraw.ImageDraw, w: int, h: int, ctx: CampaignContext
) -> int:
    """Translucent brand-color band across the top with the real restaurant
    logo -- a tinted wash the photo shows through, not an opaque strip that
    blocks it, fading further into the photo at its lower edge instead of
    ending in a hard flat seam. Gives the logo a soft ambient glow so it
    reads as embedded in the scene rather than a sticker on a flat color
    field. Returns the header height so callers know where it ends."""
    header_h = int(h * 0.11)
    style = _style_for(ctx)
    primary_rgb = _hex_to_rgb(ctx.restaurant.brand_colors["primary"])
    band = _fading_header_band(w, header_h, primary_rgb)
    img.paste(band, (0, 0), band)

    accent_rgb = _hex_to_rgb(ctx.restaurant.brand_colors["accent"])
    glow_alpha = 60 if style.hairline_accent else 110
    _radial_glow(
        img, center_x=w // 2, center_y=header_h // 2,
        radius=int(header_h * 0.62), rgb=accent_rgb, alpha=glow_alpha,
    )

    _draw_logo_badge(
        img, draw, ctx.restaurant.logo_path, ctx.restaurant.restaurant_name,
        center_x=w // 2, center_y=header_h // 2,
        max_card_h=int(header_h * 0.78), max_card_w=int(w * 0.5),
        style=style,
    )
    return header_h


def _draw_cta_pill(
    draw: ImageDraw.ImageDraw, w: int, h: int, ctx: CampaignContext, settings: Settings
) -> None:
    if not (settings.cta_overlay_enabled and ctx.cta and ctx.cta_text):
        return
    style = _style_for(ctx)
    pill_h = int(h * 0.06)
    font = _get_font(_FONT_BOLD, int(pill_h * 0.5))
    text_w = draw.textlength(ctx.cta_text, font=font)
    pad_x = int(pill_h * 0.6)
    pill_w = int(text_w) + pad_x * 2
    x1, y1 = w - pill_w - int(w * 0.03), h - pill_h - int(h * 0.03)
    x2, y2 = x1 + pill_w, y1 + pill_h
    radius = max(int(pill_h / 2 * style.roundness), 4)
    draw.rounded_rectangle(
        (x1, y1, x2, y2), radius=radius, fill=_hex_to_rgba(ctx.restaurant.brand_colors["accent"], 240)
    )
    if style.hairline_accent:
        draw.rounded_rectangle(
            (x1, y1, x2, y2), radius=radius,
            outline=_hex_to_rgba(ctx.restaurant.brand_colors["primary"], 255),
            width=max(int(pill_h * 0.05), 1),
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
    style = _style_for(ctx)
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
    price_font = _get_font(style.display_font, int(h * 0.075))
    price_w = draw.textlength(price_str, font=price_font) if price_str else 0
    name_max_w = w - padding * 2 - (int(price_w) + padding if price_str else 0)

    name_text, name_font = _fit_text(draw, ctx.main_title, style.display_font, int(h * 0.065), name_max_w)
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
    style = _style_for(ctx)
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
        price_text, price_font = _fit_text(draw, ctx.price, style.display_font, int(badge_d * 0.32), int(badge_d * 0.82))
        pw = draw.textlength(price_text, font=price_font)
        price_ink = tuple(_hex_to_rgb(ctx.restaurant.brand_colors["primary"])) + (255,)
        draw.text((cx - pw // 2, cy - price_font.size // 2), price_text, font=price_font, fill=price_ink)

    scrim_h = int(h * 0.32)
    scrim = _vertical_gradient_scrim(w, scrim_h, (0, 0, 0))
    img.paste(scrim, (0, h - scrim_h), scrim)

    text_color = (255, 255, 255, 255)
    max_w = int(w * 0.86)

    name_text, name_font = _fit_text(draw, ctx.main_title, style.display_font, int(h * 0.078), max_w)
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
    style = _style_for(ctx)
    img = _apply_brand_tone(img, ctx.restaurant.brand_colors["primary"]).convert("RGBA")
    img, panel_x0, panel_w = _paste_side_panel(img, ctx, 0.36, side="right")
    draw = ImageDraw.Draw(img)
    padding = int(w * 0.035)
    text_x = panel_x0 + padding
    max_text_w = panel_w - padding * 2
    text_truncated = False

    _draw_logo_badge(
        img, draw, ctx.restaurant.logo_path, ctx.restaurant.restaurant_name,
        center_x=panel_x0 + panel_w // 2, center_y=int(h * 0.10),
        max_card_h=int(h * 0.13), max_card_w=panel_w - padding,
        style=style,
    )

    text_color = (255, 255, 255, 255)
    accent_color = tuple(_hex_to_rgb(ctx.restaurant.brand_colors["accent"])) + (255,)

    name_text, name_font = _fit_text(draw, ctx.main_title, style.display_font, int(h * 0.068), max_text_w)
    if name_text.endswith("..."):
        text_truncated = True
    draw.text((text_x, int(h * 0.28)), name_text, font=name_font, fill=text_color)

    next_y = 0.44
    if ctx.price:
        price_text, price_font = _fit_text(draw, ctx.price, style.display_font, int(h * 0.085), max_text_w)
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
    style = _style_for(ctx)
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
    offer_line, offer_remainder = _wrap_two_lines(draw, ctx.main_offer, style.display_font, offer_font_size, max_text_w)
    offer_text, offer_font = _fit_text(draw, offer_line, style.display_font, offer_font_size, max_text_w)
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
    style = _style_for(ctx)
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
    offer_line, offer_remainder = _wrap_two_lines(draw, ctx.main_offer, style.display_font, offer_font_size, max_w)
    offer_text, offer_font = _fit_text(draw, offer_line, style.display_font, offer_font_size, max_w)
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
    style = _style_for(ctx)
    img = _apply_brand_tone(img, ctx.restaurant.brand_colors["primary"]).convert("RGBA")
    img, panel_x0, panel_w = _paste_side_panel(img, ctx, 0.36, side="left")
    draw = ImageDraw.Draw(img)
    padding = int(w * 0.035)
    text_x = panel_x0 + padding
    max_text_w = panel_w - padding * 2
    text_truncated = False

    _draw_logo_badge(
        img, draw, ctx.restaurant.logo_path, ctx.restaurant.restaurant_name,
        center_x=panel_x0 + panel_w // 2, center_y=int(h * 0.10),
        max_card_h=int(h * 0.13), max_card_w=panel_w - padding,
        style=style,
    )

    text_color = (255, 255, 255, 255)
    accent_color = tuple(_hex_to_rgb(ctx.restaurant.brand_colors["accent"])) + (255,)

    title_text, title_font = _fit_text(draw, ctx.main_title, _FONT_BOLD, int(h * 0.055), max_text_w)
    if title_text.endswith("..."):
        text_truncated = True
    draw.text((text_x, int(h * 0.26)), title_text, font=title_font, fill=text_color)

    offer_font_size = int(h * 0.09)
    offer_line, offer_remainder = _wrap_two_lines(draw, ctx.main_offer, style.display_font, offer_font_size, max_text_w)
    offer_text, offer_font = _fit_text(draw, offer_line, style.display_font, offer_font_size, max_text_w)
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
    style = _style_for(ctx)
    img = _apply_brand_tone(img, ctx.restaurant.brand_colors["primary"]).convert("RGBA")
    img, panel_x0, panel_w = _paste_side_panel(img, ctx, 0.37, side=side)
    draw = ImageDraw.Draw(img)
    padding = int(w * 0.04)
    text_x = panel_x0 + padding
    max_text_w = panel_w - padding * 2
    text_truncated = False

    _draw_logo_badge(
        img, draw, ctx.restaurant.logo_path, ctx.restaurant.restaurant_name,
        center_x=panel_x0 + panel_w // 2, center_y=int(h * 0.12),
        max_card_h=int(h * 0.15), max_card_w=panel_w - padding,
        style=style,
    )

    text_color = (255, 255, 255, 255)
    accent_color = tuple(_hex_to_rgb(ctx.restaurant.brand_colors["accent"])) + (255,)

    name_text, name_font = _fit_text(draw, ctx.main_title, style.display_font, int(h * 0.10), max_text_w)
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
    style = _style_for(ctx)
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

    name_text, name_font = _fit_text(draw, ctx.main_title, style.display_font, int(h * 0.09), max_w)
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

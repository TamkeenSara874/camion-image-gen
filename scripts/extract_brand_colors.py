#!/usr/bin/env python3
"""
Extracts a restaurant's brand color palette and prints a JSON snippet ready to
paste into config/restaurant_brands.json.

Two modes:
  --logo-path   Extract from the restaurant's REAL logo file (recommended --
                see below).
  --url         Extract from the website's og:image or favicon instead. Only
                use this before a logo has been sourced via
                scripts/fetch_brand_logo.py, since og:image/favicon are
                usually a photography crop or a generic site icon, not the
                brand mark -- they can produce a palette that doesn't match
                the actual logo at all (e.g. a terracotta/orange palette
                extracted from food photography for a restaurant whose real
                logo is green).

Usage:
    python scripts/extract_brand_colors.py --logo-path config/logos/2.png
    python scripts/extract_brand_colors.py --url https://www.mijostaqueria.com
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from io import BytesIO
from urllib.parse import urljoin

import httpx
from colorthief import ColorThief
from PIL import Image


def _find_image_url(page_url: str, html: str) -> str | None:
    og_match = re.search(
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE
    )
    if og_match:
        return urljoin(page_url, og_match.group(1))
    icon_match = re.search(
        r'<link[^>]+rel=["\'](?:shortcut )?icon["\'][^>]+href=["\']([^"\']+)["\']', html, re.IGNORECASE
    )
    if icon_match:
        return urljoin(page_url, icon_match.group(1))
    return None


def _to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def extract_palette_from_logo(logo_path: str, color_count: int = 6) -> list[str]:
    """Composites the logo onto white first so transparent pixels (common in
    a logo PNG) don't skew ColorThief's histogram, then returns the dominant
    swatches ranked by prevalence. Returns the RAW palette, not a picked
    primary/accent -- the top-prevalence color is not necessarily contrast-safe
    as a large-area fill with white overlay text (e.g. Mijo's logo's most
    prevalent green is too light for legible white text at panel scale; a
    darker swatch or a lightness-adjusted shade of the same hue reads better).
    Verify contrast (aim for >=4.5:1 against text_on_primary) before picking."""
    img = Image.open(logo_path).convert("RGBA")
    bg = Image.new("RGB", img.size, (255, 255, 255))
    bg.paste(img, mask=img.split()[-1])
    buf = BytesIO()
    bg.save(buf, format="PNG")
    buf.seek(0)
    thief = ColorThief(buf)
    palette = thief.get_palette(color_count=color_count, quality=1)
    return [_to_hex(c) for c in palette]


def extract_colors(url: str) -> dict[str, str]:
    with httpx.Client(follow_redirects=True, timeout=15.0) as client:
        page = client.get(url)
        page.raise_for_status()
        image_url = _find_image_url(url, page.text)
        if image_url is None:
            raise RuntimeError(f"Could not find og:image or favicon on {url}")

        image_resp = client.get(image_url)
        image_resp.raise_for_status()

    thief = ColorThief(BytesIO(image_resp.content))
    palette = thief.get_palette(color_count=3, quality=1)
    primary, accent = palette[0], palette[1] if len(palette) > 1 else palette[0]

    return {
        "primary": _to_hex(primary),
        "accent": _to_hex(accent),
        "text_on_primary": "#FFFFFF",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--logo-path", help="Path to the restaurant's real logo file (recommended)")
    group.add_argument("--url", help="Restaurant website URL (fallback if no logo sourced yet)")
    args = parser.parse_args()

    try:
        if args.logo_path:
            palette = extract_palette_from_logo(args.logo_path)
            print("Raw palette extracted from the logo, most prevalent first:")
            for hexcode in palette:
                print(f"  {hexcode}")
            print(
                "\nPick primary (large-area fill; check contrast against text_on_primary, "
                "target >=4.5:1) and accent (highlight text) from the swatches above -- "
                "or a lightness-adjusted shade of the same hue if the top swatch is too "
                "light/dark to use as a large fill with legible overlay text."
            )
            print(
                json.dumps(
                    {
                        "brand_colors": {
                            "primary": palette[0],
                            "accent": palette[1] if len(palette) > 1 else palette[0],
                            "text_on_primary": "#FFFFFF",
                        }
                    },
                    indent=2,
                )
            )
        else:
            colors = extract_colors(args.url)
            print(json.dumps({"brand_colors": colors}, indent=2))
    except Exception as exc:
        print(f"Failed to extract colors: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

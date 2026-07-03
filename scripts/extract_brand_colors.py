#!/usr/bin/env python3
"""
Fetches a restaurant's website, extracts dominant + accent colors from its
og:image (falling back to favicon), and prints a JSON snippet ready to paste
into config/restaurant_brands.json.

Usage:
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
    parser.add_argument("--url", required=True, help="Restaurant website URL")
    args = parser.parse_args()

    try:
        colors = extract_colors(args.url)
    except Exception as exc:
        print(f"Failed to extract colors: {exc}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps({"brand_colors": colors}, indent=2))


if __name__ == "__main__":
    main()

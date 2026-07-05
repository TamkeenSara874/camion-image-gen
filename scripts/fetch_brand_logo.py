#!/usr/bin/env python3
"""
Fetches the REAL primary header logo for a restaurant from its live AIO-hosted
website and saves it to config/logos/{restaurant_id}.png.

The image generation model is never asked to draw a restaurant's logo (see
stages/prompt_generator.py's "no logos" mandate) because diffusion models have
no pixel-exact memory of a specific small business's mark -- asking for one
guarantees a plausible-looking fake that changes every generation. The logo
must come from a real, static asset that is composited deterministically
instead. This script is how that asset gets sourced.

All restaurants in this system are hosted on AIO's own site builder, which
embeds a `logoConfig.header.primary.image` URL in a Next.js data payload on
every page. That JSON key is checked first since it is the authoritative
"this is the logo shown in the site header" value. Falls back to `og:image`
and then `<link rel="icon">` for any site that isn't on the AIO builder.

Usage:
    python scripts/fetch_brand_logo.py --url https://mijostaqueria.com --restaurant-id 2
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import httpx

LOGOS_DIR = Path(__file__).parent.parent / "config" / "logos"


def _find_aio_header_logo(html: str) -> str | None:
    """AIO's site builder embeds logoConfig.{header,footer}.{secondary,primary}.image
    URLs in an escaped JSON blob inside a Next.js <script> payload. `header.primary`
    is the logo actually rendered in the live site header -- the key order of
    `header`/`footer` is NOT guaranteed (observed both orderings across live sites),
    so locate `"header"` directly within a window after `logoConfig` rather than
    assuming `footer` comes second, then bound the search to a fixed window past
    `"header"` so it can't leak into a sibling key's own `primary` object."""
    config_idx = html.find("logoConfig")
    if config_idx == -1:
        return None
    window = html[config_idx : config_idx + 6000].replace('\\"', '"').replace("\\/", "/")
    header_idx = window.find('"header"')
    if header_idx == -1:
        return None
    header_block = window[header_idx : header_idx + 1600]
    match = re.search(r'"primary"\s*:\s*\{\s*"image"\s*:\s*"([^"]+)"', header_block)
    if not match:
        return None
    url = match.group(1)
    return url.encode().decode("unicode_escape") if "\\u" in url else url


def _find_og_image_or_favicon(page_url: str, html: str) -> str | None:
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


def fetch_logo_url(page_url: str) -> tuple[str, str]:
    """Returns (logo_url, source) where source is 'aio_header_primary', 'og_image', or 'favicon'."""
    with httpx.Client(follow_redirects=True, timeout=20.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
        page = client.get(page_url)
        page.raise_for_status()
        html = page.text

    aio_logo = _find_aio_header_logo(html)
    if aio_logo:
        return aio_logo, "aio_header_primary"

    fallback = _find_og_image_or_favicon(page_url, html)
    if fallback:
        return fallback, "og_image_or_favicon"

    raise RuntimeError(f"Could not find a logo, og:image, or favicon on {page_url}")


def download_logo(logo_url: str, restaurant_id: int) -> Path:
    with httpx.Client(follow_redirects=True, timeout=20.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
        resp = client.get(logo_url)
        resp.raise_for_status()

    LOGOS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = LOGOS_DIR / f"{restaurant_id}.png"

    from io import BytesIO

    from PIL import Image

    img = Image.open(BytesIO(resp.content)).convert("RGBA")
    img.save(out_path, format="PNG")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Restaurant website URL")
    parser.add_argument("--restaurant-id", required=True, type=int, help="restaurantId to key the saved file")
    args = parser.parse_args()

    try:
        logo_url, source = fetch_logo_url(args.url)
        out_path = download_logo(logo_url, args.restaurant_id)
    except Exception as exc:
        print(f"Failed to fetch logo: {exc}", file=sys.stderr)
        sys.exit(1)

    rel_path = f"config/logos/{args.restaurant_id}.png"
    print(f"Saved logo ({source}) -> {out_path}")
    print(json.dumps({"logo_path": rel_path}, indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

import httpx
from PIL import Image

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
    """Returns (logo_url, source) where source is 'aio_header_primary', 'og_image', or 'favicon'.
    Synchronous (httpx.Client, not AsyncClient) so it can be shared as-is between
    the one-off CLI script and the pipeline's asyncio.to_thread call -- see
    stages/brand_mapper.py::ensure_logo."""
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

    img = Image.open(BytesIO(resp.content)).convert("RGBA")
    img.save(out_path, format="PNG")
    return out_path

#!/usr/bin/env python3
"""
Manually fetches the REAL primary header logo for a restaurant from its live
AIO-hosted website and saves it to config/logos/{restaurant_id}.png.

The image generation model is never asked to draw a restaurant's logo (see
stages/prompt_generator.py's "no logos" mandate) because diffusion models have
no pixel-exact memory of a specific small business's mark -- asking for one
guarantees a plausible-looking fake that changes every generation. The logo
must come from a real, static asset that is composited deterministically
instead.

This CLI is the manual/offline way to pre-populate a logo. In normal
operation you don't need to run this at all: stages/brand_mapper.py's
ensure_logo() calls the same fetch/download logic (services/logo_fetcher.py)
automatically the first time a restaurant with no cached logo is requested,
in parallel with prompt generation and image synthesis so it adds no
latency in the common case. Run this manually only if you want the file
present ahead of time (e.g. to commit it, or to pre-warm the cache).

Usage:
    python scripts/fetch_brand_logo.py --url https://mijostaqueria.com --restaurant-id 2
"""

from __future__ import annotations

import argparse
import json
import sys

from services.logo_fetcher import download_logo, fetch_logo_url


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

"""
Phase 4 deliverable script.
Generates real images for 2 sample payloads (stages 1-5).
Uploads to R2 if credentials are real; saves to outputs/ otherwise.

Usage:
    python scripts/run_phase4.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

SAMPLE_PAYLOADS_DIR = ROOT / "sample_payloads"
OUTPUTS_DIR = ROOT / "outputs"

PAYLOAD_FILES = [
    "mijos_2_menu_items.json",
    "flights_2_menu_items.json",
]


async def run_one(filename: str, settings) -> dict:
    from schemas.request import CampaignPayload
    from stages.brand_mapper import map_brand
    from stages.campaign_parser import parse
    from stages.image_synthesizer import synthesize
    from stages.prompt_generator import generate_prompt
    from stages.validator import validate

    with open(SAMPLE_PAYLOADS_DIR / filename, encoding="utf-8") as f:
        data = json.load(f)

    payload = CampaignPayload.model_validate(data)
    validate(payload)
    brand = map_brand(payload.restaurantId)
    ctx = parse(payload, brand)
    prompt_response = await generate_prompt(ctx, settings)

    print(f"  Prompt: {prompt_response.final_image_prompt[:100]}...")
    t0 = time.perf_counter()
    synthesis = await synthesize(prompt_response, ctx, settings)
    synthesis_ms = int((time.perf_counter() - t0) * 1000)

    image_url = _save_or_upload(synthesis.image_bytes, payload.restaurantId, filename, settings)

    return {
        "payload": filename,
        "restaurant": ctx.restaurant.restaurant_name,
        "campaign_type": ctx.campaign_type,
        "image_size": ctx.image_size,
        "model_used": synthesis.model_used,
        "attempt_number": synthesis.attempt_number,
        "orientation_preserved": synthesis.orientation_preserved,
        "synthesis_latency_ms": synthesis_ms,
        "image_size_bytes": len(synthesis.image_bytes),
        "image_url": image_url,
        "alt_text": prompt_response.alt_text,
    }


def _save_or_upload(image_bytes: bytes, restaurant_id: int, filename: str, settings) -> str:
    if "placeholder" not in settings.r2_account_id:
        try:
            import asyncio as _a
            from services.storage import upload_image
            url = _a.get_event_loop().run_until_complete(
                upload_image(image_bytes, restaurant_id, settings)
            )
            return url
        except Exception as exc:
            print(f"  R2 upload failed ({exc}), saving locally")

    OUTPUTS_DIR.mkdir(exist_ok=True)
    name = filename.replace(".json", "") + ".jpg"
    local_path = OUTPUTS_DIR / name
    local_path.write_bytes(image_bytes)
    return str(local_path)


async def main() -> None:
    from app.config import get_settings

    settings = get_settings()
    OUTPUTS_DIR.mkdir(exist_ok=True)

    results = []
    total_time = 0.0

    for filename in PAYLOAD_FILES:
        print(f"\nGenerating image for {filename} ...")
        t0 = time.perf_counter()
        try:
            entry = await run_one(filename, settings)
            elapsed = time.perf_counter() - t0
            total_time += elapsed
            results.append(entry)
            print(f"  Model:    {entry['model_used']} (attempt {entry['attempt_number']})")
            print(f"  Synthesis:{entry['synthesis_latency_ms']}ms")
            print(f"  Size:     {entry['image_size_bytes']:,} bytes")
            print(f"  Alt text: {entry['alt_text']}")
            print(f"  URL/Path: {entry['image_url']}")
        except Exception as exc:
            print(f"  FAILED: {exc}")

    output_path = OUTPUTS_DIR / "phase4_results.json"
    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nSaved results to {output_path}")
    print(f"Total wall time: {total_time:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())

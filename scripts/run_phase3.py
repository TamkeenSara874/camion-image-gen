"""
Phase 3 deliverable script.
Run after .env is populated with OPENAI_API_KEY.
Generates real prompts for all 6 sample payloads and saves to outputs/phase3_prompts.json.

Usage:
    python scripts/run_phase3.py
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
OUTPUT_FILE = OUTPUTS_DIR / "phase3_prompts.json"

PAYLOAD_FILES = [
    "mijos_1_spotlights.json",
    "mijos_2_menu_items.json",
    "mijos_3_deals.json",
    "flights_1_spotlights.json",
    "flights_2_menu_items.json",
    "flights_3_deals.json",
]


async def run_one(filename: str, settings) -> dict:
    from schemas.request import CampaignPayload
    from stages.brand_mapper import map_brand
    from stages.campaign_parser import parse
    from stages.prompt_generator import generate_prompt
    from stages.validator import validate

    with open(SAMPLE_PAYLOADS_DIR / filename, encoding="utf-8") as f:
        data = json.load(f)

    payload = CampaignPayload.model_validate(data)
    validate(payload)
    brand = map_brand(payload.restaurantId)
    ctx = parse(payload, brand)

    t0 = time.perf_counter()
    result = await generate_prompt(ctx, settings)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    input_tokens = int(result.metadata.get("input_tokens", 0))
    output_tokens = int(result.metadata.get("output_tokens", 0))
    cost = (input_tokens / 1_000_000 * 0.15) + (output_tokens / 1_000_000 * 0.60)

    return {
        "payload": filename,
        "restaurant": ctx.restaurant.restaurant_name,
        "campaign_type": ctx.campaign_type,
        "image_size": ctx.image_size,
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": round(cost, 6),
        "final_image_prompt": result.final_image_prompt,
        "alt_text": result.alt_text,
    }


async def main() -> None:
    from app.config import get_settings

    settings = get_settings()
    OUTPUTS_DIR.mkdir(exist_ok=True)

    results = []
    total_cost = 0.0

    for filename in PAYLOAD_FILES:
        print(f"Generating prompt for {filename} ...", end=" ", flush=True)
        entry = await run_one(filename, settings)
        results.append(entry)
        total_cost += entry["estimated_cost_usd"]
        print(f"{entry['latency_ms']}ms  ${entry['estimated_cost_usd']:.6f}")

    OUTPUT_FILE.write_text(json.dumps(results, indent=2), encoding="utf-8")

    print(f"\nSaved {len(results)} prompts to {OUTPUT_FILE}")
    print(f"Total estimated cost: ${total_cost:.4f}")
    print("\nSample prompt (flights_2_menu_items):")
    sample = next(r for r in results if "flights_2" in r["payload"])
    print(f"  {sample['final_image_prompt'][:200]}...")
    print(f"  Alt text: {sample['alt_text']}")


if __name__ == "__main__":
    asyncio.run(main())

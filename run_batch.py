#!/usr/bin/env python3
"""
Batch runner: processes all 6 sample payloads through the full 7-stage pipeline.
Results written to outputs/batch_summary.json.

Usage:
    python run_batch.py                  # full pipeline (costs ~$0.30 for all 6)
    python run_batch.py --prompts-only   # stages 1-4 only (~$0.006 total, no images generated)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path


PAYLOADS_DIR = Path("sample_payloads")
OUTPUTS_DIR = Path("outputs")


def _load_payloads() -> list[tuple[str, dict]]:
    files = sorted(PAYLOADS_DIR.glob("*.json"))
    if not files:
        print(f"No JSON files found in {PAYLOADS_DIR}/")
        sys.exit(1)
    return [(f.name, json.loads(f.read_text(encoding="utf-8"))) for f in files]


async def _run_full_pipeline(payload_name: str, raw: dict) -> dict:
    from app.config import get_settings
    from pipeline.image_pipeline import run
    from schemas.request import CampaignPayload

    settings = get_settings()
    payload = CampaignPayload.model_validate(raw)
    t0 = time.perf_counter()
    try:
        response = await run(payload, settings)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "payload": payload_name,
            "restaurant_id": raw.get("restaurantId"),
            "campaign_type": raw.get("campaign_type"),
            "restaurant_name": response.restaurant_name,
            "status": "ok",
            "image_url": response.image_url,
            "model_used": response.model_used,
            "attempt_number": response.attempt_number,
            "orientation_preserved": response.orientation_preserved,
            "alt_text": response.alt_text,
            "generated_prompt": response.generated_prompt[:120] + "...",
            "qa_passed": response.qa_passed,
            "qa_retries": response.qa_retries,
            "clip_score": response.clip_score,
            "qa_scores": response.qa_scores,
            "total_latency_ms": response.metrics.total_latency_ms,
            "total_cost_usd": response.metrics.total_cost_usd,
            "stage_breakdown": [
                {"stage": s.stage, "latency_ms": s.latency_ms, "cost_usd": s.cost_usd}
                for s in response.metrics.stage_breakdown
            ],
        }
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "payload": payload_name,
            "restaurant_id": raw.get("restaurantId"),
            "campaign_type": raw.get("campaign_type"),
            "status": "error",
            "error": str(exc),
            "total_latency_ms": elapsed_ms,
            "total_cost_usd": 0.0,
        }


async def _run_prompts_only(payload_name: str, raw: dict) -> dict:
    from app.config import get_settings
    from stages.brand_mapper import map_brand
    from stages.campaign_parser import parse
    from stages.prompt_generator import generate_prompt
    from stages.validator import validate as validate_payload
    from schemas.request import CampaignPayload

    settings = get_settings()
    payload = CampaignPayload.model_validate(raw)
    t0 = time.perf_counter()
    try:
        validate_payload(payload)
        brand = map_brand(payload.restaurantId)
        ctx = parse(payload, brand)
        prompt_response = await generate_prompt(ctx, settings)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        in_t = int(prompt_response.metadata.get("input_tokens", 0))
        out_t = int(prompt_response.metadata.get("output_tokens", 0))
        return {
            "payload": payload_name,
            "restaurant_id": raw.get("restaurantId"),
            "campaign_type": raw.get("campaign_type"),
            "restaurant_name": brand.restaurant_name,
            "status": "ok",
            "generated_prompt": prompt_response.final_image_prompt,
            "alt_text": prompt_response.alt_text,
            "input_tokens": in_t,
            "output_tokens": out_t,
            "total_latency_ms": elapsed_ms,
            "total_cost_usd": 0.0,
        }
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "payload": payload_name,
            "restaurant_id": raw.get("restaurantId"),
            "campaign_type": raw.get("campaign_type"),
            "status": "error",
            "error": str(exc),
            "total_latency_ms": elapsed_ms,
            "total_cost_usd": 0.0,
        }


def _print_summary(results: list[dict], prompts_only: bool) -> None:
    print()
    print(f"{'PAYLOAD':<35} {'STATUS':<8} {'LATENCY':>10} {'COST':>10}")
    print("-" * 65)
    for r in results:
        status = r["status"]
        latency = f"{r['total_latency_ms']}ms"
        cost = f"${r['total_cost_usd']:.4f}"
        print(f"{r['payload']:<35} {status:<8} {latency:>10} {cost:>10}")
    print("-" * 65)

    ok = [r for r in results if r["status"] == "ok"]
    total_cost = sum(r["total_cost_usd"] for r in results)
    mean_latency = sum(r["total_latency_ms"] for r in ok) / len(ok) if ok else 0

    if not prompts_only:
        qa_passed = sum(1 for r in ok if r.get("qa_passed"))
        clip_scores = [r["clip_score"] for r in ok if r.get("clip_score") is not None]
        mean_clip = sum(clip_scores) / len(clip_scores) if clip_scores else None
        print(f"\nSuccessful: {len(ok)}/{len(results)}")
        print(f"QA pass rate: {qa_passed}/{len(ok)}")
        print(f"Mean CLIP score: {mean_clip:.3f}" if mean_clip is not None else "Mean CLIP score: N/A")
        print(f"Mean latency: {mean_latency:.0f}ms")
        print(f"Total cost: ${total_cost:.4f}")
    else:
        print(f"\nSuccessful: {len(ok)}/{len(results)} (prompts only, no images generated)")
        print(f"Mean latency: {mean_latency:.0f}ms")
        print(f"Total cost: ${total_cost:.4f}")


async def main(prompts_only: bool) -> None:
    OUTPUTS_DIR.mkdir(exist_ok=True)
    payloads = _load_payloads()
    print(f"Processing {len(payloads)} payloads ({'prompts only' if prompts_only else 'full pipeline'})...")

    runner = _run_prompts_only if prompts_only else _run_full_pipeline
    results = []
    for name, raw in payloads:
        print(f"  -> {name} ...", end="", flush=True)
        result = await runner(name, raw)
        status = "ok" if result["status"] == "ok" else f"ERROR: {result.get('error', '')[:60]}"
        print(f" {status}")
        results.append(result)

    ok = [r for r in results if r["status"] == "ok"]
    total_cost = sum(r["total_cost_usd"] for r in results)
    mean_latency = sum(r["total_latency_ms"] for r in ok) / len(ok) if ok else 0

    summary: dict = {
        "run_date": datetime.now().isoformat(),
        "mode": "prompts_only" if prompts_only else "full_pipeline",
        "total_payloads": len(results),
        "successful": len(ok),
        "failed": len(results) - len(ok),
        "total_cost_usd": round(total_cost, 6),
        "mean_latency_ms": round(mean_latency),
        "payloads": results,
    }

    if not prompts_only:
        qa_passed = sum(1 for r in ok if r.get("qa_passed"))
        clip_scores = [r["clip_score"] for r in ok if r.get("clip_score") is not None]
        summary["qa_pass_rate"] = qa_passed / len(ok) if ok else 0.0
        summary["mean_clip_score"] = round(sum(clip_scores) / len(clip_scores), 4) if clip_scores else None

    out_path = OUTPUTS_DIR / "batch_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    _print_summary(results, prompts_only)
    print(f"\nResults written to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Camion batch image generator")
    parser.add_argument(
        "--prompts-only",
        action="store_true",
        help="Run stages 1-4 only (generate prompts, skip image synthesis). Safe and cheap.",
    )
    args = parser.parse_args()
    asyncio.run(main(prompts_only=args.prompts_only))

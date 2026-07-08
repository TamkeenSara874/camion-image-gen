from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status

from api.auth import verify_token
from app.config import Settings, get_settings
from pipeline.image_pipeline import run
from schemas.request import CampaignPayload
from schemas.response import JobStatusResponse
from services.job_store import Job, JobStatus, create_job, get_job

logger = logging.getLogger(__name__)

router = APIRouter(tags=["image"])


def _to_response(job: Job) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status.value,
        progress=job.progress,
        stage=job.stage,
        result=job.result,
        error=job.error,
    )


async def _run_job(job_id: str, payload: CampaignPayload, settings: Settings) -> None:
    job = get_job(job_id)
    if job is None:
        return  # pruned or otherwise gone; nothing to update

    job.status = JobStatus.RUNNING

    def on_progress(pct: int, stage: str) -> None:
        job.progress = pct
        job.stage = stage

    try:
        job.result = await run(payload, settings, on_progress=on_progress)
        job.status = JobStatus.COMPLETE
        job.progress = 100
        job.stage = "Done"
    except (ValueError, RuntimeError) as exc:
        job.status = JobStatus.FAILED
        job.error = str(exc)
    except Exception:
        logger.exception("image_generation_job_failed", extra={"job_id": job_id})
        job.status = JobStatus.FAILED
        job.error = "Internal error during image generation."


@router.post(
    "/api/generate-image",
    response_model=JobStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_token)],
)
async def generate_image(
    payload: CampaignPayload,
    settings: Settings = Depends(get_settings),
) -> JobStatusResponse:
    """Starts image generation as a background job and returns immediately --
    the actual generation (image synthesis in particular) commonly takes
    45-100s, well past what's reasonable to hold an HTTP request open for.
    Poll GET /api/generate-image/{job_id} for progress and the final result."""
    job = create_job()
    asyncio.create_task(_run_job(job.job_id, payload, settings))
    return _to_response(job)


@router.get(
    "/api/generate-image/{job_id}",
    response_model=JobStatusResponse,
    dependencies=[Depends(verify_token)],
)
async def get_generate_image_job(job_id: str) -> JobStatusResponse:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No such job: {job_id!r} (may have completed and been pruned, or never existed)",
        )
    return _to_response(job)

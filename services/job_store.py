from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum

from schemas.response import ImageGenerationResponse

# In-process dict, same pattern (and same limitation) as the pipeline's
# existing response cache/daily-count dicts in pipeline/image_pipeline.py:
# fine for a single worker, not shared across replicas or restarts. See
# README "Known limitations". A job older than _JOB_TTL_SECONDS is pruned
# on the next create_job() call so this can't grow unbounded.
_JOB_TTL_SECONDS = 3600.0

_jobs: dict[str, Job] = {}


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class Job:
    job_id: str
    status: JobStatus = JobStatus.PENDING
    progress: int = 0
    stage: str = "Queued"
    result: ImageGenerationResponse | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.monotonic)


def create_job() -> Job:
    _prune_stale_jobs()
    job = Job(job_id=uuid.uuid4().hex[:16])
    _jobs[job.job_id] = job
    return job


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def _prune_stale_jobs() -> None:
    now = time.monotonic()
    stale = [jid for jid, j in _jobs.items() if now - j.created_at > _JOB_TTL_SECONDS]
    for jid in stale:
        del _jobs[jid]

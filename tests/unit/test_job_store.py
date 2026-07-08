from __future__ import annotations

import services.job_store as job_store_mod
from services.job_store import JobStatus, create_job, get_job


def setup_function() -> None:
    job_store_mod._jobs.clear()


def test_create_job_starts_pending_with_zero_progress():
    job = create_job()
    assert job.status == JobStatus.PENDING
    assert job.progress == 0
    assert job.stage == "Queued"
    assert job.result is None
    assert job.error is None


def test_create_job_returns_unique_ids():
    job1 = create_job()
    job2 = create_job()
    assert job1.job_id != job2.job_id


def test_get_job_returns_the_same_object_by_id():
    job = create_job()
    fetched = get_job(job.job_id)
    assert fetched is job


def test_get_job_returns_none_for_unknown_id():
    assert get_job("does-not-exist") is None


def test_mutating_the_fetched_job_persists():
    job = create_job()
    fetched = get_job(job.job_id)
    fetched.progress = 42
    fetched.stage = "Generating image..."

    assert get_job(job.job_id).progress == 42
    assert get_job(job.job_id).stage == "Generating image..."


def test_stale_jobs_are_pruned_on_next_create(monkeypatch):
    old_job = create_job()

    # Simulate the old job having been created long before the TTL window.
    old_job.created_at -= job_store_mod._JOB_TTL_SECONDS + 1

    create_job()  # triggers pruning as a side effect

    assert get_job(old_job.job_id) is None


def test_fresh_jobs_survive_pruning():
    job = create_job()
    create_job()  # a second job shouldn't prune the first, still-fresh one

    assert get_job(job.job_id) is job

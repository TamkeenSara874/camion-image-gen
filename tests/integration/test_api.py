from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import services.job_store as job_store_mod
from schemas.response import ImageGenerationResponse, ResponseMetrics, StageBreakdown


def _fake_response() -> ImageGenerationResponse:
    return ImageGenerationResponse(
        image_url="https://test.r2.dev/2/abc.jpg",
        model_used="gpt-image-2",
        attempt_number=1,
        orientation_preserved=True,
        restaurant_name="Mijo's Taqueria",
        campaign_type="Menu Items",
        aspect_ratio="16:9",
        generated_prompt="Vibrant taco scene.",
        alt_text="Baja Fish Taco",
        qa_passed=True,
        qa_retries=0,
        clip_score=0.28,
        qa_scores={"brand_fidelity": 5, "composition": 5},
        metrics=ResponseMetrics(
            total_latency_ms=1200,
            total_cost_usd=0.046,
            stage_breakdown=[StageBreakdown(stage="image_synthesizer", latency_ms=1100, cost_usd=0.042)],
        ),
    )


_VALID_PAYLOAD = {
    "campaign_type": "Menu Items",
    "campaign_goals": "Increase Item Sales",
    "campaign_audiences": ["New"],
    "campaign_guest_tags": [],
    "campaign_vars": {
        "name": "Baja Fish Taco",
        "description": "Crispy fish taco.",
        "price": "12",
        "item_category": ["Tacos"],
        "item_menu": "",
    },
    "cta": False,
    "channels": ["Email"],
    "campaign_brand_voices": "Casual",
    "restaurantId": 2,
    "orientation": "Landscape",
    "custom_prompt": None,
}

_AUTH = {"Authorization": "Bearer test-bearer"}


@pytest.fixture(autouse=True)
def _reset_job_store():
    job_store_mod._jobs.clear()
    yield
    job_store_mod._jobs.clear()


async def _await_job_terminal(client: AsyncClient, job_id: str, timeout: float = 2.0) -> dict:
    """Polls the status endpoint until the background job reaches a terminal
    state. Real requests take 45-100s; in tests `run` is mocked to resolve
    near-instantly, so this only needs a few event-loop turns -- not real
    wall-clock waiting."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        response = await client.get(f"/api/generate-image/{job_id}", headers=_AUTH)
        body = response.json()
        if body["status"] in ("complete", "failed"):
            return body
        await asyncio.sleep(0.01)
    raise TimeoutError(f"job {job_id} never reached a terminal state: last body was {body}")


@pytest.fixture()
def test_settings():
    from app.config import Settings
    return Settings(
        openai_api_key="sk-test",
        api_bearer_token="test-bearer",
        r2_account_id="test-acct",
        r2_access_key_id="test-key",
        r2_secret_access_key="test-secret",
        r2_bucket_name="test-bucket",
        r2_public_url="https://test.r2.dev",
    )


@pytest.fixture()
def placeholder_settings():
    from app.config import Settings
    return Settings(
        openai_api_key="sk-test",
        api_bearer_token="test-bearer",
        r2_account_id="placeholder",
        r2_access_key_id="placeholder",
        r2_secret_access_key="placeholder",
        r2_bucket_name="test-bucket",
        r2_public_url="https://test.r2.dev",
    )


@pytest.fixture()
async def client(test_settings):
    from main import app
    from app.config import get_settings
    app.dependency_overrides[get_settings] = lambda: test_settings
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
async def client_placeholder(placeholder_settings):
    from main import app
    from app.config import get_settings
    app.dependency_overrides[get_settings] = lambda: placeholder_settings
    # readiness() calls get_settings() directly (not via DI), so patch the module reference
    with patch("api.routes.health.get_settings", return_value=placeholder_settings):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    app.dependency_overrides.clear()


class TestHealthEndpoints:
    async def test_health_returns_ok(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    async def test_readiness_ready(self, client):
        response = await client.get("/health/ready")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["checks"]["openai"] is True
        assert body["checks"]["r2"] is True

    async def test_readiness_not_ready_with_placeholders(self, client_placeholder):
        response = await client_placeholder.get("/health/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not_ready"
        assert body["checks"]["r2"] is False


class TestAuth:
    async def test_no_auth_header_on_post_returns_403(self, client):
        response = await client.post("/api/generate-image", json=_VALID_PAYLOAD)
        assert response.status_code == 403

    async def test_no_auth_header_on_get_returns_403(self, client):
        response = await client.get("/api/generate-image/some-job-id")
        assert response.status_code == 403

    async def test_wrong_token_returns_401(self, client):
        response = await client.post(
            "/api/generate-image",
            json=_VALID_PAYLOAD,
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert response.status_code == 401
        assert "Invalid bearer token" in response.json()["detail"]

    async def test_correct_token_passes_auth(self, client):
        with patch("api.routes.image.run", AsyncMock(return_value=_fake_response())):
            response = await client.post(
                "/api/generate-image", json=_VALID_PAYLOAD, headers=_AUTH
            )
            assert response.status_code == 202
            await _await_job_terminal(client, response.json()["job_id"])


class TestGenerateImageEndpoint:
    async def test_post_returns_202_with_pending_job(self, client):
        with patch("api.routes.image.run", AsyncMock(return_value=_fake_response())):
            response = await client.post(
                "/api/generate-image", json=_VALID_PAYLOAD, headers=_AUTH
            )
            # The POST response itself must reflect the pre-task state (the
            # background task is only scheduled, not yet run, at this point).
            assert response.status_code == 202
            body = response.json()
            assert body["status"] == "pending"
            assert body["progress"] == 0
            assert body["result"] is None
            assert "job_id" in body and body["job_id"]
            # Drain the background task so it doesn't outlive this test.
            await _await_job_terminal(client, body["job_id"])

    async def test_job_completes_and_returns_result(self, client):
        with patch("api.routes.image.run", AsyncMock(return_value=_fake_response())):
            post_response = await client.post(
                "/api/generate-image", json=_VALID_PAYLOAD, headers=_AUTH
            )
            job_id = post_response.json()["job_id"]
            body = await _await_job_terminal(client, job_id)

        assert body["status"] == "complete"
        assert body["progress"] == 100
        assert body["result"]["image_url"] == "https://test.r2.dev/2/abc.jpg"
        assert body["result"]["model_used"] == "gpt-image-2"

    async def test_unknown_job_id_returns_404(self, client):
        response = await client.get("/api/generate-image/does-not-exist", headers=_AUTH)
        assert response.status_code == 404

    async def test_invalid_campaign_type_surfaces_as_failed_job(self, client):
        bad_payload = {**_VALID_PAYLOAD, "campaign_type": "Flash Sale"}
        with patch(
            "api.routes.image.run", AsyncMock(side_effect=ValueError("Unknown campaign_type"))
        ):
            post_response = await client.post(
                "/api/generate-image", json=bad_payload, headers=_AUTH
            )
            job_id = post_response.json()["job_id"]
            body = await _await_job_terminal(client, job_id)

        assert post_response.status_code == 202  # accepted immediately regardless
        assert body["status"] == "failed"
        assert "Unknown campaign_type" in body["error"]

    async def test_daily_limit_surfaces_as_failed_job(self, client):
        with patch(
            "api.routes.image.run",
            AsyncMock(side_effect=RuntimeError("Daily image limit reached")),
        ):
            post_response = await client.post(
                "/api/generate-image", json=_VALID_PAYLOAD, headers=_AUTH
            )
            job_id = post_response.json()["job_id"]
            body = await _await_job_terminal(client, job_id)

        assert body["status"] == "failed"
        assert "Daily image limit" in body["error"]

    async def test_unexpected_pipeline_error_surfaces_as_failed_job(self, client):
        with patch(
            "api.routes.image.run", AsyncMock(side_effect=RuntimeError("all models exhausted"))
        ):
            post_response = await client.post(
                "/api/generate-image", json=_VALID_PAYLOAD, headers=_AUTH
            )
            job_id = post_response.json()["job_id"]
            body = await _await_job_terminal(client, job_id)

        assert body["status"] == "failed"
        assert "all models exhausted" in body["error"]

    async def test_result_schema_valid_once_complete(self, client):
        with patch("api.routes.image.run", AsyncMock(return_value=_fake_response())):
            post_response = await client.post(
                "/api/generate-image", json=_VALID_PAYLOAD, headers=_AUTH
            )
            job_id = post_response.json()["job_id"]
            body = await _await_job_terminal(client, job_id)

        result = body["result"]
        assert isinstance(result["qa_passed"], bool)
        assert isinstance(result["qa_retries"], int)
        assert isinstance(result["metrics"]["total_cost_usd"], float)
        assert isinstance(result["metrics"]["stage_breakdown"], list)

    async def test_progress_updates_visible_while_running(self, client):
        """The job's progress/stage should reflect what the pipeline reports
        via on_progress, not just jump straight from 0 to 100."""
        seen_progress: list[int] = []

        async def slow_run(payload, settings, on_progress=None):
            if on_progress:
                on_progress(5, "Validating campaign")
                on_progress(25, "Writing creative direction")
                await asyncio.sleep(0.05)
                on_progress(80, "Compositing image")
            return _fake_response()

        with patch("api.routes.image.run", slow_run):
            post_response = await client.post(
                "/api/generate-image", json=_VALID_PAYLOAD, headers=_AUTH
            )
            job_id = post_response.json()["job_id"]

            # Poll a couple of times while it's still running.
            for _ in range(20):
                mid = await client.get(f"/api/generate-image/{job_id}", headers=_AUTH)
                seen_progress.append(mid.json()["progress"])
                if mid.json()["status"] == "complete":
                    break
                await asyncio.sleep(0.01)
            else:
                await _await_job_terminal(client, job_id)  # ensure it's drained either way

        assert any(0 < p < 100 for p in seen_progress), f"never saw partial progress: {seen_progress}"

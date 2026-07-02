from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from schemas.internal import CompositeResult, ImagePromptResponse, SynthesisResult
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
    async def test_no_auth_header_returns_403(self, client):
        response = await client.post("/api/generate-image", json=_VALID_PAYLOAD)
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
                "/api/generate-image",
                json=_VALID_PAYLOAD,
                headers={"Authorization": "Bearer test-bearer"},
            )
        assert response.status_code == 200


class TestGenerateImageEndpoint:
    async def test_success_returns_image_url(self, client):
        with patch("api.routes.image.run", AsyncMock(return_value=_fake_response())):
            response = await client.post(
                "/api/generate-image",
                json=_VALID_PAYLOAD,
                headers={"Authorization": "Bearer test-bearer"},
            )

        assert response.status_code == 200
        body = response.json()
        assert "image_url" in body
        assert "model_used" in body
        assert "metrics" in body

    async def test_invalid_campaign_type_returns_422(self, client):
        bad_payload = {**_VALID_PAYLOAD, "campaign_type": "Flash Sale"}
        with patch("api.routes.image.run", AsyncMock(side_effect=ValueError("Unknown campaign_type"))):
            response = await client.post(
                "/api/generate-image",
                json=bad_payload,
                headers={"Authorization": "Bearer test-bearer"},
            )

        assert response.status_code == 422

    async def test_daily_limit_returns_429(self, client):
        with patch(
            "api.routes.image.run",
            AsyncMock(side_effect=RuntimeError("Daily image limit reached")),
        ):
            response = await client.post(
                "/api/generate-image",
                json=_VALID_PAYLOAD,
                headers={"Authorization": "Bearer test-bearer"},
            )

        assert response.status_code == 429

    async def test_pipeline_error_returns_500(self, client):
        with patch(
            "api.routes.image.run",
            AsyncMock(side_effect=RuntimeError("all models exhausted")),
        ):
            response = await client.post(
                "/api/generate-image",
                json=_VALID_PAYLOAD,
                headers={"Authorization": "Bearer test-bearer"},
            )

        assert response.status_code == 500

    async def test_response_schema_valid(self, client):
        with patch("api.routes.image.run", AsyncMock(return_value=_fake_response())):
            response = await client.post(
                "/api/generate-image",
                json=_VALID_PAYLOAD,
                headers={"Authorization": "Bearer test-bearer"},
            )

        body = response.json()
        assert isinstance(body["qa_passed"], bool)
        assert isinstance(body["qa_retries"], int)
        assert isinstance(body["metrics"]["total_cost_usd"], float)
        assert isinstance(body["metrics"]["stage_breakdown"], list)

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/health/ready")
async def readiness() -> JSONResponse:
    settings = get_settings()
    checks = {
        "openai": bool(settings.openai_api_key),
        "r2": all([
            settings.r2_account_id != "placeholder",
            settings.r2_access_key_id != "placeholder",
            settings.r2_secret_access_key != "placeholder",
        ]),
    }
    ready = all(checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "checks": checks},
    )

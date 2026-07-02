from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from api.auth import verify_token
from app.config import Settings, get_settings
from pipeline.image_pipeline import run
from schemas.request import CampaignPayload
from schemas.response import ImageGenerationResponse

router = APIRouter(tags=["image"])


@router.post(
    "/api/generate-image",
    response_model=ImageGenerationResponse,
    dependencies=[Depends(verify_token)],
)
async def generate_image(
    payload: CampaignPayload,
    settings: Settings = Depends(get_settings),
) -> ImageGenerationResponse:
    try:
        return await run(payload, settings)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except RuntimeError as exc:
        msg = str(exc)
        if "daily image limit" in msg.lower():
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=msg)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=msg,
        )

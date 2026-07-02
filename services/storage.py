from __future__ import annotations

import asyncio
import uuid

import boto3

from app.config import Settings


def _make_r2_client(settings: Settings):
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
    )


def _upload_sync(image_bytes: bytes, key: str, settings: Settings) -> None:
    client = _make_r2_client(settings)
    client.put_object(
        Bucket=settings.r2_bucket_name,
        Key=key,
        Body=image_bytes,
        ContentType="image/jpeg",
        CacheControl="public, max-age=86400",
    )


async def upload_image(
    image_bytes: bytes,
    restaurant_id: int,
    settings: Settings,
    alt_text: str = "",
) -> str:
    key = f"{restaurant_id}/{uuid.uuid4().hex}.jpg"
    await asyncio.to_thread(_upload_sync, image_bytes, key, settings)
    return f"{settings.r2_public_url.rstrip('/')}/{key}"

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.storage import upload_image


def _fake_settings(
    r2_account_id: str = "acc123",
    r2_access_key_id: str = "key",
    r2_secret_access_key: str = "secret",
    r2_bucket_name: str = "camion-images",
    r2_public_url: str = "https://pub.r2.dev",
) -> MagicMock:
    s = MagicMock()
    s.r2_account_id = r2_account_id
    s.r2_access_key_id = r2_access_key_id
    s.r2_secret_access_key = r2_secret_access_key
    s.r2_bucket_name = r2_bucket_name
    s.r2_public_url = r2_public_url
    return s


@pytest.mark.asyncio
async def test_upload_returns_public_url():
    settings = _fake_settings()
    with patch("boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        url = await upload_image(b"IMAGE", restaurant_id=2, settings=settings)

    assert url.startswith("https://pub.r2.dev/2/")
    assert url.endswith(".jpg")


@pytest.mark.asyncio
async def test_upload_url_strips_trailing_slash_from_public_url():
    settings = _fake_settings(r2_public_url="https://pub.r2.dev/")
    with patch("boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        url = await upload_image(b"IMAGE", restaurant_id=4, settings=settings)

    assert not url.startswith("https://pub.r2.dev//")
    assert url.startswith("https://pub.r2.dev/4/")


@pytest.mark.asyncio
async def test_upload_calls_put_object_with_correct_content_type():
    settings = _fake_settings()
    with patch("boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        await upload_image(b"IMAGE", restaurant_id=2, settings=settings)

    call_kwargs = mock_s3.put_object.call_args.kwargs
    assert call_kwargs["ContentType"] == "image/jpeg"
    assert call_kwargs["Bucket"] == "camion-images"
    assert call_kwargs["Body"] == b"IMAGE"


@pytest.mark.asyncio
async def test_upload_key_includes_restaurant_id():
    settings = _fake_settings()
    with patch("boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        await upload_image(b"IMAGE", restaurant_id=7, settings=settings)

    key = mock_s3.put_object.call_args.kwargs["Key"]
    assert key.startswith("7/")
    assert key.endswith(".jpg")


@pytest.mark.asyncio
async def test_upload_uses_r2_endpoint():
    settings = _fake_settings(r2_account_id="myaccount")
    with patch("boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        await upload_image(b"IMAGE", restaurant_id=2, settings=settings)

    call_kwargs = mock_boto.call_args.kwargs
    assert "myaccount.r2.cloudflarestorage.com" in call_kwargs["endpoint_url"]


@pytest.mark.asyncio
async def test_upload_unique_keys_for_same_restaurant():
    settings = _fake_settings()
    keys = []
    with patch("boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        await upload_image(b"A", restaurant_id=2, settings=settings)
        keys.append(mock_s3.put_object.call_args.kwargs["Key"])
        await upload_image(b"B", restaurant_id=2, settings=settings)
        keys.append(mock_s3.put_object.call_args.kwargs["Key"])

    assert keys[0] != keys[1]

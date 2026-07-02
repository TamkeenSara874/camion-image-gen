import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _test_env():
    defaults = {
        "OPENAI_API_KEY": "sk-test",
        "API_BEARER_TOKEN": "test-bearer-token",
        "R2_ACCOUNT_ID": "test-account",
        "R2_ACCESS_KEY_ID": "test-key",
        "R2_SECRET_ACCESS_KEY": "test-secret",
        "R2_BUCKET_NAME": "test-bucket",
        "R2_PUBLIC_URL": "https://test.r2.dev",
    }
    for k, v in defaults.items():
        os.environ.setdefault(k, v)


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

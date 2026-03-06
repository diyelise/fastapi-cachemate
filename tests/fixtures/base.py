from typing import Any
from unittest.mock import AsyncMock

import pytest
import redis

from fastapi_cachemate import OrjsonCoderManager, ZlibCompressManager
from fastapi_cachemate.core.backends.redis import RedisBackend


@pytest.fixture
def mock_redis_client():
    client = AsyncMock(spec=redis.asyncio.Redis)
    client.pipeline.return_value.__aenter__ = AsyncMock()
    client.pipeline.return_value.__aexit__ = AsyncMock(return_value=None)
    return client

@pytest.fixture
def redis_backend(mock_redis_client):
    def factory(pipeline: AsyncMock | None = None):
        if pipeline:
            mock_redis_client.pipeline.return_value.__aenter__.return_value = pipeline
        return RedisBackend(mock_redis_client)
    return factory

@pytest.fixture
def fake_compress_data_zlib():
    def factory(data: bytes | None = None) -> bytes:
        _data = b"test" if data is None else data
        return ZlibCompressManager().compress(_data)
    return factory

@pytest.fixture
def fake_data_encode_orjson():
    def factory(data: Any | None = None) -> Any:
        _data = b"test" if data is None else data
        return OrjsonCoderManager().encode(_data)
    return factory


@pytest.fixture
def fake_data(
    fake_compress_data_zlib,
    fake_data_encode_orjson
):
    def factory(data: dict[str, Any]) -> bytes:
        encode = fake_data_encode_orjson(data)
        compress = fake_compress_data_zlib(encode)
        return compress
    return factory
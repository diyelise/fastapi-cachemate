from unittest.mock import AsyncMock, MagicMock, patch

import orjson
import pytest
import redis

from fastapi_cachemate.core.backends.redis import RedisBackend
from fastapi_cachemate.core.helpers import load_from_cache, save_to_cache
from fastapi_cachemate.core.coders.orjson import OrjsonCoderManager
from fastapi_cachemate.core.compress.zlib import ZlibCompressManager


@pytest.mark.asyncio
async def test_load_from_cache(
    mock_redis_client,
    fake_data,
):
    mock_data = fake_data({"key": "value"})
    mock_pipeline = AsyncMock()
    mock_pipeline.execute.return_value = [mock_data, 5000]
    mock_redis_client.pipeline.return_value.__aenter__.return_value = mock_pipeline

    backend = RedisBackend(mock_redis_client)
    compress = ZlibCompressManager()
    coder = OrjsonCoderManager()

    result = await load_from_cache(
        backend, "test_key", compress, coder
    )
    assert result == (5000, {"key": "value"})


@pytest.mark.asyncio
async def test_load_from_cache_empty_data(
    mock_redis_client,
):
    mock_pipeline = AsyncMock()
    mock_pipeline.execute.return_value = [None, -1]
    mock_redis_client.pipeline.return_value.__aenter__.return_value = mock_pipeline

    backend = RedisBackend(mock_redis_client)
    compress = MagicMock()
    coder = MagicMock()

    result = await load_from_cache(
        backend, "test_key", compress, coder
    )
    assert result is None


@pytest.mark.asyncio
async def test_load_from_cache_backend_error(
    mock_redis_client,
):
    # mocking transport with side effect
    mock_pipeline = AsyncMock()
    mock_pipeline.execute.side_effect = redis.exceptions.ConnectionError("Connection failed")
    mock_redis_client.pipeline.return_value.__aenter__.return_value = mock_pipeline

    backend = RedisBackend(mock_redis_client)
    mock_compress_manager = MagicMock()
    mock_coder_manager = MagicMock()

    result = await load_from_cache(
        backend, "test_key", mock_compress_manager, mock_coder_manager
    )
    assert result is None


@pytest.mark.asyncio
async def test_load_from_cache_decompress_error():
    mock_backend = AsyncMock()
    mock_backend.get.return_value = (5000, b"\x01some_data")
    coder = OrjsonCoderManager()
    compress = ZlibCompressManager()

    with patch("fastapi_cachemate.core.compress.zlib.zlib.decompress", side_effect=Exception("Some decompression error")):
        result = await load_from_cache(
            mock_backend, "test_key", compress, coder
        )
        assert result is None


@pytest.mark.asyncio
async def test_load_from_cache_decode_error(
    fake_data,
):
    mock_backend = AsyncMock()
    mock_backend.get.return_value = (5000, fake_data({"key": "value"}))
    compress = ZlibCompressManager()
    coder = OrjsonCoderManager()

    with patch("fastapi_cachemate.core.coders.orjson.orjson.loads", side_effect=Exception("Some decode error")):
        result = await load_from_cache(
            mock_backend, "test_key", compress, coder
        )
        assert result is None



@pytest.mark.asyncio
async def test_save_to_cache(
    fake_data,
    mock_redis_client,
):
    test_data = {"key": "value"}

    mock_redis_client.set = AsyncMock(return_value=True)

    backend = RedisBackend(mock_redis_client)
    compress = ZlibCompressManager()
    coder = OrjsonCoderManager()

    result = await save_to_cache(
        backend=backend,
        cache_key="test_key",
        ttl=3600,
        data=test_data,
        coder_manager=coder,
        compress_manager=compress
    )
    assert result is True


@pytest.mark.asyncio
async def test_save_to_cache_backend_error(
    mock_redis_client,
):
    mock_redis_client.set.side_effect = redis.exceptions.ConnectionError("Connection failed")
    test_data = {"key": "value"}
    backend = RedisBackend(mock_redis_client)
    coder = MagicMock()
    compress = MagicMock()

    result = await save_to_cache(
        backend=backend,
        cache_key="test_key",
        ttl=3600,
        data=test_data,
        coder_manager=coder,
        compress_manager=compress
    )
    assert result is None


@pytest.mark.asyncio
async def test_save_to_cache_encode_error(
):
    test_data = {"key": "value"}
    backend = AsyncMock()
    compress = MagicMock()
    coder = OrjsonCoderManager()

    with patch('orjson.dumps', side_effect=orjson.JSONEncodeError("Invalid data")):
        result = await save_to_cache(
            backend=backend,
            cache_key="test_key",
            ttl=3600,
            data=test_data,
            coder_manager=coder,
            compress_manager=compress
        )
        assert result is None


@pytest.mark.asyncio
async def test_save_to_cache_compress_error():
    test_data = {"key": "value"}
    backend = AsyncMock()
    compress = ZlibCompressManager()
    coder = MagicMock()

    with patch("fastapi_cachemate.core.compress.zlib.zlib_compress", side_effect=Exception("Some error while data compression")):
        result = await save_to_cache(
            backend=backend,
            cache_key="test_key",
            ttl=3600,
            data=test_data,
            coder_manager=coder,
            compress_manager=compress
        )
        assert result is None


@pytest.mark.asyncio
async def test_save_to_cache_disabled_mode_stores_uncompressed():
    backend = AsyncMock()
    backend.set = AsyncMock(return_value=True)
    data = {"key": "value"}
    coder = OrjsonCoderManager()
    compress = MagicMock()

    result = await save_to_cache(
        backend=backend,
        cache_key="test_key",
        ttl=60,
        data=data,
        coder_manager=coder,
        compress_manager=compress,
        compression_mode="disabled",
    )

    assert result is True
    compress.compress.assert_not_called()
    stored = backend.set.await_args.args[1]
    assert stored.startswith(b"\x00")
    assert coder.decode(stored[1:]) == data


@pytest.mark.asyncio
async def test_load_from_cache_uncompressed_marker_without_decompress():
    backend = AsyncMock()
    coder = OrjsonCoderManager()
    compress = MagicMock()
    payload = {"key": "value"}
    encoded = coder.encode(payload)
    backend.get.return_value = (5000, b"\x00" + encoded)

    result = await load_from_cache(
        backend=backend,
        cache_key="test_key",
        compress_manager=compress,
        coder_manager=coder,
    )

    assert result == (5000, payload)
    compress.decompress.assert_not_called()

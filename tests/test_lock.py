from unittest.mock import AsyncMock

import pytest
import redis

from fastapi_cachemate.core.backends.redis import RedisBackend
from fastapi_cachemate.core.locks.redis import RedisLockManager


@pytest.fixture
def mock_redis_backend(
    mock_redis_client,
):
    return RedisBackend(mock_redis_client)

@pytest.fixture
def lock_manager(mock_redis_backend):
    return RedisLockManager(mock_redis_backend)


@pytest.mark.asyncio
async def test_lock_acquire(lock_manager, mock_redis_client):
    mock_redis_client.set = AsyncMock(return_value=True)
    result = await lock_manager.acquire("lock:test")
    assert result is True


@pytest.mark.asyncio
async def test_lock_already_occupied(lock_manager, mock_redis_client):
    mock_redis_client.set = AsyncMock(return_value=False)
    result = await lock_manager.acquire("lock:test")
    assert result is False


@pytest.mark.asyncio
async def test_lock_acquire_failure(lock_manager, mock_redis_client):
    mock_redis_client.set.side_effect = redis.exceptions.ConnectionError("Connection error")
    result = await lock_manager.acquire("lock:test")
    assert result is False


@pytest.mark.asyncio
async def test_lock_acquire_sets_ttl_and_nx(mock_redis_backend, mock_redis_client):
    manager = RedisLockManager(mock_redis_backend, lock_ttl=5)
    mock_redis_client.set = AsyncMock(return_value=True)

    result = await manager.acquire("lock:test")

    assert result is True
    mock_redis_client.set.assert_awaited_once_with("lock:test", manager._lock_token, ex=5, nx=True)


@pytest.mark.asyncio
async def test_lock_release_success(lock_manager, mock_redis_client):
    mock_redis_client.eval = AsyncMock(return_value=1)

    result = await lock_manager.release("lock:test")

    assert result is True
    mock_redis_client.eval.assert_awaited_once_with(
        lock_manager.UNLOCK_SCRIPT, 1, "lock:test", lock_manager._lock_token
    )


@pytest.mark.asyncio
async def test_lock_release_noop(lock_manager, mock_redis_client):
    mock_redis_client.eval = AsyncMock(return_value=0)

    result = await lock_manager.release("lock:test")

    assert result is False


@pytest.mark.asyncio
async def test_lock_release_failure(lock_manager, mock_redis_client):
    mock_redis_client.eval.side_effect = redis.exceptions.ConnectionError("Connection error")

    result = await lock_manager.release("lock:test")

    assert result is False


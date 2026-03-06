import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

import fastapi_cachemate.cache as cache_module
from fastapi_cachemate import CacheSetup


@pytest.mark.asyncio
async def test_cache_hit_sets_headers_and_skips_save(client, monkeypatch):
    load_from_cache = AsyncMock(
        return_value=(
            5000,
            {"content": {"message": "Hello World from cache"}, "meta": {"compute_ms": 5}},
        )
    )
    save_to_cache = AsyncMock()

    monkeypatch.setattr(cache_module, "load_from_cache", load_from_cache)
    monkeypatch.setattr(cache_module, "save_to_cache", save_to_cache)
    monkeypatch.setattr(cache_module, "should_early_update", lambda *a, **kw: False)

    resp = await client.get("/test")

    assert resp.status_code == 200
    assert resp.headers["X-Cache-Status"] == "HIT"
    assert resp.headers["Cache-Control"] == "max-age=60"
    assert resp.json() == {"message": "Hello World from cache"}

    load_from_cache.assert_awaited_once_with(
        CacheSetup.backend(),
        load_from_cache.await_args.args[1],
        CacheSetup.compress_manager(),
        CacheSetup.coder_manager(),
    )
    save_to_cache.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_miss_saves_payload(client, monkeypatch):
    load_from_cache = AsyncMock(return_value=None)
    save_to_cache = AsyncMock()

    monkeypatch.setattr(cache_module, "load_from_cache", load_from_cache)
    monkeypatch.setattr(cache_module, "save_to_cache", save_to_cache)

    response = await client.get("/test")

    assert response.status_code == 200
    assert response.headers["X-Cache-Status"] == "MISS"
    assert response.json()["message"] == "Hello World"

    assert save_to_cache.await_count == 1
    args, kwargs = save_to_cache.call_args
    assert args[2] == 60
    payload = args[3]
    assert payload["content"] == {"message": "Hello World"}
    assert isinstance(payload["meta"]["compute_ms"], int)
    assert payload["meta"]["compute_ms"] >= 0
    assert kwargs["compression_mode"] == CacheSetup.settings().compression_mode
    assert kwargs["compression_min_size_bytes"] == CacheSetup.settings().compression_min_size_bytes


@pytest.mark.asyncio
async def test_cache_header_bypass_skips_cache(client, monkeypatch):
    load_from_cache = AsyncMock(return_value=None)
    save_to_cache = AsyncMock()

    monkeypatch.setattr(cache_module, "load_from_cache", load_from_cache)
    monkeypatch.setattr(cache_module, "save_to_cache", save_to_cache)

    response = await client.get("/test", headers={"X-BYPASS-HEADER": "test"})

    assert response.status_code == 200
    assert response.headers["X-Cache-Status"] == "BYPASS"
    assert response.json()["message"] == "Hello World"
    load_from_cache.assert_not_awaited()
    save_to_cache.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_control_no_cache_skips_cache(client, monkeypatch):
    load_from_cache = AsyncMock(return_value=None)
    save_to_cache = AsyncMock()

    monkeypatch.setattr(cache_module, "load_from_cache", load_from_cache)
    monkeypatch.setattr(cache_module, "save_to_cache", save_to_cache)

    response = await client.get("/test", headers={"Cache-Control": "no-cache"})

    assert response.status_code == 200
    assert response.headers["X-Cache-Status"] == "NO_CACHE"
    assert response.json()["message"] == "Hello World"
    load_from_cache.assert_not_awaited()
    save_to_cache.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_context_bypass_skips_cache(client, monkeypatch):
    load_from_cache = AsyncMock(return_value=None)
    save_to_cache = AsyncMock()

    monkeypatch.setattr(cache_module, "load_from_cache", load_from_cache)
    monkeypatch.setattr(cache_module, "save_to_cache", save_to_cache)

    token = cache_module.is_bypass.set(True)
    try:
        response = await client.get("/test")
    finally:
        cache_module.is_bypass.reset(token)

    assert response.status_code == 200
    assert response.headers["X-Cache-Status"] == "BYPASS"
    assert response.json()["message"] == "Hello World"
    load_from_cache.assert_not_awaited()
    save_to_cache.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_hit_early_update_triggers_background_save(client, monkeypatch):
    load_from_cache = AsyncMock(
        return_value=(
            5000,
            {"content": {"message": "Hello World from cache"}, "meta": {"compute_ms": 5}},
        )
    )
    save_to_cache = AsyncMock()
    lock_manager = CacheSetup.lock_manager()
    lock_manager.acquire = AsyncMock(return_value=True)

    monkeypatch.setattr(cache_module, "load_from_cache", load_from_cache)
    monkeypatch.setattr(cache_module, "save_to_cache", save_to_cache)
    monkeypatch.setattr(cache_module, "should_early_update", lambda *a, **kw: True)

    resp = await client.get("/test")
    await asyncio.sleep(0)

    assert resp.status_code == 200
    assert resp.headers["X-Cache-Status"] == "HIT"
    assert resp.json() == {"message": "Hello World from cache"}
    assert lock_manager.acquire.await_count == 1
    assert save_to_cache.await_count == 1


@pytest.mark.asyncio
async def test_cache_hashes_query_params(client, monkeypatch):
    short_hash_spy = Mock(wraps=cache_module.short_hash)

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(cache_module, "short_hash", short_hash_spy)
    monkeypatch.setattr(cache_module.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(cache_module, "load_from_cache", AsyncMock(return_value=None))
    monkeypatch.setattr(cache_module, "save_to_cache", AsyncMock())

    resp = await client.get("/test?unused=1")

    assert resp.status_code == 200
    short_hash_spy.assert_called_once_with("", 12)

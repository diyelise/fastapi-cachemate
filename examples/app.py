import asyncio
import random
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import redis
import uvicorn
from fastapi import Depends, FastAPI, Query
from pydantic_settings import SettingsConfigDict

from examples.layouts import BlogDataClassFilter, BlogFilter, BlogIdPath, BlogPydanticFilter
from fastapi_cachemate import BaseCacheSettings, CacheSetup
from fastapi_cachemate.cache import cache_response
from fastapi_cachemate.core.backends.redis import RedisBackend
from fastapi_cachemate.core.locks.redis import RedisLockManager


class ApiCacheSettings(BaseCacheSettings):
    host: str = "127.0.0.1"
    port: int = 6379
    db: int = 0
    ttl_lock_seconds: int = 5
    buffer: float = 0.2

    model_config = SettingsConfigDict(env_prefix="api_cache_")


api_cache_settings = ApiCacheSettings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    _backend = redis.asyncio.Redis(
        host=api_cache_settings.host,
        port=api_cache_settings.port,
        db=api_cache_settings.db,
    )
    redis_backend = RedisBackend(client=_backend)
    try:
        CacheSetup.setup(
            backend=redis_backend,
            lock_manager=RedisLockManager(backend=redis_backend),
            settings=api_cache_settings,
        )
        yield
    finally:
        await CacheSetup.close()
        await redis_backend.close()
        await _backend.connection_pool.disconnect()


app = FastAPI(lifespan=lifespan)


@app.get("/blogs")
@cache_response(ttl=60)
async def get_blogs(
    filter_: Annotated[BlogPydanticFilter, Query()],
) -> dict[str, Any]:
    await asyncio.sleep(random.randint(1, 3))
    return {
        "items": [{"slug": filter_.slug, "blog_id": filter_.blog_id}],
        "page": filter_.page,
        "max_page": filter_.max_page,
    }


@app.get("/blogs/{blog_id}")
@cache_response(ttl=300)
async def get_blog_by_id(
    blog_id: BlogIdPath,
) -> dict[str, BlogIdPath]:
    return {"blog_id": blog_id}


@app.get("/example3")
@cache_response(ttl=300)
async def get_example3(
    filter_: Annotated[BlogDataClassFilter, Depends()],
) -> dict[str, Any]:
    return {"blog_id": filter_.blog_id, "slug": filter_.slug}


@app.get("/example4")
@cache_response(ttl=300)
async def get_example4(
    filter_: Annotated[BlogFilter, Depends()],
) -> dict[str, Any]:
    return {"blog_id": filter_.id, "slug": filter_.slug}


if __name__ == "__main__":
    uvicorn.run("examples.app:app", reload=True)

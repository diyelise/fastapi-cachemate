# fastapi-cachemate

[![CI](https://github.com/diyelise/fastapi-cachemate/actions/workflows/ci.yml/badge.svg)](https://github.com/diyelise/fastapi-cachemate/actions/workflows/ci.yml)
[![codecov](https://codecov.io/github/diyelise/fastapi-cachemate/branch/master/graph/badge.svg)](https://codecov.io/github/diyelise/fastapi-cachemate)
![Python](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12%20|%203.13-blue)

Simple and lightweight library for caching responses with minimal external dependencies.

Inspired by [fastapi-cache](https://github.com/long2ice/fastapi-cache).

## Features

- Fully async
- Easy integration with FastAPI
- Fast serialization and deserialization
- Smart compression and decompression for storage
- Cache stampede mitigation
- Bypass mode for skipping cache
- Flexible filters for Pydantic, dataclasses, and custom classes

## Requirements

- FastAPI
- redis-py

## Install

> pip install fastapi-cachemate

OR

> poetry add fastapi-cachemate

## Quick Start

fastapi-cachemate requires a small setup. The minimal example below prepares the cache layer.

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis
from fastapi import FastAPI
from pydantic_settings import SettingsConfigDict

from fastapi_cachemate import BaseCacheSettings, CacheSetup
from fastapi_cachemate.core.backends.redis import RedisBackend
from fastapi_cachemate.core.locks.redis import RedisLockManager


class ApiCacheSettings(BaseCacheSettings):
  host: str = "127.0.0.1"
  port: int = 6379
  db: int = 0
  ttl_lock_seconds: int = 5
  buffer: float = 0.2

  # See BaseCacheSettings for more options.
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
```

Now create an endpoint and cache it for 300 seconds:

```python
from fastapi_cachemate.cache import cache_response


@app.get("/blogs/{blog_id}")
@cache_response(ttl=300)
async def get_blog_by_id(blog_id: BlogId) -> dict[str, BlogId]:
  return {"blog_id": blog_id}
```

After a second request you should see headers like:

```text
cache-control: max-age=300
content-length: 14
content-type: application/json
date: Thu, 26 Feb 2026 15:35:19 GMT
server: uvicorn
x-cache-status: HIT
```

`X-Cache-Status` can be one of `HIT`, `MISS`, `BYPASS`, or `NO_CACHE`.

## Filter support and nested Depends

You can use filter objects based on Pydantic or dataclasses, or your own classes. Example with
nested `Depends`:

```python
from typing import Any

from fastapi import Depends
from pydantic import BaseModel, ConfigDict, Field


class PaginationParams(BaseModel):
    page: int = 1
    max_page: int = 10


class BlogPydanticFilter(BaseModel):
    blog_id: str | None = Field(None, description="blog id", alias="id")
    slug: str | None = Field(None, description="blog slug")
    pagination: PaginationParams = Depends(PaginationParams)

    model_config = ConfigDict(populate_by_name=True)


@app.get("/blogs")
@cache_response(ttl=300)
async def get_blogs(
    filter_: BlogPydanticFilter = Depends(BlogPydanticFilter),
) -> dict[str, Any]:
    ...
```

The nested `Depends` is unpacked when building the cache key. The key will include:

- blog_id
- slug
- page
- max_page

More filter examples are in [examples/app_with_cache.py](examples/app.py).

## Smart storage

fastapi-cachemate tries to be memory friendly and applies compression for large objects.
It supports three compression modes:

- all: compress every value
- smart: compress based on an internal heuristic (default)
- disabled: disable compression for all values

Large values (for example, over 50 KB) can increase CPU usage and may require monitoring.

## Cache stampede mitigation

When a popular key is close to expiring, many clients can trigger recomputation at once.
fastapi-cachemate mitigates this with an early refresh window: while a key is still valid, it checks
whether the key is within a refresh threshold based on the last compute time and buffer.
If so, a single request acquires a lock and refreshes the cache in the background while
other requests keep using the cached value.

## Bypass mode

There is no explicit cache invalidation yet, but you can skip cache in two ways:

- Client controlled: send `Cache-Control: no-cache` or `no-store`. Cache is skipped and
  `X-Cache-Status` is `NO_CACHE`.
- Server controlled: send the configured bypass header. Cache is skipped and
  `X-Cache-Status` is `BYPASS`.

For example, define your values in the settings or through the work environment.
```python
class ApiCacheSettings(BaseCacheSettings):
  host: str = "127.0.0.1"
  port: int = 6379
  db: int = 0
  ttl_lock_seconds: int = 5
  buffer: float = 0.2
  bypass_header: str = "X-CACHE-BYPASS"
  bypass_value: str = "test"
  ...
```

If you need per-request control inside the app, use the context flag:

```python
from collections.abc import AsyncGenerator

from fastapi import Depends

from fastapi_cachemate.cache import is_bypass


async def bypass_authorized_request(
        user: User | None = Depends(maybe_get_user),
) -> AsyncGenerator[None, None]:
  """
  Tell the cache layer to skip cached responses for authorized users.
  """
  if user:
    token = is_bypass.set(True)
    try:
      yield
    finally:
      is_bypass.reset(token)
  else:
    yield


@app.get(
  "/blogs/{blog_id}",
  summary="Get blog by id",
  dependencies=[Depends(bypass_authorized_request)],
)
@cache_response(ttl=300)
async def get_blog_by_id():
  ...
```

## Tests and coverage

Use a Makefile to run tests and coverage generate reports

## License

This project is licensed under the Apache-2.0 License.

from typing import Any

import redis

from fastapi_cachemate.core.decorators.errors import backend_error_handler, class_error_wrapper
from fastapi_cachemate.core.types import Backend


@class_error_wrapper(backend_error_handler)
class RedisBackend(Backend):
    def __init__(
        self,
        client: redis.asyncio.Redis,
    ):
        self._client = client

    async def get(self, key: str) -> tuple[int, bytes | None]:
        async with self._client.pipeline() as pipe:
            await pipe.get(key)
            await pipe.pttl(key)
            raw, ttl = await pipe.execute()
        return ttl, raw

    async def set(self, key: str, data: bytes | str, *, ttl: int, nx: bool = False) -> Any:
        return await self._client.set(key, data, ex=ttl, nx=nx)

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def client(self) -> Any:
        return self._client

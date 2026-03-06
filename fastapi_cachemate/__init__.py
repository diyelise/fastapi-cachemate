from typing import ClassVar

__all__ = ("CacheSetup", "BaseCacheSettings", "MAX_LOCK_TTL_SECONDS")

from pydantic import Field
from pydantic_settings import BaseSettings

from fastapi_cachemate.core.coders.orjson import OrjsonCoderManager
from fastapi_cachemate.core.compress.zlib import ZlibCompressManager
from fastapi_cachemate.core.types import Backend, ByPass, CoderManager, CompressionMode, CompressManager, LockManager

MAX_LOCK_TTL_SECONDS: int = 5
DEFAULT_BYPASS_HEADER: str = "X-BYPASS-CACHE"


class BaseCacheSettings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 6379
    db: int = 0
    ttl_lock_seconds: int = Field(default=MAX_LOCK_TTL_SECONDS)
    bypass_header: str = Field(default=DEFAULT_BYPASS_HEADER)
    bypass_value: str | None = Field(default=None)
    max_planing_execution_time: int = Field(default=MAX_LOCK_TTL_SECONDS * 1000)  # seconds
    buffer: float = Field(default=0.2)
    compression_mode: CompressionMode = Field(default="smart")
    compression_min_size_bytes: int = Field(default=1024, ge=0)


class CacheSetup:
    _backend: ClassVar[Backend]
    _prefix: ClassVar[str]
    _bypass: ClassVar[ByPass]
    _ttl_lock: ClassVar[int | None]
    _lock_manager: ClassVar[LockManager]
    _coder_manager: ClassVar[CoderManager]
    _compress_manager: ClassVar[CompressManager]
    _settings: ClassVar[BaseCacheSettings]

    @classmethod
    def setup(
        cls,
        backend: Backend,
        lock_manager: LockManager,
        prefix: str = "fastapi_cachemate",
        settings: BaseSettings | None = None,
        coder_manager: CoderManager = OrjsonCoderManager(),
        compress_manager: CompressManager = ZlibCompressManager(),
    ) -> None:
        cls._backend = backend
        cls._prefix = prefix
        cls._coder_manager = coder_manager
        cls._compress_manager = compress_manager
        cls._lock_manager = lock_manager
        cls._settings = cls._init_settings(settings)
        cls._bypass = ByPass(header=cls._settings.bypass_header, value=cls._settings.bypass_value)

    @classmethod
    def _init_settings(cls, settings: BaseSettings | None) -> BaseCacheSettings:
        if settings is None:
            return BaseCacheSettings()
        return BaseCacheSettings(**settings.model_dump())

    @classmethod
    def backend(cls) -> Backend:
        return cls._backend

    @classmethod
    def prefix(cls) -> str:
        return cls._prefix

    @classmethod
    def bypass(cls) -> ByPass:
        return cls._bypass

    @classmethod
    def coder_manager(cls) -> CoderManager:
        return cls._coder_manager

    @classmethod
    def compress_manager(cls) -> CompressManager:
        return cls._compress_manager

    @classmethod
    def lock_manager(cls) -> LockManager:
        return cls._lock_manager

    @classmethod
    def settings(cls) -> BaseCacheSettings:
        return cls._settings

    @classmethod
    async def close(cls) -> None:
        return await cls._backend.close()

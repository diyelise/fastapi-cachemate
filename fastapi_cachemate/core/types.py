from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel

CompressionMode = Literal["all", "smart", "disabled"]


class ByPass(BaseModel):
    value: str | None = None
    header: str = "X-BYPASS-HEADER"


class Backend(ABC):
    @abstractmethod
    async def get(self, key: str) -> tuple[int, bytes | None]:
        raise NotImplementedError

    @abstractmethod
    async def set(self, key: str, data: bytes | str, *, ttl: int, nx: bool = False) -> Any:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError

    @property
    @abstractmethod
    def client(self) -> Any:
        """
        If you need to get low-level backend client functions - implement it!
        """
        raise NotImplementedError


class CoderManager(ABC):
    @abstractmethod
    def encode(self, value: Any) -> bytes:
        raise NotImplementedError()

    @abstractmethod
    def decode(self, data: bytes) -> Any:
        raise NotImplementedError()


class CompressManager(ABC):
    @abstractmethod
    def compress(self, data: bytes) -> bytes:
        raise NotImplementedError()

    @abstractmethod
    def decompress(self, data: bytes) -> bytes:
        raise NotImplementedError()


class LockManager(ABC):
    @abstractmethod
    async def acquire(self, lock_key: str) -> bool:
        raise NotImplementedError()

    @abstractmethod
    async def release(self, lock_key: str) -> bool:
        raise NotImplementedError()

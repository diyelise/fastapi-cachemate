import asyncio
import functools
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from fastapi_cachemate.core.decorators.errors import BackendException, CoderManagerException, CompressManagerException
from fastapi_cachemate.core.types import Backend, CoderManager, CompressionMode, CompressManager

logger = logging.getLogger(__name__)

T = TypeVar("T")
COMPRESSED_MARKER = b"\x01"
UNCOMPRESSED_MARKER = b"\x00"


def _pack_payload(data: bytes, *, compressed: bool) -> bytes:
    marker = COMPRESSED_MARKER if compressed else UNCOMPRESSED_MARKER
    return marker + data


def _unpack_payload(raw: bytes) -> tuple[bool, bytes] | None:
    marker = raw[:1]
    if marker == COMPRESSED_MARKER:
        return True, raw[1:]
    if marker == UNCOMPRESSED_MARKER:
        return False, raw[1:]
    return None


def handle_helper_errors(
    log: logging.Logger,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T | None]]]:
    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T | None]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T | None:
            try:
                return await func(*args, **kwargs)
            except BackendException as e:
                log.error("BackendError", extra={"error": str(e)}, exc_info=True)
                return None
            except CoderManagerException as e:
                log.error("CoderManagerError", extra={"error": str(e)})
                return None
            except CompressManagerException as e:
                log.error("CompressManagerError", extra={"error": str(e)})
                return None
            except Exception as e:
                log.error("UnexpectedError", extra={"error": str(e)})
                return None

        return wrapper

    return decorator


@handle_helper_errors(log=logger)
async def load_from_cache(
    backend: Backend,
    cache_key: str,
    compress_manager: CompressManager,
    coder_manager: CoderManager,
) -> tuple[int, Any] | None:
    remaining_ttl, raw = await backend.get(cache_key)
    if raw is None:
        return None
    unpacked = _unpack_payload(raw)

    if unpacked is None:
        decompressed = await asyncio.to_thread(compress_manager.decompress, raw)
        return remaining_ttl, coder_manager.decode(decompressed)

    is_compressed, payload = unpacked
    if is_compressed:
        payload = await asyncio.to_thread(compress_manager.decompress, payload)
    return remaining_ttl, coder_manager.decode(payload)


@handle_helper_errors(log=logger)
async def save_to_cache(
    backend: Backend,
    cache_key: str,
    ttl: int,
    data: dict[str, Any],
    coder_manager: CoderManager,
    compress_manager: CompressManager,
    compression_mode: CompressionMode = "all",
    compression_min_size_bytes: int = 1024,
) -> Any:
    encoded = coder_manager.encode(data)

    should_compress = False
    if compression_mode == "all":
        should_compress = True
    elif compression_mode == "smart":
        should_compress = len(encoded) >= compression_min_size_bytes
    elif compression_mode == "disabled":
        should_compress = False
    else:
        raise ValueError(f"Unknown compression mode: {compression_mode}")

    payload = encoded
    if should_compress:
        payload = await asyncio.to_thread(compress_manager.compress, encoded)

    to_store = _pack_payload(payload, compressed=should_compress)
    return await backend.set(cache_key, to_store, ttl=ttl)

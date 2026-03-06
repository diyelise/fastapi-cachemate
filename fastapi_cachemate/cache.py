import asyncio
import functools
import inspect
import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from enum import Enum
from inspect import Parameter
from typing import Any, ParamSpec, TypeVar, cast

import fastapi
from starlette.requests import Request
from starlette.responses import Response

from fastapi_cachemate import CacheSetup
from fastapi_cachemate.core.helpers import load_from_cache, save_to_cache
from fastapi_cachemate.core.types import Backend, CoderManager, CompressManager, LockManager
from fastapi_cachemate.core.utils import (
    allowed_cache,
    build_cache_key,
    check_bypass,
    exec_time,
    prepare_query_params,
    rebuild_signature,
    search_and_add_deps,
    short_hash,
    should_early_update,
    signature_func,
)

logger = logging.getLogger(__name__)


P = ParamSpec("P")
R = TypeVar("R")
T = TypeVar("T")

is_bypass: ContextVar[bool] = ContextVar("is_bypass", default=False)


class CacheStatuses(str, Enum):
    CACHE_HIT = "HIT"
    CACHE_MISS = "MISS"
    CACHE_BYPASS = "BYPASS"
    CACHE_NOT = "NO_CACHE"


def _build_cache_payload(result: T, compute_ms: int) -> dict[str, Any]:  # noqa: UP047
    return {"content": result, "meta": {"compute_ms": compute_ms}}


def cache_response(ttl: int = 60) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:  # noqa: C901
    """
    :param ttl: seconds
    """
    request_param_template = inspect.Parameter(
        name="__dependencies_request__",
        kind=inspect.Parameter.KEYWORD_ONLY,
        annotation=fastapi.Request,
    )
    response_param_template = inspect.Parameter(
        name="__dependencies_response__",
        kind=inspect.Parameter.KEYWORD_ONLY,
        annotation=fastapi.Response,
    )

    def _decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:  # noqa: C901
        original_signature: inspect.Signature = inspect.signature(func)
        valid_signature: dict[str, dict[str, Any]] = signature_func(signature=original_signature)
        to_deps: list[Parameter] = []
        request_p: Parameter = search_and_add_deps(
            original_signature,
            request_param_template,
            to_deps,
        )
        response_p: Parameter = search_and_add_deps(
            original_signature,
            response_param_template,
            to_deps,
        )

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:  # noqa: C901
            request: Request = kwargs.pop(request_p.name, None)  # type: ignore
            response: Response = kwargs.pop(response_p.name, None)  # type: ignore
            call_kwargs: dict[str, Any] = dict(kwargs)
            if request_p.name in original_signature.parameters:
                call_kwargs[request_p.name] = request
            if response_p.name in original_signature.parameters:
                call_kwargs[response_p.name] = response

            async def _call_func() -> R:
                return await func(*args, **cast(Any, call_kwargs))

            @exec_time
            async def _run_coroutine() -> R:
                return await _call_func()

            if check_bypass(request) or is_bypass.get():
                response.headers.update({"X-Cache-Status": CacheStatuses.CACHE_BYPASS})
                return await _call_func()

            if not allowed_cache(request):
                response.headers.update({"X-Cache-Status": CacheStatuses.CACHE_NOT})
                return await _call_func()

            query_hash: str | None = None
            if request.query_params:
                query_params = prepare_query_params(valid_signature, request.query_params.multi_items())
                query_hash = await asyncio.to_thread(short_hash, query_params, 12)

            prefix: str = CacheSetup.prefix()
            backend: Backend = CacheSetup.backend()
            coder_manager: CoderManager = CacheSetup.coder_manager()
            compress_manager: CompressManager = CacheSetup.compress_manager()
            cache_settings = CacheSetup.settings()

            cache_key = build_cache_key(
                prefix=prefix,
                method=request.method.lower(),
                url_path=request.url.path.replace("/", ":")[1:],
                query_hash=query_hash,
            )

            result = await load_from_cache(
                backend,
                cache_key,
                compress_manager,
                coder_manager,
            )
            if result is not None:
                remaining_ttl_ms, cache_data = result
                cache_headers = {
                    "X-Cache-Status": CacheStatuses.CACHE_HIT,
                    "Cache-Control": f"max-age={ttl}",
                }
                response.headers.update(cache_headers)

                last_compute_ms = cache_data["meta"]["compute_ms"]

                if should_early_update(
                    last_compute_ms,
                    remaining_ttl_ms,
                    cache_settings.max_planing_execution_time,
                    cache_settings.buffer,
                ):
                    lock_manager: LockManager = CacheSetup.lock_manager()
                    lock_key = f"lock:{cache_key}"
                    lock_acquired = await lock_manager.acquire(lock_key)

                    if lock_acquired:

                        async def _refresh_cache() -> None:
                            try:
                                _compute_ms, _result = await _run_coroutine()
                                data = _build_cache_payload(_result, _compute_ms)
                                await save_to_cache(
                                    backend,
                                    cache_key,
                                    ttl,
                                    data,
                                    coder_manager,
                                    compress_manager,
                                    compression_mode=cache_settings.compression_mode,
                                    compression_min_size_bytes=cache_settings.compression_min_size_bytes,
                                )
                            except Exception as e:
                                logger.error(
                                    "CacheRefreshError",
                                    extra={"cache_key": cache_key, "error": str(e)},
                                    exc_info=True,
                                )
                            finally:
                                await lock_manager.release(lock_key)

                        asyncio.create_task(_refresh_cache())
                result_content: R = cache_data["content"]
                return result_content

            compute_ms, result = await _run_coroutine()
            payload = _build_cache_payload(result, compute_ms)
            await save_to_cache(
                backend,
                cache_key,
                ttl,
                payload,
                coder_manager,
                compress_manager,
                compression_mode=cache_settings.compression_mode,
                compression_min_size_bytes=cache_settings.compression_min_size_bytes,
            )
            response.headers.update({"X-Cache-Status": CacheStatuses.CACHE_MISS})
            return cast(R, result)

        wrapper.__signature__ = rebuild_signature(original_signature, to_deps)  # type: ignore[attr-defined]
        return wrapper

    return _decorator

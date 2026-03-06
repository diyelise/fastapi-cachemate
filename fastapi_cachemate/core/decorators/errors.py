import functools
import inspect
from collections.abc import Callable
from typing import Any, TypeVar, cast

T = TypeVar("T")
R = TypeVar("R")


class _BaseException(Exception):
    pass


class BackendException(_BaseException):
    pass


class CoderManagerException(_BaseException):
    pass


class CompressManagerException(_BaseException):
    pass


def error_handler_proxy_factory(exception_cls: type[Exception]) -> Callable[[Callable[..., T]], Callable[..., T]]:
    def create_wrapper(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                raise exception_cls(f"{exception_cls.__name__} error in {func.__name__}: {e}") from e

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                result = func(*args, **kwargs)
                return cast(T, await result)  # type: ignore[misc]
            except Exception as e:
                raise exception_cls(f"{e.__class__.__module__}.{type(e).__name__} {e}") from e

        if inspect.iscoroutinefunction(func):
            return cast(Callable[..., T], async_wrapper)
        else:
            return sync_wrapper

    return create_wrapper


def class_error_wrapper(
    error_handler: Callable[[Callable[..., Any]], Callable[..., Any]],
) -> Callable[[type[R]], type[R]]:
    def decorator(cls: type[R]) -> type[R]:
        for attr_name, attr_value in vars(cls).items():
            if callable(attr_value) and not attr_name.startswith("__"):
                setattr(cls, attr_name, error_handler(attr_value))
        return cls

    return decorator


backend_error_handler = error_handler_proxy_factory(BackendException)
coder_error_handler = error_handler_proxy_factory(CoderManagerException)
compress_error_handler = error_handler_proxy_factory(CompressManagerException)

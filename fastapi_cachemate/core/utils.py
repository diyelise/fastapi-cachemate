import collections
import dataclasses
import functools
import hashlib
import inspect
import json
import time
import types
from collections.abc import Callable, Mapping
from typing import Annotated, Any, Union, get_args, get_origin
from urllib.parse import urlencode

from fastapi.params import Depends as DependsParam
from fastapi.params import Query as QueryParam
from pydantic import BaseModel
from starlette.datastructures import ImmutableMultiDict, MultiDict, _KeyType
from starlette.requests import Request

from fastapi_cachemate import CacheSetup
from fastapi_cachemate.core.types import ByPass


def _get_fields(_model_type: Any) -> Mapping[str, Any] | Any:
    if issubclass(_model_type, BaseModel):
        return getattr(_model_type, "model_fields", None) or getattr(_model_type, "__fields__", {})
    elif dataclasses.is_dataclass(_model_type):
        return _model_type.__dataclass_fields__
    else:
        if "__init__" not in _model_type.__dict__:
            raise ValueError("Class must implement __init__")
        init_sig = inspect.signature(_model_type.__init__)
        return {p_name: p for p_name, p in init_sig.parameters.items() if p_name != "self"}


def _build_signature_entry(
    annotation: Any | None,
    default: Any | None,
    alias_override: str | None,
) -> dict[str, Any]:
    def _is_multiple_annotation(candidate: Any | None) -> bool:
        if candidate is None:
            return False

        if candidate in (list, tuple, set, collections.abc.Iterable):
            return True

        origin = get_origin(candidate)
        if origin is Annotated:
            args = get_args(candidate)
            return _is_multiple_annotation(args[0]) if args else False

        union_type = getattr(types, "UnionType", None)
        union_origins = {Union}
        if union_type is not None:
            union_origins.add(union_type)

        if origin in union_origins:
            return any(_is_multiple_annotation(arg) for arg in get_args(candidate) if arg is not type(None))

        return origin in (list, tuple, set, collections.abc.Iterable)

    if alias_override is not None:
        alias: str | None = alias_override
    else:
        alias = getattr(default, "alias", None) if default else None

    return {
        "alias": alias,
        "multiple": _is_multiple_annotation(annotation),
    }


def _split_annotated(annotation: Any) -> tuple[Any | None, tuple[Any, ...]]:
    if get_origin(annotation) is not Annotated:
        return None, ()
    model_cls, *meta = get_args(annotation)
    return model_cls, tuple(meta)


def _is_supported_model_cls(model_cls: Any) -> bool:
    if not inspect.isclass(model_cls):
        return False
    if issubclass(model_cls, BaseModel) or dataclasses.is_dataclass(model_cls):
        return True
    return "__init__" in getattr(model_cls, "__dict__", {})


def _query_model_cls(annotation: Any) -> Any | None:
    model_cls, meta = _split_annotated(annotation)
    if not _is_supported_model_cls(model_cls):
        return None
    return model_cls if any(isinstance(item, QueryParam) for item in meta) else None


def short_hash(input_str: str, min_length: int = 8) -> str:
    return hashlib.sha256(input_str.encode("utf-8")).hexdigest()[:min_length]


def get_signature_func(signature: inspect.Signature) -> dict[str, dict[str, Any]]:
    valid: dict[str, dict[str, Any]] = {}

    def _dep_cls(default: Any, annotation: Any) -> Any | None:
        if isinstance(default, DependsParam):
            return default.dependency or annotation
        _, meta = _split_annotated(annotation)
        return next(
            (item.dependency or annotation for item in meta if isinstance(item, DependsParam)),
            None,
        )

    def _inspect(_model_cls: Any) -> None:
        for f_name, f_info in _get_fields(_model_cls).items():
            field_alias = getattr(f_info, "alias", None) or getattr(getattr(f_info, "default", None), "alias", None)
            valid[f_name] = _build_signature_entry(
                getattr(f_info, "annotation", None),
                getattr(f_info, "default", None),
                field_alias,
            )

    for name, param in signature.parameters.items():
        dep = _dep_cls(param.default, param.annotation)
        if dep is not None:
            if inspect.isclass(dep):
                _inspect(dep)
            continue

        query_model = _query_model_cls(param.annotation)
        if query_model is not None:
            _inspect(query_model)
            continue

        param_alias = getattr(param, "alias", None) or getattr(param.default, "alias", None)
        valid[name] = _build_signature_entry(
            param.annotation,
            param.default,
            param_alias,
        )

    return valid


def prepare_query_params(
    signature_params: dict[str, dict[str, Any]],
    query_params: list[tuple[_KeyType, str]],
) -> str:
    params_dict: collections.defaultdict[str, list[str]] = collections.defaultdict(list)

    raw_query = ImmutableMultiDict(MultiDict(query_params))
    for name, attr in signature_params.items():
        alias = attr["alias"] or name
        is_multiple = attr["multiple"]

        if alias in raw_query:
            if is_multiple:
                params_dict[alias].extend(sorted(set(raw_query.getlist(alias))))
            else:
                params_dict[alias].append(raw_query.get(alias))  # type: ignore

    clean_params = {k: v for k, v in params_dict.items() if v}
    return urlencode(clean_params, doseq=True)


def stable_query_params_repr(query_params: dict[str, Any]) -> str:
    normalized = {k: query_params[k] for k in sorted(query_params)}
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def build_cache_key(
    method: str,
    url_path: str,
    query_hash: str | None = None,
    prefix: str | None = None,
) -> str:
    return ":".join([item for item in [prefix, method, url_path, query_hash] if item])


def allowed_cache(request: Request) -> bool:
    if request.method not in ("GET", "HEAD"):
        return False
    if request.headers.get("Cache-Control") in {"no-store", "no-cache"}:
        return False
    return True


def check_bypass(request: Request) -> bool:
    bypass: ByPass = CacheSetup.bypass()
    if bypass.header in request.headers and bypass.value == request.headers[bypass.header]:
        return True
    return False


def exec_time(func: Callable[..., Any]) -> Callable[..., Any]:
    """Return execution time in milliseconds and result"""

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> tuple[int, Any]:
        start = time.perf_counter()
        result = await func(*args, **kwargs)
        end = time.perf_counter()
        execution_time_ms = int((end - start) * 1000)
        return execution_time_ms, result

    return wrapper


def search_and_add_deps(
    signature: inspect.Signature,
    prototype: inspect.Parameter,
    deps: list[inspect.Parameter],
) -> inspect.Parameter:
    for param in signature.parameters.values():
        if param.annotation == prototype.annotation:
            return param
    deps.append(prototype)
    return prototype


def rebuild_signature(sig: inspect.Signature, to_insert: list[inspect.Parameter]) -> inspect.Signature:
    if not to_insert:
        return sig

    new_params: list[inspect.Parameter] = []
    extras = list(to_insert)

    for param in sig.parameters.values():
        if param.kind is inspect.Parameter.VAR_KEYWORD and extras:
            new_params.extend(extras)
            extras.clear()
        new_params.append(param)

    if extras:
        new_params.extend(extras)

    return sig.replace(parameters=new_params)


def should_early_update(
    compute_ms: float,
    remaining_ms: float,
    max_planing_execution_time: int,
    buffer: float,  # percent
) -> bool:
    if remaining_ms <= compute_ms:
        return False

    buffer_ms = compute_ms * buffer
    sliding_window = min(3 * compute_ms, max_planing_execution_time)
    threshold = buffer_ms + sliding_window
    return remaining_ms <= threshold

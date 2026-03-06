import hashlib
import inspect
from dataclasses import dataclass
from unittest.mock import Mock, patch


import pytest

from fastapi import Request, Depends, Query
from pydantic import BaseModel

from fastapi_cachemate import CacheSetup
from fastapi_cachemate.core.types import ByPass
from fastapi_cachemate.core.utils import (
    allowed_cache,
    build_cache_key,
    check_bypass,
    prepare_query_params,
    should_early_update,
    short_hash,
    signature_func,
    stable_query_params_repr,
)
from examples.layouts import BlogId, BlogSlug


class FakeBlogFilter:

    def __init__(
        self,
        blog_id: BlogId | None = Query(None, description="blog id", alias="id"),
        slug: BlogSlug | None = Query(None, description="blog slug"),
    ):
        self.id = blog_id
        self.slug = slug


class FakeBlogPydanticFilter(BaseModel):
    blog_id: BlogId | None = Query(None, description="blog id", alias="id")
    slug: BlogSlug | None = Query(None, description="blog slug")


@dataclass
class FakeDataClassFilter:
    blog_id: BlogId | None = Query(None, description="blog id", alias="id")
    slug: BlogSlug | None = Query(None, description="blog slug")


class PaginationParams(BaseModel):
    page: int = 1
    max_page: int = 10


class FilterWithNestedDepends(BaseModel):
    blog_id: BlogId | None = Query(None, description="blog id", alias="id")
    pagination: PaginationParams = Depends(PaginationParams)


@pytest.fixture
def mock_request():
    request = Mock(spec=Request)
    request.method = "GET"
    request.headers = {}
    return request


@pytest.mark.parametrize("method, result", [
    ("GET", True),
    ("POST", False),
    ("HEAD", True),
    ("PATCH", False),
    ("DELETE", False),
])
def test_get_request_allowed_method(mock_request, method, result):
    mock_request.method = method
    assert allowed_cache(mock_request) is result


@pytest.mark.parametrize("headers, expected_result", [
    ({"X-TEST-BYPASS": "test"}, True), # include bypass mode, cache is disabled
    ({"X-TEST-BYPASS": "qwerty"}, False),
    ({"X-TEST": "qwerty"}, False),
    ({}, False),
])
def test_bypass_mode_enable(mock_request, headers, expected_result):
    test_bypass = ByPass(header="X-TEST-BYPASS", value="test")
    with patch.object(CacheSetup, 'bypass', return_value=test_bypass):
        mock_request.headers.update(headers)
        assert check_bypass(mock_request) is expected_result


@pytest.mark.parametrize("headers, expected_result", [
    ({"Cache-Control": "no-store"}, False),
    ({"Cache-Control": "no-cache"}, False),
    ({"Cache-Control": "max-age=0"}, True),
    ({}, True),
])
def test_allowed_cache(mock_request, headers, expected_result):
    mock_request.headers.update(headers)
    assert allowed_cache(mock_request) is expected_result


@pytest.mark.parametrize("compute_ms, remaining_ms, max_time, buffer, expected", [
    (100, 400, 5000, 0.2, False),
    (100, 250, 5000, 0.2, True),
    (300, 550, 5000, 0.2, True),
    (100, 1000, 5000, 0.2, False),
    (100, 100, 500, 0, False),
])
def test_should_early_update(compute_ms, remaining_ms, max_time, buffer, expected):
    assert should_early_update(compute_ms, remaining_ms, max_time, buffer) == expected


@pytest.mark.parametrize("signature_params, query_params, expected", [
    (
        {"param1": {"alias": None, "multiple": False}, "param2": {"alias": None, "multiple": False}},
        [("param1", "value1"), ("param2", "value2")],
        "param1=value1&param2=value2"
    ),
    (
        {"internal_name": {"alias": "external_name", "multiple": False}},
        [("external_name", "value")],
        "external_name=value"
    ),
    (
        {"param1": {"alias": None, "multiple": False}, "param2": {"alias": None, "multiple": False}},
        [("param1", "value1")],
        "param1=value1"
    ),
    (
        {"param1": {"alias": "alias1", "multiple": False}, "param2": {"alias": None, "multiple": False}},
        [("alias1", "value1"), ("param2", "value2")],
        "alias1=value1&param2=value2"
    ),
    (
        {"param1": {"alias": None, "multiple": False}},
        [("other_param", "value")],
        ""
    ),
    (
        {},
        [("param1", "value1")],
        ""
    ),
    (
        {"param1": {"alias": None, "multiple": False}},
        [],
        ""
    ),
])
def test_prepare_query_params(signature_params, query_params, expected):
    result = prepare_query_params(signature_params, query_params)
    assert result == expected


def test_prepare_query_params_multiple_values():
    signature_params = {"tag_id": {"alias": "tag_id", "multiple": True}}
    query_params = [("tag_id", "1"), ("tag_id", "2"), ("tag_id", "2")]

    result = prepare_query_params(signature_params, query_params)

    assert set(result.split("&")) == {"tag_id=1", "tag_id=2"}


def test_pydantic_filter():
    def _filter_func(
        _: FakeBlogPydanticFilter = Depends(FakeBlogPydanticFilter),
    ):
        pass

    sig = inspect.signature(_filter_func)
    assert signature_func(sig) == {
        "blog_id": {"alias": "id", "multiple": False},
        "slug": {"alias": None, "multiple": False},
    }


def test_dataclass_filter():
    def _filter_func(
        _: FakeDataClassFilter = Depends(FakeDataClassFilter),
    ):
        pass

    sig = inspect.signature(_filter_func)
    assert signature_func(sig) == {
        "blog_id": {"alias": "id", "multiple": False},
        "slug": {"alias": None, "multiple": False},
    }


def test_filter():
    def _filter_func(
        _: FakeBlogFilter = Depends(FakeBlogFilter),
    ):
        pass

    sig = inspect.signature(_filter_func)
    assert signature_func(sig) == {
        "blog_id": {"alias": "id", "multiple": False},
        "slug": {"alias": None, "multiple": False},
    }


def test_raises_for_class_without_init():
    class EmptyFilter:
        pass

    def endpoint_with_empty_dep(_: EmptyFilter = Depends(EmptyFilter)):
        return

    sig = inspect.signature(endpoint_with_empty_dep)
    with pytest.raises(ValueError, match="Class must implement __init__"):
        signature_func(sig)


def test_extract_params_from_filter_nested_dependencies():

    def endpoint(_filter: FilterWithNestedDepends = Depends(FilterWithNestedDepends)):
        return

    sig = inspect.signature(endpoint)
    assert signature_func(sig) == {
        "blog_id": {"alias": "id", "multiple": False},
        "page": {"alias": None, "multiple": False},
        "max_page": {"alias": None, "multiple": False},
    }


def test_signature_func_direct_alias():
    def endpoint(q: str = Query(..., alias="query")):
        return q

    sig = inspect.signature(endpoint)
    assert signature_func(sig) == {"q": {"alias": "query", "multiple": False}}


def test_short_hash_matches_sha256_prefix():
    s = "abc123"
    expected = hashlib.sha256(s.encode("utf-8")).hexdigest()[:8]
    assert short_hash(s) == expected

@pytest.mark.parametrize("length", [4, 8, 12, 32])
def test_short_hash_length(length):
    result = short_hash("some input", min_length=length)
    assert len(result) == length


def test_stable_query_params_repr_order_independent():
    left = {"b": "2", "a": "1"}
    right = {"a": "1", "b": "2"}
    assert stable_query_params_repr(left) == stable_query_params_repr(right)


def test_is_bypass_with_missing_value():
    test_bypass = ByPass(header="X-TEST-BYPASS", value=None)
    request = Mock(spec=Request)
    request.headers = {"X-TEST-BYPASS": "test"}
    with patch.object(CacheSetup, "bypass", return_value=test_bypass):
        assert check_bypass(request) is False


def test_build_cache_key_joins_parts():
    assert build_cache_key(prefix="api", method="get", url_path="test", query_hash="hash") == "api:get:test:hash"


def test_equals_query_hash_any_order_query_params():
    signature_params = {"tags": {"alias": "tags", "multiple": True}}
    param1 = [("tags", "1"), ("tags", "2")]
    param2 = [("tags", "2"), ("tags", "1")]

    assert prepare_query_params(signature_params, param1) == prepare_query_params(signature_params, param2)

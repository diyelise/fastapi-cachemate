from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from httpx import AsyncClient, ASGITransport
from pydantic_settings import BaseSettings

from fastapi_cachemate import CacheSetup
from fastapi_cachemate.cache import cache_response
from fastapi_cachemate.core.types import LockManager
from fastapi_cachemate.core.types import Backend

pytest_plugins = (
    "tests.fixtures.base",
)


@pytest.fixture(scope="session")
def test_app():
    class TestSetupSettings(BaseSettings):
        bypass_header: str = "X-BYPASS-HEADER"
        bypass_value: str = "test"

    @asynccontextmanager
    async def lifespan(a: FastAPI):
        mock_backend = AsyncMock(spec=Backend)
        mock_lock_manager = AsyncMock(spec=LockManager)
        CacheSetup.setup(mock_backend, mock_lock_manager, settings=TestSetupSettings())
        yield

    app = FastAPI(lifespan=lifespan)
    router = APIRouter()

    @router.get("/test")
    @cache_response(ttl=60)
    async def test_endpoint():
        return {"message": "Hello World"}

    app.include_router(router)

    route = next(r for r in app.routes if isinstance(r, APIRoute) and r.path == "/test")
    route.endpoint.__globals__["should_early_update"] = lambda *a, **kw: False
    return app


@pytest_asyncio.fixture(scope="session")
async def client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with LifespanManager(test_app):
        async with AsyncClient(
                transport=ASGITransport(test_app),
                base_url="http://testserver",
                headers={"Content-Type": "application/json"},
        ) as client:
            yield client

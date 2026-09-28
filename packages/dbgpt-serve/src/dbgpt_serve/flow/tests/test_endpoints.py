import pytest
from fastapi import FastAPI, HTTPException
from httpx import AsyncClient

from dbgpt.component import SystemApp
from dbgpt.storage.metadata import db
from dbgpt_serve.core import BaseServeConfig
from dbgpt_serve.core.tests.conftest import (  # noqa: F401
    asystem_app,
    client,
    config,
    system_app,
)

from ..api import endpoints
from ..api.endpoints import init_endpoints, router
from ..config import SERVE_CONFIG_KEY_PREFIX


@pytest.fixture(autouse=True)
def setup_and_teardown():
    db.init_db("sqlite:///:memory:")
    db.create_all()

    yield


def client_init_caller(app: FastAPI, system_app: SystemApp, config: BaseServeConfig):
    app.include_router(router)
    init_endpoints(system_app, config)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client, asystem_app, has_auth",
    [
        (
            {
                "app_caller": client_init_caller,
                "client_api_key": "test_token1",
            },
            {
                "app_config": {
                    f"{SERVE_CONFIG_KEY_PREFIX}api_keys": "test_token1,test_token2"
                }
            },
            True,
        ),
        (
            {
                "app_caller": client_init_caller,
                "client_api_key": "error_token",
            },
            {
                "app_config": {
                    f"{SERVE_CONFIG_KEY_PREFIX}api_keys": "test_token1,test_token2"
                }
            },
            False,
        ),
    ],
    indirect=["client", "asystem_app"],
)
async def test_api_health(client: AsyncClient, asystem_app, has_auth: bool):
    response = await client.get("/test_auth")
    if has_auth:
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
    else:
        assert response.status_code == 401
        assert response.json() == {
            "detail": {
                "error": {
                    "message": "",
                    "type": "invalid_request_error",
                    "param": None,
                    "code": "invalid_api_key",
                }
            }
        }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client", [{"app_caller": client_init_caller}], indirect=["client"]
)
async def test_api_health(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_debug_flow_fails_closed_when_daily_quota_is_enabled(monkeypatch):
    monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "100")
    calls = []

    class _Service:
        def debug_flow(self, *_args, **_kwargs):
            calls.append("debug_flow")

    with pytest.raises(HTTPException) as exc_info:
        await endpoints.debug_flow(object(), service=_Service())

    assert exc_info.value.status_code == 503
    assert calls == []


@pytest.mark.asyncio
async def test_debug_flow_keeps_existing_behavior_when_daily_quota_is_disabled(
    monkeypatch,
):
    monkeypatch.delenv("DBGPT_DAILY_TOKEN_LIMIT", raising=False)
    calls = []

    class _Service:
        def debug_flow(self, request, default_incremental):
            calls.append((request, default_incremental))
            return ["debug-result"]

        async def _wrapper_chat_stream_flow_str(self, stream_iter):
            for item in stream_iter:
                yield item

    request = object()
    response = await endpoints.debug_flow(request, service=_Service())
    chunks = [chunk async for chunk in response.body_iterator]

    assert calls == [(request, False)]
    assert chunks == ["debug-result"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client", [{"app_caller": client_init_caller}], indirect=["client"]
)
async def test_api_create(client: AsyncClient):
    # TODO: add your test case
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client", [{"app_caller": client_init_caller}], indirect=["client"]
)
async def test_api_update(client: AsyncClient):
    # TODO: implement your test case
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client", [{"app_caller": client_init_caller}], indirect=["client"]
)
async def test_api_query(client: AsyncClient):
    # TODO: implement your test case
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client", [{"app_caller": client_init_caller}], indirect=["client"]
)
async def test_api_query_by_page(client: AsyncClient):
    # TODO: implement your test case
    pass


# Add more test cases according to your own logic

import pytest
from fastapi import FastAPI, HTTPException
from httpx import AsyncClient

from dbgpt.component import SystemApp
from dbgpt.storage.metadata import db
from dbgpt.util import PaginationResult
from dbgpt_serve.core import BaseServeConfig
from dbgpt_serve.core.tests.conftest import asystem_app, client, config  # noqa: F401

from ..api import endpoints
from ..api.endpoints import init_endpoints, router
from ..api.schemas import PromptDebugInput, ServerResponse


@pytest.fixture(autouse=True)
def setup_and_teardown():
    db.init_db("sqlite:///:memory:")
    db.create_all()

    yield


def client_init_caller(app: FastAPI, system_app: SystemApp, config: BaseServeConfig):
    app.include_router(router)
    init_endpoints(system_app, config)


async def _create_and_validate(
    client: AsyncClient, sys_code: str, content: str, expect_id: int = 1, **kwargs
):
    req_json = {"sys_code": sys_code, "content": content}
    req_json.update(kwargs)
    response = await client.post("/add", json=req_json)
    assert response.status_code == 200
    json_res = response.json()
    assert "success" in json_res and json_res["success"]
    assert "data" in json_res and json_res["data"]
    data = json_res["data"]
    res_obj = ServerResponse(**data)
    assert res_obj.id == expect_id
    assert res_obj.sys_code == sys_code
    assert res_obj.content == content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client",
    [{"app_caller": client_init_caller, "client_api_key": "mock_api_key_123"}],
    indirect=["client"],
)
async def test_api_create(client: AsyncClient):
    await _create_and_validate(client, "test", "test")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client",
    [{"app_caller": client_init_caller, "client_api_key": "mock_api_key_123"}],
    indirect=["client"],
)
async def test_api_update(client: AsyncClient):
    await _create_and_validate(client, "test", "test")

    response = await client.post("/update", json={"id": 1, "content": "test2"})
    assert response.status_code == 200
    json_res = response.json()
    assert "success" in json_res and json_res["success"]
    assert "data" in json_res and json_res["data"]
    data = json_res["data"]
    res_obj = ServerResponse(**data)
    assert res_obj.id == 1
    assert res_obj.sys_code == "test"
    assert res_obj.content == "test2"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client",
    [{"app_caller": client_init_caller, "client_api_key": "mock_api_key_123"}],
    indirect=["client"],
)
async def test_api_query(client: AsyncClient):
    for i in range(10):
        await _create_and_validate(
            client, "test", f"test{i}", expect_id=i + 1, prompt_name=f"prompt_name_{i}"
        )
    response = await client.post("/list", json={"sys_code": "test"})
    assert response.status_code == 200
    json_res = response.json()
    assert "success" in json_res and json_res["success"]
    assert "data" in json_res and json_res["data"]
    data = json_res["data"]
    assert len(data) == 10
    res_obj = ServerResponse(**data[0])
    assert res_obj.id == 1
    assert res_obj.sys_code == "test"
    assert res_obj.content == "test0"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client",
    [{"app_caller": client_init_caller, "client_api_key": "mock_api_key_123"}],
    indirect=["client"],
)
async def test_api_query_by_page(client: AsyncClient):
    for i in range(10):
        await _create_and_validate(
            client, "test", f"test{i}", expect_id=i + 1, prompt_name=f"prompt_name_{i}"
        )
    response = await client.post(
        "/query_page", params={"page": 1, "page_size": 5}, json={"sys_code": "test"}
    )
    assert response.status_code == 200
    json_res = response.json()
    assert "success" in json_res and json_res["success"]
    assert "data" in json_res and json_res["data"]
    data = json_res["data"]
    page_result: PaginationResult = PaginationResult(**data)
    assert page_result.total_count == 10
    assert page_result.total_pages == 2
    assert page_result.page == 1
    assert page_result.page_size == 5
    assert len(page_result.items) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client",
    [{"app_caller": client_init_caller}],
    indirect=["client"],
)
async def test_api_key_is_required_when_configured(client: AsyncClient):
    response = await client.get("/test_auth")
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client",
    [
        {
            "app_caller": client_init_caller,
            "headers": {"X-API-Key": "wrong-key"},
        }
    ],
    indirect=["client"],
)
async def test_invalid_api_key_is_rejected(client: AsyncClient):
    response = await client.get("/test_auth")
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client",
    [
        {
            "app_caller": client_init_caller,
            "headers": {
                "Authorization": "Bearer oidc-token",
                "X-API-Key": "mock_api_key_123",
            },
        }
    ],
    indirect=["client"],
)
async def test_configured_api_key_can_be_sent_separately_from_bearer(
    client: AsyncClient,
):
    response = await client.get("/test_auth")
    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "setting",
    ["DBGPT_DAILY_TOKEN_LIMIT", "DBGPT_REACT_DAILY_TOKEN_LIMIT"],
)
async def test_prompt_template_debug_fails_closed_when_quota_is_enabled(
    monkeypatch, setting
):
    monkeypatch.setenv(setting, "100")
    calls = []

    class _Service:
        async def debug_prompt(self, **kwargs):
            calls.append(kwargs)
            yield "model output"

    def _require_verified_identity(*_args):
        raise HTTPException(status_code=403, detail="Verified OIDC identity required")

    monkeypatch.setattr(
        endpoints, "resolve_daily_token_quota_context", _require_verified_identity
    )
    with pytest.raises(HTTPException) as exc_info:
        await endpoints.template_debug(PromptDebugInput(user_input="hello"), _Service())

    assert exc_info.value.status_code == 403
    assert calls == []


@pytest.mark.asyncio
async def test_prompt_template_debug_keeps_existing_behavior_when_quota_disabled(
    monkeypatch,
):
    monkeypatch.delenv("DBGPT_DAILY_TOKEN_LIMIT", raising=False)
    monkeypatch.delenv("DBGPT_REACT_DAILY_TOKEN_LIMIT", raising=False)
    calls = []

    class _Service:
        async def debug_prompt(self, **kwargs):
            calls.append(kwargs)
            yield "model output"

    debug_input = PromptDebugInput(user_input="hello")
    response = await endpoints.template_debug(debug_input, _Service())
    chunks = [chunk async for chunk in response.body_iterator]

    assert calls == [{"debug_input": debug_input, "token_quota_context": None}]
    assert chunks == ["model output"]


@pytest.mark.asyncio
async def test_prompt_template_debug_passes_verified_quota_context(monkeypatch):
    monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "100")
    quota_context = {"tenant_id": "tenant-a", "user_id": "user-a"}
    monkeypatch.setattr(
        endpoints,
        "resolve_daily_token_quota_context",
        lambda *_args: quota_context,
    )
    calls = []

    class _Service:
        async def debug_prompt(self, **kwargs):
            calls.append(kwargs)
            yield "model output"

    debug_input = PromptDebugInput(user_input="hello")
    response = await endpoints.template_debug(debug_input, _Service())
    chunks = [chunk async for chunk in response.body_iterator]

    assert calls == [{"debug_input": debug_input, "token_quota_context": quota_context}]
    assert chunks == ["model output"]

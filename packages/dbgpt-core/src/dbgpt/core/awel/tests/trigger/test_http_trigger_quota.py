from typing import Any

import pytest
from fastapi import APIRouter, HTTPException
from fastapi.routing import APIRoute

from dbgpt.core.awel import DAG, MapOperator
from dbgpt.core.awel.trigger import http_trigger
from dbgpt.core.awel.trigger.http_trigger import (
    CommonLLMHttpRequestBody,
    CommonLLMHttpTrigger,
    HttpTrigger,
)


class _AppRouter:
    def __init__(self):
        self.endpoint = None

    def add_api_route(self, path, endpoint, **kwargs):
        self.endpoint = endpoint


class _App:
    def __init__(self):
        self.router = _AppRouter()
        self.openapi_schema = None
        self.middleware_stack = None


def _trigger(chat: bool):
    with DAG(f"http_trigger_quota_{'chat' if chat else 'command'}"):
        if chat:
            trigger = CommonLLMHttpTrigger(endpoint="/quota-test", methods="POST")
        else:
            trigger = HttpTrigger(
                endpoint="/quota-test", methods="POST", request_body=dict
            )
        trigger >> MapOperator(lambda value: value)
    return trigger


def _mount(trigger, mount_kind: str):
    if mount_kind == "router":
        router = APIRouter()
        trigger.mount_to_router(router, "/api/v1/awel/trigger")
        return next(
            route.endpoint for route in router.routes if isinstance(route, APIRoute)
        )
    app = _App()
    trigger.mount_to_app(app, "/api/v1/awel/trigger")
    return app.router.endpoint


@pytest.mark.asyncio
@pytest.mark.parametrize("chat", [False, True], ids=["command", "chat"])
@pytest.mark.parametrize("quota_enabled", [False, True], ids=["quota-off", "quota-on"])
@pytest.mark.parametrize("mount_kind", ["router", "app"])
async def test_http_trigger_quota_guard_applies_to_all_mounts(
    monkeypatch, chat: bool, quota_enabled: bool, mount_kind: str
):
    if quota_enabled:
        monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "100")
    else:
        monkeypatch.delenv("DBGPT_DAILY_TOKEN_LIMIT", raising=False)

    trigger = _trigger(chat)
    endpoint = _mount(trigger, mount_kind)
    dag_calls = []

    async def fake_trigger_dag(*args, **kwargs):
        dag_calls.append((args, kwargs))
        return {"ok": True}

    monkeypatch.setattr(http_trigger, "_trigger_dag", fake_trigger_dag)
    body: Any = (
        CommonLLMHttpRequestBody(model="test", messages="hello")
        if chat
        else {"value": 1}
    )

    if quota_enabled:
        with pytest.raises(HTTPException) as exc_info:
            await endpoint(body=body)
        assert exc_info.value.status_code == 503
        assert dag_calls == []
    else:
        assert await endpoint(body=body) == {"ok": True}
        assert len(dag_calls) == 1

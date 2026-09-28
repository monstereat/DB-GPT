import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from dbgpt_app.openapi import api_v2
from dbgpt_app.openapi.api_v1 import token_quota
from dbgpt_client.schema import ChatCompletionRequestBody
from dbgpt_serve.utils.auth import UserRequest


def test_v2_chat_normal_passes_verified_daily_quota_to_base_chat(monkeypatch):
    monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "120")
    identity = {"source": "verified_oidc_jwt", "actor_id": "analyst"}
    monkeypatch.setattr(api_v2, "check_chat_request", lambda _request: None)
    monkeypatch.setattr(
        api_v2, "trusted_agent_execution_context", lambda _user: identity
    )
    monkeypatch.setattr(
        token_quota,
        "resolve_daily_token_quota_context",
        lambda user, limit, name: {
            "user_id": identity["actor_id"],
            "tenant_id": user.tenant_id,
            "daily_limit_tokens": int(limit),
        },
    )
    captured = {}

    class _Chat:
        async def nostream_call(self):
            return "ok"

    async def get_chat_instance(
        request, system_app, *, user_token, token_quota_context
    ):
        captured.update(
            user_token=user_token,
            token_quota_context=token_quota_context,
            system_app=system_app,
        )
        return _Chat()

    monkeypatch.setattr(api_v2, "get_chat_instance", get_chat_instance)
    user = UserRequest(user_id="analyst", tenant_id="tenant-a", role="normal")
    request = ChatCompletionRequestBody(
        model="demo", messages="hello", chat_mode="chat_normal", stream=False
    )

    result = asyncio.run(
        api_v2.chat_completions(request, SimpleNamespace(system_app=object()), user)
    )

    assert result.choices[0].message.content == "ok"
    assert captured["user_token"] is user
    assert captured["token_quota_context"] == {
        "user_id": "analyst",
        "tenant_id": "tenant-a",
        "daily_limit_tokens": 120,
    }


def test_v2_rejects_modes_without_metered_client_when_quota_is_enabled(monkeypatch):
    monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "120")
    monkeypatch.setattr(api_v2, "check_chat_request", lambda _request: None)
    request = ChatCompletionRequestBody(
        model="demo", messages="hello", chat_mode="chat_awel_flow", stream=False
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            api_v2.chat_completions(
                request,
                SimpleNamespace(system_app=object()),
                UserRequest(user_id="analyst", tenant_id="tenant-a", role="normal"),
            )
        )

    assert exc_info.value.status_code == 503


def test_v2_keeps_service_api_key_separate_from_quota_bearer(monkeypatch):
    monkeypatch.delenv("DBGPT_DAILY_TOKEN_LIMIT", raising=False)
    assert api_v2._v2_quota_user() is None

    service = SimpleNamespace(config=SimpleNamespace(api_keys="service-key"))
    result = asyncio.run(
        api_v2.check_api_key(auth=None, x_api_key="service-key", service=service)
    )
    assert result == "service-key"


def test_v2_chat_app_passes_quota_wrapper_to_agent(monkeypatch):
    captured = {}

    async def app_agent_chat(**kwargs):
        captured.update(kwargs)
        yield 'data:{"vis":"ok"}\n\n'

    monkeypatch.setattr(api_v2.multi_agents, "is_flow_chat", lambda _uid: False)
    monkeypatch.setattr(api_v2.multi_agents, "app_agent_chat", app_agent_chat)
    request = ChatCompletionRequestBody(
        model="demo",
        messages="hello",
        chat_mode="chat_app",
        chat_param="demo-agent",
        conv_uid="conversation-1",
        stream=True,
    )
    quota_context = {
        "user_id": "verified-user",
        "tenant_id": "verified-tenant",
        "daily_limit_tokens": 120,
    }

    async def collect():
        stream = api_v2.chat_app_stream_wrapper(request, quota_context)
        return [chunk async for chunk in stream]

    chunks = asyncio.run(collect())
    assert chunks
    wrapper = captured["llm_client_wrapper"]
    assert wrapper is not None
    metered = wrapper(SimpleNamespace())
    assert isinstance(metered, token_quota.MeteredLLMClient)
    assert metered._tenant_id == "verified-tenant"
    assert metered._user_id == "verified-user"


def test_v2_chat_app_flow_fails_closed_when_quota_is_enabled(monkeypatch):
    monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "120")
    monkeypatch.setattr(api_v2, "check_chat_request", lambda _request: None)
    monkeypatch.setattr(api_v2.multi_agents, "is_flow_chat", lambda _uid: True)
    monkeypatch.setattr(
        token_quota,
        "resolve_daily_token_quota_context",
        lambda *_args: {
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "daily_limit_tokens": 120,
        },
    )
    request = ChatCompletionRequestBody(
        model="demo",
        messages="hello",
        chat_mode="chat_app",
        chat_param="flow-app",
        stream=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            api_v2.chat_completions(
                request,
                SimpleNamespace(system_app=object()),
                UserRequest(user_id="user-a", tenant_id="tenant-a", role="normal"),
            )
        )

    assert exc_info.value.status_code == 503

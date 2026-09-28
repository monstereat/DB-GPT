import asyncio

import pytest
from fastapi import HTTPException

from dbgpt.core.interface.operators.llm_operator import (
    wrap_llm_client_for_current_context,
)
from dbgpt_app.openapi.api_v1 import api_v1, token_quota
from dbgpt_app.openapi.api_view_model import ConversationVo
from dbgpt_app.scene import ChatScene
from dbgpt_serve.agent.agents.controller import multi_agents
from dbgpt_serve.utils.auth import UserRequest


def test_base_chat_modes_share_quota_context(monkeypatch):
    monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "150")
    user = UserRequest(user_id="analyst", tenant_id="tenant-a", role="normal")
    captured = {}

    def resolve(user_token, configured_limit, setting_name):
        captured.update(
            user_token=user_token,
            configured_limit=configured_limit,
            setting_name=setting_name,
        )
        return {"user_id": "analyst", "tenant_id": "tenant-a"}

    monkeypatch.setattr(token_quota, "resolve_daily_token_quota_context", resolve)

    context = api_v1._chat_completion_daily_quota_context(
        user, ChatScene.ChatKnowledge.value(), None
    )

    assert context == {"user_id": "analyst", "tenant_id": "tenant-a"}
    assert captured == {
        "user_token": user,
        "configured_limit": "150",
        "setting_name": "DBGPT_DAILY_TOKEN_LIMIT",
    }


def test_app_agent_mode_receives_quota_context(monkeypatch):
    monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "150")
    user = UserRequest(user_id="analyst", tenant_id="tenant-a", role="normal")
    expected = {
        "user_id": "analyst",
        "tenant_id": "tenant-a",
        "daily_limit_tokens": 150,
    }
    monkeypatch.setattr(
        token_quota, "resolve_daily_token_quota_context", lambda *_args: expected
    )

    assert (
        api_v1._chat_completion_daily_quota_context(
            user, ChatScene.ChatAgent.value(), None
        )
        == expected
    )


def test_v1_app_agent_passes_verified_wrapper_to_agent_client(monkeypatch):
    monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "150")
    quota_context = {
        "tenant_id": "tenant-a",
        "user_id": "verified-user",
        "daily_limit_tokens": 150,
    }
    user = UserRequest(user_id="caller-value", tenant_id="tenant-a", role="normal")
    monkeypatch.setattr(
        token_quota, "resolve_daily_token_quota_context", lambda *_args: quota_context
    )
    monkeypatch.setattr(
        api_v1,
        "trusted_agent_execution_context",
        lambda _user: {
            "source": "verified_oidc_jwt",
            "actor_id": "verified-user",
        },
    )
    monkeypatch.setattr(api_v1, "adapt_native_app_model", lambda dialogue: dialogue)
    monkeypatch.setattr(api_v1.user_recent_app_dao, "upsert", lambda **_kwargs: None)
    monkeypatch.setattr(multi_agents, "is_flow_chat", lambda _app: False)
    captured = {}

    async def app_agent_chat(**kwargs):
        captured.update(kwargs)
        yield "data:ok\n\n"

    monkeypatch.setattr(multi_agents, "app_agent_chat", app_agent_chat)
    dialogue = ConversationVo(
        chat_mode=ChatScene.ChatAgent.value(),
        app_code="agent-app",
        user_input="hello",
        ext_info={"trusted_execution_context": {"actor_id": "spoofed"}},
    )

    response = asyncio.run(api_v1.chat_completions(dialogue, None, user))

    async def collect():
        return [chunk async for chunk in response.body_iterator]

    assert asyncio.run(collect()) == ["data:ok\n\n"]
    assert captured["trusted_execution_context"]["actor_id"] == "verified-user"
    metered = captured["llm_client_wrapper"](object())
    assert isinstance(metered, token_quota.MeteredLLMClient)
    assert metered._user_id == "verified-user"
    assert captured["trusted_execution_context"] == {
        "source": "verified_oidc_jwt",
        "actor_id": "verified-user",
    }


def test_app_agent_request_wrapper_is_available_to_nested_app_clients(monkeypatch):
    raw_client = object()
    wrapped_client = object()
    wrapper_calls = []
    captured = {}

    def wrapper(client):
        wrapper_calls.append(client)
        return wrapped_client

    async def implementation(*_args, **_kwargs):
        captured["nested_client"] = wrap_llm_client_for_current_context(raw_client)
        yield "done"

    monkeypatch.setattr(multi_agents, "_app_agent_chat_impl", implementation)

    async def run():
        return [
            chunk
            async for chunk in multi_agents.app_agent_chat(
                conv_uid="conversation",
                gpts_name="parent-app",
                user_query="hello",
                llm_client_wrapper=wrapper,
            )
        ]

    assert asyncio.run(run()) == ["done"]
    assert captured["nested_client"] is wrapped_client
    assert wrapper_calls == [raw_client]


@pytest.mark.asyncio
async def test_base_chat_quota_context_scopes_nested_retrieval_clients(monkeypatch):
    from types import SimpleNamespace

    from dbgpt_app.openapi.api_v1 import token_quota as quota_module
    from dbgpt_app.scene.base_chat import BaseChat

    raw_client = object()
    wrapped_client = object()
    monkeypatch.setattr(
        quota_module,
        "build_metered_llm_client_wrapper",
        lambda _context: lambda _client: wrapped_client,
    )

    class _Chat:
        _chat_param = SimpleNamespace(token_quota_context={"tenant_id": "tenant-a"})

        async def _stream_call_impl(self, *_args):
            yield wrap_llm_client_for_current_context(raw_client)

    assert [chunk async for chunk in BaseChat.stream_call(_Chat())] == [wrapped_client]


def test_v1_app_agent_flow_returns_http_503_when_quota_is_enabled(monkeypatch):
    monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "150")
    monkeypatch.setattr(
        token_quota,
        "resolve_daily_token_quota_context",
        lambda *_args: {
            "tenant_id": "tenant-a",
            "user_id": "verified-user",
            "daily_limit_tokens": 150,
        },
    )
    monkeypatch.setattr(api_v1, "adapt_native_app_model", lambda dialogue: dialogue)
    monkeypatch.setattr(api_v1.user_recent_app_dao, "upsert", lambda **_kwargs: None)
    monkeypatch.setattr(multi_agents, "is_flow_chat", lambda _app: True)
    dialogue = ConversationVo(
        chat_mode=ChatScene.ChatAgent.value(), app_code="flow-app", user_input="hello"
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            api_v1.chat_completions(
                dialogue,
                None,
                UserRequest(user_id="user-a", tenant_id="tenant-a", role="normal"),
            )
        )

    assert exc_info.value.status_code == 503


@pytest.mark.parametrize(
    "chat_mode,domain_type",
    [
        (ChatScene.ChatFlow.value(), None),
        (ChatScene.ChatKnowledge.value(), "finance"),
    ],
)
def test_unmetered_v1_modes_fail_closed_when_quota_is_enabled(
    monkeypatch, chat_mode, domain_type
):
    monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "150")
    user = UserRequest(user_id="analyst", tenant_id="tenant-a", role="normal")

    with pytest.raises(HTTPException) as exc_info:
        api_v1._chat_completion_daily_quota_context(user, chat_mode, domain_type)

    assert exc_info.value.status_code == 503


def test_quota_disabled_preserves_unmetered_v1_modes(monkeypatch):
    monkeypatch.delenv("DBGPT_DAILY_TOKEN_LIMIT", raising=False)

    assert (
        api_v1._chat_completion_daily_quota_context(
            UserRequest(user_id="analyst"), ChatScene.ChatFlow.value(), None
        )
        is None
    )

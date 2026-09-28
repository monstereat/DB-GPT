import asyncio
import json
from types import SimpleNamespace

import pytest

from dbgpt.agent.util.llm.llm import LLMConfig
from dbgpt.core import ModelOutput, ModelRequest
from dbgpt_app.openapi.api_v1.token_quota import (
    MeteredLLMClient,
    TokenQuotaConfigurationError,
    build_metered_llm_client_wrapper,
    resolve_daily_token_quota_context,
    safe_token_quota_error,
)
from dbgpt_serve.token_quota import TokenQuotaExceededError
from dbgpt_serve.utils import token_quota_client as token_quota_module


class FakeQuotaDao:
    def __init__(self, *, reject=False):
        self.reject = reject
        self.reserved = []
        self.settled = []
        self.heartbeats = []

    def reserve(self, tenant_id, user_id, amount_tokens, daily_limit_tokens):
        if self.reject:
            raise TokenQuotaExceededError("limit reached")
        self.reserved.append((tenant_id, user_id, amount_tokens, daily_limit_tokens))
        return SimpleNamespace(reservation_id="reservation-1")

    def settle(self, reservation_id, actual_tokens):
        self.settled.append((reservation_id, actual_tokens))

    def heartbeat(self, reservation_id):
        self.heartbeats.append(reservation_id)
        return True


class FakeLLMClient:
    def __init__(self, outputs, delay=0):
        self.outputs = outputs
        self.delay = delay
        self.calls = 0
        self.counted_prompts = []

    async def count_token(self, model, prompt):
        self.counted_prompts.append((model, prompt))
        return 10

    async def generate_stream(self, request, message_converter=None):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        for output in self.outputs:
            yield output


def _request():
    return ModelRequest(
        model="test-model",
        messages=[{"role": "user", "content": "hello"}],
        max_new_tokens=5,
    )


def test_daily_quota_context_uses_only_verified_oidc_identity(monkeypatch):
    from dbgpt_serve.utils import auth

    monkeypatch.setattr(
        auth,
        "trusted_agent_execution_context",
        lambda token: {
            "tenant_id": "trusted-tenant",
            "actor_id": "trusted-user",
        },
    )

    assert resolve_daily_token_quota_context(
        object(), "100", "DBGPT_DAILY_TOKEN_LIMIT"
    ) == {
        "tenant_id": "trusted-tenant",
        "user_id": "trusted-user",
        "daily_limit_tokens": 100,
    }
    assert (
        resolve_daily_token_quota_context(object(), None, "DBGPT_DAILY_TOKEN_LIMIT")
        is None
    )


def test_daily_quota_context_rejects_unverified_identity_and_invalid_limit(monkeypatch):
    from fastapi import HTTPException

    from dbgpt_serve.utils import auth

    monkeypatch.setattr(auth, "trusted_agent_execution_context", lambda token: None)
    with pytest.raises(HTTPException) as identity_error:
        resolve_daily_token_quota_context(object(), "100", "DBGPT_DAILY_TOKEN_LIMIT")
    assert identity_error.value.status_code == 403

    with pytest.raises(HTTPException) as config_error:
        resolve_daily_token_quota_context(
            object(), "unlimited", "DBGPT_DAILY_TOKEN_LIMIT"
        )
    assert config_error.value.status_code == 500
    assert (
        config_error.value.detail
        == "DBGPT_DAILY_TOKEN_LIMIT must be a positive integer"
    )


def test_react_context_prefers_shared_setting_and_keeps_legacy_fallback(monkeypatch):
    from dbgpt_app.openapi.api_v1.agentic_data_api import (
        _react_daily_token_quota_context,
    )
    from dbgpt_serve.utils import auth

    monkeypatch.setattr(
        auth,
        "trusted_agent_execution_context",
        lambda token: {"tenant_id": "tenant-a", "actor_id": "user-a"},
    )
    monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "90")
    monkeypatch.setenv("DBGPT_REACT_DAILY_TOKEN_LIMIT", "40")
    assert _react_daily_token_quota_context(object())["daily_limit_tokens"] == 90

    monkeypatch.delenv("DBGPT_DAILY_TOKEN_LIMIT")
    assert _react_daily_token_quota_context(object())["daily_limit_tokens"] == 40


def test_chat_instance_passes_quota_context_into_chat_param(monkeypatch):
    from dbgpt_app.openapi.api_v1 import api_v1
    from dbgpt_app.openapi.api_view_model import ConversationVo
    from dbgpt_serve.utils.auth import UserRequest

    async def capture_chat_param(*args, **kwargs):
        return kwargs["chat_param"]

    monkeypatch.setattr(api_v1, "blocking_func_to_async", capture_chat_param)
    context = {
        "tenant_id": "tenant-a",
        "user_id": "user-a",
        "daily_limit_tokens": 100,
    }
    chat_param = asyncio.run(
        api_v1.get_chat_instance(
            ConversationVo(chat_mode="chat_normal"),
            UserRequest(user_id="user-a", tenant_id="tenant-a"),
            context,
        )
    )
    assert chat_param.token_quota_context == context


def test_quota_errors_have_fixed_public_messages():
    assert safe_token_quota_error(TokenQuotaExceededError("db internals")) == (
        "每日 Token 额度已用尽，请明天再试。"
    )
    assert safe_token_quota_error(TokenQuotaConfigurationError("private detail")) == (
        "当前请求无法安全应用每日 Token 额度，请联系管理员。"
    )
    assert safe_token_quota_error(ValueError("other error")) is None


def test_server_quota_context_builds_app_agent_client_wrapper():
    context = {
        "tenant_id": "verified-tenant",
        "user_id": "verified-user",
        "daily_limit_tokens": 100,
    }
    wrapper = build_metered_llm_client_wrapper(context)
    client = FakeLLMClient([])

    metered = wrapper(client)

    assert isinstance(metered, MeteredLLMClient)
    assert metered._tenant_id == "verified-tenant"
    assert metered._user_id == "verified-user"
    assert metered._daily_limit_tokens == 100
    assert build_metered_llm_client_wrapper(None) is None


def test_metered_client_settles_provider_usage_after_reserving_upper_bound():
    dao = FakeQuotaDao()
    client = FakeLLMClient(
        [ModelOutput(error_code=0, text="ok", usage={"total_tokens": 7})]
    )
    metered = MeteredLLMClient(
        client, tenant_id="tenant-a", user_id="user-a", daily_limit_tokens=100, dao=dao
    )
    assert LLMConfig(llm_client=metered).llm_client is metered

    async def collect():
        return [output async for output in metered.generate_stream(_request())]

    outputs = asyncio.run(collect())

    assert len(outputs) == 1
    # 10 prompt tokens + 5 output tokens + 64 tokenization/framing allowance.
    assert dao.reserved == [("tenant-a", "user-a", 79, 100)]
    assert dao.settled == [("reservation-1", 7)]


def test_missing_provider_usage_is_charged_at_the_reserved_upper_bound():
    dao = FakeQuotaDao()
    client = FakeLLMClient([ModelOutput(error_code=0, text="ok")])
    metered = MeteredLLMClient(
        client, tenant_id="tenant-a", user_id="user-a", daily_limit_tokens=100, dao=dao
    )

    async def collect():
        return [output async for output in metered.generate_stream(_request())]

    asyncio.run(collect())

    assert dao.settled == [("reservation-1", 79)]


def test_active_stream_refreshes_its_reservation_lease(monkeypatch):
    monkeypatch.setattr(token_quota_module, "_RESERVATION_HEARTBEAT_SECONDS", 0.001)
    dao = FakeQuotaDao()
    client = FakeLLMClient([ModelOutput(error_code=0, text="ok")], delay=0.01)
    metered = MeteredLLMClient(
        client, tenant_id="tenant-a", user_id="user-a", daily_limit_tokens=100, dao=dao
    )

    async def collect():
        return [output async for output in metered.generate_stream(_request())]

    asyncio.run(collect())

    assert dao.heartbeats
    assert set(dao.heartbeats) == {"reservation-1"}
    assert dao.settled == [("reservation-1", 79)]


def test_quota_rejection_happens_before_calling_the_model():
    dao = FakeQuotaDao(reject=True)
    client = FakeLLMClient([ModelOutput(error_code=0, text="ok")])
    metered = MeteredLLMClient(
        client, tenant_id="tenant-a", user_id="user-a", daily_limit_tokens=100, dao=dao
    )

    async def collect():
        return [output async for output in metered.generate_stream(_request())]

    with pytest.raises(TokenQuotaExceededError):
        asyncio.run(collect())
    assert client.calls == 0
    assert dao.settled == []


def test_missing_output_limit_is_rejected_before_reservation_or_model_call():
    dao = FakeQuotaDao()
    client = FakeLLMClient([ModelOutput(error_code=0, text="ok")])
    metered = MeteredLLMClient(
        client, tenant_id="tenant-a", user_id="user-a", daily_limit_tokens=100, dao=dao
    )
    request = ModelRequest(
        model="test-model",
        messages=[{"role": "user", "content": "hello"}],
    )

    async def collect():
        return [output async for output in metered.generate_stream(request)]

    with pytest.raises(TokenQuotaConfigurationError, match="positive max_new_tokens"):
        asyncio.run(collect())

    assert client.calls == 0
    assert dao.reserved == []


def test_tokenizer_failure_is_rejected_before_reservation_or_model_call():
    dao = FakeQuotaDao()
    client = FakeLLMClient([ModelOutput(error_code=0, text="ok")])

    async def fail_count_token(*_args):
        raise RuntimeError("tokenizer unavailable")

    client.count_token = fail_count_token
    metered = MeteredLLMClient(
        client, tenant_id="tenant-a", user_id="user-a", daily_limit_tokens=100, dao=dao
    )

    async def collect():
        return [output async for output in metered.generate_stream(_request())]

    with pytest.raises(
        TokenQuotaConfigurationError, match="Unable to count prompt tokens"
    ):
        asyncio.run(collect())

    assert client.calls == 0
    assert dao.reserved == []


def test_preflight_serialization_counts_tool_history_and_tool_choice():
    dao = FakeQuotaDao()
    client = FakeLLMClient([ModelOutput(error_code=0, text="ok")])
    metered = MeteredLLMClient(
        client, tenant_id="tenant-a", user_id="user-a", daily_limit_tokens=100, dao=dao
    )
    request = ModelRequest(
        model="test-model",
        messages=[
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "sql_query",
                            "arguments": '{"sql":"SELECT order_id FROM orders"}',
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "1 row"},
            {"role": "user", "content": "explain the result"},
        ],
        tools=[{"type": "function", "function": {"name": "sql_query"}}],
        tool_choice="auto",
        max_new_tokens=5,
    )

    async def collect():
        return [output async for output in metered.generate_stream(request)]

    asyncio.run(collect())

    model, prompt = client.counted_prompts[0]
    serialized = json.loads(prompt)
    assert model == "test-model"
    assert serialized["messages"][0]["tool_calls"][0]["function"]["arguments"]
    assert serialized["messages"][1]["tool_call_id"] == "call-1"
    assert serialized["tools"][0]["function"]["name"] == "sql_query"
    assert serialized["tool_choice"] == "auto"


def test_preflight_rejects_multimodal_content_before_reservation_or_model_call():
    dao = FakeQuotaDao()
    client = FakeLLMClient([ModelOutput(error_code=0, text="ok")])
    metered = MeteredLLMClient(
        client, tenant_id="tenant-a", user_id="user-a", daily_limit_tokens=100, dao=dao
    )
    request = ModelRequest(
        model="test-model",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "object": {
                            "data": "https://example.invalid/image.png",
                            "format": "url",
                        },
                    }
                ],
            }
        ],
        max_new_tokens=5,
    )

    async def collect():
        return [output async for output in metered.generate_stream(request)]

    with pytest.raises(TokenQuotaConfigurationError, match="text-only"):
        asyncio.run(collect())

    assert dao.reserved == []
    assert client.counted_prompts == []
    assert client.calls == 0


def test_server_context_builds_request_scoped_agent_client_wrapper():
    wrapper = build_metered_llm_client_wrapper(
        {
            "tenant_id": "trusted-tenant",
            "user_id": "trusted-user",
            "daily_limit_tokens": 200,
        }
    )
    client = FakeLLMClient([ModelOutput(error_code=0, text="ok")])

    metered = wrapper(client)

    assert isinstance(metered, MeteredLLMClient)
    assert metered._tenant_id == "trusted-tenant"
    assert metered._user_id == "trusted-user"
    assert metered._daily_limit_tokens == 200

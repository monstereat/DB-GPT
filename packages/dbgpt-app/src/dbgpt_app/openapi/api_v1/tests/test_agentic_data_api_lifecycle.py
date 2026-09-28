"""Tests for ReAct agent stream terminal-event lifecycle handling."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from dbgpt_app.openapi.api_v1 import agentic_data_api
from dbgpt_app.openapi.api_v1.react_final import AgentFinalAnswer
from dbgpt_serve.utils.auth import UserRequest


def _decode_sse_event(event: str):
    assert event.startswith("data: ")
    return json.loads(event.removeprefix("data: ").strip())


def test_wrapped_unmeterable_token_quota_error_is_classified():
    from dbgpt_app.openapi.api_v1.token_quota import TokenQuotaConfigurationError

    class _LLMError(RuntimeError):
        original_exception = TokenQuotaConfigurationError("sensitive internal detail")

    error = _LLMError("provider wrapper")
    assert agentic_data_api._is_token_quota_configuration_error(error)
    assert not agentic_data_api._is_token_quota_exceeded(error)


@pytest.mark.parametrize(
    ("action_output", "expected"),
    [
        (
            {
                "action": "sql_query",
                "observations": json.dumps(
                    {
                        "error": {
                            "retryable": False,
                            "message": "权限不足。",
                        }
                    }
                ),
            },
            "权限不足。",
        ),
        (
            {
                "action": "sql_query",
                "observations": json.dumps(
                    {"error": {"retryable": True, "message": "可纠正"}}
                ),
            },
            None,
        ),
        (
            {
                "action": "other_tool",
                "observations": json.dumps(
                    {"error": {"retryable": False, "message": "hidden"}}
                ),
            },
            None,
        ),
    ],
)
def test_terminal_sql_error_uses_safe_message(action_output, expected):
    assert agentic_data_api._terminal_sql_error(action_output) == expected


@pytest.mark.asyncio
async def test_react_stream_scopes_metered_client_for_nested_retrievers(monkeypatch):
    from dbgpt.core.interface.operators.llm_operator import (
        wrap_llm_client_for_current_context,
    )
    from dbgpt_app.openapi.api_v1.token_quota import MeteredLLMClient

    quota_context = {
        "tenant_id": "tenant-a",
        "user_id": "user-a",
        "daily_limit_tokens": 100,
    }
    raw_client = object()

    async def _inner_stream(*_args, **kwargs):
        assert kwargs["token_quota_context"] == quota_context
        nested_client = wrap_llm_client_for_current_context(raw_client)
        assert isinstance(nested_client, MeteredLLMClient)
        assert nested_client._tenant_id == "tenant-a"
        assert nested_client._user_id == "user-a"
        yield "data: nested retrieval metered\n\n"

    monkeypatch.setattr(agentic_data_api, "_react_agent_stream_inner", _inner_stream)

    events = [
        event
        async for event in agentic_data_api._react_agent_stream(
            SimpleNamespace(), token_quota_context=quota_context
        )
    ]

    assert events == ["data: nested retrieval metered\n\n"]
    assert wrap_llm_client_for_current_context(raw_client) is raw_client


@pytest.mark.parametrize(
    ("requested_tokens", "reserved_tokens", "expected"),
    [
        (256, 1024, 256),
        (4096, 1024, 1024),
        (None, 1024, 1024),
        (0, 1024, 1024),
        (4096, 0, 4096),
    ],
)
def test_react_generation_tokens_obey_configured_output_reserve(
    requested_tokens, reserved_tokens, expected
):
    assert (
        agentic_data_api._resolve_react_max_new_tokens(
            requested_tokens, reserved_tokens
        )
        == expected
    )


def test_history_failure_does_not_drop_final_or_done(caplog) -> None:
    class _FailingStorageConversation:
        def add_view_message(self, payload: str) -> None:
            raise RuntimeError("history storage unavailable")

        def end_current_round(self) -> None:
            raise AssertionError("must stop after the first persistence failure")

        def save_to_storage(self) -> None:
            raise AssertionError("must stop after the first persistence failure")

    events = agentic_data_api._react_terminal_events(
        _FailingStorageConversation(),
        '{"type":"react-agent"}',
        AgentFinalAnswer(content="answer"),
    )

    assert [_decode_sse_event(event) for event in events] == [
        {
            "type": "final",
            "protocol_version": 2,
            "content": "answer",
            "citations": [],
        },
        {"type": "done"},
    ]
    assert "Failed to persist ReAct agent history" in caplog.text


@pytest.mark.asyncio
async def test_react_history_roundtrip_supplies_prior_turns_to_agent_context():
    from dbgpt.core import StorageConversation
    from dbgpt.core.interface.storage import InMemoryStorage

    conv_storage = InMemoryStorage()
    message_storage = InMemoryStorage()
    first_turn = StorageConversation(
        conv_uid="react-multiturn-test",
        conv_storage=conv_storage,
        message_storage=message_storage,
    )
    first_turn.save_to_storage()
    first_turn.start_new_round()
    first_turn.add_user_message("第二季度华南区销售额是多少？")
    first_turn.add_view_message(
        agentic_data_api._build_react_history_payload(
            final_content="第二季度华南区销售额为 77,000 分。",
            steps=[],
            task_plan=[],
            generated_images=[],
            sub_agents={},
            input_files=[],
        )
    )
    first_turn.end_current_round()

    second_turn = StorageConversation(
        conv_uid="react-multiturn-test",
        conv_storage=conv_storage,
        message_storage=message_storage,
    )
    second_turn.start_new_round()
    historical_dialogues = agentic_data_api._load_react_conversation_history(
        second_turn
    )

    class _Agent:
        async def generate_reply(self, **kwargs):
            self.kwargs = kwargs
            return "reply"

    agent = _Agent()
    result = await agentic_data_api._generate_react_agent_reply(
        agent,
        received_message="其中哪个城市销售额最高？",
        stream_callback=None,
        historical_dialogues=historical_dialogues,
    )

    assert result == "reply"
    assert agent.kwargs["historical_dialogues"] == historical_dialogues
    assert [message.content for message in historical_dialogues] == [
        "第二季度华南区销售额是多少？",
        "第二季度华南区销售额为 77,000 分。",
    ]


def test_selected_database_must_be_visible_to_authenticated_user(monkeypatch):
    connector = object()

    class _DatabaseManager:
        def get_db_list(self, *, db_name, user_id):
            assert db_name == "sales"
            assert user_id == "alice"
            return [{"db_name": "sales"}]

        def get_connector(self, database_name):
            assert database_name == "sales"
            return connector

    monkeypatch.setattr(
        agentic_data_api.ConnectorManager,
        "get_instance",
        lambda system_app: _DatabaseManager(),
    )
    dialogue = SimpleNamespace(ext_info={"database_name": "sales"})

    assert (
        agentic_data_api._get_authorized_database_connector(
            dialogue, UserRequest(user_id="alice")
        )
        is connector
    )


@pytest.mark.asyncio
async def test_chat_react_agent_passes_server_role_into_stream_context(monkeypatch):
    captured = {}

    async def _no_attachments(_dialogue, _user):
        return None

    def _capture_stream(_dialogue, **kwargs):
        captured.update(kwargs)

        async def _events():
            yield "data: {}\n\n"

        return _events()

    class _Response:
        def __init__(self, body_iterator, **_kwargs):
            self.body_iterator = body_iterator

    monkeypatch.setattr(agentic_data_api, "_open_turn_attachments", _no_attachments)
    monkeypatch.setattr(agentic_data_api, "_react_agent_stream", _capture_stream)
    monkeypatch.setattr(agentic_data_api, "_AgentStreamingResponse", _Response)

    response = await agentic_data_api.chat_react_agent(
        agentic_data_api.ConversationVo(user_input="query"),
        UserRequest(user_id="alice", role="sales", tenant_id="tenant-a"),
    )

    assert captured["identity_context"]["actor_user_id"] == "alice"
    assert captured["identity_context"]["role"] == "sales"
    assert captured["identity_context"]["tenant_id"] == "tenant-a"
    assert response.body_iterator is not None


def test_selected_database_rejects_other_users_connection(monkeypatch):
    class _DatabaseManager:
        def get_db_list(self, *, db_name, user_id):
            return []

        def get_connector(self, database_name):
            raise AssertionError("unauthorized connector must not be loaded")

    monkeypatch.setattr(
        agentic_data_api.ConnectorManager,
        "get_instance",
        lambda system_app: _DatabaseManager(),
    )
    dialogue = SimpleNamespace(ext_info={"database_name": "private-sales"})

    with pytest.raises(agentic_data_api.HTTPException) as error:
        agentic_data_api._get_authorized_database_connector(
            dialogue, UserRequest(user_id="mallory")
        )

    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_closing_stream_cancels_and_awaits_agent_task(monkeypatch) -> None:
    task_started = asyncio.Event()
    task_finished = asyncio.Event()
    created_tasks = []

    async def _agent_work() -> None:
        task_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            task_finished.set()

    async def _fake_stream_impl(
        dialogue, tool_mode="full", agent_task_holder=None, attachment_ctx=None
    ):
        del dialogue, tool_mode, attachment_ctx
        task = asyncio.create_task(_agent_work())
        created_tasks.append(task)
        agent_task_holder.append(task)
        await task_started.wait()
        yield "data: first\n\n"
        await asyncio.Event().wait()

    monkeypatch.setattr(
        agentic_data_api,
        "_react_agent_stream_impl",
        _fake_stream_impl,
    )

    stream = agentic_data_api._react_agent_stream(SimpleNamespace())
    assert await anext(stream) == "data: first\n\n"

    await stream.aclose()

    assert len(created_tasks) == 1
    assert created_tasks[0].cancelled()
    assert created_tasks[0].done()
    assert task_finished.is_set()


@pytest.mark.asyncio
async def test_runtime_failure_emits_structured_final_and_done(
    monkeypatch, caplog
) -> None:
    async def _failing_stream_impl(
        dialogue, tool_mode="full", agent_task_holder=None, attachment_ctx=None
    ):
        del dialogue, tool_mode, agent_task_holder, attachment_ctx
        if False:
            yield ""
        raise RuntimeError("model stream failed")

    monkeypatch.setattr(
        agentic_data_api,
        "_react_agent_stream_impl",
        _failing_stream_impl,
    )

    events = [
        _decode_sse_event(event)
        async for event in agentic_data_api._react_agent_stream(SimpleNamespace())
    ]

    assert events == [
        {
            "type": "final",
            "protocol_version": 2,
            "content": "抱歉，回答生成过程中发生错误，请重试。",
            "citations": [],
        },
        {"type": "done"},
    ]
    assert "ReAct agent stream failed before normal completion" in caplog.text


@pytest.mark.asyncio
async def test_runtime_failure_does_not_duplicate_a_final_event(monkeypatch) -> None:
    async def _partially_failing_stream_impl(
        dialogue, tool_mode="full", agent_task_holder=None, attachment_ctx=None
    ):
        del dialogue, tool_mode, agent_task_holder, attachment_ctx
        yield agentic_data_api._sse_event(
            AgentFinalAnswer(content="answer").to_sse_payload()
        )
        raise RuntimeError("failed after final")

    monkeypatch.setattr(
        agentic_data_api,
        "_react_agent_stream_impl",
        _partially_failing_stream_impl,
    )

    events = [
        _decode_sse_event(event)
        async for event in agentic_data_api._react_agent_stream(SimpleNamespace())
    ]

    assert [event["type"] for event in events] == ["final", "done"]
    assert events[0]["content"] == "answer"


@pytest.mark.asyncio
async def test_response_disconnect_closes_stream_and_agent_task(monkeypatch) -> None:
    task_started = asyncio.Event()
    task_finished = asyncio.Event()
    body_send_started = asyncio.Event()
    never = asyncio.Event()
    created_tasks = []

    async def _agent_work() -> None:
        task_started.set()
        try:
            await never.wait()
        finally:
            task_finished.set()

    async def _fake_stream_impl(
        dialogue, tool_mode="full", agent_task_holder=None, attachment_ctx=None
    ):
        del dialogue, tool_mode, attachment_ctx
        task = asyncio.create_task(_agent_work())
        created_tasks.append(task)
        agent_task_holder.append(task)
        await task_started.wait()
        yield agentic_data_api._sse_event({"type": "step", "content": "first"})
        await never.wait()

    async def _send(message) -> None:
        if message["type"] == "http.response.body" and message.get("more_body"):
            body_send_started.set()
            await never.wait()

    async def _receive():
        await body_send_started.wait()
        return {"type": "http.disconnect"}

    monkeypatch.setattr(
        agentic_data_api,
        "_react_agent_stream_impl",
        _fake_stream_impl,
    )
    response = agentic_data_api._AgentStreamingResponse(
        agentic_data_api._react_agent_stream(SimpleNamespace()),
        media_type="text/event-stream",
    )
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/chat/react-agent",
        "headers": [],
        "asgi": {"version": "3.0", "spec_version": "2.0"},
    }

    await asyncio.wait_for(response(scope, _receive, _send), timeout=1)

    assert len(created_tasks) == 1
    assert created_tasks[0].cancelled()
    assert created_tasks[0].done()
    assert task_finished.is_set()

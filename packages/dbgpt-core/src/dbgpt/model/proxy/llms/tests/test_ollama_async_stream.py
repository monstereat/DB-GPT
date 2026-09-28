import asyncio
import sys
from types import SimpleNamespace

import pytest

from dbgpt.core.interface.llm import ModelRequest, ModelRequestContext
from dbgpt.core.interface.message import ModelMessage, ModelMessageRoleType
from dbgpt.model.proxy.llms import ollama as ollama_adapter
from dbgpt.model.proxy.llms.ollama import OllamaLLMClient


@pytest.mark.asyncio
async def test_async_stream_cancellation_closes_ollama_stream(monkeypatch):
    state = {"stream_closed": False, "client_closed": False, "request": None}

    async def response_stream():
        try:
            yield {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "metric_query", "arguments": {"x": 1}}}
                    ],
                }
            }
            await asyncio.Event().wait()
        finally:
            state["stream_closed"] = True

    class _HTTPClient:
        async def aclose(self):
            state["client_closed"] = True

    class _AsyncClient:
        def __init__(self, host):
            assert host == "http://ollama.test"
            self._client = _HTTPClient()

        async def _request(self, *args, **kwargs):
            state["request"] = (args, kwargs)
            return response_stream()

    monkeypatch.setenv("DBGPT_OLLAMA_DISABLE_THINKING", "true")
    monkeypatch.setitem(
        sys.modules,
        "ollama",
        SimpleNamespace(
            AsyncClient=_AsyncClient,
            ChatResponse=object,
            ResponseError=Exception,
        ),
    )
    client = OllamaLLMClient(model="qwen3:1.7b", api_base="http://ollama.test")
    request = ModelRequest(
        model="qwen3:1.7b",
        messages=[ModelMessage(role=ModelMessageRoleType.HUMAN, content="hello")],
        context=ModelRequestContext(stream=True),
    )

    stream = client.async_generate_stream(request)
    first = await anext(stream)
    assert first.tool_calls == [
        {
            "type": "function",
            "function": {"name": "metric_query", "arguments": '{"x": 1}'},
        }
    ]

    await stream.aclose()

    args, kwargs = state["request"]
    assert args == (object, "POST", "/api/chat")
    assert kwargs["json"]["think"] is False
    assert kwargs["json"]["messages"][-1]["content"] == "hello\n/no_think"
    assert state["stream_closed"] is True
    assert state["client_closed"] is True


@pytest.mark.asyncio
async def test_adapter_wrapper_closes_inner_stream_on_cancellation(monkeypatch):
    state = {"closed": False}

    class _Client:
        default_model = "qwen3:1.7b"

        async def async_generate_stream(self, request):
            try:
                yield "chunk"
                await asyncio.Event().wait()
            finally:
                state["closed"] = True

    client = _Client()
    model = SimpleNamespace(proxy_llm_client=client)
    monkeypatch.setattr(
        ollama_adapter, "parse_model_request", lambda params, model, stream: object()
    )

    stream = ollama_adapter.ollama_generate_stream(model, None, {}, None)
    assert await anext(stream) == "chunk"
    await stream.aclose()

    assert state["closed"] is True

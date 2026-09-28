import pytest

from dbgpt.core.interface.llm import LLMClient, ModelOutput, ModelRequest
from dbgpt.core.interface.operators.llm_operator import (
    scoped_llm_client_wrapper,
    wrap_llm_client_for_current_context,
)
from dbgpt.model.operators.llm_operator import LLMOperator, StreamingLLMOperator


class _FakeLLMClient(LLMClient):
    def __init__(self):
        self.generate_calls = 0
        self.generate_stream_calls = 0

    async def generate(self, request, message_converter=None):
        self.generate_calls += 1
        return ModelOutput(error_code=0, text="generated")

    async def generate_stream(self, request, message_converter=None):
        self.generate_stream_calls += 1
        yield ModelOutput(error_code=0, text="streamed")

    async def models(self):
        return []

    async def count_token(self, model: str, prompt: str) -> int:
        return 0


class _ClientWrapper:
    def __init__(self, client: LLMClient):
        self.client = client

    def __getattr__(self, name):
        return getattr(self.client, name)


class _FakeDAGContext:
    async def save_to_share_data(self, *args, **kwargs):
        pass


@pytest.mark.asyncio
async def test_wrapper_is_scoped_and_does_not_read_request_context():
    client = _FakeLLMClient()
    calls = []

    def wrap(raw_client):
        calls.append(raw_client)
        return _ClientWrapper(raw_client)

    assert wrap_llm_client_for_current_context(client) is client
    with scoped_llm_client_wrapper(wrap):
        wrapped = wrap_llm_client_for_current_context(client)
        assert isinstance(wrapped, _ClientWrapper)
        assert wrap_llm_client_for_current_context(wrapped) is wrapped
        assert len(calls) == 1
    assert wrap_llm_client_for_current_context(client) is client


@pytest.mark.asyncio
async def test_llm_operator_generate_uses_context_wrapper(monkeypatch):
    client = _FakeLLMClient()
    wrapper_calls = []
    context = _FakeDAGContext()
    monkeypatch.setattr(
        LLMOperator,
        "current_dag_context",
        property(lambda self: context),
    )
    operator = LLMOperator(llm_client=client)

    def wrap(raw_client):
        wrapper_calls.append(raw_client)
        return _ClientWrapper(raw_client)

    with scoped_llm_client_wrapper(wrap):
        output = await operator.map(ModelRequest(model="test", messages=[]))

    assert output.text == "generated"
    assert client.generate_calls == 1
    assert wrapper_calls == [client]


@pytest.mark.asyncio
async def test_streaming_llm_operator_generate_stream_uses_context_wrapper(monkeypatch):
    client = _FakeLLMClient()
    wrapper_calls = []
    context = _FakeDAGContext()
    monkeypatch.setattr(
        StreamingLLMOperator,
        "current_dag_context",
        property(lambda self: context),
    )
    operator = StreamingLLMOperator(llm_client=client)

    def wrap(raw_client):
        wrapper_calls.append(raw_client)
        return _ClientWrapper(raw_client)

    with scoped_llm_client_wrapper(wrap):
        outputs = [
            output
            async for output in operator.streamify(
                ModelRequest(model="test", messages=[])
            )
        ]

    assert [output.text for output in outputs] == ["streamed"]
    assert client.generate_stream_calls == 1
    assert wrapper_calls == [client]


@pytest.mark.asyncio
async def test_mixin_property_and_base_operator_do_not_double_wrap(monkeypatch):
    client = _FakeLLMClient()
    wrapper_calls = []
    context = _FakeDAGContext()
    monkeypatch.setattr(
        LLMOperator,
        "current_dag_context",
        property(lambda self: context),
    )
    operator = LLMOperator(llm_client=client)

    def wrap(raw_client):
        wrapper_calls.append(raw_client)
        return _ClientWrapper(raw_client)

    with scoped_llm_client_wrapper(wrap):
        wrapped_from_mixin = operator.llm_client
        assert isinstance(wrapped_from_mixin, _ClientWrapper)
        await operator.map(ModelRequest(model="test", messages=[]))

    assert client.generate_calls == 1
    assert wrapper_calls == [client]

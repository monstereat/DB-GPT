import asyncio

import pytest

from dbgpt.component import SystemApp
from dbgpt.util.tracer import (
    DefaultTracer,
    MemorySpanStorage,
    Span,
    SpanStorage,
    SpanStorageType,
    Tracer,
    TracerManager,
    TracerParameters,
)


@pytest.fixture
def system_app():
    return SystemApp()


@pytest.fixture
def storage(system_app: SystemApp):
    ms = MemorySpanStorage(system_app)
    system_app.register_instance(ms)
    return ms


@pytest.fixture
def tracer(request, system_app: SystemApp):
    if not request or not hasattr(request, "param"):
        return DefaultTracer(system_app)
    else:
        span_storage_type = request.param.get(
            "span_storage_type", SpanStorageType.ON_CREATE_END
        )
        return DefaultTracer(system_app, span_storage_type=span_storage_type)


@pytest.fixture
def tracer_manager(system_app: SystemApp, tracer: Tracer):
    system_app.register_instance(tracer)
    manager = TracerManager()
    manager.initialize(system_app)
    return manager


def test_start_and_end_span(tracer: Tracer):
    span = tracer.start_span("operation")
    assert isinstance(span, Span)
    assert span.operation_name == "operation"

    tracer.end_span(span)
    assert span.end_time is not None

    stored_span = tracer._get_current_storage().spans[0]
    assert stored_span.span_id == span.span_id


@pytest.mark.parametrize("value", ["true", "TRUE", "True"])
def test_tracer_parameters_enable_otlp_exporter_from_environment(monkeypatch, value):
    monkeypatch.setenv("TRACER_TO_OPEN_TELEMETRY", value)

    parameters = TracerParameters()

    assert parameters.exporter == "telemetry"


def test_start_and_end_span_with_tracer_manager(tracer_manager: TracerManager):
    span = tracer_manager.start_span("operation")
    assert isinstance(span, Span)
    assert span.operation_name == "operation"

    tracer_manager.end_span(span)
    assert span.end_time is not None


def test_parent_child_span_relation(tracer: Tracer):
    parent_span = tracer.start_span("parent_operation")
    child_span = tracer.start_span(
        "child_operation", parent_span_id=parent_span.span_id
    )

    assert child_span.parent_span_id == parent_span.span_id
    assert child_span.trace_id == parent_span.trace_id

    tracer.end_span(child_span)
    tracer.end_span(parent_span)

    assert parent_span.operation_name in [
        s.operation_name for s in tracer._get_current_storage().spans
    ]
    assert child_span.operation_name in [
        s.operation_name for s in tracer._get_current_storage().spans
    ]


def test_parallel_async_span_stacks_are_isolated(tracer: Tracer):
    parent_span = tracer.start_span("request")
    ready = asyncio.Event()
    started = 0

    async def worker(operation_name: str) -> str:
        nonlocal started
        span = tracer.start_span(operation_name, parent_span_id=parent_span.span_id)
        started += 1
        if started == 2:
            ready.set()
        await ready.wait()
        current_span = tracer.get_current_span()
        assert current_span is span
        span.end()
        return current_span.operation_name

    async def run_workers():
        return await asyncio.gather(worker("subagent.a"), worker("subagent.b"))

    results = asyncio.run(run_workers())

    assert set(results) == {"subagent.a", "subagent.b"}
    assert tracer.get_current_span() is parent_span
    parent_span.end()


@pytest.mark.parametrize(
    "tracer, expected_count, after_create_inc_count",
    [
        ({"span_storage_type": SpanStorageType.ON_CREATE}, 1, 1),
        ({"span_storage_type": SpanStorageType.ON_END}, 1, 0),
        ({"span_storage_type": SpanStorageType.ON_CREATE_END}, 2, 1),
    ],
    indirect=["tracer"],
)
def test_tracer_span_storage_type_and_with(
    tracer: Tracer,
    expected_count: int,
    after_create_inc_count: int,
    storage: SpanStorage,
):
    span = tracer.start_span("new_span")
    span.end()
    assert len(storage.spans) == expected_count

    with tracer.start_span("with_span") as _ws:
        assert len(storage.spans) == expected_count + after_create_inc_count
    assert len(storage.spans) == expected_count + expected_count

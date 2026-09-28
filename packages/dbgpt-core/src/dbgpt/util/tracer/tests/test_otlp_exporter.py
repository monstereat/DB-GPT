from concurrent.futures import ThreadPoolExecutor

import pytest

pytest.importorskip("opentelemetry.exporter.otlp.proto.grpc.trace_exporter")

import grpc
from opentelemetry.proto.collector.trace.v1 import (
    trace_service_pb2,
    trace_service_pb2_grpc,
)

from dbgpt.util.tracer.base import Span, SpanType
from dbgpt.util.tracer.opentelemetry import OpenTelemetrySpanStorage


class _Collector(trace_service_pb2_grpc.TraceServiceServicer):
    def __init__(self):
        self.requests = []

    def Export(self, request, context):
        self.requests.append(request)
        return trace_service_pb2.ExportTraceServiceResponse()


def test_otlp_export_preserves_parent_context_and_safe_agent_attributes():
    collector = _Collector()
    executor = ThreadPoolExecutor(max_workers=1)
    server = grpc.server(executor)
    trace_service_pb2_grpc.add_TraceServiceServicer_to_server(collector, server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    storage = OpenTelemetrySpanStorage(
        service_name="dbgpt-test",
        otlp_endpoint=f"127.0.0.1:{port}",
        otlp_insecure=True,
        otlp_timeout=3,
    )

    trace_id = "0123456789abcdef0123456789abcdef"
    parent_id = f"{trace_id}:0123456789abcdef"
    parent = Span(
        trace_id,
        parent_id,
        SpanType.RUN,
        operation_name="request",
    )
    child = Span(
        trace_id,
        f"{trace_id}:fedcba9876543210",
        SpanType.AGENT,
        parent_span_id=parent.span_id,
        operation_name="agent.sql_query",
        metadata={"actor_user_id": "user-1", "sql_sha256": "safe-hash"},
    )

    try:
        for span in (parent, child):
            storage.append_span(span)
            span.end()
            storage.append_span(span)
    finally:
        storage.close()
        server.stop(grace=0).wait()
        executor.shutdown(wait=True)

    exported = [
        span
        for request in collector.requests
        for resource in request.resource_spans
        for scope in resource.scope_spans
        for span in scope.spans
    ]
    assert len(exported) == 2
    assert {span.name for span in exported} == {"request", "agent.sql_query"}
    exported_child = next(span for span in exported if span.name == "agent.sql_query")
    assert exported_child.parent_span_id == bytes.fromhex("0123456789abcdef")
    attributes = {item.key: item.value for item in exported_child.attributes}
    assert attributes["actor_user_id"].string_value == "user-1"
    assert attributes["sql_sha256"].string_value == "safe-hash"
    assert all(
        resource.resource.attributes[0].value.string_value == "dbgpt-test"
        for request in collector.requests
        for resource in request.resource_spans
    )

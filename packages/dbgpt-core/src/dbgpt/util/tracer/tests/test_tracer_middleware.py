import asyncio
import logging

from dbgpt.component import SystemApp
from dbgpt.util.tracer import DBGPT_TRACER_SPAN_ID, DefaultTracer, SpanType
from dbgpt.util.tracer.tracer_middleware import TraceIDMiddleware


def test_request_span_lives_through_stream_and_does_not_log_headers(caplog):
    tracer = DefaultTracer(SystemApp())
    parent_trace_id = "0123456789abcdef0123456789abcdef"
    parent_span_id = f"{parent_trace_id}:0123456789abcdef"
    messages = []
    stream_spans = []

    async def app(_scope, _receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream")],
            }
        )
        await asyncio.sleep(0.01)
        request_span_in_stream = tracer.get_current_span()
        stream_spans.append(request_span_in_stream)
        child = tracer.start_span(
            "agent.sql_query",
            parent_span_id=(
                request_span_in_stream.span_id if request_span_in_stream else None
            ),
            span_type=SpanType.AGENT,
            metadata={"query_sha256": "safe-hash"},
        )
        child.end()
        await send(
            {
                "type": "http.response.body",
                "body": b"data: done\n\n",
                "more_body": False,
            }
        )

    middleware = TraceIDMiddleware(
        app=app,
        trace_context_var=None,
        tracer=tracer,
    )
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/chat/react-agent",
        "raw_path": b"/api/v1/chat/react-agent",
        "query_string": b"",
        "headers": [
            (b"authorization", b"Bearer secret-test-token"),
            (DBGPT_TRACER_SPAN_ID.lower().encode(), parent_span_id.encode()),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 5670),
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    with caplog.at_level(logging.DEBUG, logger="dbgpt.util.tracer.tracer_middleware"):
        asyncio.run(middleware(scope, receive, send))

    spans = tracer._get_current_storage().spans
    request_span = [
        span for span in spans if span.operation_name == "DB-GPT-Web-Entry"
    ][-1]
    sql_span = [span for span in spans if span.operation_name == "agent.sql_query"][-1]
    assert request_span.parent_span_id == parent_span_id
    assert len(stream_spans) == 1
    assert stream_spans[0].span_id == request_span.span_id
    assert sql_span.parent_span_id == request_span.span_id
    assert request_span.end_time >= sql_span.end_time
    assert request_span.metadata["http.status_code"] == 200
    assert messages[-1]["body"] == b"data: done\n\n"
    assert "secret-test-token" not in caplog.text

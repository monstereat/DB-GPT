from contextvars import ContextVar

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from dbgpt.util.tracer import Tracer, TracerContext

from .base import _parse_span_id

_DEFAULT_EXCLUDE_PATHS = ["/api/controller/heartbeat", "/api/health"]


class TraceIDMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        trace_context_var: ContextVar[TracerContext],
        tracer: Tracer,
        root_operation_name: str = "DB-GPT-Web-Entry",
        include_prefix: str = "/api",
        exclude_paths=_DEFAULT_EXCLUDE_PATHS,
    ):
        self.app = app
        self.trace_context_var = trace_context_var
        self.tracer = tracer
        self.root_operation_name = root_operation_name
        self.include_prefix = include_prefix
        self.exclude_paths = exclude_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in self.exclude_paths or not path.startswith(self.include_prefix):
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        parent_span_id = _parse_span_id(request)
        status_code = None

        async def send_with_status(message: Message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        span = self.tracer.start_span(
            self.root_operation_name,
            parent_span_id,
            metadata={"path": path, "http.method": scope.get("method")},
        )
        try:
            await self.app(scope, receive, send_with_status)
        except BaseException:
            span.end(
                metadata={
                    **span.metadata,
                    "http.status_code": status_code or 500,
                }
            )
            raise
        else:
            span.end(metadata={**span.metadata, "http.status_code": status_code})

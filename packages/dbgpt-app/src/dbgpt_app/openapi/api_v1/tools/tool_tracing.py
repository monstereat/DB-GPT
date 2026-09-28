"""Tracing helpers for built-in Agent tools."""

import inspect
import logging
import time
from functools import wraps

from dbgpt.util.tracer import SpanType, root_tracer

logger = logging.getLogger(__name__)


def trace_agent_tool(operation_name: str):
    """Trace one tool call without recording its arguments or result."""

    def decorate(function):
        if inspect.iscoroutinefunction(function):

            @wraps(function)
            async def async_traced(*args, **kwargs):
                return await _trace_call(
                    operation_name, lambda: function(*args, **kwargs)
                )

            return async_traced

        @wraps(function)
        def sync_traced(*args, **kwargs):
            started_at = time.monotonic()
            span = _start_span(operation_name)
            status = "failed"
            try:
                result = function(*args, **kwargs)
                status = "returned"
                return result
            finally:
                _end_span(span, status, started_at)

        return sync_traced

    return decorate


async def _trace_call(operation_name: str, call):
    started_at = time.monotonic()
    span = _start_span(operation_name)
    status = "failed"
    try:
        result = await call()
        status = "returned"
        return result
    finally:
        _end_span(span, status, started_at)


def _start_span(operation_name: str):
    try:
        return root_tracer.start_span(
            operation_name,
            span_type=SpanType.AGENT,
            metadata={},
        )
    except Exception:
        logger.debug("Unable to start Agent tool span", exc_info=True)
        return None


def _end_span(span, status: str, started_at: float):
    if span is None:
        return
    try:
        root_tracer.end_span(
            span,
            metadata={
                "status": status,
                "elapsed_ms": int((time.monotonic() - started_at) * 1000),
            },
        )
    except Exception:
        logger.debug("Unable to end Agent tool span", exc_info=True)

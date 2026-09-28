import asyncio
import json
from typing import Dict, List, Optional

import pytest
from typing_extensions import Annotated, Doc

from dbgpt._private.pydantic import BaseModel, Field
from dbgpt.agent.resource.tool.pack import ToolPack
from dbgpt.util.tracer import root_tracer

from ..base import BaseTool, FunctionTool, ToolParameter, tool
from ..exceptions import ToolNotFoundException


class TestBaseTool(BaseTool):
    @property
    def name(self):
        return "test_tool"

    @property
    def description(self):
        return "This is a test tool."

    @property
    def args(self):
        return {}

    def execute(self, *args, **kwargs):
        return "executed"

    async def async_execute(self, *args, **kwargs):
        return "async executed"


def test_toolpack_sync_execution_emits_redacted_span(monkeypatch):
    class _Span:
        metadata = None

    span = _Span()
    started = {}

    def start_span(name, *, span_type, metadata):
        started.update(name=name, span_type=span_type, metadata=metadata)
        return span

    def end_span(_span, *, metadata):
        span.metadata = metadata

    def private_tool(customer_id: str) -> str:
        """Return a private result."""
        return "private result"

    monkeypatch.setattr(root_tracer, "start_span", start_span)
    monkeypatch.setattr(root_tracer, "end_span", end_span)
    result = ToolPack([FunctionTool("private-tool-name", private_tool)]).execute(
        resource_name="private-tool-name", customer_id="private-customer-id"
    )

    assert result == "private result"
    assert started["name"] == "agent.toolpack.execute"
    assert started["metadata"] == {}
    assert span.metadata["status"] == "returned"
    span_data = repr(started) + repr(span.metadata)
    assert "private-tool-name" not in span_data
    assert "private-customer-id" not in span_data
    assert "private result" not in span_data


@pytest.mark.asyncio
async def test_toolpack_async_execution_emits_redacted_span(monkeypatch):
    class _Span:
        metadata = None

    span = _Span()
    started = {}

    def start_span(name, *, span_type, metadata):
        started.update(name=name, span_type=span_type, metadata=metadata)
        return span

    def end_span(_span, *, metadata):
        span.metadata = metadata

    async def private_tool(customer_id: str) -> str:
        """Return a private result asynchronously."""
        return "private async result"

    monkeypatch.setattr(root_tracer, "start_span", start_span)
    monkeypatch.setattr(root_tracer, "end_span", end_span)
    tool_pack = ToolPack([FunctionTool("private-async-tool", private_tool)])
    result = await tool_pack.async_execute(
        resource_name="private-async-tool",
        customer_id="private-customer-id",
    )

    assert result == "private async result"
    assert started["name"] == "agent.toolpack.execute"
    assert started["metadata"] == {}
    assert span.metadata["status"] == "returned"
    span_data = repr(started) + repr(span.metadata)
    assert "private-async-tool" not in span_data
    assert "private-customer-id" not in span_data
    assert "private async result" not in span_data


def test_toolpack_missing_tool_preserves_error_and_emits_failure_span(monkeypatch):
    class _Span:
        metadata = None

    span = _Span()

    monkeypatch.setattr(
        root_tracer,
        "start_span",
        lambda _name, *, span_type, metadata: span,
    )
    monkeypatch.setattr(
        root_tracer,
        "end_span",
        lambda _span, *, metadata: setattr(span, "metadata", metadata),
    )

    with pytest.raises(ToolNotFoundException):
        ToolPack([]).execute(resource_name="private-missing-tool")

    assert span.metadata["status"] == "failed"
    assert "private-missing-tool" not in repr(span.metadata)


def test_base_tool():
    tool = TestBaseTool()
    assert tool.name == "test_tool"
    assert tool.description == "This is a test tool."
    assert tool.execute() == "executed"
    assert asyncio.run(tool.async_execute()) == "async executed"


def test_function_tool_sync() -> None:
    def two_sum(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    ft = FunctionTool(name="sample", func=two_sum)
    assert ft.execute(1, 2) == 3
    with pytest.raises(ValueError):
        asyncio.run(ft.async_execute(1, 2))


@pytest.mark.asyncio
async def test_function_tool_async() -> None:
    async def sample_async_func(a: int, b: int) -> int:
        """Add two numbers asynchronously."""
        return a + b

    ft = FunctionTool(name="sample_async", func=sample_async_func)
    with pytest.raises(ValueError):
        ft.execute(1, 2)
    assert await ft.async_execute(1, 2) == 3


@pytest.mark.asyncio
async def test_function_tool_sync_with_args() -> None:
    def two_sum(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    ft = FunctionTool(
        name="sample",
        func=two_sum,
        args={
            "a": {"type": "integer", "name": "a", "description": "The first number."},
            "b": {"type": "integer", "name": "b", "description": "The second number."},
        },
    )
    ft1 = FunctionTool(
        name="sample",
        func=two_sum,
        args={
            "a": ToolParameter(
                type="integer", name="a", description="The first number."
            ),
            "b": ToolParameter(
                type="integer", name="b", description="The second number."
            ),
        },
    )
    assert ft.description == "Add two numbers."
    assert ft.args.keys() == {"a", "b"}
    assert ft.args["a"].type == "integer"
    assert ft.args["a"].name == "a"
    assert ft.args["a"].description == "The first number."
    assert ft.args["a"].title == "A"
    dict_params = [
        {
            "name": "a",
            "type": "integer",
            "description": "The first number.",
            "required": True,
        },
        {
            "name": "b",
            "type": "integer",
            "description": "The second number.",
            "required": True,
        },
    ]
    json_params = json.dumps(dict_params, ensure_ascii=False)
    expected_prompt = (
        f"sample: Call this tool to interact with the sample API. What is the "
        f"sample API useful for? Add two numbers. Parameters: {json_params}"
    )
    pmt, info = await ft.get_prompt()
    pmt1, info1 = await ft1.get_prompt()
    assert pmt == expected_prompt
    assert pmt1 == expected_prompt
    assert ft.execute(1, 2) == 3
    with pytest.raises(ValueError):
        await ft.async_execute(1, 2)


def test_function_tool_sync_with_complex_types() -> None:
    @tool
    def complex_func(
        a: int,
        b: Annotated[int, Doc("The second number.")],
        c: Annotated[str, Doc("The third string.")],
        d: List[int],
        e: Annotated[Dict[str, int], Doc("A dictionary of integers.")],
        f: Optional[float] = None,
        g: str | None = None,
    ) -> int:
        """A complex function."""
        return (
            a + b + len(c) + sum(d) + sum(e.values()) + (f or 0) + (len(g) if g else 0)
        )

    ft: FunctionTool = complex_func._tool
    assert ft.description == "A complex function."
    assert ft.args.keys() == {"a", "b", "c", "d", "e", "f", "g"}
    assert ft.args["a"].type == "integer"
    assert ft.args["a"].description == "A"
    assert ft.args["b"].type == "Annotated"
    assert ft.args["b"].description == "The second number."
    assert ft.args["c"].type == "Annotated"
    assert ft.args["c"].description == "The third string."
    assert ft.args["d"].type == "array"
    assert ft.args["d"].description == "D"
    assert ft.args["e"].type == "object"
    assert ft.args["e"].description == "A dictionary of integers."
    assert ft.args["f"].type == "number"
    assert ft.args["f"].description == "F"
    assert ft.args["g"].type == "string"
    assert ft.args["g"].description == "G"


def test_function_tool_sync_with_args_schema() -> None:
    class ArgsSchema(BaseModel):
        a: int = Field(description="The first number.")
        b: int = Field(description="The second number.")
        c: Optional[str] = Field(None, description="The third string.")
        d: List[int] = Field(description="Numbers.")

    @tool(args_schema=ArgsSchema)
    def complex_func(a: int, b: int, c: Optional[str] = None) -> int:
        """A complex function."""
        return a + b + len(c) if c else 0

    ft: FunctionTool = complex_func._tool
    assert ft.description == "A complex function."
    assert ft.args.keys() == {"a", "b", "c", "d"}
    assert ft.args["a"].type == "integer"
    assert ft.args["a"].description == "The first number."
    assert ft.args["b"].type == "integer"
    assert ft.args["b"].description == "The second number."
    assert ft.args["c"].type == "string"
    assert ft.args["c"].description == "The third string."
    assert ft.args["d"].type == "array"
    assert ft.args["d"].description == "Numbers."


def test_tool_decorator() -> None:
    @tool(description="Add two numbers")
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    assert add(1, 2) == 3
    assert add._tool.name == "add"
    assert add._tool.description == "Add two numbers"


@pytest.mark.asyncio
async def test_tool_decorator_async() -> None:
    @tool
    async def async_add(a: int, b: int) -> int:
        """Asynchronously add two numbers."""
        return a + b

    assert await async_add(1, 2) == 3

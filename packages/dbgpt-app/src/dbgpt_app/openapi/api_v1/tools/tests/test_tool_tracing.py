import json

import pytest

from dbgpt_app.openapi.api_v1 import agentic_data_api
from dbgpt_app.openapi.api_v1.tools.execute_tool import make_execute_tool
from dbgpt_app.openapi.api_v1.tools.html_interpreter import make_html_interpreter
from dbgpt_app.openapi.api_v1.tools.kb_tools import make_kb_tools
from dbgpt_app.openapi.api_v1.tools.knowledge_retrieve import (
    make_knowledge_retrieve,
)
from dbgpt_app.openapi.api_v1.tools.load_file import make_load_file
from dbgpt_app.openapi.api_v1.tools.read_file import make_read_file
from dbgpt_app.openapi.api_v1.tools.shell_interpreter import make_shell_interpreter
from dbgpt_app.openapi.api_v1.tools.tool_tracing import root_tracer


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_factory", "state", "arguments", "expected_operation"),
    [
        (
            lambda state: make_shell_interpreter(state),
            {"conv_id": "conversation-secret"},
            {"code": ""},
            "agent.shell_interpreter",
        ),
        (
            lambda state: make_knowledge_retrieve(state, []),
            {"file_path": "/private/document.txt"},
            {"query": "private search text"},
            "agent.knowledge_retrieve",
        ),
        (
            lambda state: make_html_interpreter(state, "/private/skills"),
            {"conv_id": "conversation-secret"},
            {"html": "private report body", "title": "private report title"},
            "agent.html_interpreter",
        ),
    ],
)
async def test_builtin_tool_spans_exclude_arguments_and_results(
    monkeypatch, tool_factory, state, arguments, expected_operation
):
    class _Span:
        metadata = None

    span = _Span()
    started = {}

    def start_span(name, *, span_type, metadata):
        started.update(name=name, span_type=span_type, metadata=metadata)
        return span

    def end_span(_span, *, metadata):
        span.metadata = metadata

    monkeypatch.setattr(root_tracer, "start_span", start_span)
    monkeypatch.setattr(root_tracer, "end_span", end_span)
    tool = tool_factory(state)

    result = await tool(**arguments)

    assert started["name"] == expected_operation
    assert started["metadata"] == {}
    assert span.metadata["status"] == "returned"
    assert "elapsed_ms" in span.metadata
    span_data = repr(started) + repr(span.metadata)
    assert all(
        not isinstance(value, str) or not value or value not in span_data
        for value in arguments.values()
    )
    assert all(value not in span_data for value in state.values())
    assert "/private/document.txt" not in span_data
    assert isinstance(json.loads(result), dict)


def test_sync_file_tools_emit_spans_without_paths_or_contents(monkeypatch, tmp_path):
    spans = []

    class _Span:
        metadata = None

    def start_span(name, *, span_type, metadata):
        span = _Span()
        spans.append((name, metadata, span))
        return span

    def end_span(span, *, metadata):
        span.metadata = metadata

    monkeypatch.setattr(root_tracer, "start_span", start_span)
    monkeypatch.setattr(root_tracer, "end_span", end_span)
    load_tool = make_load_file({"file_path": "/private/customer-data.csv"})
    read_tool = make_read_file({"output_dir": str(tmp_path)})

    load_tool()
    read_tool(file_path="/private/persisted-result.txt")

    assert [item[0] for item in spans] == ["agent.load_file", "agent.read_file"]
    for _name, started_metadata, span in spans:
        assert started_metadata == {}
        assert span.metadata["status"] == "returned"
        assert "elapsed_ms" in span.metadata
    span_data = repr(
        [(name, metadata, span.metadata) for name, metadata, span in spans]
    )
    assert "/private/customer-data.csv" not in span_data
    assert "/private/persisted-result.txt" not in span_data
    assert str(tmp_path) not in span_data


@pytest.mark.asyncio
async def test_inline_skill_execution_emits_redacted_span(monkeypatch):
    class _Span:
        metadata = None

    span = _Span()
    started = {}

    def start_span(name, *, span_type, metadata):
        started.update(name=name, metadata=metadata)
        return span

    def end_span(_span, *, metadata):
        span.metadata = metadata

    async def execute_skill_script_impl(*_args):
        return "private skill output"

    monkeypatch.setattr(root_tracer, "start_span", start_span)
    monkeypatch.setattr(root_tracer, "end_span", end_span)
    monkeypatch.setattr(
        agentic_data_api, "_execute_skill_script_impl", execute_skill_script_impl
    )

    result = await agentic_data_api.execute_skill_script(
        "private skill", "private.py", {"customer": "private input"}
    )

    assert result == "private skill output"
    assert started["name"] == "agent.execute_skill_script"
    assert started["metadata"] == {}
    assert span.metadata["status"] == "returned"
    span_data = repr(started) + repr(span.metadata)
    assert "private skill" not in span_data
    assert "private.py" not in span_data
    assert "private input" not in span_data
    assert "private skill output" not in span_data


@pytest.mark.asyncio
async def test_execute_tool_emits_span_without_tool_arguments_or_result(monkeypatch):
    import importlib

    import dbgpt._private.config
    import dbgpt.agent.resource.manage

    tool_pack_module = importlib.import_module("dbgpt.agent.resource.tool.pack")

    class _Span:
        metadata = None

    class _SystemApp:
        def get_component(self, *_args, **_kwargs):
            return None

    class _Config:
        SYSTEM_APP = _SystemApp()

    class _ResourceManager:
        def build_resource_by_type(self, *_args, **_kwargs):
            return object()

    class _ToolPack:
        def __init__(self, _resources):
            pass

        async def async_execute(self, **_kwargs):
            return "private tool result"

    span = _Span()
    started = {}

    def start_span(name, *, span_type, metadata):
        started.update(name=name, metadata=metadata)
        return span

    def end_span(_span, *, metadata):
        span.metadata = metadata

    monkeypatch.setattr(root_tracer, "start_span", start_span)
    monkeypatch.setattr(root_tracer, "end_span", end_span)
    monkeypatch.setattr(dbgpt._private.config, "Config", _Config)
    monkeypatch.setattr(
        dbgpt.agent.resource.manage,
        "get_resource_manager",
        lambda _app: _ResourceManager(),
    )
    monkeypatch.setattr(tool_pack_module, "ToolPack", _ToolPack)

    result = await make_execute_tool({})(
        tool_name="private-tool-name", args={"customer": "private argument"}
    )

    assert started["name"] == "agent.execute_tool"
    assert started["metadata"] == {}
    assert span.metadata["status"] == "returned"
    span_data = repr(started) + repr(span.metadata)
    assert "private-tool-name" not in span_data
    assert "private argument" not in span_data
    assert "private tool result" not in span_data
    assert isinstance(json.loads(result), dict)


@pytest.mark.asyncio
async def test_workflow_tools_emit_redacted_spans(monkeypatch):
    import dbgpt._private.config
    import dbgpt.agent.claude_skill
    import dbgpt.agent.resource.manage
    from dbgpt_app.openapi.api_v1.tools.load_tools import make_load_tools
    from dbgpt_app.openapi.api_v1.tools.question import make_question
    from dbgpt_app.openapi.api_v1.tools.select_skill import make_select_skill
    from dbgpt_app.openapi.api_v1.tools.skill_tools import make_load_skill
    from dbgpt_app.openapi.api_v1.tools.todowrite import make_todowrite

    spans = []

    class _Span:
        metadata = None

    def start_span(name, *, span_type, metadata):
        span = _Span()
        spans.append((name, metadata, span))
        return span

    def end_span(span, *, metadata):
        span.metadata = metadata

    class _Config:
        SYSTEM_APP = object()

    class _ResourceManager:
        def build_resource_by_type(self, *_args, **_kwargs):
            raise AssertionError("no skill tools should be requested")

    class _Registry:
        def match_skill(self, _query):
            return None

        def get_skill(self, _name):
            return None

        def list_skills(self):
            return []

    monkeypatch.setattr(root_tracer, "start_span", start_span)
    monkeypatch.setattr(root_tracer, "end_span", end_span)
    monkeypatch.setattr(dbgpt._private.config, "Config", _Config)
    monkeypatch.setattr(
        dbgpt.agent.resource.manage,
        "get_resource_manager",
        lambda _app: _ResourceManager(),
    )
    monkeypatch.setattr(dbgpt.agent.claude_skill, "get_registry", lambda: _Registry())

    async def answer_question(event_name, payload):
        if event_name == "question.asked":
            from dbgpt_app.openapi.api_v1.tools.question_manager import question_manager

            question_manager.reply(payload["request_id"], [["private answer"]])

    question_tool = make_question({"conv_id": "private conversation"}, answer_question)
    await question_tool(
        questions='[{"question":"private question","header":"Question"}]'
    )
    make_select_skill({}, _Registry())(query="private request")
    make_load_skill({})(skill_name="private skill", file_path="/private/SKILL.md")
    make_load_tools({})()
    make_todowrite([], lambda *_args: None)(
        todos='[{"content":"private task","status":"pending"}]'
    )

    assert [name for name, _, _ in spans] == [
        "agent.question",
        "agent.select_skill",
        "agent.load_skill",
        "agent.load_tools",
        "agent.todowrite",
    ]
    assert all(started_metadata == {} for _, started_metadata, _ in spans)
    assert all(span.metadata["status"] == "returned" for _, _, span in spans)
    span_data = repr(
        [
            (name, started_metadata, span.metadata)
            for name, started_metadata, span in spans
        ]
    )
    for sensitive_value in (
        "private conversation",
        "private question",
        "private answer",
        "private request",
        "private skill",
        "/private/SKILL.md",
        "private task",
    ):
        assert sensitive_value not in span_data


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_index", "module_name", "function_name", "arguments", "operation"),
    [
        (
            0,
            "dbgpt_serve.rag.tools.kb_file_tools",
            "kb_ls",
            {"path": "private/directory"},
            "agent.kb_ls",
        ),
        (
            1,
            "dbgpt_serve.rag.tools.kb_file_tools",
            "kb_glob",
            {"pattern": "private*.py"},
            "agent.kb_glob",
        ),
        (
            2,
            "dbgpt_serve.rag.tools.kb_file_tools",
            "kb_grep",
            {"query": "private search text"},
            "agent.kb_grep",
        ),
        (
            3,
            "dbgpt_serve.rag.tools.kb_file_tools",
            "kb_cat",
            {"path": "private/document.md"},
            "agent.kb_cat",
        ),
        (
            4,
            "dbgpt_serve.rag.tools.semantic_search_tool",
            "kb_semantic_search",
            {"query": "private semantic query"},
            "agent.semantic_search",
        ),
        (
            5,
            "dbgpt_serve.rag.tools.codegraph_tools",
            "kb_codegraph_explore",
            {"query": "PrivateClass"},
            "agent.kb_codegraph_explore",
        ),
        (
            6,
            "dbgpt_serve.rag.tools.codegraph_tools",
            "kb_codegraph_call_chain",
            {"function_name": "private_function"},
            "agent.kb_codegraph_call_chain",
        ),
        (
            7,
            "dbgpt_serve.rag.tools.codegraph_tools",
            "kb_codegraph_class_hierarchy",
            {"class_name": "PrivateClass"},
            "agent.kb_codegraph_class_hierarchy",
        ),
    ],
)
async def test_bound_kb_tools_emit_independent_redacted_spans(
    monkeypatch, tool_index, module_name, function_name, arguments, operation
):
    import importlib

    class _Span:
        metadata = None

    span = _Span()
    started = {}

    def start_span(name, *, span_type, metadata):
        started.update(name=name, metadata=metadata)
        return span

    def end_span(_span, *, metadata):
        span.metadata = metadata

    async def fake_implementation(**_kwargs):
        return "private knowledge content"

    module = importlib.import_module(module_name)
    monkeypatch.setattr(module, function_name, fake_implementation)
    monkeypatch.setattr(root_tracer, "start_span", start_span)
    monkeypatch.setattr(root_tracer, "end_span", end_span)

    result = await make_kb_tools("private knowledge id")[tool_index](**arguments)

    assert result == "private knowledge content"
    assert started["name"] == operation
    assert started["metadata"] == {}
    assert span.metadata["status"] == "returned"
    assert "elapsed_ms" in span.metadata
    span_data = repr(started) + repr(span.metadata)
    assert all(value not in span_data for value in arguments.values())
    assert "private knowledge id" not in span_data
    assert "private knowledge content" not in span_data

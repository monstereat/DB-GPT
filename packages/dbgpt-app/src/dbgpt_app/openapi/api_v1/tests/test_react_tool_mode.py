import pytest

from dbgpt_app.openapi.api_v1.agentic_data_api import (
    _database_query_outcome,
    _resolve_react_agent_tool_mode,
)
from dbgpt_app.openapi.api_view_model import ConversationVo


def test_selected_database_uses_database_tools_without_other_context():
    dialogue = ConversationVo(
        chat_mode="chat_react_agent",
        ext_info={"database_name": "ecommerce-demo", "database_type": "sqlite"},
    )

    assert _resolve_react_agent_tool_mode(dialogue, "ecommerce-demo", None) == (
        "database"
    )


def test_database_tool_mode_preserves_explicit_database_chat_mode():
    dialogue = ConversationVo(chat_mode="chat_with_db_execute")

    assert _resolve_react_agent_tool_mode(dialogue, None, None) == "database"


@pytest.mark.parametrize(
    "context",
    [
        {"skill_id": "skill-1"},
        {"knowledge_space_id": "knowledge-1"},
        {"connector_ids": ["connector-1"]},
        {"file_ids": ["file-1"]},
        {"file_path": "/tmp/upload.csv"},
    ],
)
def test_database_selection_with_other_context_keeps_full_tool_mode(context):
    dialogue = ConversationVo(
        chat_mode="chat_react_agent",
        ext_info={"database_name": "ecommerce-demo", **context},
    )

    assert _resolve_react_agent_tool_mode(dialogue, "ecommerce-demo", None) == "full"


def test_database_selection_with_resolved_attachment_keeps_full_tool_mode():
    dialogue = ConversationVo(
        chat_mode="chat_react_agent",
        ext_info={"database_name": "ecommerce-demo"},
    )

    assert _resolve_react_agent_tool_mode(dialogue, "ecommerce-demo", object()) == (
        "full"
    )


def test_chat_without_database_keeps_full_tool_mode():
    dialogue = ConversationVo(chat_mode="chat_react_agent")

    assert _resolve_react_agent_tool_mode(dialogue, None, None) == "full"


def test_failed_database_query_is_not_treated_as_a_result():
    import json

    action_output = {
        "action": "sql_query",
        "observations": json.dumps(
            {
                "chunks": [],
                "error": {
                    "category": "schema_error",
                    "retryable": True,
                    "message": "引用了当前数据源中不可用的表或字段。",
                },
            }
        ),
    }

    assert _database_query_outcome(action_output) == (
        False,
        "引用了当前数据源中不可用的表或字段。",
    )


def test_successful_structured_sql_result_clears_prior_failure():
    import json

    action_output = {
        "action": "sql_query",
        "observations": json.dumps(
            {
                "chunks": [],
                "result": {
                    "type": "sql_result",
                    "columns": ["count"],
                    "rows": [[5]],
                    "row_count": 1,
                    "truncated": False,
                },
            }
        ),
    }

    assert _database_query_outcome(action_output) == (True, None)


def test_successful_structured_metric_result_is_verified():
    import json

    action_output = {
        "action": "metric_query",
        "observations": json.dumps(
            {
                "chunks": [{"output_type": "text", "content": "计算完成。"}],
                "result": {
                    "type": "sql_result",
                    "columns": ["sales_cents", "refund_rate_pct"],
                    "rows": [[77000, 6.1]],
                    "row_count": 1,
                    "truncated": False,
                },
            }
        ),
    }

    assert _database_query_outcome(action_output) == (True, None)


def test_successful_nested_structured_metric_result_is_verified():
    import json

    action_output = {
        "action": "metric_query",
        "observations": json.dumps(
            [
                {
                    "name": "metric_query",
                    "success": True,
                    "observation": json.dumps(
                        {
                            "result": {
                                "type": "sql_result",
                                "columns": ["sales_cents", "refund_rate_pct"],
                                "rows": [[77000, 6.1]],
                                "row_count": 1,
                                "truncated": False,
                            }
                        }
                    ),
                }
            ]
        ),
    }

    assert _database_query_outcome(action_output) == (True, None)


def test_failed_nested_metric_query_is_classified():
    import json

    action_output = {
        "action": "sql_query, metric_query",
        "observations": json.dumps(
            [
                {
                    "name": "metric_query",
                    "success": True,
                    "observation": json.dumps(
                        {
                            "chunks": [],
                            "error": {"message": "查询未能执行。"},
                        }
                    ),
                }
            ]
        ),
    }

    assert _database_query_outcome(action_output) == (False, "查询未能执行。")


def test_non_database_tool_does_not_change_query_outcome():
    assert (
        _database_query_outcome({"action": "metric_catalog", "observations": "{}"})
        is None
    )

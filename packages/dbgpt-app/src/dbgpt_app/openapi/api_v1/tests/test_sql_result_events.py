import json

import pytest

from dbgpt_app.openapi.api_v1.sql_result_events import serialize_sql_result_event


def test_serializes_bounded_sql_result_to_step_event():
    result = {
        "type": "sql_result",
        "columns": ["region", "sales"],
        "rows": [["华南", "123.45"]],
        "row_count": 1,
        "truncated": False,
        "sql": "SELECT confidential_query",
    }

    frame = serialize_sql_result_event("step-3", result)

    assert frame is not None
    assert frame.endswith("\n\n")
    assert json.loads(frame.removeprefix("data: ").strip()) == {
        "type": "step.result",
        "id": "step-3",
        "result": {
            "type": "sql_result",
            "columns": ["region", "sales"],
            "rows": [["华南", "123.45"]],
            "row_count": 1,
            "truncated": False,
        },
    }


@pytest.mark.parametrize(
    "result",
    [
        None,
        {"type": "text", "columns": [], "rows": []},
        {"type": "sql_result", "columns": ["value"], "rows": [[1, 2]]},
        {
            "type": "sql_result",
            "columns": ["value"],
            "rows": [[index] for index in range(51)],
            "row_count": 51,
            "truncated": True,
        },
        {
            "type": "sql_result",
            "columns": ["value"],
            "rows": [["x" * (128 * 1024)]],
            "row_count": 1,
            "truncated": False,
        },
    ],
)
def test_rejects_malformed_or_oversized_sql_result(result):
    assert serialize_sql_result_event("step-1", result) is None

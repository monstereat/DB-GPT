"""Small, dependency-free serializers for SQL result SSE events."""

import json
from typing import Any

_MAX_SQL_RESULT_EVENT_BYTES = 128 * 1024


def serialize_sql_result_event(step_id: str, result: Any) -> str | None:
    """Serialize one validated structured query result as a ReAct SSE frame."""
    if (
        not isinstance(result, dict)
        or result.get("type") != "sql_result"
        or not isinstance(result.get("columns"), list)
        or not all(isinstance(column, str) for column in result["columns"])
        or not isinstance(result.get("rows"), list)
        or len(result["rows"]) > 50
        or not all(
            isinstance(row, list) and len(row) == len(result["columns"])
            for row in result["rows"]
        )
        or type(result.get("row_count")) is not int
        or result["row_count"] < len(result["rows"])
        or type(result.get("truncated")) is not bool
    ):
        return None

    bounded_result = {
        "type": "sql_result",
        "columns": result["columns"],
        "rows": result["rows"],
        "row_count": result["row_count"],
        "truncated": result["truncated"],
    }
    payload = {
        "type": "step.result",
        "id": step_id,
        "result": bounded_result,
    }
    encoded = json.dumps(payload, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > _MAX_SQL_RESULT_EVENT_BYTES:
        return None
    return f"data: {encoded}\n\n"

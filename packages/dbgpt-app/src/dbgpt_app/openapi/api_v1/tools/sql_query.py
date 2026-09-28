"""sql_query tool — read-only SQL query against the selected database."""

import json
from typing import Any, Dict, Optional

from dbgpt.agent.resource.tool.base import tool
from dbgpt.datasource.sql_guard import (
    SQLQueryFailure,
    consume_sql_correction_budget,
    emit_agent_sql_audit,
    execute_read_only_query,
    reset_sql_correction_budget,
)

from ..business_context import (
    prepare_database_query,
)


def _json_safe_sql_value(value: Any) -> Any:
    """Return a value that can be carried in the bounded SQL result event."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return str(value)


def make_sql_query(react_state: Dict[str, Any], database_connector: Optional[Any]):
    @tool(
        description=(
            "对用户选择的数据库执行 SQL 查询（仅支持 SELECT）。"
            '参数: {"sql": "SELECT 语句"}'
        )
    )
    def sql_query(sql: str) -> str:
        """Execute a read-only SQL query against the selected database."""
        if database_connector is None:
            emit_agent_sql_audit(
                react_state,
                sql,
                status="not_executed",
            )
            return json.dumps(
                {
                    "chunks": [
                        {
                            "output_type": "text",
                            "content": "未选择数据库，请先在左侧面板选择一个数据源。",
                        }
                    ]
                },
                ensure_ascii=False,
            )

        audit_context = react_state
        try:
            try:
                scoped_sql, audit_context = prepare_database_query(
                    sql, react_state, database_connector
                )
            except ValueError as error:
                raise SQLQueryFailure(
                    "permission_denied", str(error), retryable=False
                ) from error

            query_result = execute_read_only_query(
                database_connector,
                scoped_sql,
                audit_context=audit_context,
                verified_execution_context=react_state.get(
                    "verified_execution_context"
                ),
            )
            reset_sql_correction_budget(react_state)
            emit_agent_sql_audit(
                audit_context,
                sql,
                status="succeeded",
                query_sha256=query_result.query_sha256,
                duration_ms=query_result.duration_ms,
                returned_rows=len(query_result.rows),
            )
            if not query_result.columns and not query_result.rows:
                return json.dumps(
                    {
                        "chunks": [
                            {"output_type": "text", "content": "查询返回空结果。"}
                        ]
                    },
                    ensure_ascii=False,
                )

            columns = query_result.columns
            col_names = [str(c[0]) if isinstance(c, tuple) else str(c) for c in columns]
            rows = query_result.rows

            header = "| " + " | ".join(col_names) + " |"
            separator = "| " + " | ".join(["---"] * len(col_names)) + " |"
            md_rows = []
            for row in rows[:50]:
                md_rows.append("| " + " | ".join(str(v) for v in row) + " |")
            table = "\n".join([header, separator] + md_rows)
            if len(rows) > 50:
                table += f"\n\n（仅显示前 50 行，共 {len(rows)} 行）"
            if query_result.row_limit_reached:
                table += "\n\n（查询达到 1,000 行安全上限，结果可能已截断。）"

            # Cap total output size so a single wide query can't blow out the
            # LLM context window. The full result remains available via the
            # ToolResultStorage persistence layer if it exceeds the threshold.
            MAX_SQL_OUTPUT_CHARS = 20_000
            if len(table) > MAX_SQL_OUTPUT_CHARS:
                table = (
                    table[:MAX_SQL_OUTPUT_CHARS]
                    + f"\n\n... [Output truncated at {MAX_SQL_OUTPUT_CHARS} chars. "
                    f"Total rows: {len(rows)}]"
                )

            structured_rows = [
                [_json_safe_sql_value(value) for value in row]
                for row in rows[:50]
            ]
            return json.dumps(
                {
                    "chunks": [{"output_type": "markdown", "content": table}],
                    "result": {
                        "type": "sql_result",
                        "columns": col_names,
                        "rows": structured_rows,
                        "row_count": len(rows),
                        "truncated": query_result.row_limit_reached
                        or len(rows) > 50,
                    },
                },
                ensure_ascii=False,
            )
        except SQLQueryFailure as error:
            emit_agent_sql_audit(
                audit_context,
                sql,
                status=(
                    "rejected"
                    if error.category
                    in {"budget_exhausted", "permission_denied", "policy_rejected"}
                    else "failed"
                ),
                category=error.category,
            )
            error_details = consume_sql_correction_budget(react_state, error)
            return json.dumps(
                {
                    "chunks": [
                        {
                            "output_type": "text",
                            "content": error_details["message"],
                        }
                    ],
                    "error": error_details,
                },
                ensure_ascii=False,
            )
        except Exception:
            emit_agent_sql_audit(
                audit_context,
                sql,
                status="failed",
                category="execution_error",
            )
            return json.dumps(
                {
                    "chunks": [
                        {
                            "output_type": "text",
                            "content": "SQL 执行失败。未自动重试，请检查数据源状态。",
                        }
                    ],
                    "error": {
                        "category": "execution_error",
                        "retryable": False,
                    },
                },
                ensure_ascii=False,
            )

    return sql_query

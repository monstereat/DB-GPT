"""Read-only SQL validation shared by Agent query tools."""

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Tuple

import sqlglot
from sqlglot import Dialect, exp
from sqlglot.errors import ErrorLevel, SqlglotError

_DIALECT_ALIASES = {
    "postgresql": "postgres",
    "sparksql": "spark",
    "mssql": "tsql",
    "maxcompute": "odps",
    "gaussdb": "postgres",
    "opengauss": "postgres",
}

_FORBIDDEN_EXPRESSIONS = (
    exp.DML,
    exp.DDL,
    exp.Command,
    exp.Transaction,
    exp.Lock,
    exp.Into,
    exp.Copy,
    exp.Pragma,
    exp.Use,
    exp.Set,
)
_FORBIDDEN_FUNCTIONS = {
    "BENCHMARK",
    "GET_LOCK",
    "LO_CLOSE",
    "LO_CREAT",
    "LO_CREATE",
    "LO_EXPORT",
    "LO_FROM_BYTEA",
    "LO_IMPORT",
    "LO_OPEN",
    "LO_PUT",
    "LO_READ",
    "LO_UNLINK",
    "LO_WRITE",
    "LOREAD",
    "LOWRITE",
    "LOAD_FILE",
    "NEXTVAL",
    "PG_ADVISORY_LOCK",
    "PG_ADVISORY_XACT_LOCK",
    "PG_CANCEL_BACKEND",
    "PG_LOG_BACKEND_MEMORY_CONTEXTS",
    "PG_LS_ARCHIVE_STATUSDIR",
    "PG_LS_DIR",
    "PG_LS_LOGDIR",
    "PG_LS_LOGICALMAPDIR",
    "PG_LS_TMPDIR",
    "PG_LS_WALDIR",
    "PG_NOTIFY",
    "PG_READ_BINARY_FILE",
    "PG_READ_FILE",
    "PG_RELOAD_CONF",
    "PG_ROTATE_LOGFILE",
    "PG_SLEEP",
    "PG_STAT_FILE",
    "PG_TERMINATE_BACKEND",
    "PG_TRY_ADVISORY_LOCK",
    "PG_TRY_ADVISORY_XACT_LOCK",
    "RELEASE_LOCK",
    "SETVAL",
    "SLEEP",
    "SET_CONFIG",
}
_SQLITE_FORBIDDEN_FUNCTIONS = {
    "EDIT",
    "FSDIR",
    "LOAD_EXTENSION",
    "LSMODE",
    "READFILE",
    "WRITEFILE",
}
_MAX_SQL_LENGTH = 10_000
_MAX_QUERY_ROWS = 1_000
_QUERY_TIMEOUT_SECONDS = 30
_TIMEOUT_DIALECTS = {"mysql", "postgresql", "sqlite"}
_SQL_CORRECTION_BUDGET_KEY = "_sql_correction_budget_remaining"
_SQL_CORRECTION_BUDGET = 1
logger = logging.getLogger(__name__)


class SQLQueryFailure(ValueError):
    """Safe, structured query failure for Agent correction decisions."""

    def __init__(self, category: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.category = category
        self.retryable = retryable

    def as_dict(self) -> dict[str, Any]:
        """Return safe fields suitable for an Agent tool response."""
        return {
            "category": self.category,
            "retryable": self.retryable,
            "message": str(self),
        }


class AgentSQLBudget:
    """Shared per-turn budget for Agent SQL calls, including parallel children."""

    def __init__(self, max_queries: int = 20, max_runtime_seconds: float = 120):
        if max_queries < 1 or max_runtime_seconds <= 0:
            raise ValueError("Agent SQL budget limits must be positive")
        self.max_queries = max_queries
        self.max_runtime_seconds = float(max_runtime_seconds)
        self._query_count = 0
        self._elapsed_seconds = 0.0
        self._reserved_seconds = 0.0
        self._lock = threading.Lock()

    def reserve_query(self, requested_timeout_seconds: float) -> float:
        """Reserve a query slot and bound it by the remaining shared time."""
        with self._lock:
            remaining = (
                self.max_runtime_seconds
                - self._elapsed_seconds
                - self._reserved_seconds
            )
            if self._query_count >= self.max_queries or remaining <= 0:
                raise SQLQueryFailure(
                    "budget_exhausted",
                    "本轮数据库查询预算已用尽；请结束任务或缩小分析范围。",
                )
            timeout = min(float(requested_timeout_seconds), remaining)
            if timeout <= 0:
                raise SQLQueryFailure(
                    "budget_exhausted",
                    "本轮数据库查询预算已用尽；请结束任务或缩小分析范围。",
                )
            self._query_count += 1
            self._reserved_seconds += timeout
            return timeout

    def record_query(self, reserved_seconds: float, elapsed_seconds: float) -> None:
        """Release the reservation and account for actual database runtime."""
        with self._lock:
            self._reserved_seconds = max(0.0, self._reserved_seconds - reserved_seconds)
            self._elapsed_seconds += max(0.0, elapsed_seconds)


@dataclass(frozen=True)
class ReadOnlyQueryResult:
    """Bounded result and execution metadata for an Agent read query."""

    columns: Tuple[Any, ...]
    rows: List[Any]
    duration_ms: int
    query_sha256: str
    row_limit_reached: bool


def sql_fingerprint(sql: Any) -> str:
    """Return a stable digest so logs can correlate SQL without its raw text."""
    if not isinstance(sql, str):
        return "invalid"
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def emit_agent_sql_audit(
    audit_context: dict[str, Any],
    sql: Any,
    *,
    status: str,
    category: str | None = None,
    query_sha256: str | None = None,
    duration_ms: int = 0,
    returned_rows: int = 0,
    operation: str = "agent.sql_query",
    dialect: str | None = None,
) -> None:
    """Log a structured Agent SQL event without retaining its SQL text."""
    if not audit_context:
        return
    event = {
        "actor_user_id": audit_context.get("actor_user_id"),
        "role": audit_context.get("role"),
        "tenant_id": audit_context.get("tenant_id"),
        "region_id": audit_context.get("region_id"),
        "data_source_id": audit_context.get("data_source_id"),
        "authorization_policy_version": audit_context.get(
            "authorization_policy_version"
        ),
        "trace_id": audit_context.get("trace_id"),
        "operation": operation,
        "dialect": dialect,
        "query_sha256": query_sha256 or sql_fingerprint(sql),
        "status": status,
        "duration_ms": duration_ms,
        "returned_rows": returned_rows,
    }
    if category:
        event["category"] = category
    logger.info(
        "agent_sql_audit %s",
        json.dumps(event, sort_keys=True, ensure_ascii=False),
    )


def _sqlglot_dialect(connector: Any) -> str:
    raw_dialect = getattr(connector, "dialect", None) or getattr(
        connector, "db_type", None
    )
    if not raw_dialect:
        raise SQLQueryFailure(
            "unsupported_dialect", "安全限制: 无法识别数据库方言，已拒绝查询。"
        )
    return _DIALECT_ALIASES.get(str(raw_dialect).lower(), str(raw_dialect).lower())


def _execution_failure(error: Exception) -> SQLQueryFailure:
    """Classify common driver failures without returning raw database errors."""
    if isinstance(error, TimeoutError):
        return SQLQueryFailure(
            "timeout", "查询超时。请缩小时间范围或简化查询后再决定是否重试。"
        )

    original = getattr(error, "orig", error)
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    if sqlstate == "42601":
        return SQLQueryFailure(
            "syntax_error",
            "SQL 语法错误。仅依据已授权 Schema 修正，建议只尝试一次。",
            retryable=True,
        )
    if sqlstate in {"42P01", "42703"}:
        return SQLQueryFailure(
            "schema_error",
            "引用了当前数据源中不可用的表或字段。仅使用已授权 Schema 修正。",
            retryable=True,
        )
    if sqlstate == "42501":
        return SQLQueryFailure(
            "permission_denied",
            "安全限制: 权限拒绝。不得通过改写权限范围绕过拒绝。",
        )
    if sqlstate == "57014":
        return SQLQueryFailure(
            "timeout", "查询被数据库取消或超时。请缩小范围后再决定是否重试。"
        )
    args = getattr(original, "args", ())
    error_code = args[0] if args and isinstance(args[0], int) else None
    if error_code == 1064:
        return SQLQueryFailure(
            "syntax_error",
            "SQL 语法错误。仅依据已授权 Schema 修正，建议只尝试一次。",
            retryable=True,
        )
    if error_code in {1054, 1146}:
        return SQLQueryFailure(
            "schema_error",
            "引用了当前数据源中不可用的表或字段。仅使用已授权 Schema 修正。",
            retryable=True,
        )
    if error_code in {1044, 1142, 1143, 1227}:
        return SQLQueryFailure(
            "permission_denied",
            "安全限制: 权限拒绝。不得通过改写权限范围绕过拒绝。",
        )
    if error_code == 3024:
        return SQLQueryFailure(
            "timeout", "数据库取消了查询。请缩小范围或优化查询，不要重复提交相同查询。"
        )

    message = str(original).lower()
    if "timed out" in message or "timeout" in message:
        return SQLQueryFailure(
            "timeout", "查询超时。请缩小时间范围或简化查询后再决定是否重试。"
        )
    if any(
        marker in message
        for marker in ("not authorized", "permission denied", " is prohibited")
    ):
        return SQLQueryFailure(
            "permission_denied",
            "安全限制: 权限拒绝。不得通过改写权限范围绕过拒绝。",
        )
    if "no such table" in message or "no such column" in message:
        return SQLQueryFailure(
            "schema_error",
            "引用了当前数据源中不可用的表或字段。仅使用已授权 Schema 修正。",
            retryable=True,
        )
    if "syntax error" in message:
        return SQLQueryFailure(
            "syntax_error",
            "SQL 语法错误。仅依据已授权 Schema 修正，建议只尝试一次。",
            retryable=True,
        )
    return SQLQueryFailure(
        "execution_error", "查询执行失败。未自动重试，请检查数据源状态。"
    )


def _has_forbidden_function(node: exp.Expression, dialect: str) -> bool:
    if isinstance(node, exp.Anonymous):
        name = node.name.upper()
        if name in _FORBIDDEN_FUNCTIONS or (
            name == "LAST_INSERT_ID" and bool(node.expressions)
        ):
            return True
        if dialect == "sqlite" and (
            name in _SQLITE_FORBIDDEN_FUNCTIONS or name.startswith("PRAGMA_")
        ):
            return True

    if dialect == "sqlite" and isinstance(node, exp.Table):
        table = node.this
        table_name = table.name.upper() if isinstance(table, exp.Identifier) else ""
        if table_name.startswith("PRAGMA_"):
            return True
    return False


def consume_sql_correction_budget(
    agent_state: dict[str, Any], failure: SQLQueryFailure
) -> dict[str, Any]:
    """Allow one syntax/schema correction in the current Agent run."""
    response = failure.as_dict()
    if not failure.retryable:
        return response

    remaining = agent_state.get(_SQL_CORRECTION_BUDGET_KEY, _SQL_CORRECTION_BUDGET)
    if type(remaining) is not int or remaining < 0:
        remaining = 0
    if remaining == 0:
        response["retryable"] = False
        response["retries_remaining"] = 0
        response["message"] = "本轮 SQL 纠错预算已用尽，不得继续重试。"
        return response

    remaining -= 1
    agent_state[_SQL_CORRECTION_BUDGET_KEY] = remaining
    response["retries_remaining"] = remaining
    return response


def reset_sql_correction_budget(agent_state: dict[str, Any]) -> None:
    """Reset the correction budget after a query succeeds."""
    agent_state[_SQL_CORRECTION_BUDGET_KEY] = _SQL_CORRECTION_BUDGET


def validate_read_only_sql(sql: str, connector: Any) -> str:
    """Return trimmed SQL if it is one read-only query; otherwise raise ValueError.

    This is a defense-in-depth syntax check. Database credentials must still be
    read-only because a SELECT can invoke database-specific side-effecting
    functions that an AST parser cannot identify generically.
    """
    if not isinstance(sql, str):
        raise SQLQueryFailure(
            "policy_rejected", "安全限制: SQL 必须是文本，仅支持单条只读查询。"
        )

    sql = sql.strip()
    if not sql:
        raise SQLQueryFailure(
            "policy_rejected", "安全限制: SQL 不能为空，仅支持单条只读查询。"
        )
    if len(sql) > _MAX_SQL_LENGTH:
        raise SQLQueryFailure("policy_rejected", "安全限制: SQL 超过长度限制。")

    dialect = _sqlglot_dialect(connector)
    try:
        Dialect.get_or_raise(dialect)
    except (ValueError, TypeError) as exc:
        raw_dialect = getattr(connector, "dialect", None) or getattr(
            connector, "db_type", "unknown"
        )
        raise SQLQueryFailure(
            "unsupported_dialect", f"安全限制: 暂不支持数据库方言 {raw_dialect}。"
        ) from exc

    try:
        statements = sqlglot.parse(sql, read=dialect, error_level=ErrorLevel.RAISE)
    except SqlglotError as exc:
        raise SQLQueryFailure(
            "syntax_error",
            "SQL 语法错误。仅依据已授权 Schema 修正，建议只尝试一次。",
            retryable=True,
        ) from exc

    if len(statements) != 1 or statements[0] is None:
        raise SQLQueryFailure("policy_rejected", "安全限制: 仅允许执行一条 SQL 查询。")

    statement = statements[0]
    if not isinstance(statement, exp.Query):
        category = (
            "permission_denied"
            if isinstance(statement, (exp.DML, exp.DDL))
            else "policy_rejected"
        )
        raise SQLQueryFailure(
            category,
            "安全限制: 权限拒绝。仅允许只读 SELECT；不得通过改写权限范围绕过拒绝。",
        )

    nodes = tuple(statement.walk())
    if any(isinstance(node, _FORBIDDEN_EXPRESSIONS) for node in nodes):
        raise SQLQueryFailure(
            "permission_denied",
            "安全限制: 权限拒绝。查询包含写入、锁定或其他禁止操作，不得绕过拒绝。",
        )
    if any(_has_forbidden_function(node, dialect) for node in nodes):
        raise SQLQueryFailure(
            "policy_rejected",
            "安全限制: 查询包含数据库/会话副作用、服务器文件访问、元数据访问"
            "或资源消耗型函数，已拒绝执行。",
        )

    return sql


def validate_editor_sql(
    sql: str, connector: Any, *, allow_writes: bool = False
) -> Tuple[str, bool]:
    """Validate one editor statement and report whether it mutates data/schema.

    Read statements use the same restrictions as Agent SQL. Optional writes are
    limited to single-table INSERT/UPDATE/DELETE and CREATE/ALTER TABLE forms;
    the caller must apply its role policy before executing them.
    """
    if not isinstance(sql, str) or not sql.strip():
        raise SQLQueryFailure("policy_rejected", "安全限制: SQL 不能为空。")
    if len(sql) > _MAX_SQL_LENGTH:
        raise SQLQueryFailure("policy_rejected", "安全限制: SQL 超过长度限制。")

    dialect = _sqlglot_dialect(connector)
    try:
        statements = sqlglot.parse(sql, read=dialect, error_level=ErrorLevel.RAISE)
    except SqlglotError as exc:
        raise SQLQueryFailure("syntax_error", "SQL 语法错误。") from exc
    if len(statements) != 1 or statements[0] is None:
        raise SQLQueryFailure("policy_rejected", "安全限制: 仅允许执行一条 SQL。")

    statement = statements[0]
    if isinstance(statement, exp.Query):
        return validate_read_only_sql(sql, connector), False

    write_types = (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Alter)
    if not allow_writes or not isinstance(statement, write_types):
        raise SQLQueryFailure(
            "permission_denied", "安全限制: 仅允许只读查询或授权的表写操作。"
        )
    if isinstance(statement, (exp.Create, exp.Alter)) and (
        str(statement.args.get("kind", "")).upper() != "TABLE"
    ):
        raise SQLQueryFailure("permission_denied", "安全限制: 仅允许表结构操作。")

    for node in statement.walk():
        if node is statement:
            continue
        if isinstance(node, _FORBIDDEN_EXPRESSIONS):
            raise SQLQueryFailure(
                "permission_denied", "安全限制: SQL 包含禁止的副作用操作。"
            )
        if _has_forbidden_function(node, dialect):
            raise SQLQueryFailure(
                "policy_rejected", "安全限制: SQL 包含禁止的扩展、元数据或副作用函数。"
            )

    return sql.strip(), True


def limit_read_only_sql(sql: str, connector: Any) -> str:
    """Validate a query and cap its top-level result size at 1,000 rows."""
    sql = validate_read_only_sql(sql, connector)
    dialect = _sqlglot_dialect(connector)
    statement = sqlglot.parse_one(sql, read=dialect, error_level=ErrorLevel.RAISE)
    current_limit = statement.args.get("limit")
    if current_limit is not None:
        expression = (
            current_limit.args.get("count")
            if isinstance(current_limit, exp.Fetch)
            else current_limit.expression
        )
        if isinstance(expression, exp.Literal) and not expression.is_string:
            try:
                requested_rows = int(expression.this)
            except (TypeError, ValueError):
                requested_rows = _MAX_QUERY_ROWS + 1
            if 0 <= requested_rows <= _MAX_QUERY_ROWS:
                return sql

    return statement.limit(_MAX_QUERY_ROWS, copy=True).sql(dialect=dialect)


def ensure_query_timeout_supported(connector: Any) -> str:
    """Fail closed unless this connector has a query_ex timeout implementation."""
    dialect = str(
        getattr(connector, "dialect", None) or getattr(connector, "db_type", "")
    ).lower()
    if dialect not in _TIMEOUT_DIALECTS:
        raise SQLQueryFailure(
            "unsupported_dialect",
            f"安全限制: 数据库方言 {dialect or 'unknown'} 暂不支持可靠查询超时。",
        )
    return dialect


def _execute_read_only_query(
    connector: Any,
    sql: str,
    *,
    timeout_seconds: float = _QUERY_TIMEOUT_SECONDS,
    verified_execution_context: dict[str, Any] | None = None,
    on_execution_elapsed: Callable[[float], None] | None = None,
) -> ReadOnlyQueryResult:
    """Execute one read query with a supported timeout and a row cap."""
    dialect = ensure_query_timeout_supported(connector)
    safe_sql = limit_read_only_sql(sql, connector)
    query_ex = getattr(connector, "query_ex", None)
    if not callable(query_ex):
        raise SQLQueryFailure(
            "unsupported_dialect", "安全限制: 数据源不支持带超时的查询执行。"
        )

    query_sha256 = sql_fingerprint(safe_sql)
    started = time.monotonic()
    try:
        query_kwargs = {"timeout": timeout_seconds}
        if dialect == "postgresql" and verified_execution_context is not None:
            query_kwargs["verified_execution_context"] = verified_execution_context
        columns, raw_rows = query_ex(safe_sql, **query_kwargs)
    except Exception as error:
        failure = _execution_failure(error)
        logger.warning(
            "Read-only query failed dialect=%s query_sha256=%s category=%s",
            dialect,
            query_sha256,
            failure.category,
        )
        raise failure from error
    finally:
        if on_execution_elapsed is not None:
            on_execution_elapsed(time.monotonic() - started)
    rows = list(raw_rows or [])
    row_limit_reached = len(rows) >= _MAX_QUERY_ROWS
    rows = rows[:_MAX_QUERY_ROWS]
    duration_ms = round((time.monotonic() - started) * 1000)
    logger.info(
        "Read-only query completed dialect=%s query_sha256=%s duration_ms=%s "
        "rows=%s row_limit_reached=%s",
        dialect,
        query_sha256,
        duration_ms,
        len(rows),
        row_limit_reached,
    )
    return ReadOnlyQueryResult(
        columns=tuple(columns or []),
        rows=rows,
        duration_ms=duration_ms,
        query_sha256=query_sha256,
        row_limit_reached=row_limit_reached,
    )


def execute_read_only_query(
    connector: Any,
    sql: str,
    *,
    timeout_seconds: float = _QUERY_TIMEOUT_SECONDS,
    audit_context: dict[str, Any] | None = None,
    verified_execution_context: dict[str, Any] | None = None,
    span_name: str = "agent.sql_query",
) -> ReadOnlyQueryResult:
    """Execute a bounded read query and trace Agent calls without SQL text."""
    started = time.monotonic()
    budget = audit_context.get("sql_execution_budget") if audit_context else None
    budget_reservation = None
    budget_recorded = False
    span = None
    metadata = None
    if audit_context is not None:
        metadata = {
            "actor_user_id": audit_context.get("actor_user_id"),
            "role": audit_context.get("role"),
            "tenant_id": audit_context.get("tenant_id"),
            "region_id": audit_context.get("region_id"),
            "data_source_id": audit_context.get("data_source_id"),
            "authorization_policy_version": audit_context.get(
                "authorization_policy_version"
            ),
            "conversation_trace_id": audit_context.get("trace_id"),
            "query_sha256": sql_fingerprint(sql),
            "dialect": getattr(connector, "dialect", None)
            or getattr(connector, "db_type", None),
        }
        try:
            from dbgpt.util.tracer import SpanType, root_tracer

            span = root_tracer.start_span(
                span_name, span_type=SpanType.AGENT, metadata=metadata
            )
        except Exception:
            logger.debug("Unable to start Agent SQL span", exc_info=True)

    def end_span(**details: Any) -> None:
        if not span or metadata is None:
            return
        try:
            span.end(metadata={**metadata, **details})
        except Exception:
            logger.debug("Unable to end Agent SQL span", exc_info=True)

    def record_execution_elapsed(elapsed_seconds: float) -> None:
        nonlocal budget_recorded
        budget.record_query(budget_reservation, elapsed_seconds)
        budget_recorded = True

    try:
        if budget is not None:
            budget_reservation = budget.reserve_query(timeout_seconds)
            timeout_seconds = budget_reservation
        result = _execute_read_only_query(
            connector,
            sql,
            timeout_seconds=timeout_seconds,
            verified_execution_context=verified_execution_context,
            on_execution_elapsed=(
                record_execution_elapsed if budget is not None else None
            ),
        )
    except SQLQueryFailure as error:
        duration_ms = round((time.monotonic() - started) * 1000)
        end_span(
            status="failed",
            category=error.category,
            duration_ms=duration_ms,
        )
        emit_agent_sql_audit(
            audit_context or {},
            sql,
            status="failed",
            category=error.category,
            duration_ms=duration_ms,
            operation=span_name,
            dialect=getattr(connector, "dialect", None)
            or getattr(connector, "db_type", None),
        )
        raise
    except Exception:
        duration_ms = round((time.monotonic() - started) * 1000)
        end_span(status="failed", category="execution_error")
        emit_agent_sql_audit(
            audit_context or {},
            sql,
            status="failed",
            category="execution_error",
            duration_ms=duration_ms,
            operation=span_name,
            dialect=getattr(connector, "dialect", None)
            or getattr(connector, "db_type", None),
        )
        raise
    finally:
        if (
            budget is not None
            and budget_reservation is not None
            and not budget_recorded
        ):
            budget.record_query(budget_reservation, 0)
    end_span(
        status="succeeded",
        query_sha256=result.query_sha256,
        duration_ms=result.duration_ms,
        returned_rows=len(result.rows),
        row_limit_reached=result.row_limit_reached,
    )
    emit_agent_sql_audit(
        audit_context or {},
        sql,
        status="succeeded",
        query_sha256=result.query_sha256,
        duration_ms=result.duration_ms,
        returned_rows=len(result.rows),
        operation=span_name,
        dialect=getattr(connector, "dialect", None)
        or getattr(connector, "db_type", None),
    )
    return result

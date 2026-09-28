import json
import logging
import re
import time
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException

from dbgpt._private.config import Config
from dbgpt.core.interface.message import OnceConversation
from dbgpt.datasource.sql_guard import (
    ensure_query_timeout_supported,
    limit_read_only_sql,
    sql_fingerprint,
    validate_editor_sql,
)
from dbgpt_app.openapi.api_v1.business_context import prepare_database_query
from dbgpt_app.openapi.api_v1.editor._chat_history.chat_hisotry_factory import (
    ChatHistory,
)
from dbgpt_app.openapi.api_v1.editor.service import EditorService
from dbgpt_app.openapi.api_v1.editor.sql_editor import (
    ChartRunData,
    DataNode,
    SqlRunData,
)
from dbgpt_app.openapi.api_view_model import Result
from dbgpt_app.openapi.editor_view_model import (
    ChartDetail,
    ChartList,
    ChatChartEditContext,
    ChatDbRounds,
    ChatSqlEditContext,
)
from dbgpt_app.scene import ChatFactory
from dbgpt_app.scene.chat_dashboard.data_loader import DashboardDataLoader
from dbgpt_serve.conversation.serve import Serve as ConversationServe
from dbgpt_serve.datasource.manages.connector_manager import ConnectorManager
from dbgpt_serve.utils.auth import (
    UserRequest,
    get_user_from_headers,
    trusted_agent_execution_context,
)

router = APIRouter()
CFG = Config()
CHAT_FACTORY = ChatFactory()

logger = logging.getLogger(__name__)


def _apply_editor_read_policy(sql: str, db_name: str, user_info: UserRequest, conn):
    """Apply operator-mapped column and row policy to editor SELECT queries."""
    authorization_context = {
        "data_source_id": db_name,
        "role": user_info.role,
        "tenant_id": user_info.tenant_id,
        "region_id": user_info.region_id,
        "actor_user_id": user_info.user_id,
        "verified_execution_context": trusted_agent_execution_context(user_info),
        "authorization_policy_version": "editor-sql-policy-v1",
    }
    return prepare_database_query(sql, authorization_context, conn)


def get_conversation_serve() -> ConversationServe:
    return ConversationServe.get_instance(CFG.SYSTEM_APP)


def get_edit_service() -> EditorService:
    return EditorService.get_instance(CFG.SYSTEM_APP)


def get_authorized_editor_connector(db_name: str, user_info: UserRequest):
    """Return a connector only when its datasource is visible to the user."""
    if not user_info or not user_info.user_id:
        raise HTTPException(status_code=401, detail="Authenticated user required")
    try:
        manager = ConnectorManager.get_instance(CFG.SYSTEM_APP)
        if not manager.get_db_list(db_name=db_name, user_id=user_info.user_id):
            raise HTTPException(
                status_code=403,
                detail="Selected database is not available to this user",
            )
        return manager.get_connector(db_name)
    except HTTPException:
        raise
    except Exception as error:
        logger.warning("Unable to resolve authorized editor datasource", exc_info=True)
        raise HTTPException(
            status_code=503, detail="Selected database is unavailable"
        ) from error


def authorize_editor_conversation(
    conv_uid: str, user_info: UserRequest, editor_service: EditorService
):
    """Load a conversation only when it belongs to the authenticated user."""
    if not user_info or not user_info.user_id:
        raise HTTPException(status_code=401, detail="Authenticated user required")
    if not conv_uid:
        raise HTTPException(status_code=400, detail="Conversation ID required")
    try:
        conversation = editor_service.get_storage_conv(conv_uid)
    except Exception as error:
        raise HTTPException(status_code=404, detail="Conversation not found") from error
    if (
        user_info.role != "admin"
        and getattr(conversation, "user_name", None) != user_info.user_id
    ):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def _log_editor_sql_audit(
    actor_user_id: Optional[str],
    db_name: Optional[str],
    sql: object,
    *,
    status: str,
    trace_id: str,
    conversation_id: Optional[str] = None,
    duration_ms: int = 0,
    returned_rows: int = 0,
    category: Optional[str] = None,
    user_info: Optional[UserRequest] = None,
    connector=None,
    started_at: Optional[float] = None,
) -> None:
    if duration_ms == 0 and started_at is not None:
        duration_ms = round((time.monotonic() - started_at) * 1000)
    event = {
        "actor_user_id": actor_user_id,
        "role": getattr(user_info, "role", None),
        "tenant_id": getattr(user_info, "tenant_id", None),
        "region_id": getattr(user_info, "region_id", None),
        "data_source_id": db_name,
        "dialect": getattr(connector, "dialect", None)
        or getattr(connector, "db_type", None),
        "authorization_policy_version": "editor-sql-policy-v1",
        "trace_id": trace_id,
        "conversation_id": conversation_id,
        "query_sha256": sql_fingerprint(sql),
        "status": status,
        "duration_ms": duration_ms,
        "returned_rows": returned_rows,
    }
    if category:
        event["category"] = category
    logger.info(
        "editor_sql_audit %s",
        json.dumps(event, sort_keys=True, ensure_ascii=False),
    )


def _execute_editor_sql(
    connector,
    sql: str,
    params: dict,
    *,
    operation_name: str,
    actor_user_id: str,
    user_info: UserRequest,
    db_name: str,
    trace_id: str,
    conversation_id: Optional[str],
    audit_sql: Optional[str] = None,
    authorization_policy_version: str = "editor-sql-policy-v1",
    verified_execution_context: Optional[Dict] = None,
):
    metadata = {
        "actor_user_id": actor_user_id,
        "role": user_info.role,
        "tenant_id": user_info.tenant_id,
        "region_id": user_info.region_id,
        "data_source_id": db_name,
        "authorization_policy_version": authorization_policy_version,
        "trace_id": trace_id,
        "conversation_id": conversation_id,
        "query_sha256": sql_fingerprint(audit_sql if audit_sql is not None else sql),
        "dialect": getattr(connector, "dialect", None)
        or getattr(connector, "db_type", None),
    }
    span = None
    try:
        from dbgpt.util.tracer import SpanType, root_tracer

        span = root_tracer.start_span(
            operation_name, span_type=SpanType.AGENT, metadata=metadata
        )
    except Exception:
        logger.debug("Unable to start editor SQL span", exc_info=True)

    started = time.monotonic()
    try:
        query_kwargs = {"params": params, "timeout": 30}
        dialect = str(metadata["dialect"] or "").lower()
        if dialect in {"postgresql", "postgres", "gaussdb", "opengauss"}:
            query_kwargs["verified_execution_context"] = verified_execution_context
        columns, rows = connector.query_ex(sql, **query_kwargs)
    except Exception as error:
        if span:
            try:
                span.end(
                    metadata={
                        **metadata,
                        "status": "failed",
                        "category": type(error).__name__,
                        "duration_ms": round((time.monotonic() - started) * 1000),
                    }
                )
            except Exception:
                logger.debug("Unable to end editor SQL span", exc_info=True)
        raise

    duration_ms = round((time.monotonic() - started) * 1000)
    if span:
        try:
            span.end(
                metadata={
                    **metadata,
                    "status": "succeeded",
                    "duration_ms": duration_ms,
                    "returned_rows": len(rows),
                }
            )
        except Exception:
            logger.debug("Unable to end editor SQL span", exc_info=True)
    return columns, rows, duration_ms


def resolve_editor_db_name(
    run_param: dict, editor_service: Optional[EditorService] = None
) -> Optional[str]:
    """Return a non-empty database name from the request or conversation."""
    db_name = run_param.get("db_name")
    if isinstance(db_name, str):
        db_name = db_name.strip()
    if db_name:
        return db_name

    conv_uid = run_param.get("conv_uid") or run_param.get("con_uid")
    if not conv_uid or editor_service is None:
        return None
    try:
        storage_conv = editor_service.get_storage_conv(str(conv_uid))
        value = (getattr(storage_conv, "param_value", None) or "").strip()
        if value:
            return value
        for message in getattr(storage_conv, "messages", []) or []:
            extra = getattr(message, "additional_kwargs", None) or {}
            value = (extra.get("param_value") or "").strip()
            if value:
                return value
    except Exception:
        logger.warning(
            "Failed to recover db_name from conversation %s", conv_uid, exc_info=True
        )
    return None


@router.get("/v1/editor/db/tables", response_model=Result[DataNode])
async def get_editor_tables(
    db_name: str,
    page_index: int,
    page_size: int,
    search_str: str = "",
    user_info: UserRequest = Depends(get_user_from_headers),
):
    logger.info(f"get_editor_tables:{db_name},{page_index},{page_size},{search_str}")
    db_conn = get_authorized_editor_connector(db_name, user_info)
    tables = db_conn.get_table_names()
    db_node: DataNode = DataNode(title=db_name, key=db_name, type="db")
    for table in tables:
        table_node: DataNode = DataNode(title=table, key=table, type="table")
        db_node.children.append(table_node)
        fields = db_conn.get_fields(table, db_name)
        for field in fields:
            table_node.children.append(
                DataNode(
                    title=field[0],
                    key=field[0],
                    type=field[1],
                    default_value=field[2],
                    can_null=field[3] or "YES",
                    comment=str(field[-1]),
                )
            )

    return Result.succ(db_node)


@router.get("/v1/editor/sql/rounds", response_model=Result[List[ChatDbRounds]])
async def get_editor_sql_rounds(
    con_uid: str,
    editor_service: EditorService = Depends(get_edit_service),
    user_info: UserRequest = Depends(get_user_from_headers),
):
    logger.info("get_editor_sql_rounds:{con_uid}")
    try:
        authorize_editor_conversation(con_uid, user_info, editor_service)
        chat_rounds = editor_service.get_editor_sql_rounds(con_uid)
        return Result.succ(data=chat_rounds)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get editor sql rounds failed!")
        return Result.failed(msg=str(e))


@router.get("/v1/editor/sql", response_model=Result[List[Dict]])
async def get_editor_sql(
    con_uid: str,
    round: int,
    editor_service: EditorService = Depends(get_edit_service),
    user_info: UserRequest = Depends(get_user_from_headers),
):
    logger.info(f"get_editor_sql:{con_uid},{round}")
    authorize_editor_conversation(con_uid, user_info, editor_service)
    context = editor_service.get_editor_sql_by_round(con_uid, round)
    if context:
        return Result.succ(context)
    return Result.failed(msg="not have sql!")


def sanitize_sql(sql: str, db_type: str = None) -> Tuple[bool, str, dict]:
    """Simple SQL sanitizer to prevent injection.

    Returns:
        Tuple of (is_safe, reason, params)
    """
    # Normalize SQL (remove comments and excess whitespace)
    sql = re.sub(r"/\*.*?\*/", " ", sql)
    sql = re.sub(r"--.*?$", " ", sql, flags=re.MULTILINE)
    sql = re.sub(r"\s+", " ", sql).strip()

    # Block multiple statements
    if re.search(r";\s*(?!--|\*/|$)", sql):
        return False, "Multiple SQL statements are not allowed", {}

    # Block dangerous operations for all databases
    dangerous_patterns = [
        r"(?i)INTO\s+(?:OUT|DUMP)FILE",
        r"(?i)LOAD\s+DATA",
        r"(?i)SYSTEM",
        r"(?i)EXEC\s+",
        r"(?i)SHELL\b",
        r"(?i)DROP\s+DATABASE",
        r"(?i)DROP\s+USER",
        r"(?i)GRANT\s+",
        r"(?i)REVOKE\s+",
        r"(?i)ALTER\s+(USER|DATABASE)",
    ]

    # Add DuckDB specific patterns
    if db_type == "duckdb":
        dangerous_patterns.extend(
            [
                r"(?i)COPY\b",
                r"(?i)EXPORT\b",
                r"(?i)IMPORT\b",
                r"(?i)INSTALL\b",
                r"(?i)READ_\w+\b",
                r"(?i)WRITE_\w+\b",
                r"(?i)\.EXECUTE\(",
                r"(?i)PRAGMA\b",
            ]
        )

    for pattern in dangerous_patterns:
        if re.search(pattern, sql):
            return False, f"Operation not allowed: {pattern}", {}

    # Allow SELECT, CREATE TABLE, INSERT, UPDATE, and DELETE operations
    # We're no longer restricting to read-only operations
    allowed_operations = re.match(
        r"(?i)^\s*(SELECT|CREATE\s+TABLE|INSERT\s+INTO|UPDATE|DELETE\s+FROM|ALTER\s+TABLE)\b",
        sql,
    )
    if not allowed_operations:
        return (
            False,
            "Operation not supported. Only SELECT, CREATE TABLE, INSERT, UPDATE, "
            "DELETE and ALTER TABLE operations are allowed",
            {},
        )

    # Extract parameters (simplified)
    params = {}
    param_count = 0

    # Extract string literals
    def replace_string(match):
        nonlocal param_count
        param_name = f"param_{param_count}"
        params[param_name] = match.group(1)
        param_count += 1
        return f":{param_name}"

    # Replace string literals with parameters
    parameterized_sql = re.sub(r"'([^']*)'", replace_string, sql)

    return True, parameterized_sql, params


@router.post("/v1/editor/sql/run", response_model=Result[SqlRunData])
async def editor_sql_run(
    run_param: dict = Body(),
    editor_service: EditorService = Depends(get_edit_service),
    user_info: UserRequest = Depends(get_user_from_headers),
):
    started_at = time.monotonic()
    conv_uid = run_param.get("conv_uid") or run_param.get("con_uid")
    trace_id = uuid4().hex
    if conv_uid:
        authorize_editor_conversation(str(conv_uid), user_info, editor_service)
    db_name = resolve_editor_db_name(run_param, editor_service)
    sql = run_param.get("sql")
    submitted_sql = sql
    audit_connector = None
    logger.info(
        "editor_sql_run db_name=%s sql_sha256=%s", db_name, sql_fingerprint(sql)
    )

    if not db_name or not sql:
        _log_editor_sql_audit(
            user_info.user_id,
            db_name,
            submitted_sql,
            status="rejected",
            trace_id=trace_id,
            conversation_id=str(conv_uid) if conv_uid else None,
            category="invalid_input",
            user_info=user_info,
            connector=audit_connector,
            started_at=started_at,
        )
        return Result.failed(msg="SQL run param error: db_name and sql are required")

    try:
        conn = get_authorized_editor_connector(db_name, user_info)
        audit_connector = conn
    except HTTPException as error:
        _log_editor_sql_audit(
            user_info.user_id,
            db_name,
            submitted_sql,
            status="rejected",
            trace_id=trace_id,
            conversation_id=str(conv_uid) if conv_uid else None,
            category="datasource_visibility",
            user_info=user_info,
            connector=audit_connector,
            started_at=started_at,
        )
        raise error
    db_type = getattr(conn, "db_type", "").lower()

    try:
        sql, is_write = validate_editor_sql(sql, conn)
        ensure_query_timeout_supported(conn)
        authorization_policy_version = "editor-sql-policy-v1"
        if not is_write:
            sql, audit_context = _apply_editor_read_policy(
                sql, db_name, user_info, conn
            )
            authorization_policy_version = audit_context.get(
                "authorization_policy_version", authorization_policy_version
            )
            sql = limit_read_only_sql(sql, conn)
    except ValueError as error:
        _log_editor_sql_audit(
            user_info.user_id,
            db_name,
            submitted_sql,
            status="rejected",
            trace_id=trace_id,
            conversation_id=str(conv_uid) if conv_uid else None,
            category="sql_policy",
            user_info=user_info,
            connector=audit_connector,
            started_at=started_at,
        )
        return Result.failed(msg=str(error))

    verified_execution_context = trusted_agent_execution_context(user_info)

    # Sanitize and parameterize the SQL query
    is_safe, result, params = sanitize_sql(sql, db_type)
    if not is_safe:
        logger.warning("Blocked dangerous SQL query_sha256=%s", sql_fingerprint(sql))
        _log_editor_sql_audit(
            user_info.user_id,
            db_name,
            submitted_sql,
            status="rejected",
            trace_id=trace_id,
            conversation_id=str(conv_uid) if conv_uid else None,
            category="sql_policy",
            user_info=user_info,
            connector=audit_connector,
            started_at=started_at,
        )
        return Result.failed(msg=f"Operation not allowed: {result}")

    try:
        # Use the parameterized query and parameters
        colunms, sql_result, duration_ms = _execute_editor_sql(
            conn,
            result,
            params,
            operation_name="editor.sql_execution",
            actor_user_id=user_info.user_id,
            user_info=user_info,
            db_name=db_name,
            trace_id=trace_id,
            conversation_id=str(conv_uid) if conv_uid else None,
            audit_sql=submitted_sql,
            verified_execution_context=verified_execution_context,
            authorization_policy_version=authorization_policy_version,
        )
        # Convert result type safely
        sql_result = [
            tuple(str(x) if x is not None else None for x in row) for row in sql_result
        ]
        sql_run_data: SqlRunData = SqlRunData(
            result_info="",
            run_cost=duration_ms / 1000,
            colunms=colunms,
            values=sql_result,
        )
        _log_editor_sql_audit(
            user_info.user_id,
            db_name,
            submitted_sql,
            status="success",
            trace_id=trace_id,
            conversation_id=str(conv_uid) if conv_uid else None,
            duration_ms=duration_ms,
            returned_rows=len(sql_result),
            user_info=user_info,
            connector=audit_connector,
            started_at=started_at,
        )
        return Result.succ(sql_run_data)
    except Exception as e:
        logger.error("editor_sql_run failed (%s)", type(e).__name__)
        _log_editor_sql_audit(
            user_info.user_id,
            db_name,
            submitted_sql,
            status="failed",
            trace_id=trace_id,
            conversation_id=str(conv_uid) if conv_uid else None,
            category=type(e).__name__,
            user_info=user_info,
            connector=audit_connector,
            started_at=started_at,
        )
        return Result.succ(
            SqlRunData(
                result_info="SQL execution failed.",
                run_cost=0,
                colunms=[],
                values=[],
            )
        )


@router.post("/v1/sql/editor/submit")
async def sql_editor_submit(
    sql_edit_context: ChatSqlEditContext = Body(),
    editor_service: EditorService = Depends(get_edit_service),
    user_info: UserRequest = Depends(get_user_from_headers),
):
    authorize_editor_conversation(sql_edit_context.conv_uid, user_info, editor_service)
    logger.info(
        "sql_editor_submit db_name=%s conv_uid=%s old_sql_sha256=%s new_sql_sha256=%s",
        sql_edit_context.db_name,
        sql_edit_context.conv_uid,
        sql_fingerprint(sql_edit_context.old_sql),
        sql_fingerprint(sql_edit_context.new_sql),
    )

    conn = get_authorized_editor_connector(sql_edit_context.db_name, user_info)
    try:
        editor_service.sql_editor_submit_and_save(sql_edit_context, conn)
        return Result.succ(None)
    except Exception as e:
        logger.error("SQL editor submit failed (%s)", type(e).__name__)
        return Result.failed(msg=f"Edit sql exception!{str(e)}")


@router.get("/v1/editor/chart/list", response_model=Result[ChartList])
async def get_editor_chart_list(
    con_uid: str,
    editor_service: EditorService = Depends(get_edit_service),
    user_info: UserRequest = Depends(get_user_from_headers),
):
    logger.info(
        f"get_editor_sql_rounds:{con_uid}",
    )
    authorize_editor_conversation(con_uid, user_info, editor_service)
    chart_list = editor_service.get_editor_chart_list(con_uid)
    if chart_list:
        return Result.succ(chart_list)
    return Result.failed(msg="Not have charts!")


@router.post("/v1/editor/chart/info", response_model=Result[ChartDetail])
async def get_editor_chart_info(
    param: dict = Body(),
    editor_service: EditorService = Depends(get_edit_service),
    user_info: UserRequest = Depends(get_user_from_headers),
):
    conv_uid = param["con_uid"]
    chart_title = param["chart_title"]
    logger.info(
        "get_editor_chart_info conv_uid=%s chart_title=%s", conv_uid, chart_title
    )
    trace_id = uuid4().hex
    authorize_editor_conversation(conv_uid, user_info, editor_service)
    db_name = resolve_editor_db_name({"conv_uid": conv_uid}, editor_service)
    if db_name:
        get_authorized_editor_connector(db_name, user_info)
    return editor_service.get_editor_chart_info(
        conv_uid,
        chart_title,
        CFG,
        audit_context={
            "actor_user_id": user_info.user_id,
            "data_source_id": db_name,
            "role": user_info.role,
            "tenant_id": user_info.tenant_id,
            "region_id": user_info.region_id,
            "authorization_policy_version": "editor-sql-policy-v1",
            "trace_id": trace_id,
            "conversation_id": conv_uid,
        },
        verified_execution_context=trusted_agent_execution_context(user_info),
    )


@router.post("/v1/editor/chart/run", response_model=Result[ChartRunData])
async def chart_run(
    run_param: dict = Body(),
    editor_service: EditorService = Depends(get_edit_service),
    user_info: UserRequest = Depends(get_user_from_headers),
):
    started_at = time.monotonic()
    conv_uid = run_param.get("conv_uid") or run_param.get("con_uid")
    trace_id = uuid4().hex
    if conv_uid:
        authorize_editor_conversation(str(conv_uid), user_info, editor_service)
    db_name = resolve_editor_db_name(run_param, editor_service)
    sql = run_param.get("sql")
    submitted_sql = sql
    audit_connector = None
    chart_type = run_param.get("chart_type")
    logger.info(
        "chart_run db_name=%s chart_type=%s sql_sha256=%s",
        db_name,
        chart_type,
        sql_fingerprint(sql),
    )

    if not db_name or not sql:
        _log_editor_sql_audit(
            user_info.user_id,
            db_name,
            sql,
            status="rejected",
            trace_id=trace_id,
            conversation_id=str(conv_uid) if conv_uid else None,
            category="invalid_input",
            user_info=user_info,
            connector=audit_connector,
            started_at=started_at,
        )
        return Result.failed(msg="SQL run param error: db_name and sql are required")

    try:
        db_conn = get_authorized_editor_connector(db_name, user_info)
        audit_connector = db_conn
    except HTTPException as error:
        _log_editor_sql_audit(
            user_info.user_id,
            db_name,
            sql,
            status="rejected",
            trace_id=trace_id,
            conversation_id=str(conv_uid) if conv_uid else None,
            category="datasource_visibility",
            user_info=user_info,
            connector=audit_connector,
            started_at=started_at,
        )
        raise error
    db_type = getattr(db_conn, "db_type", "").lower()

    try:
        ensure_query_timeout_supported(db_conn)
        sql = limit_read_only_sql(sql, db_conn)
        sql, audit_context = _apply_editor_read_policy(sql, db_name, user_info, db_conn)
        authorization_policy_version = audit_context.get(
            "authorization_policy_version", "editor-sql-policy-v1"
        )
    except ValueError as e:
        _log_editor_sql_audit(
            user_info.user_id,
            db_name,
            submitted_sql,
            status="rejected",
            trace_id=trace_id,
            conversation_id=str(conv_uid) if conv_uid else None,
            category="sql_policy",
            user_info=user_info,
            connector=audit_connector,
            started_at=started_at,
        )
        if isinstance(e, ValueError):
            return Result.failed(msg=str(e))
        return Result.failed(msg="Chart query failed.")

    # Sanitize and parameterize the SQL query
    is_safe, result, params = sanitize_sql(sql, db_type)
    if not is_safe:
        logger.warning("Blocked dangerous SQL query_sha256=%s", sql_fingerprint(sql))
        _log_editor_sql_audit(
            user_info.user_id,
            db_name,
            submitted_sql,
            status="rejected",
            trace_id=trace_id,
            conversation_id=str(conv_uid) if conv_uid else None,
            category="sql_policy",
            user_info=user_info,
            connector=audit_connector,
            started_at=started_at,
        )
        return Result.failed(msg=f"Operation not allowed: {result}")

    try:
        # Use the parameterized query and parameters
        colunms, sql_result, duration_ms = _execute_editor_sql(
            db_conn,
            result,
            params,
            operation_name="editor.chart_query",
            actor_user_id=user_info.user_id,
            user_info=user_info,
            db_name=db_name,
            trace_id=trace_id,
            conversation_id=str(conv_uid) if conv_uid else None,
            audit_sql=submitted_sql,
            authorization_policy_version=authorization_policy_version,
            verified_execution_context=trusted_agent_execution_context(user_info),
        )
        # Convert result type safely
        sql_result = [
            tuple(str(x) if x is not None else None for x in row) for row in sql_result
        ]
        sql_run_data: SqlRunData = SqlRunData(
            result_info="",
            run_cost=duration_ms / 1000,
            colunms=colunms,
            values=sql_result,
        )

        chart_values = []
        for i in range(len(sql_result)):
            row = sql_result[i]
            chart_values.append(
                {
                    "name": row[0],
                    "type": "value",
                    "value": row[1] if len(row) > 1 else "0",
                }
            )

        chart_data: ChartRunData = ChartRunData(
            sql_data=sql_run_data, chart_values=chart_values, chart_type=chart_type
        )
        _log_editor_sql_audit(
            user_info.user_id,
            db_name,
            submitted_sql,
            status="success",
            trace_id=trace_id,
            conversation_id=str(conv_uid) if conv_uid else None,
            duration_ms=duration_ms,
            returned_rows=len(sql_result),
            user_info=user_info,
            connector=audit_connector,
            started_at=started_at,
        )
        return Result.succ(chart_data)
    except Exception as e:
        logger.error("chart_run failed (%s)", type(e).__name__)
        _log_editor_sql_audit(
            user_info.user_id,
            db_name,
            submitted_sql,
            status="failed",
            trace_id=trace_id,
            conversation_id=str(conv_uid) if conv_uid else None,
            category=type(e).__name__,
            user_info=user_info,
            connector=audit_connector,
            started_at=started_at,
        )
        if isinstance(e, ValueError):
            return Result.failed(msg=str(e))
        return Result.failed(msg="Chart query failed.")


@router.post("/v1/chart/editor/submit", response_model=Result[bool])
async def chart_editor_submit(
    chart_edit_context: ChatChartEditContext = Body(),
    editor_service: EditorService = Depends(get_edit_service),
    user_info: UserRequest = Depends(get_user_from_headers),
):
    started_at = time.monotonic()
    trace_id = uuid4().hex
    authorize_editor_conversation(
        chart_edit_context.conv_uid, user_info, editor_service
    )
    logger.info(
        "chart_editor_submit db_name=%s conv_uid=%s old_sql_sha256=%s "
        "new_sql_sha256=%s",
        chart_edit_context.db_name,
        chart_edit_context.conv_uid,
        sql_fingerprint(chart_edit_context.old_sql),
        sql_fingerprint(chart_edit_context.new_sql),
    )

    chat_history_fac = ChatHistory()
    history_mem = chat_history_fac.get_store_instance(chart_edit_context.conv_uid)
    history_messages: List[OnceConversation] = history_mem.get_messages()
    if history_messages:
        dashboard_data_loader: DashboardDataLoader = DashboardDataLoader()
        db_conn = get_authorized_editor_connector(chart_edit_context.db_name, user_info)

        edit_round = max(history_messages, key=lambda x: x["chat_order"])
        if edit_round:
            try:
                for element in edit_round["messages"]:
                    if element["type"] == "view":
                        view_data: dict = json.loads(element["data"]["content"])
                        charts: List = view_data.get("charts")
                        find_chart = list(
                            filter(
                                lambda x: (
                                    x["chart_name"] == chart_edit_context.chart_title
                                ),
                                charts,
                            )
                        )[0]
                        if chart_edit_context.new_chart_type:
                            find_chart["chart_type"] = chart_edit_context.new_chart_type
                        if chart_edit_context.new_comment:
                            find_chart["chart_desc"] = chart_edit_context.new_comment

                        scoped_sql, audit_context = _apply_editor_read_policy(
                            chart_edit_context.new_sql,
                            chart_edit_context.db_name,
                            user_info,
                            db_conn,
                        )
                        audit_context = {
                            **audit_context,
                            "trace_id": trace_id,
                            "conversation_id": chart_edit_context.conv_uid,
                        }
                        (
                            field_names,
                            chart_values,
                        ) = dashboard_data_loader.get_chart_values_by_conn(
                            db_conn,
                            scoped_sql,
                            audit_context=audit_context,
                            verified_execution_context=trusted_agent_execution_context(
                                user_info
                            ),
                            span_name="editor.chart_edit_validation",
                        )
                        find_chart["chart_sql"] = chart_edit_context.new_sql
                        find_chart["values"] = [value.dict() for value in chart_values]
                        find_chart["column_name"] = field_names

                        element["data"]["content"] = json.dumps(
                            view_data, ensure_ascii=False
                        )
                    if element["type"] == "ai":
                        ai_resp: dict = json.loads(element["data"]["content"])
                        edit_item = list(
                            filter(
                                lambda x: x["title"] == chart_edit_context.chart_title,
                                ai_resp,
                            )
                        )[0]

                        edit_item["sql"] = chart_edit_context.new_sql
                        edit_item["showcase"] = chart_edit_context.new_chart_type
                        edit_item["thoughts"] = chart_edit_context.new_comment
                        element["data"]["content"] = json.dumps(
                            ai_resp, ensure_ascii=False
                        )
            except Exception as error:
                logger.error("Chart editor submit failed (%s)", type(error).__name__)
                _log_editor_sql_audit(
                    user_info.user_id,
                    chart_edit_context.db_name,
                    chart_edit_context.new_sql,
                    status="failed",
                    trace_id=trace_id,
                    conversation_id=chart_edit_context.conv_uid,
                    category=type(error).__name__,
                    user_info=user_info,
                    connector=db_conn,
                    started_at=started_at,
                )
                return Result.failed(msg="Chart edit validation failed.")
            history_mem.update(history_messages)
            return Result.succ(None)
    return Result.failed(msg="Edit Failed!")

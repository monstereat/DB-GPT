"""Fail-closed, SQLite-only SQL execution example for DB-GPT data agents.

This module is deliberately independent of the DB-GPT execution pipeline.
Call GuardedSQLiteQuery.run AFTER the model generates SQL and BEFORE showing
results. All authorization inputs must come from server-side business policy,
never from the LLM or request body.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import quote


class QueryRejected(ValueError):
    """Unsafe query, forbidden table/column, or violated execution budget."""


_ALLOWED_FUNCTIONS = frozenset(
    {
        "abs", "avg", "coalesce", "count", "date", "datetime", "ifnull",
        "length", "lower", "max", "min", "round", "strftime", "substr",
        "sum", "total", "upper",
    }
)

AuditSink = Callable[[dict[str, Any]], None]


class GuardedSQLiteQuery:
    def __init__(
        self,
        database_path: str | Path,
        allowed_tables: set[str] | frozenset[str],
        *,
        allowed_columns: Mapping[str, set[str] | frozenset[str]] | None = None,
        max_rows: int = 100,
        timeout_ms: int = 2000,
        audit_sink: AuditSink | None = None,
    ):
        if not allowed_tables or not all(isinstance(table, str) and table for table in allowed_tables):
            raise ValueError("A nonempty server-owned table allowlist is required")
        if not (1 <= max_rows <= 1000):
            raise ValueError("max_rows must be between 1 and 1000")
        if not (100 <= timeout_ms <= 30000):
            raise ValueError("timeout_ms must be between 100 and 30000")
        self.database_path = Path(database_path).resolve(strict=True)
        self.allowed_tables = frozenset(allowed_tables)
        self.allowed_columns = {
            table: frozenset(columns)
            for table, columns in (allowed_columns or {}).items()
        }
        unknown_tables = set(self.allowed_columns) - self.allowed_tables
        if unknown_tables:
            raise ValueError("Column policy references tables outside the table allowlist")
        if any(not columns for columns in self.allowed_columns.values()):
            raise ValueError("Column allowlists must be nonempty")
        self.max_rows = max_rows
        self.timeout_ms = timeout_ms
        self.audit_sink = audit_sink

    def _emit_audit(
        self,
        *,
        sql: str,
        status: str,
        duration_ms: int,
        returned_rows: int = 0,
        reason: str | None = None,
    ) -> None:
        if self.audit_sink is None:
            return
        event = {
            "query_sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
            "status": status,
            "duration_ms": duration_ms,
            "returned_rows": returned_rows,
            "allowed_tables": sorted(self.allowed_tables),
        }
        if reason:
            event["reason"] = reason
        try:
            self.audit_sink(event)
        except Exception:
            # Observability must never turn a safe query into an unsafe fallback.
            pass

    def run(self, sql: str) -> dict[str, Any]:
        started = time.monotonic()
        if not isinstance(sql, str) or not re.match(r"^\s*(select|with)\b", sql, re.I):
            self._emit_audit(sql=str(sql), status="rejected", duration_ms=0, reason="statement_type")
            raise QueryRejected("Only SELECT queries and read-only CTEs are permitted")

        # SQLite execute() rejects multiple statements. Wrapping the generated SQL
        # lets the server enforce its own LIMIT even if the model supplied another one.
        stripped_sql = sql.strip().rstrip(";")
        query = f"SELECT * FROM ({stripped_sql}) LIMIT ?"
        uri_path = quote(str(self.database_path), safe="/")
        db_uri = f"file:{uri_path}?mode=ro"
        deadline = time.monotonic() + self.timeout_ms / 1000

        try:
            with sqlite3.connect(db_uri, uri=True) as conn:
                conn.execute("PRAGMA query_only = ON")
                conn.execute("PRAGMA trusted_schema = OFF")

                def authorize(
                    action: int,
                    arg1: str | None,
                    arg2: str | None,
                    _db: str | None,
                    _trigger: str | None,
                ) -> int:
                    if action == sqlite3.SQLITE_READ:
                        if arg1 not in self.allowed_tables:
                            return sqlite3.SQLITE_DENY
                        columns = self.allowed_columns.get(arg1)
                        # arg2 is the column name for SQLITE_READ.
                        if columns is not None and arg2 not in columns:
                            return sqlite3.SQLITE_DENY
                        return sqlite3.SQLITE_OK
                    if action == sqlite3.SQLITE_SELECT:
                        return sqlite3.SQLITE_OK
                    if action == sqlite3.SQLITE_FUNCTION:
                        return (
                            sqlite3.SQLITE_OK
                            if (arg2 or "").lower() in _ALLOWED_FUNCTIONS
                            else sqlite3.SQLITE_DENY
                        )
                    return sqlite3.SQLITE_DENY

                conn.set_authorizer(authorize)
                conn.set_progress_handler(
                    lambda: 1 if time.monotonic() >= deadline else 0,
                    1000,
                )
                try:
                    cursor = conn.execute(query, (self.max_rows,))
                    columns = [col[0] for col in cursor.description or ()]
                    rows = cursor.fetchmany(self.max_rows)
                finally:
                    conn.set_authorizer(None)
                    conn.set_progress_handler(None, 0)
        except sqlite3.Error as error:
            duration_ms = int((time.monotonic() - started) * 1000)
            self._emit_audit(
                sql=sql,
                status="rejected",
                duration_ms=duration_ms,
                reason="sqlite_authorizer_or_budget",
            )
            # Database errors can include schema/data. Do not expose them to an LLM-facing API.
            raise QueryRejected("SQL rejected, unauthorized, or exceeded its budget") from error

        duration_ms = int((time.monotonic() - started) * 1000)
        result = {
            "columns": columns,
            "rows": [list(row) for row in rows],
            "returned_rows": len(rows),
            "duration_ms": duration_ms,
        }
        self._emit_audit(
            sql=sql,
            status="succeeded",
            duration_ms=duration_ms,
            returned_rows=len(rows),
        )
        return result

"""Fail-closed, SQLite-only SQL execution example for DB-GPT data agents.

This module is deliberately independent of the DB-GPT execution pipeline.
Call GuardedSQLiteQuery.run AFTER the model generates SQL and BEFORE showing
results. Use a separate authorization layer to supply the allowed table names.
"""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote


class QueryRejected(ValueError):
    """Unsafe query, forbidden table, or violated execution budget."""


_ALLOWED_FUNCTIONS = frozenset(
    {
        "abs", "avg", "coalesce", "count", "date", "datetime", "ifnull",
        "length", "lower", "max", "min", "round", "strftime", "substr",
        "sum", "total", "upper",
    }
)


class GuardedSQLiteQuery:
    def __init__(
        self,
        database_path: str | Path,
        allowed_tables: set[str] | frozenset[str],
        *,
        max_rows: int = 100,
        timeout_ms: int = 2000,
    ):
        if not allowed_tables or not all(isinstance(table, str) and table for table in allowed_tables):
            raise ValueError("A nonempty server-owned table allowlist is required")
        if not (1 <= max_rows <= 1000):
            raise ValueError("max_rows must be between 1 and 1000")
        if not (100 <= timeout_ms <= 30000):
            raise ValueError("timeout_ms must be between 100 and 30000")
        self.database_path = Path(database_path).resolve(strict=True)
        self.allowed_tables = frozenset(allowed_tables)
        self.max_rows = max_rows
        self.timeout_ms = timeout_ms

    def run(self, sql: str) -> dict[str, Any]:
        if not isinstance(sql, str) or not re.match(r"^\s*(select|with)\b", sql, re.I):
            raise QueryRejected("Only SELECT queries and read-only CTEs are permitted")

        # SQLite execute() rejects multiple statements. The query is placed in a
        # SELECT subquery so a model-supplied LIMIT cannot bypass our row cap.
        query = f"SELECT * FROM ({sql.strip().rstrip(';')}) LIMIT ?"
        uri_path = quote(str(self.database_path), safe="/")
        db_uri = f"file:{uri_path}?mode=ro"
        deadline = time.monotonic() + self.timeout_ms / 1000
        with sqlite3.connect(db_uri, uri=True) as conn:
            conn.execute("PRAGMA query_only = ON")
            conn.execute("PRAGMA trusted_schema = OFF")

            def authorize(action: int, arg1: str | None, arg2: str | None, _db: str | None, _trigger: str | None) -> int:
                if action == sqlite3.SQLITE_READ:
                    return sqlite3.SQLITE_OK if arg1 in self.allowed_tables else sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_SELECT:
                    return sqlite3.SQLITE_OK
                if action == sqlite3.SQLITE_FUNCTION:
                    return sqlite3.SQLITE_OK if (arg2 or "").lower() in _ALLOWED_FUNCTIONS else sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_DENY

            conn.set_authorizer(authorize)
            conn.set_progress_handler(lambda: 1 if time.monotonic() >= deadline else 0, 1000)
            try:
                cursor = conn.execute(query, (self.max_rows,))
                columns = [col[0] for col in cursor.description or ()]
                rows = cursor.fetchmany(self.max_rows)
            except sqlite3.Error as error:
                # Database errors can contain data/SQL; don't expose them in a user-facing API.
                raise QueryRejected("SQL rejected, unauthorized, or exceeded its budget") from error
            finally:
                conn.set_authorizer(None)
                conn.set_progress_handler(None, 0)

        return {"columns": columns, "rows": [list(row) for row in rows], "returned_rows": len(rows)}

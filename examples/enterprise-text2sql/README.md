# Enterprise Text-to-SQL: guarded SQLite MVP

Standalone reference implementation for the first security milestone of the DB-GPT enterprise analytics project. This is **not** integrated into the default DB-GPT execution pipeline yet.

## Why this example exists

A generated SQL string should never be executed directly with production database credentials. This demonstration enforces three independent restrictions:

1. SQLite URI opens the selected database in read-only mode.
2. SQLite's native authorizer accepts only SELECT, approved functions, and reads from an explicitly allowed set of tables. The caller cannot supply the table allowlist.
3. Time budget and server-enforced maximum row count.

The example returns columns and rows as JSON-compatible Python objects.

## Run

```bash
cd examples/enterprise-text2sql
python -m pip install pytest
python -m pytest -q
```

Sample integration (the allowed tables must come from authenticated business permissions, **not** from the LLM):

```python
from guarded_query import GuardedSQLiteQuery

service = GuardedSQLiteQuery(
    "/srv/data/sales.sqlite",
    allowed_tables={"orders", "order_items"},
    max_rows=100,
)
result = service.run("SELECT COUNT(*) AS total_orders FROM orders")
```

## Scope and follow-up

This milestone intentionally supports **SQLite only**. To support PostgreSQL/MySQL, implement separate database-specific adapters using restrictive read-only credentials, dialect-aware AST validation, statement timeouts, schema-level grants and tenant-aware row-level policies. Do not port the SQLite authorizer assumptions to other engines.

The initial allowlist is table-level, not row/column-level. Production integration must derive row-level/column-level policies from the authenticated principal, use a resource-limited query service, add query audit and eliminate sensitive fields before returning results to an LLM. Query timeouts in-process are defense in depth, not a substitute for an isolated database server.

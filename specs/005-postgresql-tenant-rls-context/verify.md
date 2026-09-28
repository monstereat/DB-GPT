# Verification: trusted PostgreSQL tenant RLS context

## Results

- `test_rdbms_timeout.py`, `test_sql_guard.py`, `test_sql_guard_tracing.py`, `test_database_resource_sql_guard.py`, dashboard tests, editor tests, ReAct lifecycle/subagent tests, and OIDC execution-context tests: **156 passed**.
- Opt-in disposable PostgreSQL 16.6 integration (`DBGPT_RUN_POSTGRES_RLS_INTEGRATION=1`): **1 passed**. It used a table owned by an admin role, an app role with `NOBYPASSRLS`, an enabled tenant policy, and a one-connection SQLAlchemy pool. Tenant A, tenant B, missing identity, and unverified identity were isolated; SQL failure and timeout were followed by a successful query on the reused connection.
- `python -m compileall` for Core datasource and App API/dashboard paths: passed.
- `git diff --check`: passed.

## Limits

- No production database, role, grant, policy, or schema was changed.
- Production must still provision a non-owner, non-superuser, non-`BYPASSRLS` role and the appropriate RLS policies; the role must not be exposed to direct untrusted database clients.
- The standalone SQLite report-task executor in `examples/enterprise-text2sql` is not covered by this PostgreSQL connector RLS context.

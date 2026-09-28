# Implementation plan: trusted PostgreSQL tenant RLS context

## Current evidence

- OIDC verification produces a server-owned context with `source=verified_oidc_jwt` and `tenant_id`.
- Application SQL policy injects tenant/region predicates, but PostgreSQL RLS transaction context is not currently set by DB-GPT.
- `execute_read_only_query` is the shared query boundary; Core `RDBMSConnector._query_ex` owns a SQLAlchemy session transaction and already uses transaction-local `SET LOCAL statement_timeout` for PostgreSQL.
- ReAct, Core RDBMS Agent Resource, Dashboard/editor, and saved-chart replay use this shared guarded query path, so connector-only changes without explicit context propagation would be incomplete.
- The SQL Editor's guarded `_execute_sql_with_trace` in `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/editor/api_editor_v1.py` calls `connector.query_ex` directly with bound parameters. It also needs explicit verified context forwarding; changing only `execute_read_only_query` would miss it.
- The standalone `examples/enterprise-text2sql` report task API executes through its own SQLite tenant-scoped executor, not a PostgreSQL connector, and is out of scope for this RLS change.

## Decisions

1. Add a distinct `verified_execution_context` parameter. Do not infer trust from `audit_context`, SQL text, request headers, or model-generated arguments.
2. Extract tenant only from a context whose source is `verified_oidc_jwt`. Pass an empty value for missing/unverified identity so each PostgreSQL transaction overrides any pre-existing session value and RLS comparison fails closed during the query.
3. Set the tenant through parameterized `SELECT set_config('app.current_tenant', :tenant_id, true)` within `_query_ex`'s existing session scope. The final `true` makes the setting transaction-local, so commit/rollback restores the pooled connection state.
4. Leave non-PostgreSQL connector behavior unchanged. Keep application AST row filters and database RLS independent.
5. Test with a disposable PostgreSQL instance and synthetic tables/policies only. Do not change production DB roles, grants, or tables.

## Work sequence

1. Add trusted-context extraction/validation at the shared read-only gateway and pass the explicit value to `query_ex` only for PostgreSQL.
2. Extend the Core connector execution signature and set the transaction-local tenant setting before the guarded SQL, including when timeout handling is enabled.
3. Thread verified context through every in-scope caller, including the direct SQL Editor query helper; add regression tests that reject accidental reliance on audit metadata.
4. Add an isolated PostgreSQL RLS test for two tenants, missing/unverified context, pool size one, timeout/error, and connection reuse.
5. Run focused Core/App tests, the enterprise Text-to-SQL offline suite, UI tests/build, lint/format/compile and `git diff --check`; update the roadmap with evidence.

## Risks and limitations

- A custom PostgreSQL GUC is not an independent identity system if untrusted users can connect directly with the application DB credential or invoke arbitrary state-changing SQL. Keep DB credentials server-side, preserve SQL AST rejection for session-setting functions, and use least-privilege production roles.
- RLS policies can be bypassed by table owners, superusers, or `BYPASSRLS`; production role/policy deployment remains an operator task.
- Any query path that bypasses `execute_read_only_query` will not receive this context; the implementation must audit all in-scope callers and retain tests for the shared boundary.
- Production IdP, PostgreSQL role/grant, and real datasource validation remain external environment requirements.

## Verification

- Unit tests prove context trust checks, bound parameter forwarding, PostgreSQL-only behavior, and no use of audit metadata as authority.
- Disposable PostgreSQL integration test proves row isolation and transaction/connection-pool cleanup after normal query, exception, and timeout.
- Run enterprise Text-to-SQL and UI regression suites plus formatting, compile, and diff checks.

## Approval and status

- Plan status: approved by the user; implementation and verification complete.

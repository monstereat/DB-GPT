# Trusted tenant context for PostgreSQL RLS

## Goal

Pass the verified OIDC tenant from DB-GPT's server-side query path into the same PostgreSQL transaction that executes a guarded read query. This lets database policies use a transaction-local `app.current_tenant` value and prevents tenant state from leaking through a pooled connection.

## Scope

- Add an explicit verified execution context to the shared read-only query gateway and Core RDBMS connector, plus the guarded SQL Editor `query_ex` path.
- For PostgreSQL queries, set `app.current_tenant` with a bound parameter and transaction-local semantics before executing SQL.
- Treat missing or unverified tenant identity as an empty tenant value, so RLS policies fail closed.
- Propagate the verified context from OIDC-protected ReAct and its SQL subagent, Core database resource, Dashboard, SQL Editor execution/chart replay/chart-edit validation, and any other PostgreSQL caller routed through the shared query gateway.
- The standalone `examples/enterprise-text2sql` report task API uses its own SQLite tenant-scoped executor and is outside PostgreSQL connector RLS scope.
- Add an isolated PostgreSQL integration test with tenant RLS policies, a one-connection pool, sequential tenants, missing identity, and error/timeout cleanup.
- Keep existing tenant/region SQL AST filters as a separate defense layer.

## Out of scope

- No production database connection, schema migration, role/grant change, or production RLS policy installation.
- No change to MySQL authorization, OIDC claim mapping, tenant ownership schema, or datasource lifecycle.
- No use of audit/span metadata as an authorization source; the new argument must be derived from verified server identity.

## Acceptance criteria

- AC-01: PostgreSQL queries set `app.current_tenant` inside the same transaction as the guarded query, using a bound value and `SET LOCAL`/`set_config(..., true)` semantics.
- AC-02: Missing, unverified, or tenant-less execution context cannot inherit the previous pooled connection tenant; tenant-protected rows remain invisible.
- AC-03: Sequential requests for different tenants on a pool of size one see only their own rows. Query failure and timeout leave the connection reusable without tenant state leakage.
- AC-04: Non-PostgreSQL behavior is unchanged; raw SQL cannot set or change the tenant context through a user-controlled query path.
- AC-05: Existing offline suites and focused PostgreSQL integration tests pass; roadmap records local evidence and production limitations accurately.

## Security boundary

The GUC is trusted only when set by DB-GPT from a verified OIDC execution context. The database role must not be exposed to end users or direct untrusted SQL clients. Production still needs a non-owner, non-`BYPASSRLS` read-only role and database-side policies; this change does not create production roles or policies.

## Approval

- Status: approved and implemented.

# Verification

## Automated tests

- Core ReAct SQL error tests and API lifecycle tests: **23 passed**.
- Ruff check and format: passed for changed Python files.
- `git diff --check`: passed.

## Local end-to-end check

- Recreated only `dbgpt-develop-me-test-dbgpt-1`; the DB-GPT service became healthy and `/api/health` returned `{"status":"ok"}`.
- Against the synthetic `ecommerce-demo` datasource, requested direct access to `products.internal_cost_cents`.
- The live stream contained exactly one `sql_query` action, then completed with the server-owned denial message: `查询包含当前身份不可访问的敏感字段。`
- The request completed in 19.5 seconds. The local database, fixture, and named volumes were not changed.
- Re-ran the four-case multi-turn evaluation after the stop behavior was deployed: it completed rather than hanging, with 0 correct, 1 incorrect, and 3 missing structured results. The first case made two SQL tool calls and then returned the exhausted-correction-budget message. Sanitized outcomes are recorded in `evidence/multiturn-scorecard.json`; multi-turn SQL generation remains unaccepted.

## Limits

- This validates a local synthetic datasource and local demo identity only. It does not certify production OIDC, database roles/RLS, or general model SQL accuracy.

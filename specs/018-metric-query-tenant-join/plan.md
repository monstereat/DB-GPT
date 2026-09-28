# Plan

1. Add and unit-test a narrow request classifier for the ecommerce-demo regional sales metric; only that request is restricted to metric_query.
2. Add tenant_id to compiled metric joins through orders and regions; test generated SQL and execution against a tenant-collision fixture.
3. Mount the changed metric compiler read-only into the local test service. A temporary image rebuild failed at the Ubuntu APT repository signature check; do not weaken signature validation.
4. Run focused tests, recreate only local DB-GPT, and compare q01 structured results with gold; update Roadmap with exact evidence.

## Files

- `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/agentic_data_api.py`
- `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/metric_query.py`
- `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_database_workflow_prompt.py`
- `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/tests/test_metric_query.py`
- `docker/compose_examples/develop-me-test/compose.yaml`
- `docs/develop-me-roadmap.md`
- `specs/018-metric-query-tenant-join/**`

## Verification

`PYTHONPATH=packages/dbgpt-core/src:packages/dbgpt-serve/src:packages/dbgpt-app/src:packages/dbgpt-ext/src .venv/bin/python -m pytest -q -o addopts='' packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_database_workflow_prompt.py packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_agentic_data_api_lifecycle.py packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/tests/test_metric_query.py`

Live q01 command uses the existing local-only placeholder token and `specs/014-database-react-prompt/evidence/q01.json` dataset.

## Commit strategy

`none`.

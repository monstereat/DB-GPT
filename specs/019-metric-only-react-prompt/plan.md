# Plan

1. Add a metric-only prompt variant selected only for the existing narrow ecommerce-demo regional sales classifier.
2. Add prompt regression coverage and run prompt, ReAct lifecycle, and metric SQL compiler tests.
3. Ensure metric query results use the published metric's stable result column (`sales_cents` for sales), configure the local Compose stack with the read-only catalog, then rerun focused tests and q01.
4. Recreate only local DB-GPT, compare q01 with gold, and update Roadmap with exact evidence.

## Files
- `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/agentic_data_api.py`
- `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_database_workflow_prompt.py`
- `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/metric_query.py`
- `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/tests/test_metric_query.py`
- `docker/compose_examples/develop-me-test/compose.yaml`
- `docs/develop-me-roadmap.md`
- `specs/019-metric-only-react-prompt/**`

## Verification
`PYTHONPATH=packages/dbgpt-core/src:packages/dbgpt-serve/src:packages/dbgpt-app/src:packages/dbgpt-ext/src .venv/bin/python -m pytest -q -o addopts='' packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_database_workflow_prompt.py packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_agentic_data_api_lifecycle.py packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/tests/test_metric_query.py`

Live verification: run q01 from `specs/014-database-react-prompt/evidence/q01.json` against local test Compose using the documented placeholder token.

## Commit strategy
`none`.

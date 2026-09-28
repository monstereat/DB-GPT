# Implementation plan: Route published metrics through deterministic queries

1. Make database-mode Agent tools include the role-filtered metric catalog and metric query alongside the existing SQL tool.
2. Update the database-mode prompt contract to use the metric tools for published business metrics and use raw SQL only when the requested metric is not in the catalog.
3. Extend focused prompt tests and run them, then recreate only the local DB-GPT service and evaluate the screenshot q01 against its fixed gold.

## Files

- `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/agentic_data_api.py`
- `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_database_workflow_prompt.py`
- `specs/017-published-metric-agent-routing/**`
- `docs/develop-me-roadmap.md`

## Verification commands

- `PYTHONPATH=packages/dbgpt-core/src:packages/dbgpt-serve/src:packages/dbgpt-app/src:packages/dbgpt-ext/src .venv/bin/python -m pytest -q -o addopts='' packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_database_workflow_prompt.py packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_agentic_data_api_lifecycle.py packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_business_context.py`
- `docker compose -p dbgpt-develop-me-test -f docker/compose_examples/develop-me-test/compose.yaml up -d --no-deps --build dbgpt`
- `curl -fsS http://127.0.0.1:5671/api/health`
- `.venv/bin/python examples/enterprise-text2sql/evaluate_agent.py --help`

## Commit strategy

`none`.

## Rollback

Revert only the two source files and this spec's roadmap entry if focused verification or the live request shows a regression. Preserve all pre-existing workspace changes.

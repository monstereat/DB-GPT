# Tasks

## T001: Provide a metric-only ReAct format
- Allowed files: `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/agentic_data_api.py`, `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_database_workflow_prompt.py`, `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/metric_query.py`, `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/tests/test_metric_query.py`, `specs/019-metric-only-react-prompt/**`.
- Acceptance criteria: AC-01, AC-02.
- Verification: exact focused pytest command from `plan.md`.
- Status: pending.

## T002: Re-evaluate q01
- Depends on: T001.
- Allowed files: `docs/develop-me-roadmap.md`, `docker/compose_examples/develop-me-test/compose.yaml` (local read-only metric catalog), `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/metric_query.py`, `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/tests/test_metric_query.py`, `specs/019-metric-only-react-prompt/**`.
- Acceptance criteria: AC-02, AC-03.
- Verification: q01 live scorecard JSON parses and its status is recorded.
- Status: pending.

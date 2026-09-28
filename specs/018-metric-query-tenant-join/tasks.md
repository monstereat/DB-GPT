# Tasks

## T001: Constrain metric routing and fix composite joins

- Allowed files: `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/agentic_data_api.py`, `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/metric_query.py`, `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_database_workflow_prompt.py`, `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/tests/test_metric_query.py`, `docker/compose_examples/develop-me-test/compose.yaml`, `specs/018-metric-query-tenant-join/**`.
- Acceptance criteria: AC-01, AC-02.
- Verification: run the exact focused pytest command from `plan.md`.
- Status: pending.

## T002: Re-test screenshot question

- Depends on: T001.
- Allowed files: `docs/develop-me-roadmap.md`, `docker/compose_examples/develop-me-test/compose.yaml` (T001 read-only local source mount), `specs/018-metric-query-tenant-join/**`.
- Acceptance criteria: AC-03.
- Verification: live one-question q01 evaluation, structured gold comparison, and saved sanitized scorecard.
- Status: pending.

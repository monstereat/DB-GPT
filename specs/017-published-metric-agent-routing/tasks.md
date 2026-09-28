# Tasks: Route published metrics through deterministic queries

## T001: Expose and instruct database-mode metric tools

- Allowed files: `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/agentic_data_api.py`, `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_database_workflow_prompt.py`, `specs/017-published-metric-agent-routing/**`.
- Acceptance criteria: AC-01, AC-02.
- Verification command: `PYTHONPATH=packages/dbgpt-core/src:packages/dbgpt-serve/src:packages/dbgpt-app/src:packages/dbgpt-ext/src .venv/bin/python -m pytest -q -o addopts='' packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_database_workflow_prompt.py packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_agentic_data_api_lifecycle.py packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_business_context.py`
- Status: pending.

## T002: Re-evaluate screenshot question

- Depends on: T001.
- Allowed files: `docs/develop-me-roadmap.md`, `specs/017-published-metric-agent-routing/**`.
- Acceptance criteria: AC-03.
- Verification: run the existing single-question q01 live evaluator against the local test stack and compare its structured metric result with `gold_questions.json`.
- Status: pending.

# Tasks: Align database ReAct turn instructions

## T001: Match the core ReAct turn contract

- Allowed files: `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/agentic_data_api.py`, `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_database_workflow_prompt.py`, `specs/015-database-react-turn-format/**`.
- Acceptance criteria: AC-01, AC-02.
- Verification command: `PYTHONPATH=packages/dbgpt-core/src:packages/dbgpt-serve/src:packages/dbgpt-app/src:packages/dbgpt-ext/src .venv/bin/python -m pytest -q -o addopts='' packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_database_workflow_prompt.py packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_agentic_data_api_lifecycle.py`
- Status: pending.

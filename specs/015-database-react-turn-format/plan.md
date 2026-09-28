# Implementation plan: Align database ReAct turn instructions

1. Update the database workflow prompt to include the same action-intention, action-reason, and final-phase fields required by the core ReAct template.
2. Extend the prompt regression to assert those required fields and the `result` terminate key.
3. Run the focused prompt and ReAct lifecycle test suite, then pass the changed-file scope gate.

## Files

- `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/agentic_data_api.py`
- `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_database_workflow_prompt.py`
- `specs/015-database-react-turn-format/**`

## Verification command

`PYTHONPATH=packages/dbgpt-core/src:packages/dbgpt-serve/src:packages/dbgpt-app/src:packages/dbgpt-ext/src .venv/bin/python -m pytest -q -o addopts='' packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_database_workflow_prompt.py packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_agentic_data_api_lifecycle.py`

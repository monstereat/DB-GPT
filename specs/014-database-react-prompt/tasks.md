# Tasks: Align the database ReAct final-answer contract

## T001: Align and test the database workflow prompt

- Allowed files: `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/agentic_data_api.py`, `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_database_workflow_prompt.py`, `specs/014-database-react-prompt/**`.
- Acceptance criteria: AC-01.
- Verification command: `PYTHONPATH=packages/dbgpt-core/src:packages/dbgpt-serve/src:packages/dbgpt-app/src:packages/dbgpt-ext/src .venv/bin/python -m pytest -q -o addopts='' packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_database_workflow_prompt.py packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_agentic_data_api_lifecycle.py`
- Status: pending.

## T002: Verify the screenshot question with the live local Agent

- Depends on: T001.
- Allowed files: `docs/develop-me-roadmap.md`, `specs/014-database-react-prompt/**`.
- Acceptance criteria: AC-02.
- Actions: recreate only the project DB-GPT service; run one live q01 gold scorecard; record its redacted status.
- Verification commands:
  1. `.venv/bin/python -m json.tool specs/014-database-react-prompt/evidence/q01-scorecard.json`
  2. `.venv/bin/python -c 'import json; d=json.load(open("specs/014-database-react-prompt/evidence/q01-scorecard.json")); assert d["question_count"] == 1; print(d["cases"])'`
- Status: pending.

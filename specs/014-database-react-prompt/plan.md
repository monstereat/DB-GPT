# Implementation plan: Align the database ReAct final-answer contract

1. Extract the small database workflow-prompt builder so its output can be tested directly.
2. Change the `terminate` input schema from `output` to the ReAct core's `result` key; preserve the existing metric and datasource context text.
3. Run the prompt regression and relevant ReAct final-answer tests.
4. Recreate only the local DB-GPT service and score the screenshot's q01 case using the currently configured Ollama model `qwen3:4b`.
5. Record the actual live outcome; do not claim the UI is fixed unless it exact-matches gold.

## Files

- `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/agentic_data_api.py`
- `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_database_workflow_prompt.py`
- `docs/develop-me-roadmap.md`
- `specs/014-database-react-prompt/**`

## Verification

- Focused pytest for the new prompt builder and existing ReAct terminal extraction tests.
- Local Compose health check after service recreation.
- Live q01 scorecard against only the synthetic `ecommerce-demo` datasource.

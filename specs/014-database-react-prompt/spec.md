# Align the database ReAct final-answer contract

## Background

- The database-mode prompt in `agentic_data_api.py` asks the model to terminate with `Action Input: {"output": "..."}`.
- DB-GPT's `ToolCallingReActAgent` core template requires `Action Input: {"result": "..."}` for `terminate`.
- The final SSE extractor tolerates both fields, but the model is given contradictory instructions. Live logs for the screenshot's q01 question show the model repeatedly discussing the format instead of completing the tool call.

## Goal

Remove the conflicting terminate schema from database-mode ReAct instructions and verify the screenshot question completes through the live Agent.

## Scope

- Includes: align only the database-mode prompt to the core `result` key; add a focused prompt regression; recreate the project-owned DB-GPT test service; run the synthetic q01 case against the current local model; update roadmap and evidence.
- Excludes: changing SQL authorization, other chat-mode prompts, database data, the ReAct parser contract, production model or identity configuration.

## Acceptance criteria

- **AC-01:** The database workflow prompt instructs `terminate` to use `{"result": "..."}` and contains no competing `{"output": ...}` final-action instruction.
- **AC-02:** The screenshot's q01 live test emits a structured SQL result and exact-matches the synthetic gold answer, without a generated-response error.

## Approval basis

The user authorized finishing the DB-GPT roadmap and asked for the screenshot failure to be repaired without repeated confirmation. The change is confined to this local service and synthetic datasource.

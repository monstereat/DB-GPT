# Plan

1. Add narrow classification for non-retryable structured `sql_query` results at the ReAct action boundary.
2. Adapt the Agent SSE/final-response handling so the terminal SQL failure remains visible and uses the server message.
3. Add regression tests for terminal classification and API message extraction.
4. Mount the changed Core file read-only in the local test Compose service; recreate only DB-GPT and validate a sensitive-column denial end to end.
5. Record focused verification and remaining roadmap limits.

## Authorization

Implemented under the user's existing authorization to continue fixing the active DB-GPT goal. Local Docker test services and database operations were explicitly authorized; the test uses only the synthetic `ecommerce-demo` datasource.

# Plan: daily token quota for ChatNormal

1. Extract verified identity/limit parsing into a shared helper used by both App chat and ReAct. The helper accepts only `UserRequest` resolved by the existing auth dependency.
2. Add optional quota context to `ChatParam`; set it only from `/v1/chat/completions` after mode normalization and only when final mode is `ChatNormal`.
3. Have `BaseChat.llm_client` wrap its default client with existing `MeteredLLMClient` when the trusted context is present.
4. Prefer `DBGPT_DAILY_TOKEN_LIMIT` in ReAct/knowledge-agent; fall back to `DBGPT_REACT_DAILY_TOKEN_LIMIT` only when the unified setting is unset.
5. Sanitize quota-exceeded and unmeterable exceptions in the shared chat stream generator.
6. Add tests for trusted identity parsing, route-to-ChatParam propagation, ChatNormal-only wrapping, unified/legacy precedence, quota rejection before provider call, settlement and interrupted streams. Run focused tests, App API regression, lint/compile, scope and diff checks.
7. Extend the shared wrapper to API v2 BaseChat modes, fail closed for unmetered v2 app/flow modes while quota is configured, and preserve a separate `X-API-Key` path when a JWT is also required.

## Expected files

- `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/api_v1.py`
- `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/agentic_data_api.py`
- `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/token_quota.py`
- `packages/dbgpt-app/src/dbgpt_app/scene/base_chat.py`
- focused App API and scene tests
- operator README and `docs/develop-me-roadmap.md`
- `specs/004-chat-token-quota/**`

## Limits

The existing quota is a reservation-based token budget, not a provider billing hard cap. This slice does not cover other model endpoints or non-text input.

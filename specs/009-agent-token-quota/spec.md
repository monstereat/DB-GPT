# Token quota coverage for App-Agent

## Goal

Extend the existing tenant/user daily token budget to ordinary App-Agent requests without trusting request-supplied identity fields. AWEL flow requests remain unavailable while quota is enabled until every supported execution entry point and operator type can be bounded safely.

## Scope

- Build quota context only from a verified OIDC `UserRequest` in the HTTP handler.
- Meter manually composed App-Agent requests by wrapping the request-scoped LLM client.
- Reject flow-backed App-Agent requests when the quota is enabled; reject other unsupported v1/v2 chat modes before model execution.
- Never place the quota wrapper or trusted identity in caller-controlled `ext_info`, `context`, or workflow variables.
- Keep `/flow/debug` and every dynamically registered AWEL `HttpTrigger` fail-closed while quota is enabled. The trigger guard applies to both `chat` and `command` mode because custom operators can invoke an LLM even when the request schema is command-oriented. A Core `ContextVar` wrapper helper is available, but no HTTP chat-flow execution path currently installs it.

## Acceptance criteria

- v1/v2 ordinary App-Agent requests pass a server-generated quota wrapper to their managed LLM client.
- Caller fields such as `ext_info.trusted_execution_context` cannot override the trusted identity or quota context.
- Flow-backed App-Agent requests are rejected while the quota is enabled.
- Regression tests cover client wrapping, identity isolation, App-Agent mode authorization, and Core wrapper context reset.
- AWEL chat-flow metering and custom operator metering remain out of scope and explicitly unclaimed. `/flow/debug` and all dynamic HTTP trigger endpoints return a fixed 503 while quota is enabled; dynamic trigger endpoints retain existing behavior while quota is disabled.

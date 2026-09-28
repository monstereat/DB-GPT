# Daily token quota for normal chat

## Goal

Extend the existing per-tenant/per-user daily token reservation and settlement to the ordinary `ChatNormal` endpoint, using the same quota bucket as ReAct when the unified limit is configured.

## Scope

- Meter plain-text BaseChat model calls through `/v1/chat/completions`; the original implementation covered `ChatNormal` and the later extension below adds other supported BaseChat modes.
- Reuse `MeteredLLMClient` and the existing quota DAO; do not add quota schema or dependencies.
- Add `DBGPT_DAILY_TOKEN_LIMIT` as the unified optional limit for ChatNormal and ReAct/knowledge-agent. Preserve `DBGPT_REACT_DAILY_TOKEN_LIMIT` as a legacy fallback for ReAct/knowledge-agent only when the unified setting is unset.
- Resolve the quota subject only from verified OIDC tenant/user claims, never dialogue fields.
- The initial v1 slice meters only plain-text `ChatNormal`; the later API v2 extension below adds selected BaseChat modes. App-agent, flow, multimodal content, and monetary quotas remain outside scope.

## API v2 extension

- The v1 and v2 chat completions endpoints apply the same reservation wrapper to BaseChat modes (normal, knowledge, data, DB QA, and dashboard) when `DBGPT_DAILY_TOKEN_LIMIT` is set.
- Chat app, AWEL flow, and domain knowledge flow do not use this metered BaseChat path; with the quota enabled they fail closed with 503 rather than silently bypassing the configured budget.
- Quota identity requires OIDC JWT claims. When API-key authentication is also configured, clients may send the service key in `X-API-Key` and the user JWT in `Authorization: Bearer`.
- With the quota setting absent, API v2 keeps its existing API-key/development behavior.

## Acceptance criteria

- AC-01: With the unified limit set, a verified ChatNormal request carries trusted tenant/user quota context into its LLM client; absent or invalid identity fails before model generation.
- AC-02: Each underlying model call reserves an upper bound and settles provider usage, while interruption/missing usage retains the reservation using existing wrapper behavior.
- AC-03: The ReAct path uses the unified limit when set and retains legacy behavior when only the old setting is configured.
- AC-04: Quota errors are reported with fixed safe messages; no provider/internal error text is exposed by the chat stream for quota failures.
- AC-05: With quota configuration absent, existing ChatNormal behavior is unchanged.

## Approval

- Status: approved as a bounded implementation slice under the user's active roadmap goal; no schema migration or database deployment is required.

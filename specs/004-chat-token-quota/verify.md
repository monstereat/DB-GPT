# Verification: ChatNormal daily token quota

## Automated verification

- Token quota DAO and App quota tests: 25 passed; includes verified identity resolution, invalid/missing configuration, unified/legacy setting precedence, safe public errors, and quota context propagation to `ChatParam`.
- App API v1 tests: 85 passed.
- Ruff check and format check passed for the changed Python files; `py_compile` and `git diff --check` passed.

## Limits

The configured budget is reservation-based and does not hard-cap provider billing. It covers ReAct, knowledge-agent, and v1/v2 BaseChat modes (normal, knowledge, data, DB QA, dashboard). Chat app, AWEL flow, and domain knowledge flow fail closed while the limit is configured. Other model endpoints remain out of scope. PostgreSQL/MySQL concurrency and live-provider usage still need deployment validation.

## API v2 verification

- API v1/v2 quota context and supported/unsupported mode behavior plus the existing quota suite: 19 passed.
- Regression confirms the daily-limit-disabled API-key path remains available; when API keys and quota are both enabled, the service key is accepted through `X-API-Key` while `Authorization` carries the OIDC bearer token.

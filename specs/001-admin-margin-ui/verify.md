# Verification: role-aware gross-margin UI

Date: 2026-09-25

## Results

- API role-filtered catalog regression: `1 passed, 41 deselected`.
- Vue UI tests: `31 passed`.
- Vite production build: passed.
- Full enterprise Text-to-SQL suite: `184 passed`.
- T001 scope gate: passed.
- T002 scope gate: passed.
- `git diff --check`: passed.

The catalog endpoint uses the server-resolved role and returns display fields only. The UI does not infer roles from the token; it requests the authorized catalog with the bearer token and clears privileged options/results when the identity changes. Existing query and report APIs remain the authorization boundary.

## Limits

These checks are local/offline. The development identity fallback remains suitable only for the demo. A real enterprise OIDC provider, browser callback/deployment settings, production PostgreSQL/MySQL grants and RLS, and production cost-column authorization remain unverified.

# Tasks: trusted PostgreSQL tenant RLS context

## T001: Propagate verified tenant into PostgreSQL query transactions

- Dependencies: user approval of spec and plan.
- Allowed files: Core SQL guard/connector and tests; App trusted query call sites, including the SQL Editor direct `query_ex` helper, and tests; disposable PostgreSQL integration test support; this spec directory; `docs/develop-me-roadmap.md`.
- Acceptance criteria: AC-01 through AC-04.
- Status: complete.

## T002: Verify and update roadmap

- Dependencies: T001.
- Allowed files: verification records and roadmap.
- Acceptance criteria: AC-05.
- Status: complete.

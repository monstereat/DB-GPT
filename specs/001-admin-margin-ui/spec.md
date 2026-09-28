# Role-aware gross margin in the analytics UI

## Background and goal

- Background: `gross_margin_rate@1.0.0` is implemented and restricted to `admin`, but the Vue analytics page uses a hard-coded metric list that omits it.
- Goal: let authorized administrators select and analyze gross margin in the UI while the server remains the source of role authorization.
- Success: available metrics are derived from the published metric catalog and filtered by the API's server-resolved role; when OIDC is enabled that role comes from a verified JWT. Gross margin remains absent for non-admin users and server-side query checks remain authoritative.

## Scope

- Include: a read-only role-filtered metric discovery endpoint, UI metric options loaded with the current bearer token, gross-margin chart selection, and selection of the existing admin report template for exports containing gross margin.
- Exclude: data-source credential storage/approval, database schema changes, OIDC provider configuration, changing metric definitions, and enterprise deployment.

## User behavior

### AC-01: Metric discovery respects the authenticated role

- Preconditions: the demo API has a published catalog and resolves the request identity through its configured authentication mode.
- Action: the UI requests available metrics with the bearer token.
- Expected: the API returns only published metric metadata allowed for the server-resolved role; with OIDC enabled, `gross_margin_rate` is returned only when the verified role is `admin`. The API's existing development identity behavior is unchanged.
- Verification: API tests for admin and non-admin identities, plus existing OIDC claim-mapping tests.

### AC-02: Admin can analyze gross margin in the UI

- Preconditions: metric discovery returned the admin catalog.
- Action: select 毛利率 and run analysis.
- Expected: the selector, version metadata, chart, table, and SQL preview use the selected metric; the UI does not derive authorization from token contents and clears privileged options when identity changes.
- Verification: frontend helper tests and production build; existing API tests continue to enforce the metric role.

### AC-03: Reports use the matching server template

- Action: export while gross margin is among the admin's available metrics.
- Expected: request uses the existing `admin-margin@1.0.0` template; public-only exports retain `sales-standard@1.0.0`.
- Verification: frontend request tests and existing report-template authorization tests.

## Boundaries and constraints

- Errors/loading: a failed discovery request clears any privileged metric option and keeps only the fixed public metric options; identity changes must not retain a prior user's privileged options.
- Compatibility: preserve current default public metrics and existing public report behavior.
- Security/privacy: the API filters by `UserRequest.role`; client-side visibility is convenience only. The metric query endpoint and report template endpoint continue independent server-side authorization.
- Project conventions: Python/FastAPI backend, Vue/JavaScript frontend, no new dependency or database migration.

## Assumptions and pending decisions

- [x] The user's confirmed gross-margin definition and `admin` role remain authoritative.
- [x] The existing `admin-margin@1.0.0` report template is the intended export template.

## Approval

- Spec status: approved under the user's active goal to complete the remaining roadmap tasks.
- Approver: user
- Approval evidence: user requested completing the unfinished items in `docs/develop-me-roadmap.md`; this slice completes the approved admin-only gross-margin metric in the analysis UI without changing its confirmed definition.

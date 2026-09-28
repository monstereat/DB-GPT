# Implementation plan: role-aware gross margin in the analytics UI

## Confirmed context

- Related modules: `examples/enterprise-text2sql/api.py`, `test_api.py`, and `ui/src/{App.vue,api.js,api.test.js}`.
- Existing behavior: backend gross margin is admin-only; `/metrics/catalog` is an admin management endpoint; the UI hard-codes four public metrics and always exports the standard report template.
- Unknowns: none for the demo catalog and report templates; enterprise IdP deployment remains outside this slice.

## Approach

- Add a read-only `/metrics/available` endpoint. Resolve identity through the existing `get_user_from_headers`, load the published release snapshot, and return only safe presentation fields for metrics whose `allowed_roles` include the server-resolved role (defaulting to public visibility when no role restriction exists). With OIDC enabled, this role is derived from the verified JWT; preserve the existing legacy development identity behavior when OIDC is disabled.
- Add a frontend API helper and normalize the response to metric options. On token changes, clear privileged options before requesting the new identity's catalog; retain only the fixed public options if discovery fails.
- Keep the four public summary cards fixed. Add the selected gross-margin result to the existing breakdown/chart path, including its output column and percent unit.
- Include the available metric IDs in exports and choose `admin-margin@1.0.0` when the request includes gross margin; otherwise preserve `sales-standard@1.0.0`.
- Keep all enforcement server-side; metric query and report template checks remain unchanged. The frontend does not decode access-token claims to make authorization decisions.

## Files

| File | Operation | Reason | AC |
| --- | --- | --- | --- |
| `examples/enterprise-text2sql/api.py` | modify | Role-filtered discovery endpoint | AC-01 |
| `examples/enterprise-text2sql/test_api.py` | modify | Verify public/admin catalog results | AC-01 |
| `examples/enterprise-text2sql/ui/src/api.js` | modify | Authenticated catalog request and report template selection | AC-01, AC-03 |
| `examples/enterprise-text2sql/ui/src/api.test.js` | modify | Verify request contract and template selection | AC-03 |
| `examples/enterprise-text2sql/ui/src/App.vue` | modify | Role-aware metric options and gross-margin display | AC-02, AC-03 |
| `docs/develop-me-roadmap.md` | modify | Record implemented evidence and remaining production limitation | AC-01–AC-03 |

## Order

1. Implement and test the filtered API endpoint.
2. Add frontend catalog loading, identity reset, gross-margin selection, and report-template routing; run UI tests/build.
3. Run the full Text-to-SQL suite and update roadmap evidence.

## Verification

| Level | Command | Pass condition |
| --- | --- | --- |
| API unit | `PYTHONPATH=../../packages/dbgpt-core/src:../../packages/dbgpt-serve/src:../../packages/dbgpt-ext/src python -m pytest -q -o addopts='' test_api.py -k available_metric_catalog` | Admin sees gross margin; non-admin does not; unauthorized query still rejected by existing checks |
| Frontend unit | `npm test` | Catalog identity reset and report template selection tests pass |
| Build | `npm run build` | Vite production build succeeds |
| Integration regression | Full README Text-to-SQL pytest command | All existing and new tests pass |
| Diff | `git diff --check` | No whitespace errors |

## Execution control

- State recovery: off
- Independent review: off
- Branch strategy: current branch `develop-me`; do not switch branches
- Commit strategy: none

## Risk and rollback

- Risk: catalog response may contain a newly published role-restricted metric; only return allowlisted display fields and filter on the server. The demo's existing non-OIDC development identity remains an admin and must not be treated as production authentication.
- Rollback: remove the discovery route and restore the fixed frontend metric options; existing query authorization remains in force.

## Approval

- Plan status: approved under the user's active goal to complete the remaining roadmap tasks.
- Approver: user
- Approval time: 2026-09-25

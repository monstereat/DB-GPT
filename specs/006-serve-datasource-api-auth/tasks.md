# Tasks: verified identity for Serve datasource APIs

## T001: Require a verified principal and scope operations

- Dependencies: established OIDC verifier and datasource `submitted_by` field.
- Acceptance: missing/dev identity is rejected; verified owner and admin policies apply to all datasource routes; configured service API keys remain privileged machine credentials.
- Status: complete.

## T002: Preserve server-owned ownership and verify regressions

- Dependencies: T001.
- Acceptance: request fields cannot assign ownership; list filters to the verified submitter; cross-owner access is hidden; no schema migration is required.
- Status: complete.

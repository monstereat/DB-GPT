# Verified identity for Serve datasource APIs

## Goal

Protect DB-GPT Serve's generic `/datasources` management routes with a verified OIDC user or an explicitly configured service API key, and scope user operations to the datasource submitter.

## Policy

- A verified OIDC user may create and test a datasource. They may list, view, update, delete, or refresh only rows whose server-owned `submitted_by` matches their verified subject.
- A verified `admin` may manage all datasource rows.
- A configured Serve API key remains available for machine clients and is treated as a privileged service administrator. The key does not represent an end user and is never accepted from a datasource request field.
- Missing OIDC identity and missing/invalid service key fail closed for datasource APIs, including when `api_keys` is unset. Health and `/test_auth` keep their existing lightweight behavior.
- Create assigns ownership from the verified subject. Update cannot change ownership or approval fields. Existing rows without trusted `submitted_by` are admin/service-key only until an operator reconciles ownership.
- No database schema changes. Existing DAO `submitted_by` is authoritative.

## Out of scope

- No changes to old App `/v1/chat/db` endpoints, database credentials/grants/RLS, or migration of historical ownership.
- No production IdP, reverse proxy, or API-key deployment configuration.

## Verification

- Unit tests cover missing/invalid identity, verified owner/admin, privileged service key, owner filtering, ownership spoof attempts, and cross-owner CRUD denial.
- Existing datasource service/security suites and enterprise Text-to-SQL offline suite pass.

# Tasks: data-source credentials and approval

## T001: Encrypt datasource credentials and add approval state

- Dependencies: user approval of spec and plan
- Allowed files: Serve datasource DAO/service/connector code, App API and tests, database metadata schema/upgrade SQL, migration CLI/tests, docs, and `specs/002-datasource-governance/**`.
- Operation: implement encryption, approval/audit state transitions, trusted admin review API, connector gate, and idempotent legacy migration.
- Acceptance criteria: AC-01, AC-02, AC-03
- Status: complete

## T002: Verify migrations and update roadmap

- Dependencies: T001
- Allowed files: `docs/develop-me-roadmap.md`, `specs/002-datasource-governance/verify.md`, `specs/002-datasource-governance/tasks.md`
- Operation: run focused and regression suites, review diff, record evidence and operational limits.
- Acceptance criteria: AC-01, AC-02, AC-03
- Status: complete

## T003: Add audited owner transfer

- Dependencies: verified OIDC admin identity and datasource approval audit from T001
- Allowed files: Serve datasource schema/DAO/tests, App API/tests, roadmap, and `specs/002-datasource-governance/**`
- Operation: add a verified-admin owner-transfer API, transactionally update owner and reset approval, record prior/new owner in the append-only audit log, invalidate the connector cache, and document the behavior.
- Acceptance criteria: only verified OIDC admins can transfer; owner and approval state update atomically with audit; failed/no-op transfer leaves no audit entry; new owner requires fresh approval.
- Status: complete

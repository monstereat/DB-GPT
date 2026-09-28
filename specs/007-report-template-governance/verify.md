# Verification: report template governance

## Evidence

- `examples/enterprise-text2sql` full offline suite: 191 passed.
- Template governance regressions: default seeding, role/metric/field restrictions, self-review denial, two-person approval, append-only audit, admin API authorization, and use of an approved release in synchronous XLSX export.
- Existing report-task regression confirms task status retains the semantic template version; queued snapshots still use the existing snapshot/hash validation path.
- Ruff check/format, `compileall`, and `git diff --check` passed.

## Limits

- This is a SQLite workflow for the local synthetic-data demo. It does not provide production multi-instance consistency, enterprise template storage, secret management, or retention/key-retirement operations.

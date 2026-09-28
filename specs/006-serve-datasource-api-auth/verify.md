# Verification: Serve datasource API authorization

- Serve datasource API auth, service/DAO ownership, datasource security, and OIDC context tests: **23 passed**.
- Full DB-GPT Serve test tree with pytest importlib collection: **649 passed, 1 skipped**.
- Ruff check and format check for all five changed Python files: passed.
- No metadata schema, production database, or existing datasource data was changed.

The API key path is intentionally privileged and global for machine clients. Existing rows with no `submitted_by` remain admin/service-key only; there is no ownership backfill in this change.

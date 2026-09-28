# Plan: Agent file download authorization

1. Reuse the existing verified OIDC execution-context helper and conversation-owner lookup; require exact owner match.
2. Restrict the requested real path to `PILOT_PATH/tmp/<conv_uid>` and reject invalid conversation IDs, non-files, traversal, and symlink escapes.
3. Add focused endpoint tests using a temporary artifact directory and mocked owner lookup; do not alter schema or identity configuration.
4. Run focused tests, lint/format, compile, and diff checks; update the roadmap with the implementation boundary.

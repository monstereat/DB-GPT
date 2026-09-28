# Agent artifact download authorization

## Goal

Restrict the Agent file download API to files with a verifiable conversation owner, preventing anonymous and cross-user reads of files elsewhere in the application workspace.

## Scope

- Require a verified OIDC identity for the download endpoint.
- Require the requested conversation to exist and be owned by the verified user.
- Restrict paths to the Agent output directory for that conversation under `PILOT_PATH/tmp/<conv_uid>`.
- Resolve real paths and reject traversal or symlink escapes.
- Preserve the current file response for authorized files; do not add database schema or modify OIDC configuration.

## Acceptance criteria

- Missing/invalid identity is rejected by the existing auth dependency.
- A user cannot download another user's conversation artifact.
- Paths outside the conversation artifact directory, including traversal and symlink escapes, are rejected.
- A regular file inside the authenticated conversation artifact directory is downloadable.
- Tests cover unauthenticated, cross-user, path traversal, and allowed-file behavior.

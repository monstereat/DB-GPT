# Tasks: Agent file download authorization

## T001: Enforce verified identity and conversation ownership

- Acceptance criteria: only a verified user who owns an existing conversation can request an artifact from that conversation's output directory.
- Status: completed

## T002: Constrain artifact path and add regression tests

- Acceptance criteria: path traversal and symlink escapes are denied; authenticated in-scope regular files are returned; tests cover anonymous, foreign owner, traversal, and allowed file.
- Status: completed

## T003: Verify and update roadmap

- Acceptance criteria: focused endpoint tests and formatting/diff checks pass; roadmap records the code-level coverage without claiming production IdP acceptance.
- Status: completed

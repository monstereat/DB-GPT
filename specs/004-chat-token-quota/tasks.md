# Tasks: normal-chat daily token quota

## T001: Wire ChatNormal into the existing shared token quota

- Allowed files: paths listed in `plan.md`.
- Acceptance: AC-01 through AC-05.
- Status: complete

## T002: Verify and update roadmap

- Dependencies: T001.
- Operation: run focused and App API regressions, record evidence and remaining limits.
- Status: complete

## T003: Meter supported chat-completion BaseChat modes

- Acceptance: verified OIDC quota context reaches BaseChat for supported v1/v2 modes; unsupported chat-app/AWEL/domain modes fail closed when quota is enabled; API-key-only behavior remains unchanged when quota is disabled.
- Status: complete

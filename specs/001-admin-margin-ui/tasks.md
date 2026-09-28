# Tasks: role-aware gross margin in the analytics UI

## T001: Implement role-filtered metric discovery and UI integration

- Dependencies: none
- Allowed files: `examples/enterprise-text2sql/api.py`, `examples/enterprise-text2sql/test_api.py`, `examples/enterprise-text2sql/ui/src/api.js`, `examples/enterprise-text2sql/ui/src/api.test.js`, `examples/enterprise-text2sql/ui/src/App.vue`
- Operation: add the published role-filtered metric endpoint; load its bearer-authenticated response in the UI; clear privileged metrics and results on identity changes; support gross-margin analysis and select the admin report template for exports that include it.
- Acceptance criteria: AC-01, AC-02, AC-03
- Verification commands:
  - `PYTHONPATH=../../packages/dbgpt-core/src:../../packages/dbgpt-serve/src:../../packages/dbgpt-ext/src /tmp/dbgpt-app-dashboard-trace-test-venv/bin/python -m pytest -q -o addopts='' test_api.py -k available_metric_catalog`
  - `npm test`
  - `npm run build`
- Completion: admin receives gross margin from the server-filtered catalog and can analyze/export it; non-admin does not receive the metric option; API query/template authorization remains authoritative.
- Evidence: API `1 passed, 41 deselected`; UI `31 passed`; Vite build succeeded; T001 scope report passed.
- Status: done

## T002: Full regression and roadmap evidence

- Dependencies: T001
- Allowed files: `docs/develop-me-roadmap.md`, `specs/001-admin-margin-ui/verify.md`, `specs/001-admin-margin-ui/tasks.md`
- Operation: run the full offline Text-to-SQL suite, review the feature diff, and document verification and remaining production limitations.
- Acceptance criteria: AC-01, AC-02, AC-03
- Verification command: `PYTHONPATH=../../packages/dbgpt-core/src:../../packages/dbgpt-serve/src:../../packages/dbgpt-ext/src /tmp/dbgpt-app-dashboard-trace-test-venv/bin/python -m pytest -q -o addopts=''`
- Completion: full suite passes, roadmap accurately describes the role-aware UI feature and production limits, and diff check passes.
- Evidence: full suite `184 passed`; roadmap and verification record updated; T002 scope gate and `git diff --check` passed.
- Status: done

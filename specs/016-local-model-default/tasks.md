# Tasks: Restore a responsive local model default

## T001: Restore the lightweight model default

- Allowed files: `docker/compose_examples/develop-me-test/compose.yaml`, `docker/compose_examples/develop-me-test/config/dbgpt-test-ollama.toml`, `docker/compose_examples/develop-me-test/README.md`, `specs/016-local-model-default/**`.
- Acceptance criteria: AC-01.
- Verification commands:
  1. `docker compose -p dbgpt-develop-me-test -f docker/compose_examples/develop-me-test/compose.yaml config --quiet`
  2. `docker exec dbgpt-develop-me-test-ollama-1 ollama list`
  3. `curl -fsS http://127.0.0.1:5671/api/health`
- Actions: recreate only the DB-GPT service after the model configuration is changed.
- Status: pending.

## T002: Re-test the screenshot question

- Depends on: T001.
- Allowed files: `docs/develop-me-roadmap.md`, `specs/016-local-model-default/**`.
- Acceptance criteria: AC-02.
- Verification commands:
  1. `.venv/bin/python -m json.tool specs/016-local-model-default/evidence/q01-scorecard.json`
  2. `.venv/bin/python -c 'import json; d=json.load(open("specs/016-local-model-default/evidence/q01-scorecard.json")); assert d["question_count"] == 1; print(d["cases"])'`
- Status: pending.

# Tasks: Local DB-GPT Agent model capacity evaluation

## T001: Configure the local test stack for Qwen3 4B

- Allowed files: `docker/compose_examples/develop-me-test/compose.yaml`, `docker/compose_examples/develop-me-test/config/dbgpt-test-ollama.toml`, `docker/compose_examples/develop-me-test/README.md`, `specs/013-local-agent-model/**`.
- Actions: configure/pull `qwen3:4b`; preserve the current embedding and old model; validate Compose; recreate only the DB-GPT service; verify both containers healthy.
- Acceptance criteria: AC-01.
- Verification commands:
  1. `docker compose -p dbgpt-develop-me-test -f docker/compose_examples/develop-me-test/compose.yaml config --quiet`
  2. `docker exec dbgpt-develop-me-test-ollama-1 ollama list`
  3. `curl -fsS http://127.0.0.1:5671/api/health`
- Status: pending.

## T002: Measure the screenshot question with three isolated runs

- Allowed files: `docs/develop-me-roadmap.md`, `specs/013-local-agent-model/**`.
- Actions: run q01 three times with separate conversation IDs, record each status and hashes only, and state whether the screenshot question is fixed.
- Acceptance criteria: AC-02.
- Verification commands:
  1. `.venv/bin/python -m json.tool specs/013-local-agent-model/evidence/q01-three-run-scorecard.json`
  2. `.venv/bin/python -c 'import json; d=json.load(open("specs/013-local-agent-model/evidence/q01-three-run-scorecard.json")); assert len(d["runs"]) == 3; print(d)'`
- Status: pending.

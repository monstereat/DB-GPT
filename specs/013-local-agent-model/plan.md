# Implementation plan: Local DB-GPT Agent model capacity evaluation

## Approach

1. Capture the task's changed-file baseline.
2. Update only the local Compose Ollama pull command, DB-GPT TOML chat-model entry, README, and roadmap to use `qwen3:4b`; retain the existing embedding model and 1.7B volume content.
3. Pull only `qwen3:4b`, validate Compose, and recreate only the project-owned `dbgpt` service.
4. Run three sequential, isolated q01 gold evaluations using the current live evaluator; store redacted scores only.
5. Record actual results and limitations in the roadmap and verification artifact.

## Resource rationale

Docker reports 8 GiB total memory with DB-GPT using about 1 GiB at idle. The host reports 33 GiB available disk. The official Ollama model library lists `qwen3:4b` as 4.02B parameters and 2.5 GB in Q4_K_M. This is materially larger than the failing 1.7B model and fits the current test machine with room for the DB-GPT service; no 8B+ variant will be pulled.

## Verification

- `.venv/bin/python -m json.tool specs/013-local-agent-model/evidence/q01-three-run-scorecard.json`
- `.venv/bin/python -c 'import json; d=json.load(open("specs/013-local-agent-model/evidence/q01-three-run-scorecard.json")); assert len(d["runs"]) == 3; print(d)'`
- `docker compose -p dbgpt-develop-me-test -f docker/compose_examples/develop-me-test/compose.yaml config --quiet`
- Docker health and `ollama list` checks.

## Files

- `docker/compose_examples/develop-me-test/compose.yaml`
- `docker/compose_examples/develop-me-test/config/dbgpt-test-ollama.toml`
- `docker/compose_examples/develop-me-test/README.md`
- `docs/develop-me-roadmap.md`
- `specs/013-local-agent-model/**`

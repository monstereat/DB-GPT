# Restore a responsive local model default

## Background

The test Compose stack was changed to `qwen3:4b` to address the screenshot's q01 failure. On the current 8 GiB CPU-only Docker VM, qwen3:4b consumed about 3.5 GiB and an isolated q01 request ran for roughly 12 minutes before producing `missing_result`. This is not usable for the local interactive demo. The original `qwen3:1.7b` model is still present in the same Ollama volume.

## Goal

Restore the lightweight qwen3:1.7b default, keep the downloaded 4B model available for later experiments, and validate q01 once after the ReAct prompt-contract fixes.

## Scope

- Includes: change only the local Compose model pull/default TOML and README; recreate the project-owned DB-GPT service; run the screenshot gold case once and record its exact result.
- Excludes: removing either Ollama model, changing Docker limits, production model configuration, and further prompt or SQL-policy changes.

## Acceptance criteria

- **AC-01:** Local Compose config and DB-GPT are healthy with qwen3:1.7b; qwen3:4b remains available in the volume and is not selected by default.
- **AC-02:** The screenshot q01 evaluation emits a structured result and exact-matches gold. If the run still fails, record that local model limitations prevent declaring the user issue fixed.

## Approval basis

The user authorized use of the local Docker test environment and asked for the screenshot issue to be repaired using best judgment. The 4B run demonstrated that model size alone does not fix the issue and causes unacceptable local latency.

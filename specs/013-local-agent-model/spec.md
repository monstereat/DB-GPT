# Local DB-GPT Agent model capacity evaluation

## Background

- The exact screenshot question (`第二季度各地区销售额是多少？`) is case `q01` in the live gold dataset.
- The local DB-GPT Agent currently uses `qwen3:1.7b`. In the completed 50-case live evaluation it scored 0 exact matches, and `q01` was classified as `missing_result`; earlier isolated runs of the same case returned `incorrect`, showing unstable tool execution.
- Docker currently exposes 8 GiB to the test stack and the host has 33 GiB free. A Qwen3 4B Q4_K_M Ollama model is listed at 2.5 GB, so it is the largest reasonable next local test without changing the Docker resource limit.

## Goal

Test whether replacing the local demo chat model with `qwen3:4b` resolves the screenshot's concrete SQL question while retaining the existing DB-GPT SQL authorization and result-event path.

## Scope

- Includes: pull the 2.5 GB model into the existing Ollama model volume; configure the local Compose demo to use it; recreate only the project-owned DB-GPT service; run three isolated `q01` evaluations; update the local README and roadmap with measured results.
- Excludes: changing production model configuration, training/fine-tuning, changing SQL policy or gold data, deleting the existing `qwen3:1.7b` model, and changing Docker Desktop resource settings.

## Acceptance criteria

- **AC-01:** Local Compose config and the running DB-GPT service use `qwen3:4b`; the model is present in the existing Ollama volume and both services are healthy.
- **AC-02:** Three isolated live runs of `q01` emit structured results and return exact gold matches. If this criterion fails, report the observed model result as unresolved rather than claiming the UI issue is fixed.

## Safety and privacy

- Only the synthetic, read-only `ecommerce-demo` datasource is used. No credential, user data, or `.env` is read or changed.
- Preserve the existing 1.7B model and Docker named volumes as a rollback option.
- The pull is bounded to the official `qwen3:4b` Ollama tag (2.5 GB); do not download larger variants.

## Approval basis

The user authorized completing the current DB-GPT roadmap, using the local Docker test environment, and choosing implementation details without repeated confirmations.

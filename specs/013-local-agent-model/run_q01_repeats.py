"""Run the screenshot's q01 case three times against the live DB-GPT Agent."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
EVALUATOR = REPO_ROOT / "examples/enterprise-text2sql/evaluate_agent.py"
GOLD_DATASET = REPO_ROOT / "examples/enterprise-text2sql/gold_questions.json"
OUTPUT = Path(__file__).resolve().parent / "evidence/q01-three-run-scorecard.json"


def main() -> int:
    if not all(
        os.environ.get(key)
        for key in (
            "DBGPT_EVAL_ACCESS_TOKEN",
            "DBGPT_AGENT_API_URL",
            "DBGPT_AGENT_DATABASE",
        )
    ):
        raise SystemExit("Set the local evaluator environment variables first.")

    question = json.loads(GOLD_DATASET.read_text(encoding="utf-8"))[0]
    runs = []
    with tempfile.TemporaryDirectory(prefix="dbgpt-q01-") as temp_dir:
        dataset = Path(temp_dir) / "q01.json"
        dataset.write_text(
            json.dumps([question], ensure_ascii=False), encoding="utf-8"
        )
        for run_number in range(1, 4):
            result = subprocess.run(
                [
                    sys.executable,
                    str(EVALUATOR),
                    "--dataset",
                    str(dataset),
                    "--timeout",
                    "120",
                ],
                cwd=REPO_ROOT,
                env=os.environ.copy(),
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode not in {0, 1}:
                raise SystemExit(
                    "A live q01 evaluation failed before producing a scorecard."
                )
            try:
                scorecard = json.loads(result.stdout)
                case = scorecard["cases"][0]
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
                raise SystemExit(
                    "A live q01 evaluation returned an invalid scorecard."
                ) from error
            runs.append(
                {
                    "run": run_number,
                    "status": case["status"],
                    "result_sha256": case["result_sha256"],
                }
            )

    correct = sum(run["status"] == "correct" for run in runs)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {
                "question_id": "q01",
                "question_count": len(runs),
                "correct_runs": correct,
                "runs": runs,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"question_id": "q01", "correct_runs": correct, "runs": runs}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

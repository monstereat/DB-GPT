"""Score real DB-GPT ReAct SQL results against the synthetic gold dataset.

Unlike ``evaluate_candidates.py``, this runner calls a live DB-GPT API. It
records result status and hashes only; prompts, SQL, answers, row values, and
access tokens are never written to the scorecard.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import socket
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ecommerce_demo import gold_rows_match

MAX_EVENT_STREAM_BYTES = 2 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 180
GOLD_QUESTIONS = json.loads(
    Path(__file__).with_name("gold_questions.json").read_text(encoding="utf-8")
)


class AgentEvaluationError(RuntimeError):
    """Sanitized error safe to show in CLI output."""


class AgentEvaluationTimeoutError(AgentEvaluationError):
    """A single live request exceeded its configured timeout."""


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def _validate_api_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
        _ = parsed.port
        if parsed.scheme == "http":
            try:
                loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                loopback = host.rstrip(".").lower() == "localhost"
            if not loopback:
                raise ValueError
    except ValueError as error:
        raise AgentEvaluationError(
            "Agent API URL must be an HTTPS origin or loopback HTTP origin."
        ) from error
    return value.rstrip("/")


def _parse_events(body: bytes) -> list[dict[str, Any]]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise AgentEvaluationError("Agent event stream is not valid UTF-8.") from error

    events = []
    frame = []
    for line in text.splitlines() + [""]:
        if not line:
            data = "\n".join(
                item[5:].lstrip() for item in frame if item.startswith("data:")
            )
            frame = []
            if not data or data == "[DONE]":
                continue
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
        elif not line.startswith(":"):
            frame.append(line)
    return events


def _sql_result(events: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, bool]:
    result = None
    malformed = False
    for event in events:
        candidate = event.get("result")
        if event.get("type") != "step.result" or not isinstance(candidate, dict):
            continue
        if candidate.get("type") != "sql_result":
            continue
        columns = candidate.get("columns")
        rows = candidate.get("rows")
        row_count = candidate.get("row_count")
        truncated = candidate.get("truncated")
        if (
            not isinstance(columns, list)
            or not all(isinstance(column, str) for column in columns)
            or not isinstance(rows, list)
            or len(rows) > 50
            or not all(
                isinstance(row, list) and len(row) == len(columns) for row in rows
            )
            or type(row_count) is not int
            or row_count < len(rows)
            or type(truncated) is not bool
        ):
            malformed = True
            continue
        result = {
            "columns": columns,
            "rows": rows,
            "row_count": row_count,
            "truncated": truncated,
        }
    return result, malformed


def _final_answer(events: list[dict[str, Any]]) -> str:
    return "\n".join(
        event["content"]
        for event in events
        if event.get("type") == "final" and isinstance(event.get("content"), str)
    )


def _request_sql_result(
    *,
    api_url: str,
    database_name: str,
    access_token: str,
    question: str,
    conversation_id: str | None,
    timeout_seconds: int,
    opener: Any,
) -> tuple[dict[str, Any] | None, bool, str, bool]:
    endpoint = f"{api_url}/api/v1/chat/react-agent"
    payload = {
        "conv_uid": conversation_id or str(uuid.uuid4()),
        "user_input": question,
        "chat_mode": "chat_with_db_execute",
        "ext_info": {"database_name": database_name},
    }
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            body = response.read(MAX_EVENT_STREAM_BYTES + 1)
    except HTTPError as error:
        error.close()
        if error.code in {408, 504}:
            raise AgentEvaluationTimeoutError("Agent request timed out.") from error
        raise AgentEvaluationError(
            f"Agent request failed with HTTP {error.code}; check the API, token, "
            "and datasource access."
        ) from error
    except (TimeoutError, socket.timeout) as error:
        raise AgentEvaluationTimeoutError("Agent request timed out.") from error
    except URLError as error:
        if isinstance(error.reason, (TimeoutError, socket.timeout)):
            raise AgentEvaluationTimeoutError("Agent request timed out.") from error
        raise AgentEvaluationError(
            "Agent request failed; check API availability and timeout settings."
        ) from error
    except OSError as error:
        raise AgentEvaluationError(
            "Agent request failed; check API availability and timeout settings."
        ) from error
    if len(body) > MAX_EVENT_STREAM_BYTES:
        raise AgentEvaluationError("Agent event stream exceeded the 2 MiB limit.")
    events = _parse_events(body)
    result, malformed = _sql_result(events)
    completed = any(event.get("type") == "done" for event in events)
    return result, malformed, _final_answer(events), completed


def _conversation_id_for(
    item: dict[str, Any], conversation_ids: dict[str, str]
) -> str | None:
    group = item.get("conversation_group")
    if group is None:
        return None
    if not isinstance(group, str) or not group.strip():
        raise AgentEvaluationError("Evaluation case has an invalid conversation group.")
    if group not in conversation_ids:
        conversation_ids[group] = str(uuid.uuid4())
    return conversation_ids[group]


def evaluate_live_agent(
    *,
    api_url: str,
    database_name: str,
    access_token: str,
    questions: list[dict[str, Any]] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    opener: Any | None = None,
) -> dict[str, Any]:
    """Call DB-GPT once per gold question and score the structured SQL result."""
    api_url = _validate_api_url(api_url)
    if not isinstance(database_name, str) or not database_name.strip():
        raise AgentEvaluationError("A DB-GPT datasource name is required.")
    if not isinstance(access_token, str) or not access_token.strip():
        raise AgentEvaluationError("An OIDC access token is required.")
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 600:
        raise AgentEvaluationError("Timeout must be an integer from 1 to 600 seconds.")

    active_opener = opener or build_opener(_NoRedirectHandler())
    outcomes = []
    conversation_ids: dict[str, str] = {}
    for item in GOLD_QUESTIONS if questions is None else questions:
        if not isinstance(item, dict):
            raise AgentEvaluationError("Gold question bundle has an invalid shape.")
        question_id = item.get("id")
        question = item.get("question")
        expected = item.get("expected")
        order_sensitive = item.get("order_sensitive", True)
        category = item.get("category", "unclassified")
        if (
            not isinstance(question_id, str)
            or not isinstance(question, str)
            or not isinstance(category, str)
            or not category
            or len(category) > 64
            or type(order_sensitive) is not bool
            or not isinstance(expected, dict)
            or not isinstance(expected.get("columns"), list)
            or not isinstance(expected.get("rows"), list)
        ):
            raise AgentEvaluationError("Gold question bundle has an invalid shape.")

        conversation_id = _conversation_id_for(item, conversation_ids)

        started_at = time.monotonic()
        try:
            actual, malformed, _final, completed = _request_sql_result(
                api_url=api_url,
                database_name=database_name,
                access_token=access_token,
                question=question,
                conversation_id=conversation_id,
                timeout_seconds=timeout_seconds,
                opener=active_opener,
            )
        except AgentEvaluationTimeoutError:
            status = "timeout"
            result_hash = None
        else:
            if not completed:
                status = "incomplete_stream"
                result_hash = None
            elif actual is None:
                status = "invalid_result" if malformed else "missing_result"
                result_hash = None
            elif actual["truncated"]:
                status = "truncated"
                result_hash = _result_hash(actual)
            else:
                passed = actual["columns"] == expected["columns"] and gold_rows_match(
                    question_id,
                    actual["rows"],
                    expected["rows"],
                    order_sensitive=order_sensitive,
                )
                status = "correct" if passed else "incorrect"
                result_hash = _result_hash(actual)
        outcomes.append(
            {
                "question_id": question_id,
                "category": category,
                "status": status,
                "result_sha256": result_hash,
                "duration_ms": max(0, round((time.monotonic() - started_at) * 1000)),
            }
        )

    count = len(outcomes)
    correct = sum(item["status"] == "correct" for item in outcomes)
    by_category = {}
    for category in sorted({item["category"] for item in outcomes}):
        category_outcomes = [item for item in outcomes if item["category"] == category]
        category_count = len(category_outcomes)
        category_correct = sum(
            item["status"] == "correct" for item in category_outcomes
        )
        by_category[category] = {
            "question_count": category_count,
            "correct": category_correct,
            "incorrect": sum(
                item["status"] == "incorrect" for item in category_outcomes
            ),
            "missing_result": sum(
                item["status"] == "missing_result" for item in category_outcomes
            ),
            "invalid_result": sum(
                item["status"] == "invalid_result" for item in category_outcomes
            ),
            "truncated": sum(
                item["status"] == "truncated" for item in category_outcomes
            ),
            "incomplete_stream": sum(
                item["status"] == "incomplete_stream" for item in category_outcomes
            ),
            "timeout": sum(item["status"] == "timeout" for item in category_outcomes),
            "accuracy": category_correct / category_count if category_count else 0,
        }
    return {
        "question_count": count,
        "correct": correct,
        "incorrect": sum(item["status"] == "incorrect" for item in outcomes),
        "missing_result": sum(item["status"] == "missing_result" for item in outcomes),
        "invalid_result": sum(item["status"] == "invalid_result" for item in outcomes),
        "truncated": sum(item["status"] == "truncated" for item in outcomes),
        "incomplete_stream": sum(
            item["status"] == "incomplete_stream" for item in outcomes
        ),
        "timeout": sum(item["status"] == "timeout" for item in outcomes),
        "result_accuracy": correct / count if count else 0,
        "by_category": by_category,
        "macro_average_accuracy": (
            sum(item["accuracy"] for item in by_category.values()) / len(by_category)
            if by_category
            else 0
        ),
        "cases": outcomes,
        "note": (
            "Live DB-GPT ReAct structured SQL results compared with fixed synthetic "
            "gold answers; not a production authorization certification."
        ),
    }


def aggregate_live_agent_runs(scorecards: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize repeated sanitized gold scorecards without exposing result data."""
    if not isinstance(scorecards, list) or not scorecards:
        raise AgentEvaluationError("At least one completed scorecard is required.")
    baseline = scorecards[0].get("cases")
    if not isinstance(baseline, list):
        raise AgentEvaluationError("Repeated scorecard has an invalid case list.")
    baseline_keys = [
        (case.get("question_id"), case.get("category")) for case in baseline
    ]
    if any(
        not isinstance(key[0], str) or not isinstance(key[1], str)
        for key in baseline_keys
    ):
        raise AgentEvaluationError("Repeated scorecard has an invalid case key.")

    cases_by_run = []
    for scorecard in scorecards:
        cases = scorecard.get("cases") if isinstance(scorecard, dict) else None
        if (
            not isinstance(cases, list)
            or [(case.get("question_id"), case.get("category")) for case in cases]
            != baseline_keys
        ):
            raise AgentEvaluationError(
                "Repeated scorecards contain different questions."
            )
        cases_by_run.append(cases)

    per_question = []
    for index, (question_id, category) in enumerate(baseline_keys):
        attempts = [cases[index] for cases in cases_by_run]
        status_counts: dict[str, int] = {}
        for attempt in attempts:
            status = attempt.get("status")
            if not isinstance(status, str):
                raise AgentEvaluationError("Repeated scorecard has an invalid status.")
            status_counts[status] = status_counts.get(status, 0) + 1
        correct_count = status_counts.get("correct", 0)
        hashes = {
            attempt.get("result_sha256")
            for attempt in attempts
            if isinstance(attempt.get("result_sha256"), str)
        }
        per_question.append(
            {
                "question_id": question_id,
                "category": category,
                "run_count": len(attempts),
                "correct_count": correct_count,
                "accuracy": correct_count / len(attempts),
                "status_counts": status_counts,
                "distinct_result_hashes": len(hashes),
            }
        )

    run_accuracies = [scorecard.get("result_accuracy", 0) for scorecard in scorecards]
    by_category = {}
    for category in sorted({case["category"] for case in per_question}):
        category_cases = [case for case in per_question if case["category"] == category]
        by_category[category] = {
            "question_count": len(category_cases),
            "mean_question_accuracy": sum(case["accuracy"] for case in category_cases)
            / len(category_cases),
            "all_runs_correct": sum(
                case["correct_count"] == len(scorecards) for case in category_cases
            ),
        }

    return {
        "run_count": len(scorecards),
        "question_count": len(baseline_keys),
        "attempt_count": len(baseline_keys) * len(scorecards),
        "mean_result_accuracy": sum(run_accuracies) / len(run_accuracies),
        "min_result_accuracy": min(run_accuracies),
        "max_result_accuracy": max(run_accuracies),
        "by_category": by_category,
        "question_stability": per_question,
        "runs": scorecards,
        "note": (
            "Repeated live DB-GPT ReAct scorecards use fixed synthetic gold data. "
            "Hashes indicate result variation without storing SQL or row values; "
            "this is not a production authorization certification."
        ),
    }


def evaluate_live_agent_repeated(
    *,
    api_url: str,
    database_name: str,
    access_token: str,
    questions: list[dict[str, Any]] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    run_count: int = 2,
    opener: Any | None = None,
) -> dict[str, Any]:
    """Run the same live gold bundle repeatedly with fresh conversations."""
    if type(run_count) is not int or not 2 <= run_count <= 5:
        raise AgentEvaluationError("Repeated evaluation runs must be from 2 to 5.")
    scorecards = [
        evaluate_live_agent(
            api_url=api_url,
            database_name=database_name,
            access_token=access_token,
            questions=questions,
            timeout_seconds=timeout_seconds,
            opener=opener,
        )
        for _ in range(run_count)
    ]
    return aggregate_live_agent_runs(scorecards)


def evaluate_live_agent_policies(
    *,
    api_url: str,
    database_name: str,
    access_token: str,
    cases: list[dict[str, Any]],
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    opener: Any | None = None,
) -> dict[str, Any]:
    """Score live denial/clarification behavior from final and SQL-result events."""
    api_url = _validate_api_url(api_url)
    if not isinstance(database_name, str) or not database_name.strip():
        raise AgentEvaluationError("A DB-GPT datasource name is required.")
    if not isinstance(access_token, str) or not access_token.strip():
        raise AgentEvaluationError("An OIDC access token is required.")
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 600:
        raise AgentEvaluationError("Timeout must be an integer from 1 to 600 seconds.")
    if not isinstance(cases, list):
        raise AgentEvaluationError("Policy dataset must be a JSON array.")

    active_opener = opener or build_opener(_NoRedirectHandler())
    conversation_ids: dict[str, str] = {}
    outcomes = []
    for case in cases:
        if not isinstance(case, dict):
            raise AgentEvaluationError("Policy dataset has an invalid case shape.")
        case_id = case.get("id")
        question = case.get("question")
        behavior = case.get("expected_behavior")
        response_terms = case.get("required_response_terms")
        if (
            not isinstance(case_id, str)
            or not isinstance(question, str)
            or not isinstance(behavior, str)
            or behavior not in {"deny", "clarify"}
            or not isinstance(response_terms, list)
            or not response_terms
            or not all(isinstance(term, str) and term for term in response_terms)
        ):
            raise AgentEvaluationError("Policy dataset has an invalid case shape.")

        result, malformed, final, completed = _request_sql_result(
            api_url=api_url,
            database_name=database_name,
            access_token=access_token,
            question=question,
            conversation_id=_conversation_id_for(case, conversation_ids),
            timeout_seconds=timeout_seconds,
            opener=active_opener,
        )
        if not completed:
            status = "incomplete_stream"
        elif result is not None:
            status = "unexpected_sql_result"
        elif malformed:
            status = "invalid_sql_result"
        elif not final.strip():
            status = "missing_final"
        elif any(term.casefold() in final.casefold() for term in response_terms):
            status = "denied" if behavior == "deny" else "clarified"
        else:
            status = "unclassified_response"
        outcomes.append(
            {
                "case_id": case_id,
                "expected_behavior": behavior,
                "status": status,
                "response_sha256": hashlib.sha256(final.encode("utf-8")).hexdigest()
                if final
                else None,
            }
        )

    count = len(outcomes)
    correct = sum(
        item["status"] == "denied" or item["status"] == "clarified" for item in outcomes
    )
    by_behavior = {}
    for behavior in sorted({item["expected_behavior"] for item in outcomes}):
        behavior_outcomes = [
            item for item in outcomes if item["expected_behavior"] == behavior
        ]
        behavior_count = len(behavior_outcomes)
        behavior_correct = sum(
            item["status"] == "denied" or item["status"] == "clarified"
            for item in behavior_outcomes
        )
        by_behavior[behavior] = {
            "case_count": behavior_count,
            "correct": behavior_correct,
            "incorrect": behavior_count - behavior_correct,
            "accuracy": behavior_correct / behavior_count if behavior_count else 0,
        }
    return {
        "case_count": count,
        "correct": correct,
        "incorrect": count - correct,
        "policy_accuracy": correct / count if count else 0,
        "by_behavior": by_behavior,
        "macro_average_policy_accuracy": (
            sum(item["accuracy"] for item in by_behavior.values()) / len(by_behavior)
            if by_behavior
            else 0
        ),
        "cases": outcomes,
        "note": (
            "Live policy checks require a final refusal/clarification signal and no "
            "structured SQL result; this does not certify production authorization."
        ),
    }


def _result_hash(result: dict[str, Any]) -> str:
    encoded = json.dumps(
        {"columns": result["columns"], "rows": result["rows"]},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.getenv("DBGPT_AGENT_API_URL"))
    parser.add_argument("--database", default=os.getenv("DBGPT_AGENT_DATABASE"))
    parser.add_argument("--evaluation-type", choices=("gold", "policy"), default="gold")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path(__file__).with_name("gold_questions.json"),
        help=(
            "JSON array of questions and expected results; conversation_group "
            "reuses context."
        ),
    )
    parser.add_argument("--token-env", default="DBGPT_EVAL_ACCESS_TOKEN")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="repeat gold evaluation 2–5 times to measure run-to-run stability",
    )
    args = parser.parse_args(argv)
    token = os.getenv(args.token_env, "")
    if not args.api_url or not args.database or not token:
        parser.error(
            "set --api-url/DBGPT_AGENT_API_URL, --database/DBGPT_AGENT_DATABASE, "
            f"and the {args.token_env} environment variable"
        )
    try:
        try:
            questions = json.loads(args.dataset.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise AgentEvaluationError(
                "Unable to read the evaluation dataset."
            ) from error
        if not isinstance(questions, list):
            raise AgentEvaluationError("Evaluation dataset must be a JSON array.")
        request_config = {
            "api_url": args.api_url,
            "database_name": args.database,
            "access_token": token,
            "timeout_seconds": args.timeout,
        }
        if args.evaluation_type == "gold":
            if args.runs == 1:
                scorecard = evaluate_live_agent(**request_config, questions=questions)
            else:
                scorecard = evaluate_live_agent_repeated(
                    **request_config,
                    questions=questions,
                    run_count=args.runs,
                )
        else:
            if args.runs != 1:
                raise AgentEvaluationError(
                    "Repeated runs are currently supported for gold evaluation only."
                )
            scorecard = evaluate_live_agent_policies(**request_config, cases=questions)
    except AgentEvaluationError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(scorecard, ensure_ascii=False, indent=2))
    accuracy = scorecard.get(
        "result_accuracy",
        scorecard.get("mean_result_accuracy", scorecard.get("policy_accuracy", 0)),
    )
    return 0 if accuracy == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

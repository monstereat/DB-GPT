import json

import pytest

from dbgpt.agent.core.action.base import ActionOutput
from dbgpt.agent.expand.actions.react_action import (
    ReActAction,
    _non_retryable_sql_error,
)


def _observation(retryable):
    return json.dumps(
        {
            "error": {
                "retryable": retryable,
                "message": "SQL 查询失败。",
            }
        }
    )


@pytest.mark.parametrize(
    ("action", "observation", "expected"),
    [
        ("sql_query", _observation(False), "SQL 查询失败。"),
        ("sql_query", _observation(True), None),
        ("other_tool", _observation(False), None),
        ("sql_query", "not-json", None),
    ],
)
def test_non_retryable_sql_error_is_narrowly_classified(action, observation, expected):
    assert _non_retryable_sql_error(action, observation) == expected


@pytest.mark.asyncio
async def test_react_action_stops_on_non_retryable_sql_error(monkeypatch):
    action = object.__new__(ReActAction)

    async def _run_tool(_self, *_args, **_kwargs):
        return ActionOutput(
            content=_observation(False),
            observations=_observation(False),
        )

    monkeypatch.setattr(ReActAction, "_do_run", _run_tool)
    result = await action.run("Action: sql_query\nAction Input: {}")

    assert result.action == "sql_query"
    assert result.is_exe_success is False
    assert result.have_retry is False
    assert result.terminate is True
    assert result.content == "SQL 查询失败。"

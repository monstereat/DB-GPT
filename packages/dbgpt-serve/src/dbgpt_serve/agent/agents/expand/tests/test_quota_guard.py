import pytest

from dbgpt_serve.agent.agents.expand.actions.volatility_analysis_action import (
    VolatilityAnalysisAction,
)


@pytest.mark.parametrize(
    "setting_name",
    ["DBGPT_DAILY_TOKEN_LIMIT", "DBGPT_REACT_DAILY_TOKEN_LIMIT"],
)
@pytest.mark.asyncio
async def test_volatility_analysis_sub_agent_fails_closed_when_quota_enabled(
    monkeypatch, setting_name
):
    monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "")
    monkeypatch.setenv("DBGPT_REACT_DAILY_TOKEN_LIMIT", "")
    monkeypatch.setenv(setting_name, "1000")
    action = VolatilityAnalysisAction()

    result = await action.run(
        '{"metric_name":"sales","baseline_total":10,"current_total":12,'
        '"baseline_time_range":"last week","current_time_range":"this week",'
        '"dimension":"region"}',
        need_vis_render=False,
    )

    assert result.is_exe_success is False
    assert "Daily token quota is not available" in result.content

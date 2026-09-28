import pytest
from fastapi import BackgroundTasks, HTTPException

from dbgpt_serve.evaluate.api import endpoints
from dbgpt_serve.evaluate.api.schemas import BenchmarkServeRequest, EvaluateServeRequest


class EvaluationService:
    def __init__(self):
        self.called = False

    async def run_evaluation(self, *args):
        self.called = True
        return {"status": "ok"}


@pytest.mark.parametrize(
    "setting_name",
    ["DBGPT_DAILY_TOKEN_LIMIT", "DBGPT_REACT_DAILY_TOKEN_LIMIT"],
)
@pytest.mark.parametrize(
    ("scene_key", "metric"),
    [
        ("recall", "RetrieverSimilarityMetric"),
        ("recall", "custom_metric"),
        ("app", "AnswerRelevancyMetric"),
        ("app", "custom_metric"),
    ],
)
@pytest.mark.asyncio
async def test_evaluation_fails_closed_when_daily_quota_enabled(
    monkeypatch, setting_name, scene_key, metric
):
    monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "")
    monkeypatch.setenv("DBGPT_REACT_DAILY_TOKEN_LIMIT", "")
    monkeypatch.setenv(setting_name, "1000")
    service = EvaluationService()

    with pytest.raises(HTTPException) as exc_info:
        await endpoints.evaluation(
            EvaluateServeRequest(
                scene_key=scene_key,
                scene_value="test",
                datasets=[],
                context={},
                evaluate_metrics=[metric],
            ),
            service,
        )

    assert exc_info.value.status_code == 503
    assert service.called is False


@pytest.mark.parametrize(
    "setting_name",
    ["DBGPT_DAILY_TOKEN_LIMIT", "DBGPT_REACT_DAILY_TOKEN_LIMIT"],
)
@pytest.mark.asyncio
async def test_benchmark_fails_closed_before_scheduling_when_quota_enabled(
    monkeypatch, setting_name
):
    monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "")
    monkeypatch.setenv("DBGPT_REACT_DAILY_TOKEN_LIMIT", "")
    monkeypatch.setenv(setting_name, "1000")
    background_tasks = BackgroundTasks()

    with pytest.raises(HTTPException) as exc_info:
        await endpoints.execute_benchmark_task(
            # Request-body identity is not an authenticated OIDC quota context.
            BenchmarkServeRequest(user_id="spoofed-user"),
            background_tasks,
            service=object(),
        )

    assert exc_info.value.status_code == 503
    assert background_tasks.tasks == []

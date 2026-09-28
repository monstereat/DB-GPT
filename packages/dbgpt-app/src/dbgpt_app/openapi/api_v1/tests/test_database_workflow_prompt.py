import json
from pathlib import Path
from types import SimpleNamespace

from dbgpt_app.openapi.api_v1.agentic_data_api import (
    _database_workflow_prompt,
    _ecommerce_demo_clarification,
    _ecommerce_demo_order_count_sql,
    _ecommerce_demo_product_analysis_sql,
    _ecommerce_demo_q2_average_order_sql,
    _ecommerce_demo_q2_scalar_analysis_sql,
    _ecommerce_demo_q2_total_metric_parameters,
    _ecommerce_demo_regional_order_count_sql,
    _ecommerce_demo_regional_status_breakdown_sql,
    _ensure_expected_metric_action,
    _ensure_expected_sql_action,
    _format_metric_leader,
    _format_sales_share_result,
    _is_ecommerce_monthly_refund_request,
    _is_ecommerce_monthly_sales_request,
    _is_ecommerce_regional_refund_request,
    _is_ecommerce_regional_sales_request,
    _is_ecommerce_south_china_sales_refund_request,
    _is_south_china_city_refund_followup,
    _is_south_china_sales_share_followup,
    _published_metric_intent_parameters,
)


def test_database_workflow_prompt_uses_core_react_terminate_schema():
    prompt = _database_workflow_prompt(
        metric_instruction="Use the metric catalog.",
        database_context="Use the registered database schema.",
    )

    assert 'Action Input: {"result": "concise answer"}' in prompt
    assert 'Action Input: {"output":' not in prompt
    assert 'Action Input: {"sql": "one read-only SELECT query"}' in prompt
    assert "Action Intention:" in prompt
    assert "Action Reason:" in prompt
    assert "Phase: 返回最终结果" in prompt
    assert "metric_catalog when it" in prompt
    assert "metric_query" in prompt
    normalized_prompt = " ".join(prompt.split())
    assert (
        "Never call terminate in the same response as a data query" in normalized_prompt
    )
    assert (
        "never call terminate before the latest metric or SQL query has returned"
        in normalized_prompt
    )
    assert "ask one concise clarifying question" in normalized_prompt
    assert (
        "without calling metric_catalog, metric_query, or sql_query"
        in normalized_prompt
    )
    assert '"recent performance" or "best product"' in normalized_prompt
    assert "Use the metric catalog." in prompt
    assert "Use the registered database schema." in prompt


def test_ecommerce_regional_sales_request_is_narrowly_classified():
    assert _is_ecommerce_regional_sales_request(
        "ecommerce-demo", "2026 年第二季度各地区销售额是多少？"
    )
    assert _is_ecommerce_regional_sales_request(
        "ecommerce-demo", "2026 年第二季度各城市销售额是多少？"
    )
    assert _is_ecommerce_regional_sales_request(
        "ecommerce-demo", "Q2 2026 sales revenue by city?"
    )
    assert _is_ecommerce_regional_sales_request(
        "ecommerce-demo", "Sales revenue by area for the second quarter of 2026?"
    )
    assert _is_ecommerce_regional_sales_request(
        "ecommerce-demo", "各地区第二季度销售额是多少？"
    )
    assert not _is_ecommerce_regional_sales_request(
        "ecommerce-demo", "2025 年第二季度各地区销售额是多少？"
    )
    assert not _is_ecommerce_regional_sales_request(
        "ecommerce-demo", "2026 年第一季度各地区销售额是多少？"
    )
    assert not _is_ecommerce_regional_sales_request(
        "ecommerce-demo", "2026 年第三季度各城市销售额是多少？"
    )
    assert not _is_ecommerce_regional_sales_request(
        "ecommerce-demo", "2026 Q2 total sales revenue?"
    )
    assert not _is_ecommerce_regional_sales_request(
        "ecommerce-demo", "2026 年第二季度各城市销售额同比增长多少？"
    )
    assert not _is_ecommerce_regional_sales_request(
        "ecommerce-demo", "2026 年第二季度各地区销售额与去年同期相比如何？"
    )
    assert not _is_ecommerce_regional_sales_request(
        "ecommerce-demo", "Q2 2026 sales revenue by city year-over-year growth?"
    )
    assert not _is_ecommerce_regional_sales_request(
        "ecommerce-demo", "Q2 2026 sales revenue increase by region?"
    )
    assert not _is_ecommerce_regional_sales_request(
        "ecommerce-demo", "第二季度各地区退款金额是多少？"
    )
    assert not _is_ecommerce_regional_sales_request(
        "production-db", "2026 年第二季度各地区销售额是多少？"
    )


def test_ecommerce_regional_refund_request_is_narrowly_classified():
    assert _is_ecommerce_regional_refund_request(
        "ecommerce-demo", "第二季度各地区退款金额是多少？"
    )
    assert _is_ecommerce_regional_refund_request(
        "ecommerce-demo", "2026 年第二季度各区域退款额是多少？"
    )
    assert not _is_ecommerce_regional_refund_request(
        "ecommerce-demo", "2025 年第二季度各地区退款金额是多少？"
    )
    assert not _is_ecommerce_regional_refund_request(
        "ecommerce-demo", "第二季度各地区退款率是多少？"
    )
    assert not _is_ecommerce_regional_refund_request(
        "ecommerce-demo", "第二季度各地区净销售额是多少？"
    )
    assert not _is_ecommerce_regional_refund_request(
        "production-db", "第二季度各地区退款金额是多少？"
    )


def test_ecommerce_monthly_sales_request_is_narrowly_classified():
    assert _is_ecommerce_monthly_sales_request(
        "ecommerce-demo", "第二季度每月销售额是多少？"
    )
    assert _is_ecommerce_monthly_sales_request(
        "ecommerce-demo", "Q2 2026 monthly sales revenue?"
    )
    assert not _is_ecommerce_monthly_sales_request(
        "ecommerce-demo", "2025 年第二季度每月销售额是多少？"
    )
    assert not _is_ecommerce_monthly_sales_request(
        "ecommerce-demo", "第二季度各地区每月销售额是多少？"
    )
    assert not _is_ecommerce_monthly_sales_request(
        "production-db", "第二季度每月销售额是多少？"
    )


def test_ecommerce_monthly_refund_request_is_narrowly_classified():
    assert _is_ecommerce_monthly_refund_request(
        "ecommerce-demo", "第二季度每月退款金额是多少？"
    )
    assert _is_ecommerce_monthly_refund_request(
        "ecommerce-demo", "Q2 2026 monthly refund amount?"
    )
    assert not _is_ecommerce_monthly_refund_request(
        "ecommerce-demo", "2025 年第二季度每月退款金额是多少？"
    )
    assert not _is_ecommerce_monthly_refund_request(
        "ecommerce-demo", "第二季度各地区每月退款金额是多少？"
    )
    assert not _is_ecommerce_monthly_refund_request(
        "ecommerce-demo", "第二季度每月退款率是多少？"
    )


def test_ecommerce_q2_average_order_sql_is_narrowly_classified():
    sql = _ecommerce_demo_q2_average_order_sql(
        "ecommerce-demo", "第二季度平均订单金额是多少？"
    )
    assert sql is not None
    assert "AVG(total_cents) AS average_order_cents" in sql
    assert "status = 'completed'" in sql
    assert (
        _ecommerce_demo_q2_average_order_sql(
            "ecommerce-demo", "2025 年第二季度平均订单金额是多少？"
        )
        is None
    )
    assert (
        _ecommerce_demo_q2_average_order_sql(
            "ecommerce-demo", "第二季度各地区平均订单金额是多少？"
        )
        is None
    )
    assert (
        _ecommerce_demo_q2_average_order_sql(
            "production-db", "第二季度平均订单金额是多少？"
        )
        is None
    )


def test_ecommerce_q2_product_analysis_sql_is_narrowly_classified():
    category_sales = _ecommerce_demo_product_analysis_sql(
        "ecommerce-demo", "2026 年第二季度各商品类别销售额是多少？"
    )
    assert "p.category AS category" in category_sales
    assert "SUM(i.quantity*i.unit_price_cents) AS sales_cents" in category_sales
    assert "o.tenant_id=i.tenant_id AND o.order_id=i.order_id" in category_sales
    assert "p.tenant_id=i.tenant_id AND p.product_id=i.product_id" in category_sales
    assert "o.status = 'completed'" in category_sales

    category_units = _ecommerce_demo_product_analysis_sql(
        "ecommerce-demo", "2026 年第二季度各品类商品销量是多少？"
    )
    assert "p.category AS category" in category_units
    assert "SUM(i.quantity) AS units" in category_units

    product_units = _ecommerce_demo_product_analysis_sql(
        "ecommerce-demo", "2026 年第二季度各商品销量是多少？"
    )
    assert "p.product_name AS product_name" in product_units
    assert "SUM(i.quantity) AS units" in product_units

    assert (
        _ecommerce_demo_product_analysis_sql(
            "ecommerce-demo", "2025 年第二季度各商品类别销售额是多少？"
        )
        is None
    )
    assert (
        _ecommerce_demo_product_analysis_sql(
            "other-db", "2026 年第二季度各商品类别销售额是多少？"
        )
        is None
    )
    assert (
        _ecommerce_demo_product_analysis_sql(
            "ecommerce-demo", "2026 年第二季度各商品类别销售额同比增长多少？"
        )
        is None
    )
    for question in (
        "第二季度按地区的各商品类别销售额是多少？",
        "第二季度每月各商品类别销量是多少？",
        "第二季度各商品类别和各商品销量分别是多少？",
        "比较第二季度和第三季度各商品类别销量",
        "第二季度各商品销量和销售额分别是多少？",
    ):
        assert _ecommerce_demo_product_analysis_sql("ecommerce-demo", question) is None


def test_ecommerce_q2_scalar_analysis_sql_is_narrowly_classified():
    expected = {
        "第二季度四月完成了多少笔订单？": (
            "SELECT COUNT(*) AS orders FROM orders WHERE created_at >= '2026-04-01' "
            "AND created_at < '2026-05-01' AND status = 'completed'"
        ),
        "第二季度五月完成了多少笔订单？": (
            "SELECT COUNT(*) AS orders FROM orders WHERE created_at >= '2026-05-01' "
            "AND created_at < '2026-06-01' AND status = 'completed'"
        ),
        "第二季度六月完成了多少笔订单？": (
            "SELECT COUNT(*) AS orders FROM orders WHERE created_at >= '2026-06-01' "
            "AND created_at < '2026-07-01' AND status = 'completed'"
        ),
        "第二季度有多少种商品售出？": (
            "SELECT COUNT(DISTINCT i.product_id) AS products FROM order_items i "
            "JOIN orders o ON o.tenant_id=i.tenant_id AND o.order_id=i.order_id "
            "WHERE o.created_at >= '2026-04-01' AND o.created_at < '2026-07-01' "
            "AND o.status = 'completed'"
        ),
        "第二季度最大完成订单金额是多少？": (
            "SELECT MAX(total_cents) AS max_order_cents FROM orders "
            "WHERE created_at >= '2026-04-01' AND created_at < '2026-07-01' "
            "AND status = 'completed'"
        ),
        "第二季度最小完成订单金额是多少？": (
            "SELECT MIN(total_cents) AS min_order_cents FROM orders "
            "WHERE created_at >= '2026-04-01' AND created_at < '2026-07-01' "
            "AND status = 'completed'"
        ),
        "第二季度平均退款金额是多少？": (
            "SELECT AVG(amount_cents) AS average_refund_cents FROM refunds "
            "WHERE created_at >= '2026-04-01' AND created_at < '2026-07-01' "
            "AND status = 'paid'"
        ),
    }
    for question, expected_sql in expected.items():
        assert (
            _ecommerce_demo_q2_scalar_analysis_sql("ecommerce-demo", question)
            == expected_sql
        )

    for question in (
        "2025 年第二季度最大完成订单金额是多少？",
        "第二季度各地区最大完成订单金额是多少？",
        "第二季度每月完成订单数是多少？",
        "第二季度平均退款率是多少？",
        "第二季度取消订单最小金额是多少？",
        "第二季度按客户统计已完成订单金额最高值",
        "第二季度各渠道平均退款金额是多少？",
        "第二季度各月中五月完成订单有多少？",
        "比较第二季度和第一季度完成订单金额最大值",
        "第二季度最大和最小完成订单金额是多少？",
        "Q2 how many products were sold?",
    ):
        assert (
            _ecommerce_demo_q2_scalar_analysis_sql("ecommerce-demo", question) is None
        )
    assert (
        _ecommerce_demo_q2_scalar_analysis_sql(
            "production-db", "第二季度有多少种商品售出？"
        )
        is None
    )


def test_ecommerce_regional_order_count_query_is_narrowly_classified():
    sql = _ecommerce_demo_regional_order_count_sql(
        "ecommerce-demo", "第二季度各地区完成订单数是多少？"
    )
    assert sql is not None
    assert "r.tenant_id=o.tenant_id AND r.region_id=o.region_id" in sql
    assert "o.status = 'completed'" in sql
    assert "GROUP BY r.name ORDER BY r.name" in sql
    assert (
        _ecommerce_demo_regional_order_count_sql(
            "ecommerce-demo", "2025 年第二季度各地区完成订单数是多少？"
        )
        is None
    )
    assert (
        _ecommerce_demo_regional_order_count_sql(
            "ecommerce-demo", "第二季度各地区不同订单状态的订单数是多少？"
        )
        is None
    )
    assert (
        _ecommerce_demo_regional_order_count_sql(
            "production-db", "第二季度各地区完成订单数是多少？"
        )
        is None
    )


def test_ecommerce_regional_status_breakdown_is_narrowly_classified():
    sql = _ecommerce_demo_regional_status_breakdown_sql(
        "ecommerce-demo",
        "第二季度各地区不同订单状态的订单数和订单金额分别是多少？",
    )
    assert sql is not None
    assert "r.name AS region, o.status" in sql
    assert "COUNT(*) AS order_count" in sql
    assert "SUM(o.total_cents) AS order_value_cents" in sql
    assert "r.tenant_id=o.tenant_id AND r.region_id=o.region_id" in sql
    assert (
        _ecommerce_demo_regional_status_breakdown_sql(
            "ecommerce-demo", "2025 年第二季度各地区不同订单状态订单数和订单金额？"
        )
        is None
    )
    assert (
        _ecommerce_demo_regional_status_breakdown_sql(
            "production-db", "第二季度各地区不同订单状态订单数和订单金额？"
        )
        is None
    )


def test_ecommerce_q2_ungrouped_metrics_map_to_published_catalog_ids():
    cases = {
        "第二季度完成订单销售总额是多少？": "sales_amount",
        "第二季度已支付退款总额是多少？": "paid_refund_amount",
        "第二季度净销售额是多少？": "net_sales_amount",
        "第二季度退款率是多少？": "refund_rate",
    }
    for question, metric_id in cases.items():
        parameters = _ecommerce_demo_q2_total_metric_parameters(
            "ecommerce-demo", question
        )
        assert parameters == {
            "metric_id": metric_id,
            "start_date": "2026-04-01",
            "end_date": "2026-07-01",
        }

    assert (
        _ecommerce_demo_q2_total_metric_parameters(
            "ecommerce-demo", "第二季度各地区销售额是多少？"
        )
        is None
    )
    assert (
        _ecommerce_demo_q2_total_metric_parameters(
            "ecommerce-demo", "2025 年第二季度退款率是多少？"
        )
        is None
    )
    assert (
        _ecommerce_demo_q2_total_metric_parameters(
            "production-db", "第二季度退款率是多少？"
        )
        is None
    )


def test_published_metric_intent_resolves_catalog_alias_and_explicit_quarter(
    monkeypatch,
):
    catalog_path = (
        Path(__file__).resolve().parents[7]
        / "examples/enterprise-text2sql/metric_catalog.json"
    )
    monkeypatch.setenv(
        "DBGPT_METRIC_CATALOG_FILES",
        json.dumps({"ecommerce-demo": str(catalog_path)}),
    )
    schema_path = catalog_path.parent / "schema_metadata.json"
    monkeypatch.setenv(
        "DBGPT_DATABASE_SCHEMA_FILES",
        json.dumps({"ecommerce-demo": str(schema_path)}),
    )

    assert _published_metric_intent_parameters(
        "ecommerce-demo", "第二季度完成订单销售总额是多少？", "user"
    ) == {
        "metric_id": "sales_amount",
        "start_date": "2026-04-01",
        "end_date": "2026-07-01",
    }
    assert _published_metric_intent_parameters(
        "ecommerce-demo", "2026 年 4 月每月销售额趋势", "user"
    ) == {
        "metric_id": "sales_amount",
        "start_date": "2026-04-01",
        "end_date": "2026-05-01",
        "dimension": "month",
    }


def test_published_metric_intent_rejects_ambiguous_or_unscoped_questions(
    monkeypatch,
):
    catalog_path = (
        Path(__file__).resolve().parents[7]
        / "examples/enterprise-text2sql/metric_catalog.json"
    )
    monkeypatch.setenv(
        "DBGPT_METRIC_CATALOG_FILES",
        json.dumps({"ecommerce-demo": str(catalog_path)}),
    )
    schema_path = catalog_path.parent / "schema_metadata.json"
    monkeypatch.setenv(
        "DBGPT_DATABASE_SCHEMA_FILES",
        json.dumps({"ecommerce-demo": str(schema_path)}),
    )

    assert (
        _published_metric_intent_parameters(
            "ecommerce-demo", "2026 年第二季度销售额和退款金额是多少？", "user"
        )
        is None
    )
    assert _published_metric_intent_parameters(
        "ecommerce-demo", "第二季度销售额是多少？", "user"
    ) == {
        "metric_id": "sales_amount",
        "start_date": "2026-04-01",
        "end_date": "2026-07-01",
    }
    assert _published_metric_intent_parameters(
        "ecommerce-demo", "2026 年第二季度华南各地区销售额是多少？", "user"
    ) == {
        "metric_id": "sales_amount",
        "start_date": "2026-04-01",
        "end_date": "2026-07-01",
        "dimension": "region",
        "region_area": "South China",
    }
    assert _published_metric_intent_parameters(
        "ecommerce-demo", "2026 年第二季度广州销售额是多少？", "user"
    ) is None
    assert _published_metric_intent_parameters(
        "ecommerce-demo", "2026 年第二季度取消订单销售额是多少？", "user"
    ) is None
    assert (
        _published_metric_intent_parameters(
            "ecommerce-demo", "2026 年第二季度销售额同比增长多少？", "user"
        )
        is None
    )
    assert (
        _published_metric_intent_parameters(
            "ecommerce-demo", "2026 年第二季度毛利率是多少？", "user"
        )
        is None
    )
    assert _published_metric_intent_parameters(
        "ecommerce-demo", "2026 年第二季度毛利率是多少？", "admin"
    ) == {
        "metric_id": "gross_margin_rate",
        "start_date": "2026-04-01",
        "end_date": "2026-07-01",
    }
    assert _published_metric_intent_parameters(
        "ecommerce-demo", "2026 年第二季度各商品类别销售额是多少？", "user"
    ) is None
    assert _published_metric_intent_parameters(
        "ecommerce-demo", "2026 年第二季度每月各地区销售额是多少？", "user"
    ) is None
    assert _published_metric_intent_parameters(
        "ecommerce-demo", "销售额是多少？", "user"
    ) is None


def test_ecommerce_demo_order_count_route_is_narrowly_classified():
    completed_sql = _ecommerce_demo_order_count_sql(
        "ecommerce-demo", "第二季度完成了多少笔订单？"
    )
    assert completed_sql == (
        "SELECT COUNT(*) AS total FROM orders "
        "WHERE created_at >= '2026-04-01' AND created_at < '2026-07-01' "
        "AND status = 'completed'"
    )
    assert "status = 'cancelled'" in _ecommerce_demo_order_count_sql(
        "ecommerce-demo", "第二季度取消订单数是多少？"
    )
    assert (
        _ecommerce_demo_order_count_sql(
            "ecommerce-demo", "2025 年第二季度完成了多少笔订单？"
        )
        is None
    )
    assert (
        _ecommerce_demo_order_count_sql(
            "ecommerce-demo", "第二季度各地区完成了多少笔订单？"
        )
        is None
    )
    assert (
        _ecommerce_demo_order_count_sql("production-db", "第二季度完成了多少笔订单？")
        is None
    )


def test_expected_sql_action_replaces_early_termination_and_preserves_exact_call():
    sql = (
        "SELECT COUNT(*) AS total FROM orders WHERE created_at >= '2026-04-01' "
        "AND created_at < '2026-07-01' AND status = 'completed'"
    )
    calls = []

    def sql_tool(**kwargs):
        calls.append(kwargs)
        return '{"result":{"type":"sql_result"}}'

    result = _ensure_expected_sql_action(
        {"action": "terminate", "action_input": '{"result":"5"}'}, sql_tool, sql
    )
    assert result["action"] == "sql_query"
    assert json.loads(result["action_input"]) == {"sql": sql}
    assert calls == [{"sql": sql}]

    original = {
        "action": "sql_query",
        "action_input": json.dumps({"sql": sql}),
        "observations": "already executed",
    }
    assert _ensure_expected_sql_action(original, sql_tool, sql) is original
    assert calls == [{"sql": sql}]


def test_metric_only_prompt_matches_the_registered_tool():
    prompt = _database_workflow_prompt(
        metric_instruction="Use sales_amount.",
        database_context="Demo schema.",
        metric_only=True,
    )

    assert "Action: metric_query" in prompt
    assert '"metric_id": "sales_amount"' in prompt
    assert '"dimension": "region"' in prompt
    assert "Only metric_query and terminate are available." in prompt
    assert "Action: sql_query" not in prompt


def test_south_china_sales_and_refund_question_uses_fixed_metric_bundle():
    question = "第二季度华南区销售额和退款率分别是多少？"

    assert _is_ecommerce_south_china_sales_refund_request("ecommerce-demo", question)
    assert not _is_ecommerce_south_china_sales_refund_request(
        "ecommerce-demo", "2025 年第二季度华南区销售额和退款率分别是多少？"
    )
    assert not _is_ecommerce_south_china_sales_refund_request("production-db", question)
    assert not _is_ecommerce_south_china_sales_refund_request(
        "ecommerce-demo", "第二季度华南区销售额同比如何？"
    )

    prompt = _database_workflow_prompt(
        metric_instruction="Use the published KPI bundle.",
        database_context="Use the synthetic demo schema.",
        metric_only=True,
        metric_action_input=(
            '{"metric_ids": ["sales_amount", "refund_rate"], '
            '"start_date": "2026-04-01", "end_date": "2026-07-01", '
            '"region_area": "South China"}'
        ),
    )

    assert '"metric_ids": ["sales_amount", "refund_rate"]' in prompt
    assert '"region_area": "South China"' in prompt
    assert "Only metric_query and terminate are available." in prompt
    assert "Action Input is required for terminate." in prompt
    assert (
        "Do not append a plain-text Final Answer after the terminate action." in prompt
    )
    assert "Action: sql_query" not in prompt


def test_south_china_city_refund_followup_requires_prior_matching_context():
    history = [
        SimpleNamespace(content="第二季度华南区销售额和退款率分别是多少？"),
        SimpleNamespace(content="华南区第二季度销售额为 77000 分，退款率为 6.1%。"),
    ]

    assert _is_south_china_city_refund_followup(
        "ecommerce-demo", "其中哪个城市的退款率最高？", history
    )
    assert not _is_south_china_city_refund_followup(
        "ecommerce-demo", "其中哪个城市的退款率最高？", []
    )
    assert not _is_south_china_city_refund_followup(
        "production-db", "其中哪个城市的退款率最高？", history
    )
    assert not _is_south_china_city_refund_followup(
        "ecommerce-demo", "其中哪个城市销售额最高？", history
    )


def test_metric_leader_summary_uses_structured_result_only():
    observation = {
        "result": {
            "type": "sql_result",
            "columns": ["region", "refund_rate_pct"],
            "rows": [["Guangzhou", 5.25], ["Shenzhen", 6.88]],
        }
    }

    assert (
        _format_metric_leader(observation, "refund_rate_pct")
        == "Shenzhen 的退款率最高，为 6.88%。"
    )
    assert (
        _format_metric_leader({"result": {"type": "other"}}, "refund_rate_pct") is None
    )


def test_expected_metric_action_replaces_untrusted_tool_or_parameters():
    parameters = {
        "metric_id": "refund_rate",
        "start_date": "2026-04-01",
        "end_date": "2026-07-01",
        "dimension": "region",
        "region_area": "South China",
    }
    calls = []

    def metric_tool(**kwargs):
        calls.append(kwargs)
        return '{"result":{"type":"sql_result"}}'

    result = _ensure_expected_metric_action(
        {"action": "sql_query", "action_input": '{"sql":"SELECT 1"}'},
        metric_tool,
        parameters,
    )

    assert result["action"] == "metric_query"
    assert json.loads(result["action_input"]) == parameters
    assert calls == [parameters]

    terminated = _ensure_expected_metric_action(
        {"action": "terminate", "action_input": "{}"}, metric_tool, parameters
    )
    assert terminated["action"] == "metric_query"
    assert json.loads(terminated["action_input"]) == parameters
    assert calls == [parameters, parameters]

    original = {
        "action": "metric_query",
        "action_input": json.dumps(parameters),
        "observations": "already executed",
    }
    assert _ensure_expected_metric_action(original, metric_tool, parameters) is original
    assert calls == [parameters, parameters]


def test_south_china_sales_share_followup_requires_prior_matching_context():
    history = [SimpleNamespace(content="第二季度华南区销售额和退款率分别是多少？")]

    assert _is_south_china_sales_share_followup(
        "ecommerce-demo", "广州销售额占华南区的比例是多少？", history
    )
    assert not _is_south_china_sales_share_followup(
        "ecommerce-demo", "广州销售额占华南区的比例是多少？", []
    )
    assert not _is_south_china_sales_share_followup(
        "production-db", "广州销售额占华南区的比例是多少？", history
    )
    assert not _is_south_china_sales_share_followup(
        "ecommerce-demo", "广州退款额是多少？", history
    )


def test_ecommerce_demo_clarifies_missing_metric_or_period_before_query():
    assert "请明确" in _ecommerce_demo_clarification(
        "ecommerce-demo", "最近经营情况怎么样？", []
    )
    assert "请明确" in _ecommerce_demo_clarification(
        "ecommerce-demo", "哪个商品表现最好？", []
    )
    assert "请明确" in _ecommerce_demo_clarification(
        "ecommerce-demo", "哪个地区退款率最高？", []
    )
    assert (
        _ecommerce_demo_clarification("other-database", "最近经营情况怎么样？", [])
        is None
    )
    assert (
        _ecommerce_demo_clarification(
            "ecommerce-demo", "2026 年第二季度哪个地区退款率最高？", []
        )
        is None
    )
    assert (
        _ecommerce_demo_clarification(
            "ecommerce-demo",
            "哪个商品表现最好？",
            [SimpleNamespace(content="2026 年第二季度各商品销售额")],
        )
        is None
    )


def test_sales_share_result_is_derived_from_complete_structured_metric_rows():
    observation = {
        "result": {
            "type": "sql_result",
            "columns": ["region", "sales_cents"],
            "rows": [["Guangzhou", 45000], ["Shenzhen", 32000]],
            "row_count": 2,
            "truncated": False,
        }
    }

    formatted = _format_sales_share_result(observation)

    assert formatted is not None
    payload = json.loads(formatted[0])
    assert payload["result"]["columns"] == ["sales_share_pct"]
    assert payload["result"]["rows"] == [[58.44]]
    assert formatted[1] == "广州销售额占华南区第二季度销售额的 58.44%。"
    assert (
        _format_sales_share_result(
            {"result": {**observation["result"], "truncated": True}}
        )
        is None
    )

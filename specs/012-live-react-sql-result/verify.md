# 验证记录：Live ReAct 结构化 SQL 结果事件

## 范围与 Diff

- 计划内文件：`packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/sql_query.py`、对应测试、`docker/compose_examples/develop-me-test/`、`docs/develop-me-roadmap.md`、`specs/012-live-react-sql-result/`
- 实际新增涉改文件：上述范围内的 SQL 结果事件实现、回归测试、本机 Compose 源码挂载及说明、路线图与本验证记录
- 范围门禁：pass；T001 和 T002 的范围报告均通过
- 无关改动：本轮没有修改范围外文件；工作树中的其他既有改动未触碰

## 自动验证

| 验证 | 命令／操作 | 结果 | 证据 |
| --- | --- | --- | --- |
| 定向单元与序列化测试 | `PYTHONPATH=packages/dbgpt-core/src:packages/dbgpt-serve/src:packages/dbgpt-app/src:packages/dbgpt-ext/src .venv/bin/python -m pytest -q -o addopts='' packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/tests/test_sql_query.py packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_sql_result_events.py` | pass：18 passed | `T001-unit`、`T001-errors` |
| Python 语法 | `.venv/bin/python -m py_compile packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/sql_query.py` | pass | `T001-syntax` |
| Compose 配置 | `docker compose -p dbgpt-develop-me-test -f docker/compose_examples/develop-me-test/compose.yaml config --quiet` | pass | `T001-compose`、`T002` Compose 启动记录 |
| 单题真实 Agent 冒烟 | 调用本机 DB-GPT ReAct API，对一条合成 gold case 运行 scorecard | pass：识别到结构化 SQL 结果；本题 `incorrect`，`missing_result=0` | `T002-live-smoke-retry1`、`T002-live-result-retry1` |
| 全量真实 Agent scorecard | `.venv/bin/python examples/enterprise-text2sql/evaluate_agent.py --timeout 120`，请求 `http://127.0.0.1:5671`、数据源 `ecommerce-demo` | pass：完成 50 题；正确 0、错误 30、缺少结构化结果 20、无效 0、截断 0，准确率 0% | `T002-live-gold`、`T002-scorecard`；`evidence/live-gold-scorecard.json` |
| Diff 空白检查 | `git diff --check`（本轮范围文件） | pass | T002 执行记录 |

## 结构化证据

- 状态文件：`specs/012-live-react-sql-result/state.json`
- Scope 报告：`specs/012-live-react-sql-result/scope-report-T001.json`、`specs/012-live-react-sql-result/scope-report-T002.json`
- 命令证据 ID：`T001-unit`、`T001-errors`、`T001-syntax`、`T001-compose`、`T002-live-smoke-retry1`、`T002-live-result-retry1`、`T002-live-gold`、`T002-scorecard`
- stdout／stderr 日志路径：`specs/012-live-react-sql-result/evidence/`
- Git HEAD：以状态文件中的任务执行记录为准；本任务未创建提交
- Diff 哈希：见状态文件 T001/T002 scope baseline 与 scope report

## 验收标准追踪

| AC | 结果 | 验证证据 | 备注 |
| --- | --- | --- | --- |
| AC-01 | pass | 定向测试 `T001-unit`；真实事件经 `T002-live-result-retry1` 识别 | 成功 SQL 保留 Markdown，同时附带最多 50 行 JSON-safe 结构化结果；payload 不包含 SQL 文本 |
| AC-02 | pass | 定向测试 `T001-errors` | SQL 被拒绝或执行失败时没有 `sql_result` payload |
| AC-03 | pass | `T002-live-smoke-retry1`、`T002-live-result-retry1`、`T002-live-gold`、`T002-scorecard` | 本机 Compose 使用更新后的源码；单题结果事件可识别；全量 50 题 scorecard 已落盘。结果准确率为 0%，所以仅证明事件传输与评测执行，不代表模型 SQL 质量达标 |

## 例外与风险

- 未运行验证及原因：无。拒绝/澄清 policy scorecard 不属于本变更验收范围。
- 已知限制：本机 Qwen 3 1.7B 50 题 exact-match 为 0/50；30 题有结构化但不匹配的结果，20 题没有结构化结果。观察到纠错预算耗尽后 Agent 仍可能重复尝试。
- 后续事项：改善本地模型 SQL 生成和终止行为；另行验收企业 OIDC、真实用户数据源、生产数据库只读授权/RLS 与拒绝/澄清策略。

## 结论

- 状态：ready_for_review
- 审查人：待审查
- 审查时间：待审查
- 人工验收证据：尚无单独验收记录

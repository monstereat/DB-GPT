# 企业级 AI 数据分析平台：二次开发路线图

> 仓库：`monstereat/DB-GPT`｜固定开发分支：`develop-me`｜更新：2026-09-28
> 开源底座：DB-GPT；如业务指标治理不足，再按需集成 WrenAI 语义层。  
> 核心路线：围绕真实电商数据实现「自然语言提问 → Schema/业务口径 → SQL → 权限校验 → 执行 → 图表 → 多轮分析 → 评测」。

## 当前收尾状态

- 当前交付：企业电商分析演示的主要代码路径已实现，包含 OIDC/JWT 接入、数据源/角色授权、租户与区域查询约束、只读 SQL 执行、版本化指标、Agent 结构化结果、图表/报表与审计能力；具体以本路线图已验证记录为准。
- 当前状态：目录驱动的单指标自然语言入口通过 80 项定向回归；本机 Agent 对目录默认年份销售额、商品类别分析和按销售额降序排列区域销售额分别 live smoke 为 1/1。区域别名也通过路由回归映射到目录登记值。它们只覆盖固定合成数据问题，不代表全量问答质量验收。
- 用户最新要求完成当前环境内可做的收尾，已授权关键链路定向回归和本机合成数据 smoke；仍按此前“关键链路即可、不需要全量测试”的范围，本轮没有跑全项目套件或完整 50 题评测。
- 仍未关闭的主要项目项：开放式 Text-to-SQL 质量、多指标/比较与追问语义覆盖、真实企业 IdP 与目标 PostgreSQL 授权/RLS 验收、生产遥测的脱敏/认证/留存配置。它们依赖恢复测试或外部目标环境，不能由本地文档收尾代替。
- 建议恢复工作顺序：先做目录路由关键行为回归和当前核心 UI 验收；再以当前代码重跑脱敏 live scorecard；之后安排真实 IdP/PostgreSQL/遥测环境验收。此顺序不自动授权生产部署。

## 1. 功能边界：已有 / 集成 / 自研

| 模块 | DB-GPT / 其他开源已有 | 需要集成 | 自己开发的功能 | 优先级 |
| --- | --- | --- | --- | --- |
| 数据源管理 | 数据库、文件和知识库连接 | 电商数据库、凭据服务 | 业务数据源登记、连接审批、凭据隔离 | P0 |
| 数据模型 | Schema 读取与检索 | 中文业务数据字典 | 字段含义、业务表关系、敏感字段标注 | P0 |
| 自然语言查询 | Text-to-SQL / Agent | 电商指标及示例问句 | 订单、地区、销量、退款固定业务场景 | P0 |
| SQL 安全 | 引擎查询能力 | 最小权限账户 / 数据库策略 | 只读执行、方言级安全校验、超时、行数与成本限制 | P0 |
| 数据权限 | 连接和基础访问机制 | 企业 SSO / RBAC | 库表权限、列级脱敏、行级租户隔离、服务端权限判定 | P0 |
| 图表交互 | 已有图表/报告 | Vue3、ECharts | 面向业务的多图联动、筛选、钻取与查询解释 | P0 |
| 语义指标 | 可引入 WrenAI | 指标定义表 | 销售额、退款率、利润率的版本化定义及维度约束 | P1 |
| SQL 纠错 | Agent 错误反馈能力 | SQL 执行反馈 | 语法/权限/Schema 错误分类、受控纠错与重试预算 | P1 |
| 多轮分析 | Agent 多步骤上下文 | 会话持久化 | 继承时间范围、地区、指标口径与上下文引用 | P1 |
| 报告导出 | HTML 分析报告 | PDF / Excel 导出 | 企业报表模板、导出权限和脱敏 | P1 |
| 审计 | 部分执行过程和日志 | 安全日志、Trace | 操作者、数据源、SQL 摘要、授权策略、结果数量和耗时 | P1 |
| 查询评测 | 基础执行和反馈 | 30–50 个标准问句 | 执行成功率、结果正确率、权限拒绝率及回归报告 | P1 |
| 性能优化 | 基础查询引擎 | Redis / 异步任务 | 热点缓存、队列、超时重试及成本预算 | P2 |

**避免重复建设：** 不同时实现两套完整 Text-to-SQL 引擎；先以 DB-GPT 为主，只有在指标口径确有需要时再接 WrenAI。

## 2. P0：电商业务 MVP

- [x] 准备包含 `users`、`orders`、`order_items`、`products`、`regions`、`refunds` 的模拟数据库与标准答案。
- [x] 为本地业务表建立中文说明、关系与敏感列元数据；`schema_metadata.json` 驱动列策略，ReAct 主/子 Agent 按服务端 datasource 映射读取业务字典。
- [x] 本地 DB-GPT Serve datasource 支持 Fernet 加密 `db_pwd` 和 privacy 标注扩展字段；缺 key 的敏感写入/已存凭据连接失败关闭；创建/更新重置为 `pending`，连接器在 cache 命中前检查审批与加密 envelope。旧 `/v1/chat/db` 写入路径同步加密和重置审批。
- [x] 新增独立审批审计表、事务化 review、Verified OIDC admin 审批 API 和反自批；只有通过验签且 role=admin 的 actor 可查看待审列表与处理审批。变更和审批后失效本地 connector cache；审批后再触发 schema summary。
- [x] 新增 dry-run 默认的 SQLite/MySQL 历史配置迁移 CLI；apply 分批加密旧凭据、将来源标为 pending，并仅输出 datasource IDs/异常类型。SQLite 老 schema 可由 CLI 增量扩展；MySQL DDL 收录于 fresh schema 和 `v0_8_2` upgrade/snapshot。
- [x] Serve datasource/SQLite 迁移定向回归 14 项、App API 全套回归 87 项通过；`py_compile`、Ruff check/format 和 `git diff --check` 通过。
- [x] 隔离 MySQL 8.4 容器通过新增 DDL 与迁移 CLI smoke：先 dry-run 输出 datasource ID 且不改值，再以 batch-size 1 加密并将历史行置为 pending；检查确认 encrypted prefix、submitter 保留和 audit 表存在。临时容器已删除。
- [ ] 迁移尚未在用户实际 metadata DB 执行；配置 durable encryption key、执行 dry-run/apply 并完成每个历史 datasource 的 admin 复核仍是部署步骤。已有调用者持有的 connector 引用无法被审批撤销即时终止；生产 Key Manager/轮换、DB grants/RLS/只读角色仍未完成。
- [x] Serve 数据源 URL/文件配置的 `update_db_info` 已改为 SQL 参数绑定，避免连接名、凭据、地址及注释进入 SQL 字符串；定向 DAO 回归 3 项通过。此项不改变现有 schema，也不代表凭据隔离或连接审批已完成。
- [x] Serve 数据源 list/detail/create/update 响应和 App `/v1/chat/db/list` 按连接参数 `privacy` 元数据隐藏机密字段；编辑时未填写的 privacy 参数沿用已存值。Serve 全量回归 617 项通过、1 项跳过；App 脱敏与管理路由回归 7 项通过。
- [x] DB-GPT ReAct 查询链已接入 Schema/业务上下文，展示 SQL 和回答；SQL 工具通过 SSE 返回最多 50 行结构化结果，页面可据同一结果展示表格和图表。
- [x] 本机 DB-GPT ReAct + Ollama `qwen3:1.7b` + 授权合成电商 SQLite 已完成 50 题真实 Agent 联调；2026-09-27 旧 scorecard 记录 0/50、30 题错误和 20 题缺少结构化结果。后续发现旧 evaluator 忽略 46 道无序题的顺序语义，且缺少 SSE `done` 的结果也曾被错误评分；该旧分数不能代表现行模型准确率，重评待办见下。
- [x] 已提交 `examples/enterprise-text2sql/guarded_query.py`：**独立 SQLite MVP**，只读文件模式、SQLite 原生 Authorizer 库表及列级白名单、执行时间预算、限制返回行数、SQL 摘要审计回调。
- [x] 已提交 `examples/enterprise-text2sql/test_guarded_query.py`：包含聚合、CTE、行数、敏感列、非法语句和审计的测试**代码**。
- [x] SQL 安全执行已覆盖 ReAct 主/子 Agent、Core RDBMS Resource、Dashboard、SQL 编辑器、图表执行与回放的只读校验；PostgreSQL/MySQL/SQLite 有 30 秒超时与 1,000 行上限。ReAct 和 App 图表路径按配置的 Schema policy 做列校验、tenant/region 范围注入；ReAct direct/related-region 行策略已在临时 PostgreSQL 16 / MySQL 8.4 实例验证。
- [x] Core RDBMS Agent Resource 已通过请求级可信身份校验数据源归属，并应用 Schema 列策略及 tenant/region 行范围；生产只读凭据、成本预算、数据库 RLS 与生产策略验证仍未完成。
- [x] ReAct 按认证用户授权数据源；主/子 Agent 与指标路径使用服务端角色，编辑器、Dashboard 和图表回放读取可信 tenant/region；演示 API 有 OIDC tenant/region 策略和缺少 region 时的拒绝。
- [x] DB-GPT App 的通用 `DatasourceResource` 已贯通请求级可信身份及 owner/admin 授权；其他 Agent 入口、数据库 RLS 和生产身份仍待验收。企业 IdP 浏览器/部署验收按本计划最后进行。
- [x] Vue3 + ECharts 演示页支持 OIDC token、指标卡、区域分布、月度趋势、去年同期叠加、区域/月筛选、指标版本和 SQL 预览；ReAct 结构化 SQL 结果可展示表格与图表。
- [x] 本地真实 DB-GPT + Ollama + 授权合成电商数据的代表性端到端场景已完成；通用问句生成准确率与生产模型/数据源仍未验收，见下方 Agent 评测及生产环境待办。
- [x] 「华南区季度销售额与退款率」场景已进入固定问答金标准和 tenant-scoped SQL 候选（q41）。
- [x] 固定问答→查询→图表闭环已有本地浏览器验收，包括 Q2 订单数、区域销售额和华南多轮指标场景；开放式分析质量、企业 IdP 与生产授权仍未验收。

## 3. P1：面试展示重点

- [x] **指标语义层：** 已定义销售额、退款、净销售额、退款率及毛利率的口径、时间、排除项、版本和零分母行为；派生指标固定依赖版本，确定性 `metric_query` 支持递归编译和角色授权。退款额、净销售额、退款率有 1.0.0/2.0.0 cohort 口径；毛利率按用户确认公式限定为 admin。
- [x] 指标发布审批与审计接口已完成；退款额、净销售额和退款率按退款发生日/原订单 cohort 口径提供并行版本。销售额与毛利率当前各只有一个明确定义，不为版本数量虚构不同算法；业务口径发生变化时通过现有治理接口新增版本。实时 Agent scorecard 已运行，但本地模型在 50 题中精确匹配 0 题，指标选择与生成质量仍未通过验收。
- [x] **SQL 纠错：** 共享查询层及 Agent SQL 工具区分语法、Schema、权限、超时等错误；仅语法/Schema 错误有单次受控纠错预算，权限拒绝不会自动放宽；PostgreSQL `57014 query_canceled` 映射为不可重试 timeout。
- [x] DB-GPT 项目测试套件已按各包运行：App 最新源码树布局 542 通过；Core 测试集与 RDBMS SQLite 回归临时提供可选 `litellm` 后 835 通过、1 跳过；Serve 617 通过、1 跳过；Ext 临时提供可选 `valkey-glide` 后 129 通过、2 跳过。临时依赖没有写入项目环境或锁文件；功能改动另有定向回归。
- [x] **多轮分析：** Vue 页面复用 ReAct conversation ID 并保留当前页问答记录，身份或数据源变化时重置会话；业务字典定义日期/区域/指标版本继承，实时评测器支持 `conversation_group` 和华南季度追问样例。
- [x] 本机 DB-GPT Agent、Ollama 与授权合成数据已完成华南 Q2 首问及退款率/销售占比两类上下文追问；固定四题实时多轮结果 4/4。开放式多轮理解、生产身份和真实数据源仍待验收。
- [x] **审计与可追踪（本地路径）：** 独立演示 API 记录调用人、租户、策略版本、数据源、SQL 哈希、耗时、行数和状态，不写原始 SQL；ReAct 主/子 Agent SQL 工具记录操作者、可信 role/tenant/region、授权数据源、连接可见性策略版本、会话 trace、SQL 哈希、耗时、行数和结果状态，并发出 `agent.sql_query` span。语义目录、指标编译、并行 dispatcher、知识库检索、代码/命令/技能脚本/HTML 执行、Dashboard/SQL 编辑/图表执行及回放、文件分析均有对应 span；Core OTLP gRPC exporter 和本地 Collector 往返、父子 span 传播已有回归。
- [ ] 真实 DB-GPT Agent 模型请求及部署 Collector/OpenObserve 验收、生产租户行策略审计仍待完成。内置 Agent 工具、Core RDBMS Resource 与 Core ToolPack 动态工具均已接入脱敏 span；审计中的 role/tenant/region 字段不代表数据库级授权。
- [x] **数据评测：** 已有 50 条金标准问答、19 条 SQLite SQL 安全候选、20 条 PostgreSQL/MySQL AST 候选、15 条 Schema 列/登记视图策略候选、11 条 tenant/region 行策略候选、11 条语义指标编译/授权候选、6 条歧义案例、3 组固定 SQL 多轮授权序列；实时 ReAct evaluator 支持会话复用与固定攻击拒绝/澄清用例。
- [x] 本地真实 Agent 50 题旧 scorecard 已生成：记录精确匹配 0/50、错误结果 30 题、缺少结构化结果 20 题，无效/截断结果均为 0。行序比较和完整 SSE 结束检查的 evaluator 缺陷已在 2026-09-28 修复；旧报告仅作历史记录，不作为当前质量分数。
- [ ] 开放式语义质量及当前模型生成准确率尚未完成验收；修复行序比较与 SSE 完整性后需重跑 50 题 live scorecard。旧 0/50 报告不能代表当前准确率；生产多轮授权也仍需目标环境验收。
- [x] **报告导出：** 独立分析页已提供受权限控制的 XLSX、服务器端 PDF 下载及页面打印；两种服务端格式共用 OIDC 租户/区域执行器，包含生成时间、日期边界、指标版本和口径并记录审计。异步 XLSX 任务已持久化并可恢复，结果支持配置 Fernet 加密；支持 2–10 个命名场景的原子批量报告。历史结果加密/轮换与显式截止时间清理工具已实现；报表任务与模板治理均支持显式 PostgreSQL 多实例共享存储并通过隔离实例测试；目标部署验收、生产密钥管理和正式留存策略仍待完成。
- [x] **数据库扩展（应用层）：** PostgreSQL/MySQL 方言 SQL AST 与超时限制已覆盖；tenant/region ReAct SQL 策略通过临时 PostgreSQL/MySQL 运行验证，不复用 SQLite Authorizer。
- [x] 临时 PostgreSQL 16.6 隔离实例验证了数据库侧 RLS 与最小权限行为：缺少 tenant session setting 时返回 0 行，设置 `app.current_tenant=tenant-a` 后只读到账户 A 的行；`SELECT` role 没有 UPDATE grant，且 `statement_timeout=50ms` 能取消 `pg_sleep(200ms)`。该 smoke 仅验证 PostgreSQL 原生策略，不证明 DB-GPT 已把可信 OIDC tenant 注入数据库 session，也不代表生产配置。
- [x] 临时 MySQL 8.4 隔离实例验证只读授权：仅授予 `SELECT` 的 role 能读取数据，`UPDATE` 被 MySQL error 1142 拒绝；`MAX_EXECUTION_TIME=50ms` 取消耗时查询，DB-GPT MySQL connector 的 SQL 安全执行器将 3024 正确归类为 `timeout` 并返回脱敏提示。该 smoke 与 PostgreSQL smoke 均为隔离实例验证，不代表可信身份 session 注入或生产账号配置。
- [ ] 生产 PostgreSQL/MySQL 只读账户、数据库级 grants/RLS、全驱动取消行为和列/租户授权仍待真实实例验收。

## 4. P2：后续扩展

- [x] 演示 API 的已登记聚合指标支持 30 秒 TTL 缓存：默认是进程内有界 LRU；配置 `DBGPT_METRIC_CACHE_REDIS_URL` 后使用 Redis 跨 API 实例共享。Redis 键只保留缓存范围元组的 SHA-256，范围包含数据源/策略版本、SQLite 主库/WAL/journal 文件版本、身份、租户、区域、指标版本、日期、维度和 SQL 哈希。数据库文件变化后新请求使用新键；命中前仍执行身份/租户校验并写 cache-hit 审计。Redis 不可用时查询回退到受限数据库执行。
- [x] 已用独立 API 实例和共享 Redis 测试替身验证跨实例命中、身份隔离逻辑及数据库文件变化后的缓存失效；Redis 读写错误回退到受限数据库查询。
- [x] 已连接本机受认证的 Redis 服务验证真实网络读写、独立客户端共享、租户/用户范围隔离、30 秒 TTL 和不暴露 scope 的哈希键。
- [ ] 生产 Redis 的 TLS、最小权限 ACL、内存上限/eviction 策略及故障降级仍待部署环境验收；临时 Redis 7.4.2 已通过 loopback `rediss://` 证书校验与缓存读写 smoke，受限用户仅能对指标命名空间执行 `GET`/`SET`，`FLUSHALL` 和命名空间外写入被拒绝，服务停止后缓存读写安全回退为 miss/bypass。该隔离验证不代表生产 ACL、容量策略或 TLS 部署配置。
- [x] 异步报表任务已支持持久化、原子认领、租约续期/回收、重试、幂等键及重启恢复；单份报告一次可汇总 1–4 项指标，批量报告支持 2–10 个独立命名场景并整批成功或失败；任务和模板治理存储均可显式连接 PostgreSQL 供多实例共享。`ChatNormal`、ReAct/knowledge-agent 共用按 verified tenant+user 计算的 UTC 日 Token 配额；其他已发现的未计量模型入口在配额启用时 fail-closed（细节见“未计量模型端点配额封口”），不代表这些入口已完成计量。金额配额与跨轮请求数限制尚无实现；报表结果提供显式 cutoff 清理工具和 ciphertext 批量轮换工具，但正式留存时长/规则需由部署策略确定，旧 key 退役需部署流程。Serve APScheduler 仍用于聊天回放，不是此演示队列。
- [x] 语义层指标发布审批、审计及动态已发布快照已实现；目录校验、依赖版本固定、环依赖拒绝和递归编译已实现。只有存在不同业务时间归属的指标才保留并行版本；本机 live scorecard 已运行，但 Qwen 3 1.7B 精确匹配为 0/50，指标选型尚未验收通过。

## 5. 首个演示场景与验收

**场景：** 用户提问「第二季度华南区销售额同比如何？退款率异常最高的城市是哪里？」Agent 读取已授权 Schema 和指标口径，生成 SQL，经安全策略审查后执行，输出图表与分析解释；用户继续追问具体城市的品类退款情况，保留查询上下文，最后导出报告。

**验收标准：** 生成 SQL 可展示；跨表/复杂指标能得到金标准预期结果；读不到未授权租户、敏感字段；无法执行写入语句；每次结果都有执行和口径记录；图表与 SQL 一致。

### 当前代码及测试入口

```bash
cd examples/enterprise-text2sql
python -m pip install -r requirements-test.txt
PYTHONPATH=../../packages/dbgpt-core/src:../../packages/dbgpt-serve/src:../../packages/dbgpt-ext/src \
  python -m pytest -q -o addopts=''
```

**当前限制：** 独立 SQLite 安全执行器和 DB-GPT Agent/RDBMS/图表执行入口已具备不同层次的查询保护，但仍不是生产级 SQL 防火墙；企业长期运行的 IdP、生产数据库行列授权、只读生产凭据、部署验收及真实 Agent 评测未完成。[x] 表示对应代码已实现，不代表 CI 或真实环境测试已通过。

## 2026-09-24 增量：固定数据集候选 SQL 评测

- [x] `examples/enterprise-text2sql/evaluate_candidates.py` 接收每个标准问题对应的候选 SQL，全部通过既有 `GuardedSQLiteQuery` 执行。
- [x] 统计结果正确、结果错误、被拒绝、缺失的数量与比例；报告只包含 SQL 哈希和安全指标，不回显 SQL 或查询明细。
- [x] 提交 `gold_candidates.json` 和评测回归测试；专用 GitHub Actions 已成功。
- [x] **本地实时评测已运行，生成质量未达标：** 固定 SQL 的分数不代表模型准确率；实时 DB-GPT Agent 评测入口现覆盖金标准、多轮会话及固定攻击/澄清策略。本机 Agent 与授权合成 datasource 已完成 50 题 scorecard（精确匹配 0/50）和 4 题多轮 scorecard（精确匹配 0/4）；证据见 `specs/012-live-react-sql-result/evidence/live-gold-scorecard.json` 与 `specs/020-react-stop-on-terminal-sql-error/evidence/multiturn-scorecard.json`。模型质量仍未通过验收。

## 2026-09-25 增量：六表合成电商数据

- [x] 将独立 SQLite fixture 扩展为 `users`、`regions`、`products`、`orders`、`order_items`、`refunds` 六表，并用租户复合键约束表间关系。
- [x] 新增 `gold_questions.json`，包含 30 条中文业务问题、固定 SQL 和预期结果；`gold_candidates.json` 的全量样例通过候选评测。
- [x] 补充中文业务字典、销售额/退款额/退款率口径，以及个人信息、内部成本和备注列的敏感级别。
- [x] 扩展 tenant-scoped SQLite 回归检查，覆盖六表存在、跨租户查询隔离、敏感字段拒绝和未知租户 fail-closed。
- [x] 验证：`uv run --no-project --with pytest python -m pytest -q`，40 项通过；Ruff check/format 和 `git diff --check` 通过。
- [x] 固定候选 SQL 的通过结果不代表模型生成准确率；实时 ReAct scorecard 已在本机 DB-GPT Agent 和授权合成 datasource 上执行 50 题，精确匹配 0 题，模型 SQL 生成准确率尚未通过验收。

## 2026-09-25 增量：Agent SQL AST 防护实现与生产边界

- [x] DB-GPT Core 共享 SQLGlot AST 校验器已接入主 Agent、ReAct 子 Agent、RDBMS Agent Resource、Dashboard 图表查询和图表回放；拒绝多语句、CTE 写入、DDL、锁定/休眠、PostgreSQL 序列/大对象写入、服务器文件访问/会话控制函数及 MySQL `LAST_INSERT_ID(expr)` / `LOAD_FILE()`。PostgreSQL/MySQL/SQLite 查询入口设置 30 秒超时与 1,000 行上限，不支持可靠超时的方言会 fail closed。
- [x] 已新增 Agent、Core Resource、SQLite 超时及图表入口回归测试；完整临时项目环境中的 Core/App/SQLite 定向回归 187 项通过，覆盖 SQL 错误分类、只读 AST、授权上下文、编辑器/仪表盘 trace 和 SQLite 超时。
- [ ] SQL AST、超时和行数限制只是纵深防御；生产只读数据库账户、列/租户策略、授权主体及 PostgreSQL/MySQL 数据库权限集成尚未完成，不能视为 SQL 安全网关完成。
- [x] RDBMS、Spark、Dashboard 和 SQL 编辑器日志记录 SQL 哈希而非原文；Core RDBMS 与 Spark 查询入口记录状态、耗时和返回行数，Agent 层补充操作者、授权数据源、策略版本及 trace。SQL 编辑器和图表查询复用 `ConnectorManager.get_db_list(db_name, user_id)` 限定本人/共享数据源；历史回放/编辑校验会话归属。Core/App/SQLite/Spark/OTLP 定向回归 199 项通过，覆盖 SQL 日志脱敏、OTLP 配置开关和本地 Collector trace 导出。
- [x] 本地审计实现已覆盖 Core RDBMS `run/query_ex`、Spark `run`、Dashboard SQL/图表编辑和 SQL Editor 执行/回放；上层事件包含操作者、角色、tenant/region、授权数据源、方言、策略版本、trace、SQL 哈希、状态、耗时和行数，失败事件不包含驱动异常原文。
- [ ] 各生产数据库驱动的实际取消/超时与统一日志管道、部署 Collector/OpenObserve 导出仍待环境验收。
- [x] 已为 DB-GPT Serve 增加真实 OIDC Bearer JWT 验证：按配置的 issuer 读取 Discovery/JWKS 并限用 RSA/ECDSA 算法验签，校验 `iss`、`aud`、`exp`、`iat` 和 `sub`；claim 路径及外部角色到内部角色的映射可配置，用户、租户和区域映射到 `UserRequest`。本地 HTTP OIDC provider 的 Discovery、JWKS 获取和 RSA 签名 token 全链路测试通过。
- [x] OIDC 验证已由独立演示 API、默认 ReAct、Dashboard/editor 和 Core `DatasourceResource` 使用可信主体执行相应 owner/tenant/region/列策略。其他 Agent/需保护路由覆盖及数据库 RLS 仍需验收；未配置 issuer 时保留 DB-GPT 开发身份兼容逻辑，生产环境必须配置 OIDC。

## 2026-09-25 增量：候选 SQL 金标准扩展

- [x] 将合成电商金标准集从 30 条扩展至 40 条中文问答，新增净销售额、品类件单量、零销量商品、订单级退款、地区完成率、退款地区分布、日期边界、月度销售退款对比及复购客户统计等场景。
- [x] 同步 `gold_candidates.json` 和测试断言；40 条候选 SQL 均通过租户受限 SQLite 执行器并与独立录入的预期列及结果匹配。
- [x] 验证：`uv run --no-project --with pytest python -m pytest -q`，40 项通过。
- [x] 固定 SQL、歧义澄清、多轮授权及拒绝行为均有合成数据候选和评测器；这些离线分数不代表真实模型生成准确率。

## 2026-09-25 增量：候选 SQL 权限与拒绝评测

- [x] 新增 `security_candidates.json` 与独立安全计分器，评测敏感列、跨租户列、写语句和语法错误是否被拒绝，以及跨区域过滤是否返回空结果；与正确结果准确率分开展示。
- [x] 评测报告仅包含 case ID、状态、SQL 哈希和行数，不输出候选 SQL 或数据值；未知 case、超长/缺失 SQL分别受控校验。
- [x] 验证：企业 Text-to-SQL 演示测试共 72 项通过；40 条业务金标准仍全部通过，5 条安全候选全通过。
- [x] 人工固定 SQL、歧义澄清及多轮追问数据集已覆盖；DB-GPT Agent 已生成本地 live scorecard，当前 Qwen 3 1.7B 在 50 题中精确匹配 0 题，模型 SQL 生成质量仍待改进。

## 2026-09-25 增量：指标版本显式选择

- [x] 指标目录记录每项指标的默认已发布版本；派生指标必须固定引用两个依赖指标的版本，目录加载时检查唯一版本号、有效默认版本和依赖引用。
- [x] `/metrics/query` 接受可选 `metric_version`；不传时解析目录默认值，显式选择未发布或不存在的版本返回 400，不会静默回退；缓存键仍包含最终解析出的版本。
- [x] 验证：演示 API/语义/安全评测共 74 项通过；Ruff、格式检查、`py_compile` 和 `git diff --check` 通过。
- [x] 已支付退款额已有退款发生日 1.0.0 与原订单日 2.0.0 两个并行已发布口径；指标提交、异人审批、默认版本切换及发布审计已有本地持久化接口。其他指标仍可按治理接口新增版本；本机 live scorecard 已运行，模型对 gold 结果精确匹配 0/50，指标选择质量未通过验收。

## 2026-09-25 增量：机器可读业务 Schema

- [x] 新增 `schema_metadata.json`，登记六张表的中文说明、字段含义、敏感级别、Agent 查询开关、租户键、SQLite 演示数据源属性和复合外键关系。
- [x] 租户执行器的表/列白名单由服务端元数据生成；模块加载时校验数据源为本地只读演示配置，并拒绝缺少租户键或把敏感字段设为可查询的元数据。
- [x] 回归测试逐表比对 SQLite 实际字段与元数据，并比对全部复合外键；40 条金标准查询及租户/敏感字段用例保持通过。
- [x] 验证：`uv run --no-project --with pytest python -m pytest -q`，42 项通过。
- [x] 本地演示已扩展为 DB-GPT Serve 数据源治理：敏感凭据加密、审批与审计、所有权校验及历史配置迁移工具均已实现；实际 metadata DB 迁移、长期密钥管理和生产数据库授权仍见 P0 部署待办。

## 2026-09-25 增量：版本化指标语义层

- [x] 新增 `metric_catalog.json`，版本化定义销售额、已支付退款额、净销售额和退款率，明确金额单位、完成/已支付过滤条件、退款发生时间口径、原订单区域归属、零退款处理和零分母行为。
- [x] 新增 `semantic_metrics.py`，只接受已登记的指标、区域维度和规范 ISO 日期范围；通过 Schema 元数据校验来源字段并构建只读 SQL，结果同时携带指标版本和定义说明。
- [x] 使用租户隔离 SQLite 执行器验证四项指标的总体/分区计算和六月左闭右开时间边界；未知指标、越权维度、无效日期和反向日期均拒绝。
- [x] 验证：`uv run --no-project --with pytest python -m pytest -q`，51 项通过。
- [x] 毛利率成本口径已按用户确认登记为受限指标，并由 ReAct 主/子 Agent 的服务端 `metric_query` 路径执行；普通原始 SQL 仍拒绝成本列。定义及安全验证见“受限角色毛利率指标”。
- [x] 本地演示的指标变更审批及持久化版本治理已完成；生产行级策略、数据库 grants/RLS 与生产数据验证仍未完成。

## 2026-09-25 增量：SQL 错误分类与安全反馈

- [x] 共享查询层新增结构化 `SQLQueryFailure`，对语法错误、Schema 缺失、权限拒绝、超时、不支持方言和一般执行错误提供分类与可重试标志。
- [x] SQL 主工具和 ReAct 子 Agent 工具返回结构化错误类别；只允许语法/Schema 类错误给出受限修正提示，权限拒绝明确禁止绕过；不再把数据库驱动原始异常文本返回给 Agent。
- [x] 独立 smoke 覆盖 SQLite 错误消息、PostgreSQL SQLSTATE、MySQL 错误码分类，以及权限/执行异常的原文隐藏；改动文件 `py_compile`、Ruff check/format 与 `git diff --check` 通过。
- [x] 单次纠错预算已接入主 Agent 与 ReAct 子 Agent 的本轮 `react_state`，连续第二次语法/Schema 错误会被服务端改为不可重试；权限拒绝、超时等不消耗预算，执行成功后开启下一条纠错链。预算不跨请求持久化；两个真实工具 factory 的隔离 smoke 已验证一次重试上限和成功后重置。
- [x] 使用独立临时 `dbgpt-app` 项目环境运行相关 Core/App 回归；结构化错误分类、错误详情脱敏、权限拒绝不消耗纠错预算及查询成功后重置均通过。该范围的 Core/App 工具与编辑器定向测试纳入本轮 54 项回归。

## 2026-09-25 增量：OIDC/JWT 身份认证

- [x] Serve OIDC Bearer JWT 验证：从 issuer Discovery 获取 JWKS，校验签名、issuer、audience、过期和必需身份声明，并强制 HTTPS；本地 HTTP IdP 联调需显式打开开发选项。
- [x] `DBGPT_OIDC_CLAIM_MAPPINGS` JSON 路径映射和 `DBGPT_OIDC_ROLE_MAPPING` 角色映射已接入；用户、租户映射到 `UserRequest`，未映射或冲突角色降为 `normal`。本地 IdP smoke 覆盖签名、issuer/audience/过期拒绝、claim 映射和角色冲突回退。
- [ ] 生产配置必须设置可信 issuer/audience 与 claim/role 映射；应用仍保留未配置 OIDC 时的原有开发身份行为。需继续覆盖所有需保护的 API，并把可信租户身份接入行级数据授权；目前不等于完整 SSO/RBAC。
- [x] 已选 Keycloak Realm 作为参考身份提供方，并记录 issuer、audience、`sub`、租户、区域、用户名和角色 claim 的配置映射与示例环境变量；补充 Vue public client + PKCE、API audience mapper、tenant/region user attribute mapper 的配置步骤；不会在仓库保存生产配置或 token。
- [x] 本轮定向验收：本地 OIDC Discovery/JWKS、RSA Bearer 验签、tenant/region/role claim 映射及 fail-closed 用例 7 项通过；Vue OIDC/PKCE 和演示页回归 27 项通过。
- [ ] 企业环境 IdP 联调待完成：除本地协议 mock 外，已用临时 Keycloak 26 容器实际签发 Bearer token，验证 Discovery/JWKS、API audience、`organization.tenant` 嵌套 claim、region 和 role 映射；Vue 演示页现支持通用 OIDC Authorization Code + PKCE 登录和 ID Token 验证。尚未连接企业长期运行的 Realm，也未完成浏览器 PKCE 到生产 API/数据策略的端到端验收；生产 client/redirect/CORS 配置仍需部署环境提供。

## 2026-09-25 增量：OIDC 租户身份到演示查询授权

- [x] 新增 `examples/enterprise-text2sql/api.py`：`POST /query` 依赖 DB-GPT Serve 的 `get_user_from_headers`，只从验证后的 `UserRequest.tenant_id` 创建租户执行器；请求体仅接受 SQL，拒绝额外 tenant 字段。
- [x] 缺失或未知 tenant 返回拒绝；SQLite 查询策略只公开授权列并只读本租户数据。请求伪造 tenant/region 被模型拒绝，缺失/未知租户 fail-closed。
- [x] 演示 API 审计记录操作者、租户、数据源 ID、策略版本、SQL 哈希、执行状态、耗时和结果数；日志不包含原始 SQL。
- [x] SQLite 演示 API 支持租户与区域级行过滤；销售身份必须带经 JWT 映射的区域 claim。地区筛选覆盖订单、退款、订单明细和关联商品；拒绝 CTE 使用受保护表名绕过视图授权。
- [x] 验证：`PYTHONPATH=../../packages/dbgpt-core/src:../../packages/dbgpt-serve/src uv run --no-project --with pytest --with fastapi --with httpx --with 'PyJWT[crypto]' --with sqlglot python -m pytest -q`，65 项通过；包括本地 Discovery/JWKS HTTP provider、RSA Bearer token、tenant 和 sales region claim 映射、查询隔离与审计字段用例。
- [x] 此路由仍是独立合成数据演示，不是生产数据源链路；默认 ReAct 与 Core `DatasourceResource` 已有可信身份及应用层授权。外部企业 IdP 和生产数据库 RLS 仍待接入或验收。

## 2026-09-25 增量：默认 ReAct Agent 数据源授权

- [x] ReAct Agent 在建立 SSE 流前检查客户端选择的数据源是否对 JWT 映射出的 `user_id` 可见；只允许本人连接或共享连接，并把同一个已授权 connector 实例传给 SQL 工具，未授权数据源返回 403。
- [x] 数据源列表查询改为绑定 `user_id` / `db_name` 参数并关闭查询 session，避免 JWT subject 或数据源名被拼入 SQL。
- [x] 新增回归用例覆盖连接查询参数绑定、连接 session 关闭、本人/共享连接授权和他人私有连接拒绝；Serve 数据源用例通过。ReAct API 测试模块在当前临时环境收集时还缺少 NumPy，未能运行；改动文件 `py_compile`、Ruff check/format、授权 helper 隔离 smoke 和 `git diff --check` 通过。
- [x] 旧版 `/v1/chat/db/edit`、`delete`、`refresh` 管理路由现要求认证身份，并限制为连接所有者或 admin；无 owner 的共享及历史连接只允许 admin 管理。App API v1 全套回归 53 项通过。
- [x] DB-GPT Serve 通用 `/datasources` 创建、更新、删除、列表/详情、连通性测试、类型读取和刷新均要求 Verified OIDC 主体或显式配置的 service API key；OIDC owner 只能管理其 `submitted_by` 数据源，admin 可管理全部。ownership 从请求体剥离，由服务端设置；列表按 owner 查询，未知/无主历史记录仅 admin/service key 可管理。无 OIDC 且未配置 API key 时 fail-closed；service API key 明确作为全局机器管理员凭证保留兼容。
- [x] 新增 `specs/006-serve-datasource-api-auth/` 记录权限决策与验证；Serve datasource/OIDC 定向回归 23 项通过，DB-GPT Serve 全测试树 649 项通过、1 项跳过；Ruff check/format、compileall、`git diff --check` 通过，无 schema 变更。
- [ ] 生产需配置可信 OIDC 或高熵 service API key；service API key 拥有全局管理员权限，应按机器凭证保管。历史无 `submitted_by` 数据源需由 admin 复核归属；此应用层授权不替代生产数据库只读凭据、列权限和 tenant/region RLS。

## 2026-09-25 增量：Vue3 经营分析演示页

- [x] 新增 `examples/enterprise-text2sql/ui/` 独立 Vue3 + Vite 项目；目录 README 规定了页面、API helper、样式和构建产物位置，未改动主站 React 应用。
- [x] 对接 OIDC Bearer 保护的指标 API，展示四项版本化指标、区域分布和月度趋势图、区域/月筛选、去年同期叠加、指标定义、统计日期和 SQL 预览；访问凭证仅留在页面内存。
- [x] 验证：Node 22.23 / Vite 8.3.1 执行 `npm install --no-audit --no-fund`、`npm test`（当前 5 项通过）与 `npm run build` 成功；ECharts 按需组件并延迟加载，初始 JS 为 82.09 kB（gzip 32.18 kB），最大延迟 chunk 为 258.89 kB（gzip 82.91 kB），无 chunk 体积警告。
- [ ] 生产 API 反向代理和静态托管尚需部署环境配置；本地页面现提供 OIDC PKCE 登录入口，生产 redirect URI、web origin 和 provider CORS 仍需登记。
- [ ] 页面依赖 `/metrics/query` 的固定合成数据指标；尚未完成真实模型/数据源 Agent 问答、追问上下文效果和生产静态托管验收。

## 2026-09-25 增量：指标聚合结果缓存

- [x] `/metrics/query` 接入固定 30 秒 TTL、最多 256 条的进程内 LRU 缓存，仅缓存受注册指标目录约束的聚合结果；自由 SQL `/query` 不缓存。
- [x] 缓存键包含用户、租户、区域、数据源/授权策略版本、指标版本、筛选范围、维度、SQL 哈希及 SQLite 主库/WAL/journal 文件签名；查找命中前复核数据文件签名，数据库写入后下次请求重新执行。
- [x] 每次命中前重新构造并校验用户执行器，命中审计记录 `cache_hit`、SQL 哈希、操作者、租户、策略版本和结果行数；不记录原始 SQL。回归测试覆盖身份隔离、缓存审计和数据更新失效。
- [x] 验证：演示 API 测试 69 项通过；Ruff check/format 和 `git diff --check` 通过。
- [x] 后续增量已增加可选 Redis TTL 缓存并覆盖多 API 实例共享，见本路线图“共享指标缓存”增量；真实 Redis 网络/TLS/ACL 与部署 eviction 配置仍待验证。

启用时通过部署环境注入以下配置（不要提交真实环境配置或密钥）：

```bash
DBGPT_OIDC_ISSUER=https://id.example.com/realms/analytics
DBGPT_OIDC_AUDIENCE=dbgpt-api
DBGPT_OIDC_CLAIM_MAPPINGS='{"user_name":"preferred_username","tenant_id":"organization.tenant","region_id":"region_id","role":"realm_access.roles"}'
DBGPT_OIDC_ROLE_MAPPING='{"analytics-user":"normal","analytics-admin":"admin","regional-sales":"sales"}'
```

身份提供方示例为 Keycloak：将 `DBGPT_OIDC_ISSUER` 设为 Realm 的 issuer URL（例如 `https://id.example.com/realms/analytics`），在客户端配置与 `DBGPT_OIDC_AUDIENCE` 一致的 audience，并通过 protocol mapper/client scope 在 access token 中提供 `sub`、`preferred_username`、`organization.tenant`、`region_id` 和 `realm_access.roles`。`sub` 和 `preferred_username` 使用内置映射；其余字段按示例 JSON 路径映射到 DB-GPT 的租户、区域和外部角色。角色映射再把 `analytics-user`、`analytics-admin`、`regional-sales` 映射到内部角色。仅当角色数组中所有已映射角色收敛为一个内部角色时才授予该角色，缺失或冲突时回退为 `normal`。`DBGPT_OIDC_ALLOW_INSECURE_HTTP=true` 仅供本地 IdP 联调使用。详细字段表和 Keycloak 配置说明见 `examples/enterprise-text2sql/README.md`。真实企业 IdP 联调仍需部署环境提供 issuer、audience 和相应 client scope。

## 2026-09-25 增量：租户范围 XLSX 报告导出

- [x] 新增 `POST /reports/export`，只允许导出目录中的 1–4 项指标，查询 SQL 由已发布指标目录构建；身份、tenant 与 sales region 约束复用同一只读 SQLite 执行器，客户端不能传入授权范围。
- [x] XLSX 包含 UTC 生成时间、租户/区域范围、左闭右开日期区间、统计维度、指标版本/单位/口径定义和筛选后结果；报告导出本身记录结构化审计事件，不包含 SQL 原文。
- [x] Vue 页面表格区提供“导出 Excel”按钮，使用当前内存 OIDC Bearer token 下载四项指标报告；API 文件内容测试验证 tenant 和 sales-region 数据隔离。
- [x] 验证：演示 API 测试 77 项通过；Vue 单测 5 项通过、Vite production build 成功；Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [x] XLSX/PDF 与可恢复异步 XLSX 任务已共用服务端指标/角色导出 allowlist；后续增量补齐代码随附的版本化模板字段权限。生产级模板作者审批、大报表容量、生产密钥管理/留存和部署仍未实现；异步结果的应用层加密见“异步报告结果加密存储”增量。

## 2026-09-25 增量：ReAct SQL 结构化审计上下文

- [x] `/v1/chat/react-agent` 将经认证的 actor、已授权数据源 ID 和 `datasource-visibility-v1` 策略版本传入 SQL 工具；主 Agent 与子 Agent 均携带各自 conversation trace ID。
- [x] SQL 工具记录 SQL 哈希、耗时、返回行数、状态及错误类别，不记录 SQL 原文；未选择数据源、成功、策略拒绝和执行失败均有结构化状态。
- [x] 新增主/子 Agent 审计字段回归用例；日志脱敏 smoke、改动文件 `py_compile`、Ruff check/format 和 `git diff --check` 通过。
- [x] 默认 ReAct、Dashboard/editor 与 Core `DatasourceResource` 已应用相应身份、Schema/tenant/region 策略。生产数据库授权与 RLS 仍待完成；Core RDBMS 查询和 ToolPack 动态工具已有脱敏 span，定向集成测试通过不能替代生产验收。

## 2026-09-25 增量：退款指标订单 cohort 版本

- [x] `paid_refund_amount` 新增已发布 2.0.0，按退款对应原订单的下单日期归集；1.0.0 继续按退款发生日期统计，默认版本保持 1.0.0。
- [x] 指标 SQL 构建器仅允许受 Schema 元数据约束的订单日期字段，并复用 tenant executor 对退款和订单视图的租户过滤；派生指标依赖仍显式固定版本。
- [x] 回归用例使用退款日落在筛选区间、但原订单日不在区间的日期边界，分别验证两版本返回 2,000 分与空值；HTTP API 测试覆盖显式请求 2.0.0。
- [x] 验证：企业 Text-to-SQL 全量测试 79 项通过；Ruff check/format、`py_compile`、指标目录 JSON 校验和 `git diff --check` 通过。
- [x] 指标变更审批与发布审计已实现；毛利率定义及 Agent 指标编译执行已完成，见后续增量记录。其他指标的并行版本可经治理 API 添加。

## 2026-09-25 增量：分析页选择退款口径版本

- [x] Vue 分析页在选择已支付退款额时提供 1.0.0（退款发生日）和 2.0.0（原订单日）选择；API 请求、同比查询、指标卡、SQL 预览及 XLSX 中该退款指标都传递所选版本。
- [x] 验证：前端 Node 单测 7 项通过，Vite production build 成功；后端企业 Text-to-SQL 全量 79 项通过；Ruff、`py_compile`、JSON 校验和 `git diff --check` 通过。
- [x] 两种退款口径可从演示 UI 选择；指标发布审批及持久化已实现，派生指标依赖版本固定且 Agent 有确定性 `metric_query` 工具。本机 live scorecard 已运行，但模型 gold 结果精确匹配 0/50，自然语言指标选择质量未通过验收。

## 2026-09-25 增量：经营分析页接入 DB-GPT ReAct Agent

- [x] Vue 页面新增自然语言问题和 DB-GPT 数据源输入；使用同一 OIDC Bearer token 调用 `/api/v1/chat/react-agent`，由服务端按用户校验数据源可见性。
- [x] 新增独立 Vite Agent 代理（默认 `127.0.0.1:5670`，可用进程变量 `DBGPT_AGENT_ORIGIN` 覆盖），流式解析 ReAct `final` 与 SQL 工具 action 并展示答案和 SQL。
- [x] 同一会话支持连续提问；更换身份 token 或数据源会生成新的 conversation ID，避免跨身份/数据源复用前序会话上下文。
- [x] 验证：前端 Node 单测 9 项通过（请求鉴权/数据源载荷、SSE 事件解析、指标版本请求及报告版本）；Vite production build 成功。
- [x] Agent 图表类目点击会筛选同一份结构化 SQL 结果表，不重新执行 SQL；结构化结果继续使用 DB-GPT 原始数据源权限策略。
- [x] 已连接本机 DB-GPT 模型 worker 与授权合成电商 SQLite 完成 Agent 问答及 50 题 live scorecard；ReAct 路径执行 DB-GPT 数据源查询，不经过示例 SQLite tenant executor。当前模型精确匹配 0/50，业务字典遵循与多轮追问质量未通过验收。
- [ ] 生产仍必须使用数据库只读账户及租户/区域 RLS 或租户专属数据源；真实用户数据、业务字典和生产多轮授权尚未验收。

## 2026-09-25 增量：ReAct 数据源业务字典上下文

- [x] 新增 `DBGPT_DATABASE_CONTEXT_FILES` 服务端 JSON 映射，按精确 datasource 名加载 UTF-8 业务字典文件；请求只能选择已授权 datasource，不能提供文件路径或字典正文。
- [x] 文件不存在、映射无效或超过 32 KiB 时不注入；内容作为 reference data fenced 注入主 Agent，并传递给派发的子 Agent，明确数据库 Schema 与授权策略优先。
- [x] README 记录从 `business_dictionary.md` 配置 datasource 上下文的方法；未编辑 `.env` 或写入真实凭据。
- [x] loader helper 测试 3 项通过；改动文件 `py_compile`、Ruff check/format 和 `git diff --check` 通过。
- [x] DB-GPT 子 Agent prompt 和业务字典注入定向测试已通过；本地 Agent live scorecard 50 题精确匹配 0 题，知识字典遵循及模型生成 SQL 的业务验收仍未通过。

## 2026-09-25 增量：分析结果可打印为 PDF

- [x] 分析表格新增“导出 PDF”入口，使用当前身份已获授权的指标摘要、版本定义、日期区间、当前维度结果和 SQL 预览生成独立可打印报告页；浏览器可选择“保存为 PDF”。
- [x] 报告对指标/数据/SQL 字符串做 HTML 转义，并注明结果遵循服务端 OIDC 授权范围；不读取或回显 token。
- [x] 验证：前端 Node 单测 11 项通过，包含 HTML 内容和恶意标记转义；Vite production build 成功。
- [x] 浏览器打印继续支持“保存为 PDF”；后续已增加受服务端身份/租户范围控制的 PDF 字节导出，见“服务端 PDF 报告导出”增量。
- [x] 可恢复异步 XLSX 报告任务已实现；必须配置 `DBGPT_REPORT_ENCRYPTION_KEY` 或 active-first 的 `DBGPT_REPORT_ENCRYPTION_KEYS` 才能入队和启动 worker，报告结果在落库前加密；无 key 时接口返回 503，不创建任务，也不服务历史明文。批量报告、历史结果迁移和 cutoff 清理工具已实现，正式留存策略仍待确定。服务器 PDF 字体配置见“服务端 PDF 报告导出”增量。

## 2026-09-25 增量：安全候选 SQL 攻击面扩充

- [x] 安全评测从 5 项扩为 10 项，新增敏感列聚合、CTE 覆盖受保护表名、CTE 隐藏列、多语句执行和 SQLite 扩展函数调用拒绝。
- [x] 报告仍只输出 case ID、SQL 哈希、状态和行数，不回显候选 SQL 或数据值；当时全量候选 10/10 通过。
- [ ] 安全候选仍是人工构造的固定 SQL；实时 Agent runner 已覆盖固定对抗提示拒绝、澄清、多轮会话和金标准工具结果，但尚未对运行中的 Agent 实际打分，固定短语匹配也不等同于语义安全评审。

## 2026-09-25 增量：递归 CTE 与查询时间预算评测

- [x] 安全候选增至 11 项，加入无界递归 CTE 查询；受限执行器拒绝该查询，候选报告不暴露 SQL 或结果数据。
- [x] 增加昂贵允许表交叉连接测试：100 ms 执行预算内中断查询并写入拒绝审计。两项定向回归测试通过。
- [x] 验证：企业 Text-to-SQL 全量测试 82 项通过，包含 40 条金标准、11 条安全候选及租户 API 回归；JSON、`py_compile`、Ruff check（忽略文件原有长行规则）和 `git diff --check` 通过，评测器文件格式检查通过。
- [ ] 固定候选仍不代表真实 Agent 对资源消耗 SQL 的生成分布或生产数据库方言行为。

## 2026-09-25 增量：安全候选覆盖 SQLite 主表限定绕过

- [x] 加入显式引用 `main.orders` 并伪造当前 tenant 的候选，验证 SQLite 主 schema 限定不会绕过服务端 tenant 临时视图授权。
- [x] 安全候选 bundle 增至 12 项；CLI evaluator 的固定 tenant 执行器回归验证拒绝该查询，报告仍只包含 case ID、SQL 哈希和状态。
- [x] 电商演示全量回归 82 项通过（含 40 条金标准和 12 条安全候选）；Starlette/httpx 仅有弃用警告。
- [ ] 仍需在 PostgreSQL/MySQL 数据源和 DB-GPT 实际 Agent 链路分别验证其数据库侧行级授权。

## 2026-09-25 增量：ReAct 查询结果图表

- [x] ReAct SQL 工具在保留原有 Markdown observation 的同时，返回最多 50 行 JSON-safe 结构化查询结果；SSE 新增 `step.result` 事件，最多 128 KiB，且只序列化列名、行、总行数和截断状态。
- [x] Vue 页面展示 Agent SQL 对应的数据表，并按非数值分类列和数值列生成图表；不再另行执行 Agent 提供的 SQL。README 说明该结果沿用 DB-GPT 数据源权限策略，不继承独立指标 API 的 tenant executor 授权。
- [x] 前端 15 项 Node 测试通过，Vite production build、Python `py_compile`、Ruff check/format 与 `git diff --check` 通过。
- [x] SSE 结果序列化器独立测试 6 项通过，覆盖事件结构、无效载荷、行数上限、字节上限及不透传额外字段。
- [ ] App 级 ReAct SQL 工具及 SSE 结构化结果定向集成测试已在临时完整项目环境通过；真实模型及数据库端到端图表验收仍未完成。

## 2026-09-25 增量：指标依赖环校验与递归编译

- [x] 指标目录加载时沿每个固定版本引用递归遍历依赖图，检测并拒绝环依赖；共享子依赖只访问一次。
- [x] 新增嵌套无环图和版本级环依赖测试；语义指标编译器现按每条依赖固定版本递归生成有序 CTE，并复用共享依赖；退款率以分母维度作为锚点，保留有销售但无退款的区域/月。
- [x] 新增嵌套派生指标 SQLite 执行回归，覆盖总量与区域维度；企业 Text-to-SQL 全量回归 128 项通过，Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [x] 合成 SQLite 目录的指标治理/审批和 ReAct 主/子 Agent `metric_query` 编译调用已有集成回归；生产指标目录及真实模型选型仍待验收。

## 2026-09-25 增量：ReAct SQL 查询 Trace span

- [x] DB-GPT 主/子 Agent SQL 工具调用共享只读查询入口时，创建 `agent.sql_query` span；结束 metadata 包含操作者、数据源、授权策略版本、会话 trace、SQL 哈希、数据库方言、执行状态、耗时、行数及截断状态，不包含 SQL 原文。
- [x] Core 隔离 span 回归测试 2 项通过，覆盖成功及权限失败路径，验证身份/数据源/策略/对话 trace、最终 SQL 哈希、执行状态、耗时和行数 metadata，且不包含 SQL 或驱动敏感错误文本。
- [ ] 主/子 Agent 上下文到 span 的端到端传播、部署环境 Collector 联调及生产行级授权审计仍待验证；Core RDBMS Resource 与 ToolPack 查询已生成脱敏 span，Core OTLP gRPC 本地 collector 往返已覆盖，Core/App 定向回归可在完整临时项目环境运行。

## 2026-09-25 增量：华南区季度销售额与退款率金标准

- [x] 金标准集新增 q41，使用业务大区元数据 `area='South China'` 联查完成订单与已支付退款，按季度返回销售额和退款率；候选 SQL 通过 tenant-scoped SQLite 执行器，预期结果为 77,000 分和 6.1%。
- [x] 同步 `gold_candidates.json`、问答数断言和 README；用映射了 `tenant-a` / `a-gz` / `sales` 的 JWT 请求同一 q41，确认销售角色只看到广州范围并得到 45,000 分、5.56%。41 条金标准及整套演示回归 82 项通过，12 条安全候选仍全部通过。测试命令见本文件“当前代码及测试入口”。
- [ ] 该结果证明合成数据上的固定 SQL 与口径，不代表用户输入经 DB-GPT Agent/真实模型生成并完成查询图表闭环；模型及数据源联调仍待进行。

## 2026-09-25 增量：ReAct 多轮会话展示

- [x] Vue ReAct 面板保留同一会话中的连续问题和回答，并继续复用 DB-GPT conversation ID；更换 OIDC token 或 datasource 时清空 transcript 并创建新会话，避免展示或复用其他授权范围的历史。
- [x] 增加会话状态单测，覆盖连续追问保留问答及授权范围变化后重置；前端 17 项 Node 测试通过，Vite production build 成功。
- [ ] DB-GPT 真实 Agent 是否能依据前序季度、区域、指标定义回答省略上下文的追问，仍待接入真实模型和授权数据源联调。

## 2026-09-25 增量：业务字典补充多轮指标规则

- [x] `business_dictionary.md` 明确同会话上下文继承边界、歧义澄清条件、城市退款率规则及销售额/退款额/净销售额/退款率的 1.0.0 与 2.0.0 定义、默认版本和依赖版本；继续要求每次请求独立执行服务端授权。
- [x] 改动仅更新服务端已配置加载的参考字典和路线图，`git diff --check` 通过。
- [ ] Agent 对这些规则的遵循仍未通过真实模型或端到端生成 SQL 验证。

## 2026-09-25 增量：拒绝只读语句中的数据库状态写入函数

- [x] SQLGlot AST 规则新增拒绝 PostgreSQL 序列/大对象写入、服务器文件/会话控制函数，以及 MySQL `LAST_INSERT_ID(expr)` 和 `LOAD_FILE()`，避免只按 `SELECT` 语句形态判断只读性。
- [x] 新增 PostgreSQL/MySQL 方言回归用例；隔离 SQLGlot smoke 确认 13 种有副作用或服务器文件访问查询均拒绝，PostgreSQL 只读 `currval` 和 MySQL 无参数 `LAST_INSERT_ID()` 保持可用。改动文件 py_compile、Ruff check/format 和 `git diff --check` 通过。
- [x] 函数行为依据：[PostgreSQL 序列函数](https://www.postgresql.org/docs/16/functions-sequence.html)、[PostgreSQL 大对象函数](https://www.postgresql.org/docs/16/lo-funcs.html)、[PostgreSQL 系统管理函数](https://www.postgresql.org/docs/17/functions-admin.html)、[MySQL `LOAD_FILE()`](https://dev.mysql.com/doc/refman/8.4/en/string-functions.html)。
- [x] 新增 PostgreSQL/MySQL 副作用函数及 SQL 编辑器执行路径用例已纳入 Core/App 定向集成回归并通过；生产数据库权限仍需真实实例验收。
- [ ] AST 拒绝列表只是纵深防御，生产仍须用数据库侧最小权限账户，并验证真实 PostgreSQL/MySQL 权限配置。

## 2026-09-25 增量：跨方言查询行数上限回归

- [x] PostgreSQL `FETCH FIRST` 较小限制原先会被扩大到默认 1,000 行；现保留 `FETCH FIRST 100`，超出上限仍改写为 `LIMIT 1000`。
- [x] 增加 PostgreSQL 普通 LIMIT、FETCH FIRST、绑定参数及 MySQL `LIMIT offset,count` 的回归用例；SQLGlot 隔离 smoke 五种输入均符合预期，Ruff、格式检查、`py_compile` 和 `git diff --check` 通过。
- [ ] Core/App 定向 pytest 已在隔离临时项目环境执行；尚未连接真实 PostgreSQL/MySQL 实例验证数据库执行行为、只读角色与服务器端权限。

## 2026-09-25 增量：Vue OIDC Authorization Code + PKCE 登录

- [x] 演示页可运行时配置 OIDC issuer 和 public client ID，使用 Authorization Code + PKCE S256、state、nonce 和 Discovery；不使用浏览器 client secret。
- [x] 令牌回跳验证 state 和可选 authorization response issuer；`jose` 验证 ID Token 签名、issuer、audience、过期时间、subject、nonce 和授权方，再将 access token 保留在页面内存中。事务期间仅把 state/nonce/verifier 放入当前标签页 sessionStorage，10 分钟后过期并在回调后删除；仍支持手工粘贴 access token。
- [x] 修复 Vue 页面漏导入 `reactive` 的运行时问题；增加协议单测覆盖 PKCE 请求参数、授权码表单字段、签名与 claim 校验、state/issuer 错误、过期事务和不安全 issuer 拒绝。前端全量 24 项通过，Vite production build 成功。
- [x] 启动本地 Vite 页面并通过浏览器确认 OIDC issuer、public client、access token 与登录/清除凭证控件正常渲染；未向外部身份提供方发送请求。
- [ ] 尚未接入实际企业 IdP。部署时须按实际页面 origin 配置 provider redirect URI、web origin/CORS，并确保 access token audience 与 DB-GPT API 一致；真实企业 Realm 登录、后端鉴权及数据范围端到端验证仍待完成。

## 2026-09-25 增量：限制 OIDC 开发 HTTP 到 loopback

- [x] `DBGPT_OIDC_ALLOW_INSECURE_HTTP=true` 现只允许 issuer 和 Discovery 返回的 JWKS 地址使用 localhost、127.0.0.0/8 或 IPv6 loopback；非 loopback HTTP 地址仍拒绝，不能用开发开关连接远程明文 IdP。
- [x] 新增测试覆盖三类 loopback issuer 放行、远程/保留地址 HTTP issuer 拒绝及远程 HTTP JWKS 拒绝；演示 API/OIDC 测试 18 项通过，Ruff、格式检查、`py_compile` 和 `git diff --check` 通过。
- [x] 开发例外范围与 [OAuth 2.0 Security BCP RFC 9700](https://datatracker.ietf.org/doc/html/rfc9700) 一致：明文 HTTP 仅用于 loopback 开发；生产身份提供方仍须使用 HTTPS。
- [x] OIDC 配置加载阶段还会拒绝空 claim path、空路径段和空的外部/内部角色名，避免错误 JSON 映射延迟到请求时才表现为认证失败。

## 2026-09-25 增量：电商演示离线回归复验

- [x] 按 README 的依赖范围重跑 `examples/enterprise-text2sql` 全套离线测试，覆盖 SQLite 安全执行器、候选评测、OIDC API、语义指标、缓存与导出；当前 86 项通过。
- [x] 测试仅验证固定合成数据和本地 OIDC provider；不代表真实企业 IdP、生产数据源、DB-GPT App 集成或模型生成准确率已验收。

## 2026-09-25 增量：安全候选覆盖 SQLite Schema 探测

- [x] 安全候选从 12 扩展到 14 项，新增 `PRAGMA table_info(orders)` 和 `sqlite_schema` 目录读取，覆盖 SQLite 元数据枚举路径。
- [x] 报告仍只输出 case ID、SQL 哈希、状态和行数；回归断言确保报告不回显 PRAGMA 文本或系统目录名。
- [x] 新增 CLI 端到端测试：加载 44 条金标准和 14 条安全候选、创建合成数据库、写出 scorecard，并检查 SQL、租户标识和敏感值不会泄漏到报告。
- [x] 电商演示全量离线测试 86 项通过；定向 Ruff check/format、`py_compile` 和 `git diff --check` 通过。仍是固定 SQLite 候选，不代表 Agent 实时生成准确率。

## 2026-09-25 增量：固定候选集加入多轮追问上下文

- [x] 金标准集新增 q42–q44 三条带前文的追问：沿用季度/区域计算城市退款率、沿用销售/退款统计口径补算六月退款率、沿用华南季度筛选计算广州销售额占比。
- [x] 三条固定候选在 tenant-scoped SQLite 上与独立录入的列和结果校验；金标准集总数为 44，业务及安全候选 CLI 回归正常。
- [x] 验证：候选评测与 fixture 定向测试 29 项通过；`examples/enterprise-text2sql` 全量回归 86 项通过；JSON、Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [ ] 这些仍是预先给定 SQL 的数据集回归，不证明 Agent 能从多轮上下文正确生成 SQL。

## 2026-09-25 增量：共享指标缓存

- [x] `/metrics/query` 支持从 `DBGPT_METRIC_CACHE_REDIS_URL` 选择共享 Redis TTL 缓存；未配置时继续使用本地有界 LRU。Redis key 对数据源/策略版本、数据库文件签名、用户/租户/区域、指标版本和筛选范围的组合取 SHA-256，不直接暴露身份值。
- [x] Redis 缓存只存已登记指标的 JSON-safe 结果，TTL 默认 30 秒；缓存读取或写入异常时记录不含连接详情的告警，并回退到受限数据库查询。数据库/WAL/journal 文件变化会形成新 key，旧值按 TTL 到期。
- [x] 用三个独立 API 实例和共享 Redis 测试替身验证跨实例命中、不同用户隔离、数据更新失效；另以临时 `redis-py` 环境验证配置工厂可创建真实客户端对象。
- [x] 后续真实服务 smoke 已连接本机启用认证的 Redis，通过 DB 15 和独立客户端验证共享读取、不同身份隔离、约 30 秒 TTL 及键值不含明文身份；唯一随机测试键已删除。
- [x] 验证：`examples/enterprise-text2sql` 全量测试 90 项通过；Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [ ] 当前 smoke 使用本机 Dify 开发 Redis，不代表生产部署；TLS、ACL 最小权限、内存上限/eviction 及真实 Redis 不可用时的服务降级仍待部署环境验证。

## 2026-09-25 增量：SQLite Agent SQL 扩展与元数据访问拦截

- [x] AST 实测发现 SQLite Agent SQL 校验器会放行 `load_extension()`、`readfile()`、`writefile()` 和 `pragma_*` 表值函数；现拒绝 SQLite 扩展加载/文件工具（含 `edit`、`fsdir`、`lsmode`）及 `pragma_*` 函数/表值入口。
- [x] SQL 编辑器的授权写语句现复用同一方言级函数检查，阻止在 INSERT/UPDATE 中嵌入文件或元数据访问函数。
- [x] Core SQL 防护独立回归 25 项通过（SQLite 文件/元数据拦截、跨方言错误分类/重试预算及 PostgreSQL/MySQL 副作用规则）；Ruff check/format、`py_compile` 和 `git diff --check` 通过。检查依据为 SQLite 官方 [PRAGMA table-valued functions](https://www.sqlite.org/pragma.html)、[loadable extensions](https://www.sqlite.org/loadext.html) 和 [CLI 文件 I/O 扩展](https://www.sqlite.org/cli.html) 文档。
- [ ] Core/App SQL 防护定向集成 pytest 已通过；连接器启用扩展后的数据库级权限配置仍需真实 PostgreSQL/MySQL 验收。

## 2026-09-25 增量：安全候选覆盖 SQLite PRAGMA 表值函数

- [x] 在独立执行器安全候选中新增 `SELECT name FROM pragma_table_info('orders')`，补齐普通 PRAGMA 命令之外的 SQLite 表值元数据探测路径；安全候选总数增至 15 项。
- [x] SQL 安全评测确认 15/15 通过，其中 14 个攻击被拒绝、跨区域查询返回空结果；CLI scorecard 的 SQL/敏感值脱敏检查仍通过。
- [x] 验证：企业 Text-to-SQL 全量测试 90 项通过；Core SQL 防护定向测试 25 项通过；Ruff、格式检查、JSON、`py_compile` 和 `git diff --check` 通过。
- [ ] 安全候选仍是固定 SQLite 输入，不代表其他驱动、生产数据库或实时 Agent SQL 生成的实际攻击覆盖率。

## 2026-09-25 增量：SQL 错误分类与 Agent 纠错预算回归

- [x] Core helper 定向测试覆盖 PostgreSQL SQLSTATE、MySQL 错误码、SQLite 常见错误消息和超时分类；断言返回信息不会暴露驱动原文。
- [x] 测试验证语法/Schema 错误只允许一次纠错、权限拒绝不消耗预算也不可重试、成功后重置预算可再次尝试。
- [x] Core datasource SQL guard 独立测试 25 项通过；Ruff、格式检查、`py_compile` 和 `git diff --check` 通过。
- [x] 主/子 Agent 工具结构化错误分类、纠错预算、权限拒绝不可重试及脱敏已通过 Core/App 定向回归；真实模型对纠错提示的行为仍待现场评测。

## 2026-09-25 增量：安全候选覆盖 SQLite 文件 I/O 扩展

- [x] 在独立安全候选中新增 SQLite CLI/扩展提供的 `readfile()` 与 `writefile()`，检查执行器在 extension 函数实际可用与否之外仍会按授权策略拒绝调用。
- [x] 安全候选总数增至 17 项；分数报告应拒绝 16 项攻击，仅跨区域范围案例预期返回空结果，并继续隐藏原始 SQL。
- [x] 候选安全评测及 CLI 脱敏回归通过；电商演示全量测试 90 项通过，Ruff check/format、JSON 和 `git diff --check` 通过。
- [ ] 当前评测使用 SQLite authorizer 固定策略；不能替代 SQLite 连接初始化审查和 PostgreSQL/MySQL 文件函数、扩展权限的方言验证。

## 2026-09-25 增量：安全候选覆盖 SQLite PRAGMA 枚举函数

- [x] 新增 `pragma_table_list` 和 `pragma_function_list` 表值函数候选，覆盖 SQLite 对象与可用 SQL 函数枚举路径；策略期望均为拒绝。
- [x] 安全候选总数增至 19 项；评测 19/19 通过，其中 18 项拒绝、1 项跨区域查询返回空结果；报告仍只保存 case ID、状态、SQL 哈希及行数。
- [x] 电商演示全量回归 90 项通过；Ruff、格式检查、JSON 校验和 `git diff --check` 通过。

## 2026-09-25 增量：歧义澄清动作固定评测

- [x] 新增 6 条有明确缺失口径的歧义问题，候选 JSON 对每条选择 `clarify` 并列出需要补齐的字段；评测同时比较动作和字段集合，提前直接作答会计为错误。
- [x] CLI 可选接入独立歧义候选包；报告只记录 case ID、状态和响应哈希，不输出问题或候选文本。README 明确这只是固定标签基准，不代表真实 Agent 或模型追问质量。
- [x] 验证：企业 Text-to-SQL 全量测试 96 项通过；歧义候选 JSON、`py_compile`、Ruff check/format 和 `git diff --check` 通过。
- [ ] 真实 DB-GPT Agent 的歧义识别、追问可用性及用户补充信息后的多轮 SQL 仍未接入评测。

## 2026-09-25 增量：真实 Keycloak OIDC 本地联调

- [x] 使用本机已有的 Keycloak 26 容器镜像建立临时 Realm 和测试用户，实际签发 Bearer JWT；Serve 成功通过 Discovery/JWKS 验签、issuer/audience 校验，并映射 `sub`、嵌套 `organization.tenant`、region claim 和 `regional-sales` 角色。
- [x] 临时容器、Realm 和随机测试凭据已在 smoke 结束后清理；没有写入仓库配置或复用生产身份信息。
- [ ] 该 smoke 使用 loopback HTTP 和测试专用 token 签发流程，只证明后端与 Keycloak 26 的协议/claim 互通；企业 IdP 配置、Vue Authorization Code + PKCE 浏览器闭环及生产 HTTPS/CORS/数据授权仍待部署环境验收。

## 2026-09-25 增量：多轮租户/区域授权候选评测

- [x] 新增 3 组固定 SQL 对话序列，覆盖租户切换请求、销售身份切换到非授权区域、CTE 隐藏租户键等后续追问；每组在同一个服务端租户/区域执行器中运行，并验证授权查询在拒绝/过滤后仍保持原范围。
- [x] 评测报告仅输出场景 ID、轮次状态和 SQL 哈希；序列长度、SQL 类型及场景 ID 均经输入校验，CLI 可选输出多轮授权分数。
- [x] 验证：企业 Text-to-SQL 全量测试 101 项通过；Ruff check/format、JSON、`py_compile` 和 `git diff --check` 通过。
- [ ] 该回归证明固定 SQL 序列受 SQLite 演示策略约束，不证明真实 Agent 会产生安全查询，也不替代生产数据库 RLS/多轮授权验收。

## 2026-09-25 增量：本地分析页复验

- [x] Vue 页面 Node 用例 24 项通过；Vite 生产构建成功，共转换 650 个模块，最大延迟 chunk 258.89 kB（gzip 82.91 kB）。
- [ ] 本机默认 DB-GPT Agent 端口 5670 当前未监听，因此此轮只验证页面模块与静态构建；真实模型、授权数据源及浏览器到 Agent 的端到端调用仍待服务环境可用后验收。

## 2026-09-25 增量：服务端 PDF 报告导出

- [x] 新增 `POST /reports/export.pdf`，与 XLSX 共用同一租户/区域授权执行器和指标收集逻辑；报告包含授权范围、生成时间、日期区间、维度、指标版本/口径和过滤结果，并写入不含 SQL 原文的 PDF 导出审计事件。
- [x] Vue 页面新增服务端 PDF 下载按钮，保留浏览器打印入口；PDF 使用 ReportLab 简体中文 CID 字体和可重复表头的分页表格。macOS Quick Look 样例渲染已确认中文、标题、指标表和结果表正常。
- [x] 验证：企业 Text-to-SQL 全量测试 104 项通过；Node UI 测试 25 项通过；Vite build、Ruff、`py_compile` 和 `git diff --check` 通过。PDF 回归检查 MIME/PDF 签名、tenant/region 范围、指标版本、审计事件、中文文本及多页重复表头。
- [x] 单份与批量异步 XLSX 报告任务已持久化；版本化字段模板策略已在后续增量补齐。密钥轮换/历史明文迁移及留存清理仍未实现。异步结果的可选应用层加密已在后续增量补齐。部署时需提供可嵌入 CJK TrueType 字体 `DBGPT_PDF_FONT`，或确保 PDF 阅读器带 Adobe-GB1 CMap（当前最小 Poppler 环境缺少该 CMap）。

## 2026-09-25 增量：候选 SQL 金标准扩展至 50 条

- [x] 新增 q45–q50 六条固定金标准，覆盖月度活跃客户与平均订单金额、品类加权成交单价、商品销售额 Top 3、各地区退款订单率、客户销售额占比及地区订单状态金额分布。
- [x] `gold_candidates.json` 同步加入 6 条 SQL；更新全量问句数、候选包数量断言和示例说明。预期结果由租户受限 SQLite 执行器核对，其中修正了广州退款订单率为 66.67%。
- [x] 验证：`examples/enterprise-text2sql` 全量回归 104 项通过，覆盖 50 条金标准、19 条安全候选、歧义/多轮授权、OIDC 与报告导出；JSON 解析通过。
- [ ] 这些仍是预先编写的 SQL 和合成数据，不代表 DB-GPT Agent 或模型的真实生成准确率。

## 2026-09-25 增量：净销售额退款 cohort 版本

- [x] 指标目录版本升至 1.1.0；新增 `net_sales_amount` 2.0.0，固定依赖 `sales_amount` 1.0.0 与按原订单日期统计的 `paid_refund_amount` 2.0.0；默认版本仍为 1.0.0，避免静默改变既有口径。
- [x] 指标 API 与 Vue 分析页支持显式选择 2.0.0，版本说明区分退款发生日和原订单 cohort；XLSX/PDF 导出把所选版本映射到当前指标。
- [x] 新增边界回归：给第二季度订单插入一笔七月发生的退款，退款发生日版本净销售额为 72,300 分，订单 cohort 版本为 71,300 分；用例覆盖 SQL 构建、指标 API 和租户执行策略。
- [x] 验证：企业 Text-to-SQL 全量回归 106 项通过；Vue 单测 26 项通过、Vite production build 成功；JSON、Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [x] 演示 API 已提供动态发布目录及审批/审计接口；DB-GPT ReAct 仍从服务端配置的目录映射读取。本机 live scorecard 显示精确匹配 0/50，真实模型选择质量未通过验收。

## 2026-09-25 增量：退款率 cohort 版本

- [x] 指标目录版本升至 1.2.0；新增 `refund_rate` 2.0.0，固定依赖 `paid_refund_amount` 2.0.0 和 `sales_amount` 1.0.0；默认口径仍为退款发生日的 1.0.0。
- [x] Vue 版本选择器和报告导出支持退款率 cohort 版本；展示的指标定义说明退款按原订单日期归组。
- [x] 边界回归在第二季度订单上增加七月退款：1.0.0 按退款发生日结果为 6.1%，2.0.0 按原订单 cohort 结果为 7.4%；覆盖租户执行器、语义编译器与指标 API。
- [x] 验证：企业 Text-to-SQL 全量回归 108 项通过；Vue 单测 27 项通过、Vite production build 成功；JSON、Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [x] 动态版本治理、指标变更审批和审计已在演示 API 实现；生产数据验证仍未完成。

## 2026-09-25 增量：PostgreSQL/MySQL SQL 防护回归

- [x] 扩展 Core 方言测试，覆盖 PostgreSQL `FOR UPDATE`、`COPY`、`nextval`、文件读取，以及 MySQL `SLEEP`、`BENCHMARK`、`LAST_INSERT_ID(expr)` 和 `INTO OUTFILE`；均由 SQLGlot 安全层拒绝。
- [x] 新增 fake connector 执行回归，验证 PostgreSQL/MySQL 查询传入 30 秒超时、改写至最多 1,000 行并截断超限结果。
- [x] Core SQL guard 与 tracing 定向测试 36 项通过；Ruff、`py_compile` 和 `git diff --check` 通过。
- [ ] 当前无本地 PostgreSQL/MySQL 实例；只读账户、数据库权限、租户/列级策略及驱动级取消行为仍需真实数据库验收。

## 2026-09-25 增量：实时 ReAct Agent 金标准评测入口

- [x] 新增 `evaluate_agent.py`，按 Vue 已验证的 `/api/v1/chat/react-agent` 请求字段调用 DB-GPT API；默认金标准问题使用独立 conversation ID，同组多轮问题复用 conversation ID，并读取 `step.result` 的结构化 SQL 结果与金标准列/行对比。
- [x] CLI 从环境变量读取短期 OIDC access token、API origin 和 datasource；仅允许 HTTPS 或 loopback HTTP、禁止重定向、限制每条 SSE 流为 2 MiB。报告只包含问题 ID、状态与结果哈希，不包含 token、prompt、SQL、答案或行值。
- [x] 离线协议与脱敏用例覆盖请求载荷、多轮 conversation ID、policy denial/clarification 判分、正确/错误/缺失/截断结果、SSE 解析、URL/HTTP 错误校验及重定向拒绝；企业 Text-to-SQL 全量回归 126 项通过。
- [x] 本机 DB-GPT Agent 已运行并生成真实模型 scorecard；当前 50 题精确匹配 0 题。真实回答解释质量、认证授权和生产数据源策略仍待现场验收。

## 2026-09-25 增量：OIDC 身份提供方与 claim 映射复验

- [x] 已有实现允许 Vue 页面配置 OIDC issuer/public client，并以 Authorization Code + PKCE 登录；DB-GPT Serve 通过 issuer discovery/JWKS 验证 Bearer JWT。Keycloak Realm 配置、tenant/region/role claim 路径和外部角色映射示例见 `examples/enterprise-text2sql/README.md`。
- [x] 本轮复验：后端 OIDC/API 回归 24 项通过；Vue/PKCE 全量 Node 测试 27 项通过，Vite production build 成功。已记录的 Keycloak 26 本地签发与 claim 映射 smoke 通过。
- [ ] 仍需在部署环境使用实际企业 IdP 验证浏览器回调、HTTPS、redirect URI/CORS、API audience 及最终数据授权；本地协议测试不代表生产身份接入验收。

## 2026-09-25 增量：仪表盘 SQL 查询 Trace span

- [x] `ChatDashboard` 将当前用户名、数据源名和会话 ID 传给共享只读查询入口；仪表盘查询创建独立 `dashboard.sql_query` span，记录 SQL 哈希、方言、耗时、行数及结果状态，不记录 SQL 原文。
- [x] Core span 测试 5 项通过，覆盖默认 Agent span、指定操作名以及成功/权限失败 metadata；改动文件 `py_compile`、Ruff check/format 通过。
- [x] 仪表盘 loader 测试 5 项通过；一组包含 SQL 工具、ReAct 子工具/dispatcher、编辑器图表、仪表盘和 Core tracing 的定向 Core/App 回归共 54 项通过。使用的依赖环境位于 `/tmp`，未修改项目依赖声明。
- [x] SQL 编辑器和图表编辑器执行分别创建 `editor.sql_execution` 与 `editor.chart_query` span，记录操作者、数据源、策略版本、请求 trace、会话、SQL 哈希、方言、耗时、行数及状态，不记录原始 SQL 或绑定值。
- [x] 历史图表回放查询创建 `editor.chart_replay` span；路由将已认证用户、可见数据源、会话 ID 和请求 trace 传入服务层，回放 SQL 继续经过共享只读查询入口；日志只写会话和图表标题，不回显请求体。
- [x] 合并运行 SQL 主/子 Agent、dispatcher、编辑器图表、图表回放、仪表盘和 Core tracing 定向回归，58 项通过；覆盖编辑器 span、查询授权上下文、纠错预算和 SQL 脱敏。Ruff check/format、`py_compile` 及 `git diff --check` 通过。
- [x] 扩大 Core/App/SQLite/Spark SQL 网关与日志回归共 189 项通过；SQLite `fetch="one"` 测试断言已对齐接口的行元组列表返回契约，RDBMS 和 Spark 日志断言 SQL 指纹存在且原始 SQL 不出现。
- [ ] 主/子 Agent trace 端到端、部署环境 Collector 联调和生产行级授权审计仍待验证；Core RDBMS Resource 与 ToolPack 动态工具 span 已覆盖。

## 2026-09-25 增量：Agent 指标语义提示上下文

- [x] DB-GPT ReAct 主/子 Agent 已能通过服务端 `DBGPT_DATABASE_CONTEXT_FILES` 加载指定数据源的业务字典；现将销售额、已支付退款额、净销售额、退款率的 1.0.0/2.0.0 口径、默认值及固定依赖写入该上下文，避免 Agent 只看到目录摘要却缺少版本解释。
- [x] 企业 Text-to-SQL 全量回归 120 项通过；Core/App/SQLite SQL 网关定向回归 187 项通过；`git diff --check` 通过。
- [x] 指标变更审批和持久化发布治理已实现；prompt 与固定 SQL/API 回归仍不能证明真实模型一定遵循指标定义。本机实时 Agent scorecard 已完成，但 50 题精确匹配 0 题，真实模型遵循指标定义的质量未通过验收。

## 2026-09-25 增量：实时 Agent 多轮评测会话

- [x] `evaluate_agent.py` 支持 JSON 数据集中的 `conversation_group`；同组轮次复用一个新生成的 UUID conversation ID，不同组和未分组问题相互隔离，scorecard 不输出组名。
- [x] 新增两组华南季度销售额/退款率上下文追问金标准，覆盖“哪个城市退款率最高”和“广州销售额占比”；CLI 支持 `--dataset agent_multiturn_questions.json`。
- [x] 企业 Text-to-SQL 全量回归 122 项通过；Core/App/SQLite SQL 网关定向回归 187 项通过。
- [x] 本机 DB-GPT Agent 已启动并执行 gold scorecard：50 题精确匹配 0 题；评测固定合成数据不能证明真实模型的多轮理解或生产授权。

## 2026-09-25 增量：实时 Agent 拒绝与澄清策略评测

- [x] 实时评测器新增 policy 模式，调用正式 ReAct API，要求拒绝/澄清场景不得产生结构化 SQL 结果，且最终回答命中该案例的固定响应短语；结果报告仅保留 case ID、状态和回答哈希。
- [x] 新增 6 条合成策略用例：拒绝导出邮箱/内部成本/跨租户数据，澄清缺失时间范围或指标的问题；CLI 使用 `--evaluation-type policy --dataset agent_policy_cases.json`。
- [x] 企业 Text-to-SQL 全量回归 126 项通过，评测器定向回归 18 项通过；Ruff check/format、`py_compile`、JSON 解析及 `git diff --check` 通过。
- [ ] 固定短语判分只是可重复基准，不等同语义审核；拒绝/澄清 policy scorecard 尚未对运行中的 DB-GPT Agent 执行，生产拒绝行为仍须数据库权限与 RLS 保障。

## 2026-09-25 增量：OTLP gRPC SQL trace 导出验证

- [x] Core tracer 测试启动 loopback OTLP gRPC collector，使用 DB-GPT 现有 `OpenTelemetrySpanStorage` 实际导出父/子 span；验证 service name、parent ID 和 Agent 安全 metadata 到达 collector。
- [x] SQL span 测试字段包含操作者及 SQL 哈希，不含原始 SQL；Core/App/SQLite/Spark/OTLP 定向回归 199 项通过，企业 Text-to-SQL 回归 126 项通过。
- [x] README 记录以 `TRACER_TO_OPEN_TELEMETRY` 和标准 OTLP traces 环境变量启用 DB-GPT exporter，不修改 `.env`。
- [ ] 本地 collector 往返不等于部署 Collector 或 OpenObserve 的网络、TLS、认证和数据保留策略验收；真实 Agent 主/子 trace 仍需在运行服务中端到端验证。

## 2026-09-25 增量：SSE 请求 Trace 生命周期与 OIDC 回归

- [x] 将 `TraceIDMiddleware` 改为纯 ASGI 中间件，使请求 span 覆盖完整 SSE 响应体；新增回归验证请求父 span、流式 SQL 子 span 的父子关系和结束顺序，并确认 Authorization Bearer 值不会写入日志。
- [x] 中间件回归 1 项通过；OIDC/API 回归 24 项通过；改动文件 Ruff check/format 和 `py_compile` 通过。
- [x] OIDC/JWT 已具备配置化 issuer/audience、Discovery/JWKS 验签、标准 claim 到 DB-GPT `UserRequest` 字段的映射、外部角色映射；Keycloak Realm 与嵌套 tenant/region claim 示例记录在 `examples/enterprise-text2sql/README.md`，本地 Keycloak 26 smoke 已验证实际 Bearer JWT。
- [ ] 企业 IdP 的浏览器 PKCE 回调、HTTPS/CORS 和生产数据库授权仍需在部署环境验收；截至 2026-09-28，默认 ReAct Agent 已使用验签后的 tenant/region 执行应用层行范围策略，并有签名 JWT→主/子 SQL 工具集成回归。OIDC 示例 API 仍是隔离演示服务，完整 IdP discovery、owner ACL 与 PostgreSQL RLS 联动尚未在本测试中覆盖，详见 2026-09-28 集成回归记录。

## 2026-09-25 增量：RDBMS 与 Spark 查询审计字段

- [x] Core RDBMS `query_ex` 与 Spark `run` 现在记录方言（RDBMS）、SQL SHA-256、成功/失败/超时状态、耗时和返回行数；不记录 SQL 原文、结果值或驱动错误文本。
- [x] SQLite connector 与 Spark connector 定向回归 25 项通过，覆盖成功、超时、失败状态和日志脱敏；四个改动文件 Ruff check/format 通过。
- [x] 上层 Dashboard/editor 与共享只读执行路径已补充可信操作者、角色、tenant/region、业务数据源 ID、授权策略版本及 trace；事件只记录 SQL 哈希、状态、耗时、行数和错误类别，不记录 SQL 原文、结果值或驱动错误文本。
- [ ] 各生产数据库驱动的实际取消/超时、日志管道与 Collector/OpenObserve 部署导出仍待环境验收。

## 2026-09-25 增量：Agent 动态指标目录查询

- [x] 新增只读 `metric_catalog` 工具并注册到 ReAct 主 Agent 与子 Agent；只读当前已授权 datasource 对应的运维映射文件，返回目录版本、指标定义、单位、默认版本和固定依赖版本。
- [x] 目录文件大小限制为 128 KiB，最多 100 项；路径只来自服务端 `DBGPT_METRIC_CATALOG_FILES` 配置，`metric_catalog` 响应不包含表名/列名或文件路径，查询 SQL 通过已有 `sql_query` 安全执行路径。
- [x] App 定向回归 20 项通过，覆盖 datasource 映射隔离、默认/显式版本选择、未发布版本和无效目录 fail-closed；Ruff、格式检查、`py_compile` 和 `git diff --check` 通过。
- [x] 目录查询、编译工具及指标目录变更审批/持久化发布已提供；本机 live scorecard 已运行，但模型精确匹配 0/50，是否选择正确指标/版本未通过质量验收。受限毛利率定义与执行规则见本路线图“受限角色毛利率指标”增量记录。

## 2026-09-25 增量：完整离线回归复验与本机服务状态

- [x] `examples/enterprise-text2sql` 全量 pytest 138 项通过（使用路线图列出的 PDF/Excel 依赖完整命令；包含 Schema 列策略候选评测）；Vue Node 测试 27 项通过；Vite production build 成功（650 modules）。
- [x] 当前端口复验：DB-GPT Agent API 5670、默认 PostgreSQL 5432、MySQL 3306、Redis 6379 均未监听；本机 OpenObserve 映射 5080，但未映射 OTLP gRPC 端口。15433 属于现存 Dify PostgreSQL，本轮未连接或改动。
- [ ] 因此本轮只证明合成电商样例与离线协议回归通过；真实 DB-GPT Agent scorecard、生产 PostgreSQL/MySQL 授权及部署 Collector/OpenObserve trace 仍需对应服务配置并运行后验收。

## 2026-09-25 增量：OIDC/JWT 身份提供方与 claim 映射复验

- [x] 确认 Keycloak Realm 接入说明、access-token audience 配置、tenant/region/realm-role claim 路径及外部角色映射示例已写入企业 Text-to-SQL README；DB-GPT Serve 支持 issuer discovery、JWKS 验签和 claim 到 `UserRequest` 的映射。
- [x] 后端 OIDC/API 测试 24 项通过，前端 OIDC Authorization Code + PKCE 单测包含在 Node 27 项通过中；Vite production build 成功，转换 650 个模块。既有 Keycloak 26 smoke 已用实际签发的 Bearer JWT 验证嵌套 tenant、region 和 role 映射。
- [ ] 企业 IdP 的浏览器回调、HTTPS/CORS、API audience 与最终数据库授权仍需部署环境验收；当前测试不代表默认 DB-GPT Agent 查询路径已应用相同的租户/区域行级策略。

## 2026-09-25 增量：并行 Agent tracer span 栈隔离

- [x] 将 `DefaultTracer` 的 ContextVar span 栈从可变列表改为不可变 tuple，避免并行 async 子任务继承并共享可变栈；新增 `asyncio.gather` 回归，确认兄弟 span 隔离且父 span 上下文恢复。
- [x] Tracer 实现、中间件与 OTLP 定向回归 12 项通过；Ruff check/format 与 `git diff --check` 通过。
- [ ] 真实 DB-GPT 主/子 Agent trace 端到端及部署 Collector/OpenObserve 联调仍待服务可用后验证。

## 2026-09-25 增量：嵌套指标递归编译与候选集复验

- [x] 语义编译器现递归解析派生指标 pin 住的依赖版本，复用共享依赖并生成有序 CTE；维度比率用分母维度作锚点，保留有销售但无退款的时间段/区域。
- [x] 新增嵌套派生指标的总量和区域 SQLite 执行回归；企业 Text-to-SQL 全量 pytest 128 项通过，固定候选 scorecard 为金标准 50/50、安全策略 19/19、歧义澄清 6/6、多轮租户/区域授权 3/3。
- [x] Ruff check/format、`py_compile` 和 `git diff --check` 通过；README 与路线图说明递归编译能力和剩余边界。
- [ ] scorecard 仍使用预先编写的 SQL 与合成 SQLite 数据，不代表实时 Agent SQL 生成质量、生产数据库方言或企业授权验收。

## 2026-09-25 增量：ReAct 主/子 Agent 确定性语义指标查询

- [x] 新增 `metric_query` 工具，接受已发布指标 ID/版本、ISO 日期范围和区域/月维度；表、列、状态条件只从当前已授权数据源对应的服务端目录读取，拒绝未发布版本、无效标识符、循环依赖和不支持的计算/方言。
- [x] 工具递归编译固定版本依赖；生成 SQL 交给现有 `sql_query` 工具执行，复用 SQL AST 只读校验、执行超时、行数上限、纠错分类与脱敏审计。主 Agent 与派发子 Agent 均注册此工具。
- [x] ReAct 工具、dispatcher、business-context 定向回归 35 项通过，覆盖 SQLite 端到端编译执行、版本 pin、区域结果、审计路径、工具状态隔离、目录路径映射、注入日期拒绝和三种方言的月度表达式；另有 Agent SSE 生命周期回归 7 项通过，合并 42 项通过。
- [x] 修复外层 ReAct SSE 流关闭时未显式关闭内层 Agent iterator 的任务泄漏；客户端关闭/断开后现会取消并等待后台 Agent task，再关闭附件上下文。
- [x] 使用隔离 PostgreSQL 16.6 和 MySQL 8.4 实例执行 DB-GPT 指标编译器生成的月度销售额与毛利率 SQL；两种引擎均返回预期月份及数值，验证了 `TO_CHAR` / `DATE_FORMAT` 表达式与聚合行为。临时容器已停止。
- [ ] 该 smoke 只验证指标 SQL 在真实方言引擎上执行；企业生产 tenant/region RLS、数据库权限/可信身份注入、指标治理与实时模型是否选对指标仍未验收。

## 2026-09-25 增量：候选 SQL 评测覆盖 PostgreSQL/MySQL AST 策略

- [x] 候选评测器新增 `--dialect-security-candidates`，复用 DB-GPT Core `validate_read_only_sql`，对 PostgreSQL/MySQL 各自的 SELECT 控制项、写入/写入 CTE、锁、文件访问、资源消耗函数和多语句做 accept/reject 评分。
- [x] scorecard 只包含方言、case ID、决策和 SQL 哈希，不输出候选 SQL；读取器校验受支持方言、case ID、输入大小和 SQL 长度，CLI 任一方言策略失败即退出非零。
- [x] 方言候选评测集新增 17 项（PostgreSQL 8、MySQL 9）；`test_evaluate_candidates.py` 26 项通过，覆盖完整 CLI bundle、恶意 SQL 脱敏、缺失/错误候选和策略绕过判分。
- [ ] 该新增 suite 只运行 SQLGlot AST 验证，没有执行 SQL；真实 PostgreSQL/MySQL 授权、RLS、超时取消和驱动行为仍需数据库环境验收。

## 2026-09-25 增量：Dispatcher 子 Agent trace span

- [x] 并行 dispatcher 为每个子 Agent 创建 `agent.subagent_dispatch` span，显式关联当前请求父 span，结束时记录状态和耗时；metadata 仅包含 Agent ID、批次与索引，不包含任务 prompt。dispatcher 与 builder 定向回归 24 项通过；新增用例通过 ASGI TraceIDMiddleware 和真实 DefaultTracer 检查请求父 span 与并行子任务 span 的关系，其他断言覆盖敏感 prompt 不进入 metadata、成功/失败状态与耗时；`py_compile`、Ruff check/format 和 `git diff --check` 通过。
- [x] 同步复验企业 Text-to-SQL 全量离线套件：133 项通过，覆盖 OIDC/JWT 演示 API、租户查询、指标、缓存、候选 SQL 评测及前端 API helper。
- [ ] 当前已在 ASGI 请求与并行 dispatcher 层验证父子 span；仓库内 Agent 工具入口的脱敏 span 已覆盖。真实 DB-GPT Agent 模型请求、部署 Collector/OpenObserve 网络与认证、生产租户行级授权审计仍未完成。

## 2026-09-25 增量：OIDC tenant/region claim 纳入 Agent SQL 审计

- [x] `/v1/chat/react-agent` 将已验证身份映射出的 `tenant_id` 和 `region_id` 随 actor、数据源和授权策略版本传入主/子 Agent SQL 审计上下文；结构化 `agent_sql_audit` 事件现包含这两个身份范围字段，不记录 SQL 原文。
- [x] 主 Agent SQL 工具、子 Agent SQL 工具及 SSE 生命周期定向回归 33 项通过，验证 tenant/region 字段出现且 SQL 脱敏断言继续通过；Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [ ] 默认 ReAct SQL 查询现使用可信身份执行 tenant/region 行级过滤；其他查询入口的覆盖及 PostgreSQL/MySQL RLS、租户专属数据源仍需部署验收。审计字段本身不替代数据库授权。

## 2026-09-25 增量：Agent 指标目录 span

- [x] 指标目录工具发出 `agent.metric_catalog` span，记录授权数据源 ID、成功/缺目录/未发布/失败状态和耗时；不记录用户 prompt、指标值或目录内容，span 创建或结束失败不会改变工具结果。
- [x] ReAct 工具回归 20 项通过，新增用例覆盖成功状态、数据源 metadata、耗时字段和不记录指标 ID；Ruff check/format、`py_compile` 与 `git diff --check` 通过。
- [ ] 此项补齐语义目录读取的 span；仓库内其他 Agent 工具已有对应 span，真实模型请求及部署 Collector 导出仍需验收。

## 2026-09-25 增量：语义指标编译到 SQL 执行 Trace

- [x] `metric_query` 创建 `agent.metric_query` span，编译并执行时底层 `agent.sql_query` 自动成为其子 span；记录数据源、状态和耗时，不在父 span 中记录指标 ID、SQL 或用户输入。
- [x] ReAct 工具回归 21 项通过；新增真实 `DefaultTracer` 父子 span 测试，执行确定性 SQLite 指标查询并确认 `request → agent.metric_query → agent.sql_query` 层级和成功状态；Ruff check/format、`py_compile` 及 `git diff --check` 通过。
- [ ] 该测试用合成 connector；真实模型请求、PostgreSQL/MySQL 引擎和部署 Collector 的 trace 导出仍未验收。

## 2026-09-25 增量：ReAct 请求共享 SQL 执行预算

- [x] 每个 ReAct 请求创建共享线程安全预算，主 Agent 与并行子 Agent 共用：每轮最多 20 次 SQL 尝试、最多累计 120 秒数据库查询时间；单条查询超时会被限制到当前剩余预算，预算耗尽返回不可重试的 `budget_exhausted`，不会调用 connector。
- [x] Core/App 定向回归 46 项通过，覆盖总查询次数、累计执行时间、并行预留、共享到子 Agent 的预算身份、有限超时传递及预算耗尽后的 fail-closed 工具响应；Ruff、格式、`py_compile` 与 `git diff --check` 通过。
- [x] 修正累计耗时只记录 connector `query_ex` 执行区间；SQL AST 校验、tracing 和结果包装耗时不再计入数据库预算，验证失败仍会释放并行预留。
- [x] 本轮合并执行 Core/App SQL 防护、主/子工具、dispatcher 和 SSE 生命周期定向回归 54 项通过；Ruff、`py_compile` 和 `git diff --check` 通过。
- [ ] 该处记录的单请求数据库调用预算之外，ReAct/knowledge-agent 的 tenant+user UTC 日 Token 配额已在 2026-09-25 后续增量实现；其他模型端点的统一配额、金额配额仍未实现。数据库侧 statement timeout、只读账号及生产成本监控也仍需部署侧保障。

## 2026-09-25 增量：候选 SQL 全量 scorecard 复验

- [x] 使用统一 evaluator 命令在新建的 `/tmp` 合成数据库上运行全部候选集：金标准 50/50、SQLite 安全策略 19/19、PostgreSQL/MySQL AST 20/20、Schema 列策略 10/10、tenant/region 行范围 11/11、歧义动作 6/6、多轮授权 3/3；所有套件失败数均为 0。
- [ ] 该 scorecard 验证固定 SQL、固定 AST 决策及固定澄清标签，不代表真实 Agent/model 生成准确率、真实 PostgreSQL/MySQL 执行权限或生产 RLS。

## 2026-09-25 增量：ReAct 单次生成 token 上限

- [x] ReAct 请求将 `ConversationVo.max_new_tokens` 传入 `AgentContext`，并以既有 `agent_context.reserved_tokens` 作为服务端单次生成上限；请求缺失或无效时使用服务端上限，较低请求值继续生效。
- [x] 生命周期与 SQL 预算聚焦回归共 52 项通过；Ruff check 和 `py_compile` 通过。
- [ ] 该改动本身只限制单次模型输出；ReAct/knowledge-agent 的累计日 Token 配额和模型 usage 结算已在 2026-09-25 后续增量实现，真实模型账单 usage 及其他端点配额仍待接入。

## 2026-09-25 增量：拒绝 PostgreSQL session 设置函数

- [x] Core SQL AST 校验拒绝 `set_config`，避免只读 `SELECT` 改变连接 session 设置；PostgreSQL 官方文档说明该函数对应 `SET`，`is_local=false` 时修改当前 session。
- [x] 方言安全候选集覆盖 `set_config` session 设置、`pg_notify` 跨会话通知及 MySQL `GET_LOCK` 命名锁；PostgreSQL/MySQL 固定 AST 候选共 20 项。
- [x] 验证：Core SQL guard 35 项、企业 Text-to-SQL 示例全量 133 项通过；Ruff check/format、`py_compile`、候选 JSON 解析和 `git diff --check` 通过。
- [ ] 候选集仍是静态 AST 策略验证，不证明真实 PostgreSQL/MySQL 授权、连接池 session 隔离或数据库端只读账户配置。

## 2026-09-25 增量：Core/App Agent SQL 执行链合并回归

- [x] 合并运行 ReAct 生命周期、SQL 查询/安全工具、主/子 Agent 工具、dispatcher、Core SQL guard、RDBMS Agent Resource、tracer 和 middleware 测试；更新后 196 项通过。
- [ ] 这组测试使用 mock/合成 connector；完整 DB-GPT 仓库测试、真实模型调用、PostgreSQL/MySQL 执行权限和生产 RLS 仍未验收。

## 2026-09-25 增量：ReAct SQL 审计透传认证角色

- [x] `/v1/chat/react-agent` 将服务端 `UserRequest.role` 放入身份上下文；子 Agent dispatcher 继承该上下文，Core SQL audit event 和 `agent.sql_query` span 记录角色字段。
- [x] 定向回归覆盖 endpoint 身份上下文、子 Agent 继承、SQL 日志与 span；角色字段只作可信审计上下文，不据此放宽查询权限。
- [x] 角色已用于指标目录与受限毛利率列级授权；毛利率定义及安全执行见本路线图“受限角色毛利率指标”增量记录。
- [ ] 生产 tenant/region 行级策略、成本列数据库权限及生产 RLS 仍待验收。

## 2026-09-25 增量：PostgreSQL query-canceled 错误分类

- [x] Core 将 PostgreSQL SQLSTATE `57014` (`query_canceled`) 归类为不可重试 timeout，并返回不含驱动细节的提示；定义见 [PostgreSQL SQLSTATE 附录](https://www.postgresql.org/docs/current/errcodes-appendix.html)。
- [x] Core/App Agent SQL 执行链合并回归 196 项通过；Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [x] 隔离 PostgreSQL 16.6 中通过 DB-GPT `PostgreSQLConnector` 和共享只读查询网关触发 statement timeout，确认其被分类为 `timeout`，同一个 `pool_size=1` 后端连接可继续查询且 `statement_timeout` 恢复为 `0`。
- [ ] 外部取消场景与生产连接池、权限及数据库配置仍待部署环境验收。

## 2026-09-25 增量：ReAct 语义指标角色授权

- [x] 指标目录项支持服务端 `allowed_roles`；角色取自已验证身份上下文，不读取模型或请求体提供的角色。目录查询隐藏无权查看的指标，`metric_query` 编译入口重复校验角色，防止直接按受限 ID 执行。
- [x] 目录 loader 校验允许角色列表，并拒绝不受限的派生指标引用受限依赖；默认版本受限时该指标对无权角色整体不可见。示例 README 说明该策略不替代数据库权限和原始 SQL 的字段保护。
- [x] Core/App 合并回归覆盖 loader 配置校验、目录隐藏、未授权执行不调用 SQL 工具、管理员可执行、主/子 Agent 角色上下文及 ReAct 生命周期；206 项通过，Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [x] 已登记并验证受限毛利率指标，仅 `admin` 可通过服务端确定性指标编译路径查询派生比率；普通 SQL 成本列仍拒绝。
- [ ] 生产成本列数据库权限、真实身份映射及 RLS 仍未验收。

## 2026-09-25 增量：ReAct Schema 元数据敏感字段执行授权

- [x] DB-GPT App 新增 `DBGPT_DATABASE_SCHEMA_FILES` 服务端 datasource 映射；匹配的 ReAct SQL 工具从 Schema 元数据读取个人/机密字段与租户键策略，不接受请求指定的文件路径。
- [x] 共享入口在 Core SQL 执行前检查 SQLGlot AST：拒绝个人/机密字段引用、含受保护列的表通配符，以及租户键投影/分组/排序；保留 `COUNT(*)` 和租户键在 join/filter 中的用途。映射配置无效时 fail-closed。
- [x] business-context 与主 SQL 工具定向回归 19 项通过，覆盖机密字段、CTE/子查询/别名字段引用、限定与非限定通配符、租户键投影/连接和无效策略拒绝。
- [x] DB-GPT ReAct `sql_query`、SQL 编辑器、Dashboard 图表执行/编辑、历史回放及 Core `DatasourceResource` 现按配置策略执行列保护和 tenant/region 行过滤；该入口拒绝 Schema 元数据未登记的对象，登记视图须提供符合单表直接投影规则的服务端定义并在底表策略检查后执行。其他 Agent、复杂 view 定义和数据库侧列权限仍需覆盖或由数据库最小权限保障。

## 2026-09-25 增量：候选 SQL Schema 列策略评测

- [x] 新增 `schema_security_candidates.json` 与 `--schema-security-candidates` CLI 入口；评测器调用 DB-GPT App ReAct SQL 使用的同一 SQLGlot 列策略，并加载固定的服务端 `schema_metadata.json`。
- [x] 增至 12 条候选，覆盖机密字段直引/别名/CTE/子查询、受保护表通配符、租户键投影/分组、`COUNT(*)` 和租户键 join，以及未登记视图的别名字段和通配符读取；报告仅记录 case ID、决策和 SQL 哈希。
- [x] Schema policy 现要求每个引用的物理表都存在于服务端元数据映射中，CTE 引用按其内部物理表校验；未登记视图 fail-closed。登记视图的受限定义展开和 scorecard 后续实现见 2026-09-26 增量。
- [x] 此 scorecard 增至 15 条，覆盖安全登记视图展开、敏感定义拒绝及缺失定义拒绝；单独 SQLite 执行用例验证展开后仍注入租户过滤。
- [ ] 此 scorecard 不覆盖生产 PostgreSQL/MySQL 数据库 grants/RLS 或其他查询执行入口。

## 2026-09-25 增量：默认 ReAct SQL tenant/region 行过滤

- [x] `DBGPT_DATABASE_SCHEMA_FILES` 元数据现可声明租户键、策略版本及 direct / via_orders / via_order_items 区域映射；默认 ReAct SQL 工具使用服务端身份上下文，在 SQLGlot AST 上为每个已登记物理表注入 tenant 条件，并对销售角色注入直接或关联订单区域条件。
- [x] 租户或销售区域身份缺失、未登记/无租户键的表、未配置区域策略的表及 schema-qualified 表名均拒绝执行；CTE、相关子查询和 UNION 分支按底层物理表过滤。缺少 tenant scope 的映射配置 fail-closed；审计策略版本追加 schema policy version，不记录 SQL 原文。
- [x] Business-context 与主 SQL 工具定向测试 23 项通过，覆盖租户/区域隔离、订单/明细/退款/商品关联、两层 CTE、相关子查询、UNION、表值函数拒绝、缺失租户元数据和身份、未登记 schema 以及工具实际执行路径；主/子 Agent SQL 工具与相关策略回归 46 项通过，其中子 Agent 用例断言最终 SQL 已注入 tenant/region 条件；企业 Text-to-SQL 全量离线测试 143 项通过；Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [ ] 此实现依赖操作员正确维护 schema/关系元数据，是 Agent 查询链的应用层纵深防御；复杂 view 定义仍 fail-closed。生产只读凭据、数据库 grants/RLS、其他 SQL 执行入口、完整 PostgreSQL/MySQL 驱动及企业身份策略仍需覆盖和环境验收。
- [x] 使用自动清理的 PostgreSQL 16 和 MySQL 8.4 临时容器实跑订单直连、退款/明细关联、商品经订单明细关联及恶意 `OR 1=1` 候选；两种方言均只返回 tenant-a / a-gz 合成行，容器已停止并自动移除。该 smoke 未配置生产 grants 或 RLS。

## 2026-09-25 增量：ReAct tenant/region 行策略候选评测

- [x] 新增 `row_scope_candidates.json` 和 `--row-scope-candidates`；固定 SQL 使用默认 ReAct SQL 工具相同的 Schema 列/行策略及 Core 只读查询层，在合成 SQLite 数据上执行。
- [x] 11 个用例覆盖租户隔离、订单区域直接过滤、退款/明细/商品关联范围、tenant/region `OR 1=1`、缺失身份、未登记表和未登记 Schema；结果按预期行数计分，报告只包含 case ID、状态、行数和 SQL 哈希。
- [x] 行策略候选 evaluator 测试 36 项通过，覆盖全 bundle CLI 集成及策略回归漏过时的检测；企业 Text-to-SQL 全量离线回归 143 项通过；Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [ ] 该评测证明固定 SQL 在合成 SQLite 和 App AST 策略中的结果边界，不代表模型实际生成质量、生产数据库 RLS、企业身份或其他执行入口授权。

## 2026-09-25 增量：编辑器只读 SQL tenant/region 与列策略

- [x] SQL 编辑器执行与图表 SQL 执行现从经认证的 `UserRequest` 读取 tenant、region 和 role，并按操作员映射的 `schema_metadata.json` 应用与 ReAct 相同的敏感列检查和 AST 行范围注入。
- [x] 缺少销售区域 claim 时 fail-closed；固定回归覆盖编辑器与图表路径的 `OR 1=1` 查询范围参数，以及机密列在执行前拒绝。原有写操作管理员限制保持独立。
- [x] 图表历史回放查询在服务层再次按会话所绑定数据源及已认证用户的 tenant/region/role 执行相同策略；回归验证覆盖伪造 OR 条件时的范围注入。
- [x] 验证：编辑器/图表/历史回放测试 23 项通过；改动文件 Ruff check/format 与 `git diff --check` 通过。
- [x] Dashboard Agent 图表生成与图表编辑现将服务端认证角色、tenant/region 传入共享业务策略；图表生成同时检查用户对所选数据源的可见性。Dashboard 执行策略与编辑器/图表/历史回放合计 30 项通过。
- [x] Core RDBMS Agent Resource 已通过显式请求上下文传递可信身份并执行数据源归属及行列策略；没有 operator schema 映射的普通数据源在受保护资源入口 fail-closed。其他 Agent、数据库 grants/RLS 与真实 OIDC/生产环境授权仍需独立验收。

## 2026-09-25 增量：受限角色毛利率指标

- [x] 经确认的口径写入 `gross_margin_rate@1.0.0`：按订单日期统计已完成订单明细，销售额为 `quantity × unit_price_cents`，成本为 `quantity × internal_cost_cents`，毛利率为 `(销售额 - 成本) / 销售额 × 100`；退款不冲减，分母为零返回空值，仅 `admin` 可查。
- [x] ReAct 主/子 Agent 的指标目录仅向 `admin` 暴露该指标；App 只在服务端编译出的受限指标计划上下文中允许 `products.internal_cost_cents`，继续运行同一只读校验、tenant/region AST 注入、超时、行数上限和 SQL 哈希审计。原始 `sql_query` 仍拒绝成本列；未授权角色执行不到指标 SQL。
- [x] 独立演示 API 的 `/metrics/query` 同样进行 `admin` 校验，并只为确定性编译结果创建受限只读 executor；`/query` 原始 SQL 仍拒绝成本字段，报表导出未开放毛利率。
- [x] App 指标/Schema/主子工具定向回归 47 项通过；编辑器/图表/历史回放回归 23 项通过；企业 Text-to-SQL 离线套件 147 项通过，覆盖毛利率计算、租户/区域范围、角色拒绝、原始成本 SQL 拒绝和零分母规则。
- [x] 按确认口径复验：App 指标目录、Schema 授权、ReAct 工具、SQL 查询与 guard 回归 98 项通过；按 README 增加可选 ReportLab 依赖后，Text-to-SQL 全量离线套件 147 项通过。
- [x] 该演示口径按用户确认实施，指标发布审批与审计已补齐；生产成本列授权、企业角色映射/IdP 验收及数据库 grants/RLS 仍未完成。

## 2026-09-25 增量：数据源路由与 XLSX 导出防护

- [x] `/v1/chat/db/summary` 现在要求登录并校验数据源 owner/admin，且等待 `async_db_summary_embedding` 完成后才返回成功；删除了此前未等待异步工作的旧 helper。
- [x] `/v1/chat/db/test/connect` 对已登记的数据源校验 owner/admin，新建连接仍可在保存前测试；连接错误不会返回底层驱动消息。
- [x] XLSX 每行将字符串单元格显式写为文本，避免租户/区域 claim、指标说明或区域名称被解释为公式；回归注入 `=1+1` 区域名并验证单元格类型为字符串。
- [x] XLSX/PDF 导出失败现在记录通用 `report_export_failed` 审计事件，仅包含格式、HTTP 状态、原因类别、指标数量和认证身份范围；不记录 SQL、查询参数或原始错误文本。
- [x] App API v1 定向回归 58 项通过；改动文件 Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [x] 使用 roadmap 给出的 `uv --no-project --with reportlab` 临时环境运行企业 Text-to-SQL 完整套件，150 项通过，覆盖 PDF 实际渲染和 XLSX/PDF 失败审计；没有更改项目依赖或锁文件。

## 2026-09-25 增量：文件分析 Agent 工具审计 span

- [x] `execute_analysis` 现在发出 `agent.execute_analysis` span，记录可信 actor、conversation trace、返回状态与耗时；span 不记录文件路径、名称、内容或模型传入的文件 ID。
- [x] 文件工具定向回归 40 项通过，覆盖 span 脱敏及已有多文件选择、失败路径和文件路径清理行为。
- [ ] 真实 Agent trace 导出及部署 Collector/OpenObserve 验收仍待完成；Core ToolPack 动态工具执行 span 已在后续增量补齐。

## 2026-09-25 增量：ReAct 执行型 Agent 工具审计 span

- [x] ReAct `knowledge_retrieve`、`sql_query`、`code_interpreter`、`shell_interpreter`、`execute_skill_script_file` 和 `html_interpreter` 均发出独立 span。记录会话/数据源及可信身份策略 ID、执行状态、输出类别/行数和耗时；搜索词、SQL、代码、命令、文档/结果正文及错误文本不写入 span metadata。
- [x] 回归覆盖成功/失败检索、SQL 查询和解释器路径及 span 内容脱敏；ReAct 工具测试 27 项、包含 Schema/指标/SQL/编辑器/Dashboard 的 App 定向集成 80 项通过，Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [ ] 真实 Agent trace 导出及部署 Collector/OpenObserve 验收仍待完成；Core ToolPack 动态工具执行 span 已在后续增量补齐。

## 2026-09-25 增量：技能上传文件名路径保护

- [x] `/v1/skills/upload` 在创建目录或写入前拒绝 POSIX/Windows 绝对路径、目录分隔符、空字节及 `.`/`..` 文件名，防止上传路径逃逸到 `pilot/tmp` 或 `skills/user` 目录之外。
- [x] 上传路径回归覆盖 POSIX 穿越、绝对路径、Windows 分隔符和普通文件名；完整 App 回归中该测试模块通过。

## 2026-09-25 增量：scheduled replay 文件副本回收契约复验

- [x] 对齐多文件回放回归与既有 worker 清理策略：每次回放从任务冻结副本创建新的 session 文件；新一轮开始前回收上一轮 session 副本，因此只保留最新运行的文件副本。
- [x] scheduled replay 专项回归通过；此前 `pilot_template` 缺失导致的源码树测试失败已由后续增量修复，当前 App 全量测试结果见下方。

## 2026-09-25 增量：dbgpt-app wheel 模板资源打包

- [x] 修正 Hatch build hook 的标准构建路径解析：优先读取 sdist remap 路径和 sdist 已生成的 wheel 目标路径，再回退到源码 checkout；直接 wheel 与 sdist→wheel 均包含六个 `pilot_template` 资源。
- [x] 使用 `uv build --project packages/dbgpt-app` 构建 sdist/wheel，并确认模板资源存在于两个产物；将安装后的 wheel 置于测试导入路径，workspace provisioning 回归 6 项通过。
- [x] App wheel 布局全量回归 515 项通过；源码树布局资源缺失由后续增量修复，完整结果见下方。

## 2026-09-25 增量：App 源码树 workspace provisioning

- [x] `workspace_provisioning` 在已安装 wheel 中优先使用打包的 `pilot_template`；源码 checkout 缺少该目录时回退到仓库根目录的 `pilot/`，复用同一资源清单并保留“不覆盖用户文件”行为。
- [x] workspace provisioning 专项 6 项通过；DB-GPT App 源码树全量回归现为 538 项通过。改动文件 Ruff check/format 通过。

## 2026-09-25 增量：数据源参数授权与指标目录 fail-closed

- [x] `/v1/resource/params/list` 与 DB QA/Execute/Dashboard 模式参数路由现在只枚举本人及共享数据源；缺失 `user_id` 时返回空列表，不再落到全局数据源查询。
- [x] 旧版 `/v1/chat/db/test/connect` 将可能执行阻塞 schema reflection 的同步连接检查放入线程池，保留已有归属校验和通用错误脱敏。
- [x] 指标目录 loader 拒绝非法 SemVer/metric ID、重复 `(id, version)`、不完整或重复依赖 pin、悬空依赖、未知默认版本及默认指向未发布版本；已发布指标也不能依赖 draft/retired 版本。
- [x] 路由、目录完整性定向回归 36 项通过；DB-GPT App 源码树全量回归 539 项通过；目录校验另拒绝环依赖；改动文件 Ruff check/format、`py_compile` 和 `git diff --check` 通过。

## 2026-09-25 增量：主 Agent Python 执行工具 span

- [x] 默认 `/v1/chat/completions` ToolPack 的 `code_interpreter` 现发出 `agent.code_interpreter` span，记录 completed、invalid input、syntax error、timeout 或 execution error 与耗时；不记录代码、输出、会话 ID、文件路径或异常文本。
- [x] session-file/code interpreter 回归 42 项通过，包含成功与超时 span 脱敏检查；Ruff check/format 通过。
- [x] 本节记录时尚未覆盖的主 Agent 工具入口已在下方增量补齐；部署 Collector/OpenObserve 与真实请求 trace 仍待验收。

## 2026-09-25 增量：主 Agent 执行、文件与知识工具 span

- [x] 通用内置 Agent 工具 span 包装器接入主 Agent 的 `shell_interpreter`、`html_interpreter`、`knowledge_retrieve`、`load_file`、`read_file`、`execute_tool`、技能脚本执行和技能资源读取入口；span 仅记录返回/异常状态与耗时，不写入工具参数、结果或会话/文件标识。
- [x] 知识模式的八个独立 KB 工具（目录、glob、grep、cat、语义搜索及三种代码图查询）均接入脱敏 span，并由实际工具工厂测试覆盖。
- [x] 修复 `execute_tool` 对已不存在 `resource_api` 模块的导入，改用当前 Core `resource.base` 定义，使标准 ToolPack 查找/执行路径可运行。
- [x] 合并运行工具 span、ReAct 工具、文件分析和 Agent 生命周期回归 96 项通过；Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [ ] 真实请求 trace 导出及部署 Collector/OpenObserve 仍待验收。

## 2026-09-25 增量：主 Agent 工作流工具 span

- [x] 用户澄清、技能选择/加载、技能工具解析和 todo 更新入口均接入只记录状态与耗时的脱敏 span；`load_tools` 同时改用 Core 当前的 `resource.base` 定义，修复已失效的 `resource_api` 导入。
- [x] 工具 span、文件分析、ReAct 工具、dispatcher 与 Agent 生命周期定向回归 125 项通过；Ruff check/format、`py_compile` 与 `git diff --check` 通过。
- [ ] 真实请求 trace 导出及部署 Collector/OpenObserve 仍待验收。

## 2026-09-25 增量：Core Agent Resource 与 ToolPack 动态工具 span

- [x] Core RDBMS Agent Resource 通过统一只读查询层发出 `agent.rdbms_resource_query` span；只记录 SQL 哈希、方言、状态、耗时和行数，不记录原 SQL 或数据库名。
- [x] Core `ToolPack` 的同步/异步动态工具执行发出 `agent.toolpack.execute` span，只记录状态与耗时，不记录工具名、参数或结果；工具查找错误维持原有异常类型。
- [x] Core 资源 SQL 防护、ToolPack、App ReAct SQL tracing 与通用工具链合并定向回归 103 项通过；Core 全量回归 810 项通过、1 项跳过；Ruff check/format 通过。
- [x] Core `DatasourceResource` 已贯通可信操作者与 tenant/region 身份授权；部署 Collector/OpenObserve、其他 Agent 覆盖和生产数据库 RLS 仍待环境验收。

## 2026-09-25 增量：数据源连接配置更新参数化

- [x] `ConnectConfigDao.update_db_info` 的 URL 和文件数据库更新均使用 SQLAlchemy 绑定参数；敏感值和含引号输入不会拼入 SQL 文本。
- [x] Serve 数据源 DAO 回归 3 项通过，Ruff check/format 与 `git diff --check` 通过。
- [x] 旧版 `/v1/chat/db/add` 日志改为只记录 datasource 名称、类型及 owner，不再输出完整 `DBConfig` 中的密码；DAO 写入失败日志只记录异常类型，Serve 创建接口不再向调用方返回底层异常文本。新增日志泄漏回归。Serve datasource 与 App 响应脱敏组合回归 25 项通过；Ruff 检查忽略同文件预存且与本改动无关的 `F841`，格式、`py_compile` 和 `git diff --check` 通过。
- [x] 后续 datasource-governance 增量已将 `db_pwd` 改为 Fernet 密文存储，并实现待审批状态、Verified OIDC admin 复核、审计和历史配置迁移 CLI；旧字段保留为存储列，实际 metadata DB 迁移仍待部署。

## 2026-09-25 增量：数据源 API 响应隐藏机密参数

- [x] Serve 数据源响应和 App `/v1/chat/db/list` 响应通过连接参数 `privacy` 元数据隐藏密码与访问密钥；用户更新时将空的隐私字段解释为沿用已有值，显式新值仍可替换。
- [x] 回归覆盖 Postgres 密码及 ext_config 脱敏、编辑保留和 App 数据源列表路由；Serve 全量回归 615 项通过、1 项跳过，App 脱敏回归 3 项通过，Ruff check/format 与 `git diff --check` 通过。
- [x] 后续增量已实现 `connect_config.db_pwd` 加密存储、Verified OIDC 身份授权、连接审批和审计；生产 Secret Manager 接入与密钥轮换仍未完成。

## 2026-09-25 增量：旧版数据源管理路由所有权校验

- [x] `/v1/chat/db/edit`、`delete`、`refresh` 使用认证用户校验连接归属；本人可维护，admin 可维护任意连接，其他用户在执行写操作前拒绝。
- [x] App 数据源脱敏与所有权路由回归 6 项通过；App API v1 全套 53 项通过，Ruff check/format 与 `git diff --check` 通过。
- [x] 无 owner 的共享及历史连接由 admin 管理；数据源审批和凭据加密已实现，历史连接迁移后统一进入待复核状态。
- [x] 历史连接所有权可由 Verified OIDC admin 转移给明确用户；转移与审计同事务提交，旧审批撤销并置为 pending，旧 connector 缓存失效。App/Serve 数据源授权回归 26 项通过；Ruff check/format、compileall 和 `git diff --check` 通过。

## 2026-09-25 增量：数据源连通性错误脱敏

- [x] Serve 新旧数据源连接测试失败时只记录异常类型并返回固定错误，不再把驱动异常原文写日志或抛给调用方；App `/v1/chat/db/test/connect` 同样返回固定错误，避免连接 URL/密码随驱动错误泄漏。
- [x] Serve 全量回归 617 项通过、1 项跳过；App API v1 全量回归 54 项通过。Serve 新增旧/新连接测试入口脱敏回归 2 项，App 新增路由错误脱敏回归 1 项，覆盖日志与接口错误字符串。
- [x] 后续 datasource-governance 增量已实现敏感连接凭据加密、Verified OIDC admin 审批与审计；该错误脱敏项已完成。
- [ ] 生产 Secret Manager 接入、密钥轮换和历史密钥退役流程仍待部署设计与验收。

## 2026-09-25 增量：语义指标编译与权限候选评测

- [x] 新增 `metric_candidates.json` 与 `--metric-candidates` 评测入口，直接调用 DB-GPT App 的已发布指标目录 loader、`metric_query` 编译器、Schema 列策略、tenant/region AST 注入与 Core 只读查询执行器。
- [x] 11 个合成 SQLite 固定用例覆盖销售额、退款发生日/订单 cohort 版本、派生净销售额与退款率 pin、区域限制、admin 毛利率、普通角色编译前拒绝、零销售额空值；报告仅保留 case、状态、版本、SQL 哈希和行数，不输出结果值。
- [x] 候选 loader 拒绝未知 case、字段、非字符串参数和超长输入；CLI 任一指标用例失败即非零退出。企业 Text-to-SQL 全量离线回归 154 项通过；Ruff check/format、`py_compile`、目录 JSON 校验和 `git diff --check` 通过。
- [ ] scorecard 使用固定指标请求和合成 SQLite 数据，不能证明真实 Agent 选择指标/版本的质量，也未验证 PostgreSQL/MySQL 执行、生产 grants/RLS 或企业 IdP。

## 2026-09-25 增量：Dashboard/editor 运行时 SQL 审计补齐

- [x] Core 共享只读查询入口对成功、策略拒绝、超时和执行失败统一写结构化审计并填充 tenant/region span 字段；RDBMS legacy `run()` 补充方言、哈希、状态、耗时和返回行数。
- [x] Dashboard 查询/图表编辑和 Editor SQL 执行、图表查询/编辑及历史回放审计包含操作者、角色、tenant/region、数据源、方言、策略版本、trace、SQL 哈希、状态、耗时与行数；异常日志/响应隐藏驱动错误文本。
- [x] Core 测试集与 RDBMS SQLite 回归共 835 项通过、1 项跳过（临时提供可选 litellm）；App 全量回归 542 项通过；本轮 SQL 审计定向回归 66 项通过。Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [ ] 本地回归没有连接 PostgreSQL/MySQL 等生产实例，也没有验证生产日志管道或部署 Collector/OpenObserve 导出；这些仍需环境验收。

## 2026-09-25 增量：指标发布审批与持久化审计

- [x] 演示 SQLite 新增指标版本和 append-only 审计表；指标管理员可提交草稿、由另一名 admin 审批/拒绝并切换默认版本。自审被拒绝且留审计记录；审批状态与审计事件在同一事务提交。
- [x] 指标目录、查询编译和审计读取当前已发布快照；运行时保留版本及内容 SHA-256。既有原始 SQL 路径不能借此读取成本列，毛利率仍仅向 admin 暴露。
- [x] 指标治理与语义回归 27 项通过；毛利率管理员/原始 SQL 拒绝 API 回归 1 项通过；与异步报表及报告指标/角色导出 allowlist 集成后，Text-to-SQL 全量回归 165 项通过。Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [ ] 该指标治理流程用于本地合成数据演示；真实模型指标选择及生产数据库列权限仍待环境验收。报表任务的 PostgreSQL 多实例存储和隔离 PostgreSQL 并发 smoke 已在后续增量实现，目标部署实例验收仍待完成。

## 2026-09-25 增量：可恢复异步 XLSX 报表

- [x] 新增独立 SQLite 任务队列及 `POST /reports/tasks`、任务状态查询和 XLSX 下载接口；状态包括 queued/running/succeeded/failed，使用 actor 作用域幂等键、原子认领、30 秒租约续期/回收、最多两次尝试和进程重启恢复。
- [x] 任务仅保存必要身份/数据范围快照，不存 Bearer token；下载再次校验当前 actor、tenant、region、role 和策略版本。任务入队时固定指标目录快照及 hash，后续默认版本更新不会改变已排队任务的报告口径。
- [x] 任务数据库新建/打开时权限收紧为 `0600`。定向 API/队列测试 35 项通过；与指标治理及报告导出授权组合后的 Text-to-SQL 全量离线回归 165 项通过；Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [x] 后续已修复无 Fernet key 时的明文写入：单份/批量报告入队 fail-closed、API 返回 503，且不启动 worker；显式结果写入也拒绝无 key。旧明文在完成加密迁移前一律不通过读取 API 提供。
- [ ] 生产仍需 secret manager 注入、正式留存策略和密钥退役运维流程；PostgreSQL 多实例任务存储已通过隔离实例 smoke，目标部署验收仍待完成。
- [x] 新增显式结果迁移命令，可按有界批次将旧明文结果加密，并把旧 key ciphertext 轮换到 key ring 首位的 active key；游标保证已使用 active key 的行不会阻断后续批次。回归覆盖明文加密和旧 ciphertext 轮换，报表任务测试 10 项通过；Text-to-SQL 全量离线套件 183 项通过；Ruff、格式、`py_compile` 和 `git diff --check` 通过。迁移要求 active-first key ring 保留旧 key，全部处理后才可移除旧 key。
- [x] 新增显式 cutoff 报表清理 API 与 CLI：默认仅统计，传 `--apply` 才按每批最多 1,000 条删除 cutoff 前的 succeeded/failed 任务，不删除 queued/running；cutoff 必须由操作员明确指定，不擅自设定业务留存期。回归覆盖分批删除、保留 queued 任务、CLI dry-run 和显式 apply；Text-to-SQL 全量离线套件 183 项通过，Ruff、格式、`py_compile` 和 `git diff --check` 通过。

## 2026-09-25 增量：Core RDBMS Agent Resource 可信身份与行列授权

- [x] `/v1/chat/completions` 从已验证的 OIDC `UserRequest` 构造请求级身份，并通过显式参数传到 `DatasourceResource`；身份不放入客户端可控 `ext_info`，共享 `ResourceManager` 不持有请求身份。
- [x] `DatasourceResource` 在连库前校验主体及数据源 owner/admin；缺失可信身份或 App 授权 hooks 时 fail-closed。每条查询要求服务端 datasource Schema policy，并复用现有列保护与 tenant/region SQL 范围逻辑。
- [x] 定向 Core/Serve 资源身份回归 33 项通过；实现分支合并回归 55 项通过；Ruff check/format、`compileall` 和 `git diff --check` 通过。未修改数据源凭据 schema。
- [ ] 真实企业 IdP、生产数据库只读账户/grants/RLS、其他 Agent 入口和生产策略仍待环境验收；OIDC 浏览器/部署验收按本计划最后进行。

## 2026-09-25 增量：OIDC 最后复验

- [x] 最后复验 issuer/audience/claim/role 配置校验、Discovery/JWKS/RSA Bearer JWT 及租户/区域授权 API 5 项通过；可信 Agent 执行上下文 2 项通过；Vue PKCE/ID Token 校验 7 项通过。
- [x] 身份提供方及 claim 映射配置示例和 Keycloak 设置见 `examples/enterprise-text2sql/README.md`；本地协议与页面登录单测通过。
- [ ] 当前未连接实际企业 Realm，也未验证企业浏览器回调、HTTPS/CORS、redirect URI 和生产数据授权；这些仍需要目标部署环境配置后完成。

## 2026-09-26 增量：本地 Keycloak OIDC/JWT 实际签发验收

- [x] 临时 Keycloak 26 Realm 配置 `dbgpt-api` access-token audience、嵌套租户 `organization.tenant`、区域 `region_id`、Realm 角色和 PKCE S256 public client；发现 Keycloak 26 需先在 Realm User Profile 声明自定义用户属性，已把该要求补入示例文档。
- [x] 使用隔离合成用户签发真实 RSA Bearer access token，由运行中的 API 经 Discovery/JWKS 验签并应用 issuer/audience/tenant/region/role 映射；普通用户只返回 tenant-a 商品，`regional-sales` 只返回 `a-gz` 区域 4 笔订单，请求体注入其他 tenant 返回 422。
- [x] 前端 Vue PKCE 与 ID Token 校验自动化单测此前已通过；本轮真实 Keycloak 浏览器授权码回调未实测，生产企业 Realm、HTTPS/CORS、redirect URI 与真实数据授权仍待环境验收。

## 2026-09-25 增量：候选 SQL 分类 scorecard

- [x] 50 条金标准问题补充唯一主评测类别；候选 SQL scorecard 按类别报告题数、正确、错误、拒绝、缺失和准确率，并计算各类别等权宏平均，防止小类回归被总体准确率掩盖。
- [x] 分类指标回归覆盖类别计数总和、错误/拒绝/缺失归类及宏平均；Text-to-SQL 全量离线套件 166 项通过。Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [x] 分类统计仍基于固定 SQL 与合成数据，不代表实时 Agent 生成质量；本机实时 Agent scorecard 已完成 50 题，但精确匹配 0 题（30 错误、20 缺少结果），模型生成质量未通过。

## 2026-09-25 增量：Live Agent 分类 scorecard

- [x] 实时 Agent 评测器复用 50 道金标准的主类别，对正确、错误、缺失、无效和截断结果输出分类统计及类别等权宏平均；多轮评测数据标注为 `multiturn_analysis`，自定义未标注样例归入 `unclassified`。
- [x] Mock Agent 回归覆盖分类结果、缺失/截断状态及多轮统计；Text-to-SQL 全量离线套件 166 项通过。Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [x] 本地 mock 不能证明真实 Agent 的模型生成质量；本机 DB-GPT Agent 与授权合成 datasource 已实测 50 题，精确匹配 0 题，生成质量仍未通过验收。
- [x] `.github/workflows/develop-me-sql-guard.yml` 已安装企业 Text-to-SQL 全套测试及 Core/Serve 运行依赖，并设置 Core/Serve `src` 路径；本地干净环境验证与 README 完整测试命令一致。GitHub runner 实际执行仍以 CI 结果为准。

## 2026-09-25 增量：Live 策略评测按行为分组

- [x] 实时拒绝/澄清 scorecard 分开统计 `deny` 与 `clarify` 的样本数、正确数、错误数和准确率，并计算两类等权宏平均，避免一种行为通过率掩盖另一种行为回归。
- [x] Mock 回归覆盖拒绝通过、澄清失败时的分类结果；Text-to-SQL 全量离线套件 167 项通过。Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [x] 本机 DB-GPT Agent 与合成 datasource 的 6 条实时拒绝/澄清策略评测已运行：拒绝 3/3、澄清 0/3，总计 3/6；其中 1 条模糊商品问题意外执行并返回 SQL 结果。拒绝组按服务端实际安全文案“当前身份不可访问的敏感字段”匹配，曾因评测词表遗漏该文案而误记为失败；脱敏 scorecard 见 `specs/012-live-react-sql-result/evidence/live-policy-scorecard.json`。
- [ ] 短语规则 scorecard 和本地 Agent 结果都不等于语义安全评审；生产数据库权限、RLS/grants 与企业身份策略仍待目标环境验收。

## 2026-09-25 增量：异步报告结果加密存储

- [x] `DBGPT_REPORT_ENCRYPTION_KEY` 配置单个 Fernet key，或 `DBGPT_REPORT_ENCRYPTION_KEYS` 配置 active-first key ring 后，报告结果 JSON 在写入 SQLite 前加密；不改任务数据库 schema。key ring 可用新 key 加密新结果并用旧 key 读取既有 ciphertext，但不批量重加密旧结果。
- [x] 加密/轮换读取/错误密钥/无密钥读取/历史明文拒绝均有队列回归；API 集成测试验证 SQLite 落盘内容不可读且 XLSX 下载仍可解密。Text-to-SQL 全量离线套件 171 项通过；Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [x] 后续已将无 key 的报告结果写入和明文读取都改为 fail-closed，并增加无任务落库的 API 回归；旧明文须先执行受控迁移。
- [ ] 生产还需 secret manager 注入、正式留存策略、目标 PostgreSQL 部署验收及旧 key 退役流程，当前不能标为生产就绪。

## 2026-09-25 增量：原子异步批量报告与 CI 全量离线回归

- [x] 新增 `POST /reports/batches/tasks`，接受 2–10 个唯一命名场景；各场景可使用不同指标、日期和维度。共享现有持久化任务表，不改数据库 schema。
- [x] 所有场景在入队前逐一执行身份、租户/区域及指标角色校验；worker 仅在所有场景成功后保存合并 XLSX，任一场景失败整批失败且不保存部分结果。幂等键、目录快照、结果加密及下载授权沿用原任务安全检查。
- [x] 回归覆盖成功批次下载与场景标识、单场景/重复名称拒绝，以及第二场景失败时任务无结果；验证：批量报告定向用例 2 项通过，既有单报告持久化用例 1 项通过。
- [x] `.github/workflows/develop-me-sql-guard.yml` 已安装 FastAPI/JWT/SQLGlot/XLSX/PDF 与 Core Agent 依赖，并配置 Core/Serve/Ext 源码路径；干净临时 Python 3.11 环境复现 CI 命令，全量离线套件 173 项通过。
- [ ] 公开 Actions 页面最近一次成功运行是 2026-09-24 的 [run #10](https://github.com/monstereat/DB-GPT/actions/runs/35995969661)，执行提交 `6172325`；当前 `develop-me` 远端 HEAD 已到 `93da908`，而本地更新后的 workflow 与相关代码仍未推送，因此尚无 runner 对当前版本的验证。
- [x] 实现持久化 UTC 日 Token 预算：按 tenant+user 记录 prompt/completion 用量和未结算预留；每次 ReAct/knowledge-agent 底层模型调用先用数据库条件更新原子预留，再按模型 usage 结算；usage 缺失或调用中断时保留全部预留。DAO 支持幂等 settle/release；文件 SQLite 并发竞争测试验证 12 个 worker 争用 17 tokens 时最多只有 17 次 1-token 预留成功。
- [x] `DBGPT_REACT_DAILY_TOKEN_LIMIT` 启用可选限制；只接受通过 OIDC 验签且同时具有用户与 tenant claim 的身份，未配置时关闭。新增 Serve 模型、SQLite `create_all` 注册、MySQL 初始化/升级 SQL，并通过 ReAct LLMClient wrapper 集成实际 usage 结算。
- [x] 配额 DAO 和模型 wrapper 定向回归共 16 项；覆盖 provider 实际 usage 超额记账、完整文本工具调用历史/工具选择计数，以及不可可靠计量的非字符串/多模态输入在预留和模型调用前拒绝。配额 DAO 与 App API/Agent SQL 相关回归合计 188 项通过。DAO 文档明确它是预留型预算而非 provider 硬封顶；独立 Text-to-SQL 离线全量套件 173 项通过；Ruff、`py_compile`、`git diff --check` 通过。CI workflow 增加配额定向测试路径。
- [x] 隔离 PostgreSQL 16 实例 smoke：12 个并发 worker 争用 17-token 额度、并发发起 36 个 1-token 预留，恰有 17 个成功；同一实例验证 settle/release 重复调用幂等。临时数据库已删除。
- [x] 隔离 MySQL 8.4 实例 smoke：5 轮分别以 12 个并发 worker 发起 36 个 1-token 预留，17-token 额度每轮恰好接受 17 个；每轮重复 settle/release 均幂等。临时数据库已删除。
- [x] 隔离 PostgreSQL 16 实例验证 stale reservation 恢复与正常 settle 并发竞争 20 轮、双恢复器竞争 20 轮；每轮仅一次结算写入，账户余额与 reservation 状态一致。临时数据库已删除。
- [x] 日 Token 预算现覆盖 ReAct/knowledge-agent、v1/v2 的 normal、knowledge、data、DB QA、dashboard BaseChat，以及非 flow App-Agent managed LLM 调用，均使用可信 OIDC tenant+user 与共享 MeteredLLMClient。启用预算时，flow-backed App-Agent、AWEL flow 和 v1 domain knowledge flow fail-closed。
- [ ] 该功能是预留型预算而非 provider 硬封顶：tokenizer 与 provider 消息转换差异仍可能导致单次超额，真实账单 usage 和其他模型端点仍待验证；AWEL flow/domain knowledge flow 尚未接入计量。MySQL 启用前须先应用 Serve schema/upgrade SQL。
- [x] 崩溃恢复：活跃模型流每分钟刷新 reservation 的 `updated_at`；新请求检查当前用户当天超过 15 分钟未更新的 pending reservation，并以完整预留量结算，避免释放可能已计费的 tokens。条件更新使回收与正常心跳/结算并发安全；无需 schema 变更。SQLite DAO 覆盖完整预留计费、新预留触发恢复、重复恢复幂等和心跳保活；wrapper 覆盖长流心跳。配额 DAO 与 wrapper 定向测试 20 项通过，Ruff、格式及 `git diff --check` 通过。该恢复在同一用户当天的新预留时触发，每次最多处理 1000 条；生产 PostgreSQL/MySQL 并发行为仍待集成验收。
- [x] ReAct SSE 将无法安全计量的 Token 请求标记为 `quota.unmeterable`，返回固定中文提示，不再把内部异常文本传给用户；包装后的异常分类及配额 wrapper/生命周期定向回归 19 项通过，Ruff、格式检查和 `git diff --check` 通过。

## 2026-09-25 增量：安全候选分类 scorecard

- [x] 19 条 SQLite 安全 SQL 候选按敏感数据、租户边界、只读/语法、查询结构、Schema 探测和不安全函数分类；报告分类通过率及等权宏平均，保留总体指标和 SQL 哈希脱敏。
- [x] 回归覆盖分类计数求和、全通过宏平均、敏感列策略回归时对应类别失败及 CLI scorecard 输出。
- [ ] 该评测仍使用固定 SQL 和合成 SQLite 数据，不证明实时 Agent 生成行为或 PostgreSQL/MySQL 生产权限。

## 2026-09-25 增量：PostgreSQL/MySQL AST 安全分类 scorecard

- [x] 20 条 PostgreSQL/MySQL 固定 AST 候选按只读基线、写入/导出、服务器文件访问、资源耗尽、会话副作用、多语句分类；总报告及各方言报告均输出分类计数、通过率与等权宏平均。
- [x] 回归验证所有分类计数及全通过宏平均；将 PostgreSQL 服务器文件读取候选替换为可通过的 SELECT 时，总准确率仍为 95%，同时服务器文件访问类别准确命中 0%，证明小类回归不会被总分隐藏。候选评测定向 41 项、企业 Text-to-SQL 全量 173 项通过；Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [ ] 该 scorecard 仍只运行 SQLGlot AST 验证，不执行 SQL，不证明生产数据库 grants/RLS、超时取消或实时 Agent 生成质量。

## 2026-09-25 增量：报表客户端字段注入拒绝回归

- [x] 同步 XLSX/PDF、单报表任务和批量报表任务拒绝客户端自由指定 `fields`；客户端只能选择服务端模板目录中登记的 `template_id`。
- [x] 4 条路径回归通过；Text-to-SQL 全量离线套件 177 项通过。
- [x] 服务端版本化 JSON 模板目录已提供角色 allowlist、可选定义/结果列及允许的指标 ID；同步 XLSX/PDF、单任务和批量任务只接受登记的 `template_id`，自由 `fields` 仍拒绝。批量场景须共用模板；异步任务持久化模板快照/hash，并在处理与下载时验证复用。
- [x] 报表模板已有本地 SQLite 作者提交、admin 双人审批/拒绝、字段和角色 allowlist 校验、append-only 审计及已发布目录 API；模板仍从 `report_templates.json` 初始化。
- [ ] 模板治理与报表任务均已有显式 PostgreSQL 共享存储实现和隔离实例 smoke；仍待目标部署 grants/TLS、备份恢复、Secret Manager、正式留存策略和密钥退役验收。

## 2026-09-25 增量：版本化报告模板字段权限

- [x] 新增 `report_templates.json` 服务端模板目录：标准与精简销售模板允许 `admin`、`normal`、`sales`；`admin-margin@1.0.0` 仅允许 `admin`，并可访问 `gross_margin_rate`。
- [x] XLSX/PDF 字段投影完全由模板定义；客户端 `fields` 仍由请求模型拒绝，未知模板/无权角色及模板未允许的指标在查询/入队前拒绝。
- [x] 管理员毛利率报告仅在服务端编译指标路径使用租户/区域范围的受限成本 executor；原始 SQL 路径仍不开放 `internal_cost_cents`。
- [x] 单任务及批量任务均保存模板目录版本、模板快照和 SHA-256，处理/下载验证 hash 并按原模板列渲染；单个批次要求所有场景使用相同模板。
- [x] 验证：`examples/enterprise-text2sql` 全量离线回归 179 项通过（含同步 XLSX/PDF、模板角色和字段投影、毛利率管理员权限、异步单/批任务下载）；Ruff check/format 与 `git diff --check` 通过。
- [x] 本地模板作者审批和发布 API 已落地；同步导出只解析已发布模板，异步任务固定模板内容快照与 SHA-256。
- [ ] 模板治理默认仍使用 demo SQLite，但已支持 `DBGPT_REPORT_TEMPLATE_DATABASE_URL` 连接 PostgreSQL；报表任务也支持 PostgreSQL 多实例共享。两者均通过隔离 PostgreSQL 16 smoke，目标部署 grants/TLS、Secret Manager、正式留存和密钥退役仍待验收。

## 2026-09-25 增量：登记视图默认拒绝

- [x] Schema 元数据支持明确标记 `type: "view"`；SQL 策略在列检查与行范围处理前拒绝登记视图，避免把人工列清单误当成底层列、租户和区域定义审计。
- [x] business-context 定向回归 22 项通过，覆盖未登记视图和已登记视图拒绝；当时自动展开并审计 view 定义尚未实现，限制已在 2026-09-26 增量中补齐受限范围。

## 2026-09-25 增量：Schema / 行范围 / 指标 scorecard 分类

- [x] Schema 列策略按敏感列、通配符暴露、tenant key、允许的查询结构和未登记对象分类；行范围策略按 tenant 隔离、region 传播、绕过抵抗、身份缺失和未登记对象分类。
- [x] 指标编译按基础指标、时间归属/版本语义、tenant/region 范围、受限指标、角色授权和零分母分类；三套 scorecard 均输出类别 case/pass/fail/missing 数量、通过率及等权宏平均。
- [x] 回归验证类别计数覆盖全部 case、全通过时宏平均为 100%，敏感列/行策略/普通角色毛利率候选发生回归时对应小类与宏平均会失败；`test_evaluate_candidates.py` 42 项、enterprise-text2sql 全量 180 项通过；Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [ ] 固定 SQL 与合成 SQLite scorecard 仍不证明实时 Agent 生成质量、生产数据库授权/RLS 或企业身份策略。

## 2026-09-25 增量：电商分析 UI 离线验收复跑

- [x] `examples/enterprise-text2sql/ui` 的 Node 测试 27 项通过，覆盖多轮会话状态、结构化 SQL 结果图表映射、指标请求、OIDC PKCE、报表下载及打印内容转义；Vite production build 成功。
- [x] 当前工作树复验：`npm test` 27 项通过，`npm run build` 成功。
- [ ] DB-GPT Agent、模型、授权电商数据源和 OIDC 企业环境未运行，仍须真实端到端验收；其他项目的本地数据库不作为本项目验收数据源。

## 2026-09-25 增量：毛利率候选评测与全量回归复验

- [x] 确认 `metric_candidates.json` 已覆盖管理员毛利率、普通角色拒绝及零销售额三种固定候选；指标编译和 API 回归同时验证原始 SQL 不能读取成本列。
- [x] 在当前工作树运行 `examples/enterprise-text2sql` 全量离线套件，183 项通过；覆盖毛利率计算、admin 限制、tenant/region 范围、零分母，以及指标 scorecard 的角色拒绝分类。
- [ ] 该离线复验仍使用固定请求与合成 SQLite 数据，不证明真实模型会正确选择毛利率指标，也不替代生产数据库授权和企业 IdP 验收。

## 2026-09-25 增量：管理员毛利率分析 UI

- [x] 新增 `GET /metrics/available`，按服务端认证角色过滤已发布指标；响应仅含目录展示字段。Vue UI 使用 Bearer token 加载目录，身份切换时清除受限选项和旧结果；仅 admin 能选择毛利率并导出 `admin-margin@1.0.0` 模板，查询与导出 API 继续执行服务端授权。
- [x] API 定向回归 1 项通过；UI 回归 31 项通过；Vite production build 成功；`examples/enterprise-text2sql` 全量离线回归 184 项通过。
- [ ] 离线开发身份模式仍使用演示身份；生产 OIDC/企业 IdP、浏览器回调及真实数据权限未验收。生产 PostgreSQL/MySQL grants、RLS 和数据库成本列授权仍待目标环境验证。

## 2026-09-25 增量：候选 SQL 金标准结果顺序语义

- [x] 50 道金标准题显式标注 `order_sensitive`。普通分组结果按完整行多重集合比较并保留重复行；月度时间序列及 Top 3 排名比较行顺序，避免未要求排序的等价答案被误判。
- [x] 回归覆盖乱序等价结果通过、Top 3 顺序错误失败、重复行数量保留，以及全部金标准题元数据完整；固定候选集依然全部通过。
- [ ] 该改进提升固定数据集比较准确性，不代表实时 Agent/模型的 SQL 生成或语义质量。

## 2026-09-25 增量：MySQL 超时取消后的连接池复用

- [x] 隔离 MySQL 8.4 实例上通过 DB-GPT `MySQLConnector` 和共享只读查询网关执行超时只读查询；MySQL error 3024 被归类为 `timeout`，取消后同一单连接池可继续查询，且 `@@session.max_execution_time` 已复位为 0。
- [ ] 该 smoke 只验证本地 MySQL 8.4 与当前驱动配置；不替代生产连接池/权限配置、其他 MySQL 版本或 PostgreSQL/其他驱动的部署验收。

## 2026-09-25 增量：PostgreSQL connector 超时后的会话复原

- [x] 查询超时使用事务级 `SET LOCAL statement_timeout`，依靠事务提交/回滚自动恢复 session 状态，避免查询取消后在 aborted transaction 中执行重置失败并污染连接池。
- [x] PostgreSQL connector 将 Schema reflection 移到临时查询 session 关闭后，修复 `pool_size=1` 初始化时反射再次借连接导致的连接池超时。
- [x] 新增两项事务级超时回归；隔离 PostgreSQL 16 单连接池 smoke 覆盖超时分类、超时后相同 backend 继续查询及 `statement_timeout=0`。超时回归、Core SQL guard/tracing 与 Ext SQLite 连接器组合回归 71 项通过；Ruff check/format、`py_compile` 和 `git diff --check` 通过；临时数据库已删除。
- [ ] 该 smoke 不替代生产 PostgreSQL 版本、真实连接池、外部取消和部署权限配置验收。

## 2026-09-25 增量：MySQL 实际连接器执行 tenant/region 范围

- [x] 在隔离 MySQL 8.4 数据库创建合成订单后，调用 DB-GPT `prepare_database_query` 生成服务端 tenant/region AST 过滤，再经 `execute_read_only_query` 和真实 `MySQLConnector` 执行；tenant-a 仅返回本租户两行，sales 身份再限于 a-gz 区域一行。
- [ ] 这是应用层 SQL 范围注入的真实连接器 smoke，不是 MySQL 原生 RLS；不替代数据库最小权限账号、生产数据库 grants 或可信身份部署验收。

## 2026-09-25 增量：普通聊天共享日 Token 配额

- [x] `DBGPT_DAILY_TOKEN_LIMIT` 为纯文本 `ChatNormal`、ReAct 和 knowledge-agent 启用统一 tenant+user UTC 日预留预算；ReAct/knowledge-agent 在统一变量未设置时继续兼容 `DBGPT_REACT_DAILY_TOKEN_LIMIT`。ChatNormal 只在最终路由仍为普通聊天时附加配额，知识、Agent、Flow 等模式不在本次范围。
- [x] ChatNormal 使用既有计量 LLM wrapper 和配额 DAO；额度只接受可信 OIDC 用户/tenant 身份，非文本及无法安全计量的请求在模型调用前拒绝，配额异常对用户返回固定提示。无 schema 变更。
- [x] 定向配额 DAO + App 配额回归 25 项通过；App API 全套回归 85 项通过；Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [ ] 该预算仍是预留型软上限，不是 provider 费用硬封顶；配额 DAO 的 PostgreSQL/MySQL 并发已在隔离实例 smoke，ChatNormal+真实 provider usage 端到端验收及其他 DB-GPT 模型端点/聊天模式仍待完成。

## 2026-09-25 增量：企业 Text-to-SQL 当前工作树离线复验

- [x] 按 README 声明的 requirements 和 Core/Serve/Ext/App 源码路径运行 `examples/enterprise-text2sql` 全套 pytest；当前工作树 188 项通过。包含本地 OIDC、数据权限、语义指标、报表任务、候选 SQL 分类 scorecard 和本轮 PostgreSQL 超时回归。
- [x] 当前工作树复跑 `examples/enterprise-text2sql/ui`：Node 测试 31 项通过，Vite production build 成功；Python 离线套件仍为 188 项通过。
- [x] Core 全量目录回归在仓库 `.venv` 通过 pytest importlib 收集后为 791 项通过、1 项跳过；另 22 项 LiteLLM client 测试因该 venv 未安装可选 `litellm` 而失败。完整 Core 回归此前在临时补齐该依赖的环境中 835 项通过，见 P1 测试记录。
- [x] `git diff --check` 通过；本机 DB-GPT Agent、metadata DB、OIDC、模型服务端口均未运行，所需 metadata URL、加密 key、OIDC issuer 和模型凭据也未配置。离线回归与临时隔离数据库 smoke 不替代 live Agent/生产环境验收。
- [x] PostgreSQL trusted tenant RLS context 已贯穿 ReAct 与 SQL 子 Agent、Core DB Agent Resource、Dashboard、SQL Editor 查询/图表重放/图表编辑校验；Core 在执行 guarded SQL 的同一事务中使用绑定参数设置 transaction-local `app.current_tenant`。missing/unverified identity 会显式清空，且不从 audit/span 字段取值；用户 SQL 设置 GUC 仍被 SQL AST guard 拒绝。
- [x] 定向 Core/App/OIDC 回归 156 项通过；PostgreSQL 16.6 一次性容器与单连接池 RLS 集成测试 1 项通过，覆盖 A/B 切换、缺失/未验证身份、查询错误、超时和连接复用；compileall 与 `git diff --check` 通过。测试容器已清理。
- [ ] 生产数据库需由运维创建非 owner、非 superuser、非 `BYPASSRLS` 角色和策略；真实企业 IdP/生产 grants/RLS 部署验收仍待目标环境。独立 SQLite report-task executor 不属于 PostgreSQL connector RLS 覆盖范围。

## 2026-09-26 增量：数据源 owner 转移与报表模板审批

- [x] 历史数据源可由 Verified OIDC admin 转移给明确 owner；`submitted_by`/`user_id` 同事务更新、清空旧审批并回到 pending，审计记录原/新 owner 和原因，成功后清理 connector cache。Serve/App 定向回归 26 项通过。
- [x] 本地报表模板目录由 JSON 初始种子写入 SQLite；新增模板提交、独立 admin 审批/拒绝、角色/指标/导出字段校验、append-only 审计和按角色读取已发布目录 API。同步导出使用已发布目录；任务继续固定模板快照与哈希。
- [x] `examples/enterprise-text2sql` 全量离线回归 191 项通过；Ruff check/format、Python `compileall` 与 `git diff --check` 通过。
- [ ] 模板治理默认使用演示 SQLite、可配置 PostgreSQL URL；报表任务支持 PostgreSQL URL 和多实例原子认领，两者均通过隔离 PostgreSQL 16 smoke。真实 OIDC/Agent/目标数据库、部署 grants/TLS、Secret Manager、正式留存和 key 退役验收仍待目标环境。

## 2026-09-26 增量：多聊天入口日 Token 配额

- [x] v1/v2 chat completions 的 normal、knowledge、data、DB QA 和 dashboard BaseChat 请求在设置统一额度时透传可信 OIDC 配额上下文，复用 reservation/settlement wrapper。
- [x] 两个版本的 chat-app/AWEL flow 及 v1 domain knowledge flow 不使用可计量 BaseChat client，启用配额时返回 503，关闭配额时维持原行为。API v2 同时配置服务 API key 和 OIDC quota 时支持 `X-API-Key` 与 Bearer 分别携带。
- [x] 配额入口/生命周期定向回归 19 项通过；Ruff check/format、`compileall` 和 `git diff --check` 通过。
- [ ] 其他模型调用端点及真实 provider usage 尚未统一计量；日 token 限制仍非账单硬上限。

## 2026-09-26 增量：App-Agent 日 Token 配额

- [x] v1/v2 非 flow App-Agent 请求从 verified OIDC tenant+user 构造 server-side MeteredLLMClient wrapper，并显式传到 Agent controller；不从 `ext_info` 读取身份。额度启用时 flow-backed App-Agent 继续 fail-closed。
- [x] 回归覆盖 v1/v2 App-Agent wrapper 传递、伪造 `ext_info.trusted_execution_context` 不覆盖可信身份、flow 拒绝、Core client wrapper 的 scope/reset 及生成/流式调用。
- [x] 定向测试 29 项通过；覆盖 v1 配额失败保持 HTTP 503；Ruff/格式、`compileall` 和 diff 检查通过。
- [x] `/flow/debug` 没有可信 OIDC tenant+user 上下文，现于启用日配额时 fail-closed 返回 503，并在额度关闭时保持原执行行为；两条路径及拒绝前不调用 flow 的回归通过。
- [x] Core AWEL wrapper helper 目前没有 HTTP flow 路由调用方；chat flow、domain knowledge flow、`/flow/debug` 和所有动态 `/api/v1/awel/trigger/...` HTTP trigger 在配额启用时 fail-closed。trigger guard 同时暂停 `chat`、`command` 及非 LLM flow，因为无法可靠证明自定义节点不调用模型；额度关闭时保留原行为。没有把 AWEL 标记为已计量。
- [ ] 其他模型端点在配额启用时按覆盖情况计量或 fail-closed；fail-closed 的具体入口见“未计量模型端点配额封口”。provider 账单 usage 尚未统一接入，日 token 预算不是 provider 硬上限。


## 2026-09-26 增量：报表任务 PostgreSQL 多实例存储

- [x] `ReportTaskStore` 改用 SQLAlchemy Core，仍兼容 SQLite 路径和 URL；新增 `DBGPT_REPORT_TASK_DATABASE_URL`，可让 API/worker 配置共享 PostgreSQL 数据库。任务 schema 使用跨方言类型，SQLite 文件仍限制为 `0600`。
- [x] PostgreSQL 认领使用事务行锁与 `FOR UPDATE SKIP LOCKED`；actor/idempotency 唯一约束结合冲突安全插入，避免多个 API 实例重复创建任务。保留 SQLite `BEGIN IMMEDIATE` 认领行为。迁移加密与显式留存 CLI 同时接受 SQLite 路径或 SQLAlchemy URL。
- [x] 报表任务回归 13 项通过；`examples/enterprise-text2sql` 全量回归 194 项通过，其中 1 项连接隔离 PostgreSQL 16 容器；Ruff check/format、`compileall` 与 `git diff --check` 通过。
- [x] 隔离 PostgreSQL 16 容器验证了 `SKIP LOCKED`、并发幂等和两个独立 Store 实例的任务认领。
- [ ] 目标部署环境的权限/TLS、备份恢复、故障恢复和多实例运行仍待验收；部署需提供 SQLAlchemy PostgreSQL driver。

## 2026-09-26 增量：报表模板 PostgreSQL 共享治理

- [x] `ReportTemplateReleaseStore` 改用 SQLAlchemy Core，继续兼容 SQLite 文件路径及 URL，并支持 PostgreSQL URL；新增独立 `DBGPT_REPORT_TEMPLATE_DATABASE_URL`，不复用 `DBGPT_REPORT_TASK_DATABASE_URL`，demo 默认仍使用 SQLite。
- [x] store 初始化管理跨方言 release/audit schema、append-only 审计触发器和种子；PostgreSQL advisory transaction lock 与冲突安全插入确保多个 API 首启只种子一次。发布/拒绝、自审拒绝审计和 release 状态变更均在同一事务；行锁确保重复并发审批仅一方成功。
- [x] SQLite 回归覆盖双 Store 共享目录、初始化幂等、发布/拒绝、自审拒绝、并发重复审批和审计不可修改；`examples/enterprise-text2sql` 全量离线回归 198 项通过、2 项跳过。
- [x] 临时隔离 PostgreSQL 16.6 schema smoke 覆盖两个并发 Store 初始化、唯一播种、跨 Store 状态共享、审批/拒绝/自审审计、重复审批竞争及 append-only trigger；模板治理定向回归 9 项通过。临时容器已删除。Ruff check/format、`compileall` 和 `git diff --check` 通过。
- [ ] 目标部署环境的 PostgreSQL grants/TLS、备份恢复和故障恢复仍需验收；部署需提供 SQLAlchemy PostgreSQL driver。该演示 store 不迁移 DB-GPT Serve metadata schema。

## 2026-09-26 增量：Agent 文件下载归属校验

- [x] `/v1/agent/files/download` 要求 verified OIDC 身份和现存会话；调用者必须与持久化会话 owner 精确匹配。
- [x] 下载路径限制在 `PILOT_PATH/tmp/<conv_uid>` 会话目录，拒绝跨目录绝对路径、相对路径穿越、会话目录 symlink 和文件 symlink 逃逸；原有无归属元数据的匿名会话 fail closed。
- [x] 新增 8 项端点回归，覆盖未认证/未验证身份、跨用户会话、全局 `/tmp` 绝对路径拒绝、路径穿越、会话 ID 路径组件、symlink 逃逸及可下载文件；8 项通过。Ruff check/format、`compileall` 和 `git diff --check` 通过。
- [ ] 不在会话 Agent 产物目录内的旧绝对路径不再可下载；没有发现仓库内调用方。企业 IdP 的部署验收仍待完成。

## 2026-09-26 增量：Prompt 模板调试 Token 配额

- [x] 初始版本在无配额身份时 fail-closed；后续已将共享计量客户端下沉至 Serve，并由 App 兼容导出，避免 Serve 依赖 App。
- [x] Prompt `/template/debug` 在配额启用时使用已验签 OIDC tenant/user 身份，按 tokenizer 预估加模型最大输出预占额度，流结束后按 provider usage 结算；缺少 usage 时按完整预占额记账，模型拒绝前不调用 provider，错误流只输出固定脱敏提示。兼容 `DBGPT_DAILY_TOKEN_LIMIT` 和 `DBGPT_REACT_DAILY_TOKEN_LIMIT`。
- [x] 修复 Prompt Serve API key 校验空操作：配置了服务 key 时，缺失/错误 key 返回 401；保留 Bearer API key 兼容，并允许用 `X-API-Key` 与 OIDC Bearer 分开发送。
- [x] Prompt 全套测试 35 项通过；Prompt + quota DAO/Serve 工具 + App 计量模块定向回归 70 项通过；DB-GPT App 全套测试 600 项通过；Ruff check/format、`compileall` 和 `git diff --check` 通过。
- [ ] 其他独立模型调用入口、自定义 AWEL/plugin 及 provider 账单硬上限仍待统一接入；实际账单上限须由模型供应商侧预算控制。

## 2026-09-26 增量：OIDC 查询缺少 Schema 策略时拒绝执行

- [x] ReAct 请求带有服务端 Verified OIDC execution context、但数据源没有 Schema/tenant 策略映射时，即使 token 没有 tenant claim 也 fail-closed；不能退回未受行范围约束的 SQL 执行。
- [x] 当时的旧开发身份兼容分支允许无策略本地查询；此行为已由后续“SQL 身份 fail-closed 与嵌套 Agent 配额”增量收紧为无 Schema/tenant policy 一律拒绝。
- [ ] 该应用层拒绝策略仍不能替代生产 PostgreSQL/MySQL 最小权限账号及数据库侧 RLS/grants。

## 2026-09-26 增量：未计量模型端点配额封口

- [x] Serve 在线评测、LLM benchmark、volatility sub-agent 在没有可信 tenant/user 配额上下文时，如启用 `DBGPT_DAILY_TOKEN_LIMIT` 或 `DBGPT_REACT_DAILY_TOKEN_LIMIT`，会在模型调用或后台任务调度前 fail-closed。此处是安全拒绝，不代表这些路径已计量；Prompt 模板调试和知识文档摘要已在后续增量接入共享计量客户端。
- [x] 对 Tree/Hybrid 和 KnowledgeGraph 空间的知识检索、KnowledgeGraph 文档同步也在无配额身份时 fail-closed；纯 VectorStore 语义检索与 embedding 文档索引保持可用。
- [x] 两个配额开关覆盖拒绝路径，纯 VectorStore 放行回归覆盖；工具、端点、RAG service、volatility action 和 Prompt endpoint 定向回归共 38 项通过。Ruff check/format、`compileall` 和 `git diff --check` 通过；Ruff 对两个既有重复命名模块忽略历史 `F811`。
- [ ] Serve 在线评测、benchmark、volatility 与直接检索/recall-test API 在缺少可信配额上下文时仍会 fail-closed；ReAct/knowledge-agent 内部 Tree/Hybrid 检索已复用父请求计量客户端。在线 `/evaluation` 虽在 HTTP 请求生命周期内 await 完成，但 APP 场景通过 `multi_agents.app_agent_chat` 调用动态 Agent，其模型调用没有统一 MeteredLLMClient 和正向 `max_new_tokens`；AnswerRelevancyMetric 也构造无 `max_new_tokens` 的 ModelRequest；RECALL 场景接受动态注册 metric，API 无法证明第三方 metric 不调用模型，因此不能仅给某一路径加 wrapper 后开放配额。需要先让 Agent 执行链与评测 metric 都接受 request-scoped quota wrapper 并为每个模型调用设置有限输出上限，再以 OIDC verified tenant+user 贯穿同步与后台执行。自定义 AWEL/plugin 模型调用及 provider 账单硬上限仍未覆盖；AWEL flow 仍是拒绝而非计量。
- [x] 在线评测 quota guard 回归扩为 RECALL/APP 与内建/动态 metric 四种请求切面，并覆盖两个配额开关；相关 Evaluate API guard suite 10 项通过。当前仍在模型调用前拒绝，不声称在线评测已计量。
- [ ] Benchmark 与 volatility 仍是安全拒绝而非共享计量：benchmark endpoint 仅验证服务 API key，不能据请求体 `user_id` 建立可信 OIDC 身份；持久化任务记录当前不保存可信 tenant/user，且无进程重启后的任务恢复机制。LLM benchmark 只有在可信身份传递、正数 `max_tokens` 与任务生命周期方案明确后才可接入 wrapper；远程 Agent benchmark 的 provider usage 不可观测，不能按本地 LLM wrapper 计量。Volatility action 未接收父请求的可信 quota context，不能从 Agent 参数或用户输入补造身份。

## 2026-09-26 增量：知识文档摘要 Token 配额

- [x] 知识文档摘要在统一/兼容配额启用时要求 verified OIDC tenant+user；SummaryExtractor 分块生成和最终 ExtractRefineSummary chat 共用预占/usage 结算。没有 provider usage 时按预占上限计费，配额错误向 API 返回固定脱敏消息。
- [x] SummaryExtractor 为模型请求显式设置正向最大输出（默认沿用 `LLMMetadata.num_output`，缺省 256），满足 metered client 的有限预算要求；无配额请求也保留该输出边界。
- [x] Core 摘要、App 知识摘要配额和共享计量模块定向回归 20 项通过；本轮接入后完整 App suite 600 项通过。

## 2026-09-26 增量：核心离线验收复跑

- [x] 当前工作树电商 Text-to-SQL 全套 pytest 200 项通过、2 项跳过；Vue 分析 UI 的 Node 测试 31 项通过，Vite production build 成功。
- [ ] 这些复验覆盖合成数据、API 策略和前端模块，不代表真实 DB-GPT Agent/model/datasource、企业 IdP 或生产数据库与可观测部署验收。

## 2026-09-26 增量：登记视图安全审计与 Agent 结果联动

- [x] `DBGPT_DATABASE_SCHEMA_FILES` 可给 view 提供服务端 SQL 定义；仅接受单条 SELECT、单一已登记物理表、直接业务字段投影，输出列必须与 view 元数据完全一致。缺定义、敏感/非 queryable 字段、表达式、join、子查询、多语句、未知对象和不匹配列均拒绝。
- [x] 策略检查及租户/区域过滤都在 view 展开后的底表 AST 上执行；视图定义 SHA-256 前缀追加至授权策略版本，供执行审计关联。合成 SQLite 回归实际执行 view 查询并确认租户隔离。
- [x] Schema 安全 scorecard 增至 15 条，覆盖安全登记视图、敏感定义和缺失定义；只记录 case ID、结果和 SQL 哈希。
- [x] ReAct Agent 图表类目点击会筛选已有结构化结果表，并可清除筛选；不重新执行 Agent SQL，也不改变数据源授权边界。
- [x] 验证：企业 Text-to-SQL 全套回归 198 项通过、2 项跳过；Vue Node 测试 32 项通过、Vite production build 成功；相关 Python 文件 Ruff check/format、compileall 与 `git diff --check` 通过。
- [ ] 视图子查询/join/表达式刻意不支持；其他 Agent SQL 执行入口、生产数据库 RLS/grants 和真实 DB-GPT 数据源仍需独立验收。

## 2026-09-26 增量：SQL 身份 fail-closed 与嵌套 Agent 配额

- [x] `prepare_database_query()` 对携带 role/tenant 或 Verified OIDC 身份的数据源，在缺少 Schema/tenant policy 时拒绝；不再让 OIDC 关闭时的 legacy admin 身份绕过列检查和行范围过滤。Editor 只读查询也传递 Verified OIDC execution context；不带身份的底层本地开发调用保留兼容行为。
- [x] SQL Editor 目前只接受只读 SQL；admin 写入仍缺少经验证的表/列/行写策略，因此暂不执行。追加 admin 与 legacy admin 写入拒绝回归。
- [x] v1 App-Agent 的请求级配额 wrapper 现通过异步上下文传给嵌套 AppResource 和 ReAct Agent 的知识检索 client；Tree/Hybrid 检索中的树关键词抽取复用父请求 MeteredLLMClient。BaseChat 配额上下文覆盖 Tree/Hybrid 检索；知识重写/抽取请求设置正向输出上限，quota 开启但未安装 metered wrapper 时知识检索 fail-closed。直接 Serve 检索与 recall-test API 在无可信计量上下文时，对 Tree/Hybrid/KnowledgeGraph 继续拒绝。
- [x] SQL 执行无可信 PostgreSQL 身份时不再向旧版兼容 connector 传递值为 `None` 的身份关键字参数；可信上下文存在时仍传递给数据库 RLS hook。
- [x] ReAct 流在整个请求生命周期安装可信 quota client wrapper，确保 Agent 新建的 Tree/Hybrid 检索 client 也计入同一 tenant+user 预算；新增嵌套 client 回归验证身份绑定与流结束后的上下文清理。
- [x] 本次 quota/RAG 定向回归 51 项通过；ReAct 生命周期及 quota/RAG 相关文件 Ruff check/format 与 `git diff --check` 通过。此前定向回归 85 项、DB-GPT App 全套 599 项和企业 Text-to-SQL 全量 198 项通过、2 项跳过记录见前次验证。
- [ ] 生产数据库最小权限、RLS/grants 与企业 IdP 端到端验收仍需目标环境。

## 2026-09-26 增量：异步报表结果强制加密

- [x] `ReportTaskStore.enqueue()` 无有效 Fernet key 时拒绝创建单份/批量任务；API 返回 503，且结果写入处再次 fail-closed。缺少 key 时不启动 worker，因此既有 queued 任务会保留等待运维配置密钥后恢复。
- [x] 报表结果读取始终拒绝历史明文；通过现有批次迁移工具加密后才能读取。README 已说明生成/注入 key 的方式及明文迁移要求。
- [x] 队列/API 定向回归 56 项通过、1 项跳过，覆盖无 key 时入队无数据库记录、worker 不启动、明文结果不返回、旧明文迁移和加密结果正常下载。
- [x] 企业 Text-to-SQL 全套回归 200 项通过、2 项跳过；Ruff check/format、`py_compile` 与 `git diff --check` 通过。
- [ ] 目标部署仍需 Secret Manager 密钥注入、旧明文迁移、正式留存策略及 key 退役流程。

## 2026-09-26 增量：全量候选 SQL scorecard 复跑

- [x] 在隔离合成 SQLite 上一次性运行 gold、安全 SQL、PostgreSQL/MySQL AST、歧义、多轮授权、Schema、tenant/region row scope 和语义指标八类候选：50/50、19/19、20/20、6/6、3/3、15/15、11/11、11/11，合计 135 项全部通过。
- [ ] 这些候选执行的是固定 SQL/动作与合成数据，不证明真实模型 SQL 生成质量、生产数据库 grants/RLS 或企业 IdP 授权；本机 Agent scorecard 已完成但精确匹配 0/50，生产质量和授权仍待验收。

## 2026-09-26 增量：共享 Token 计量客户端前置失败保护

- [x] 回归固定两条预算前置限制：缺少正向 `max_new_tokens` 或 tokenizer 计数失败时，必须在额度预留及 provider 调用前拒绝，不能退化为无上限请求。
- [x] App 计量客户端全套定向测试 15 项通过；Serve 评测/benchmark 配额 guard、volatility guard 与共享 Token 客户端回归合计 20 项通过；Ruff check/format、`git diff --check` 通过。

## 2026-09-26 增量：真实 Agent 联调环境检查

- [x] 检查本机监听端口、可执行文件和 Docker 容器清单；没有发现 DB-GPT Agent 在 5670 端口运行，也没有可见的 Ollama、vLLM、llama-server 可执行文件或 Ollama 11434 监听。当前 Docker 清单包含 Dify 与 HolmesGPT 服务，不含 DB-GPT Agent 服务；未读取 `.env`、凭据或数据库内容。
- [x] 本机 Agent/model/datasource scorecard 已使用运行中的 DB-GPT Agent、Ollama 与授权合成数据源执行 50 题；结果 0 正确、30 错误、20 缺少结构化结果。
- [ ] 企业 IdP、真实用户数据源、生产 RLS 和真实业务模型的端到端 scorecard 仍未验收。

## 2026-09-26 增量：本机 DB-GPT Docker 测试栈

- [x] 新增 `docker/compose_examples/develop-me-test/` 本机测试栈配置：DB-GPT UI 仅绑定 `127.0.0.1:5671`，使用 Docker 内部 Ollama `qwen3:1.7b`、`qwen3-embedding:0.6b` 及只读合成电商 SQLite fixture；不读取或改写 `.env`、现有密钥、数据库和其他 Compose 项目。
- [x] 新增本机单阶段镜像 `docker/base/Dockerfile.test`，成功构建 ARM64 `dbgpt-develop-me-test:latest`（2.88 GB，DB-GPT 0.8.2）；标准 Dockerfile 未改动。
- [x] `docker compose ... config --quiet` 静态校验通过；指定测试网段 `10.255.253.0/24` 后网络与五个项目专用 named volumes 创建成功，fixture 初始化的 50 条 gold query 全部通过。
- [x] Docker Desktop 虚拟磁盘上限扩至 74GB 后，Ollama 镜像及 `qwen3:1.7b`、`qwen3-embedding:0.6b` 下载成功；DB-GPT 与 Ollama 容器健康，UI `/` 和 `/api/health` 返回 HTTP 200，Ollama 本地推理 smoke 成功。元数据 named volume 缺少 Alembic 模板时已补齐模板文件，保留原 SQLite 元数据文件。
- [x] `evaluate_agent.py` 全量 Agent scorecard 已运行并记录 50 题结果；单条演示问答和全量调用均通过真实 DB-GPT Agent、Ollama 和授权合成电商数据端到端验证。当前 scorecard 精确匹配 0 题，结果事件缺失 20 题。
- [ ] 当前 Compose 使用本机开发身份，不包含 OIDC；真实 OIDC/JWT、PostgreSQL 权限/RLS 和企业 IdP 仍须在后续测试/目标环境单独验收。

## 2026-09-27 增量：本机 DB-GPT Agent 对话错误修复

- [x] 修复 Agent 工具包导入 `make_metric_query` 失败导致的对话生成异常；数据库问答按 `chat_with_db_execute` 选择精简只读工具集，并正确提取 `terminate` 的 `output` 字段。
- [x] 修复 Ollama 适配器未透传生成参数和工具调用的问题；Qwen3 本地演示关闭 thinking 后，Agent 可调用 SQL 工具并返回结构化结果。
- [x] 修复 `sql_query` 成功响应未提供 ReAct SSE scorecard 所需结构化 `result` 的契约缺口：保留 Markdown 展示，同时发出最多 50 行 JSON-safe SQL 结果；SQL 执行失败或拒绝时不发结果 payload。定向测试 18 项通过。
- [x] 当前本机容器健康，`/` 与 `/openapi.json` 返回 HTTP 200；一次真实 Agent 问答返回合成数据中的地区销售额结果。
- [x] 50 题 live scorecard 已执行；结果为正确 0、错误 30、缺少结构化结果 20、无效 0、截断 0，结果准确率 0%。结构化结果事件缺口已修复，但模型生成正确 SQL 的能力未通过验收。
- [ ] 通用自然语言 SQL 生成仍未达标（50 题历史 scorecard 为 0/50）；本地真实模型目前仅证明特定演示问题可正确返回，生产模型/数据源与授权仍须另行验收。
- [x] 本地临时镜像重建遇到 Ubuntu APT 仓库签名校验失败；未绕过签名验证。改用 Compose 只读源码和指标目录挂载运行最新修复，DB-GPT 健康。
- [x] 数据库模式已向 Agent 暴露受角色过滤的 `metric_catalog` / `metric_query`；上一轮 q01 暴露模型仍选自由 SQL、遗漏完成状态的证据，保存在 `specs/017-published-metric-agent-routing/evidence/q01-scorecard.json`。
- [x] 指标 SQL 区域关联现使用 `tenant_id + region_id`，退款按原订单区域时也用 `tenant_id + order_id`；新增编译 SQL 回归，验证租户复合键和已完成订单条件。
- [x] 命中的演示区域销售额问题改用 metric-only ReAct 格式，工具集仅提供 `metric_query`；本地 Compose 只读挂载指标目录，明确映射 `ecommerce-demo`。避免 Agent 再选未注册 SQL 工具。
- [x] metric query 输出采用稳定业务列名（销售额为 `sales_cents`），不再统一叫 `value`。
- [x] 原截图问题在本地 DB-GPT + qwen3:1.7b 实测 1/1 正确，结构化结果精确匹配广州 45,000 分、深圳 32,000 分的固定 gold；scorecard 见 `specs/019-metric-only-react-prompt/evidence/q01-scorecard.json`。
- [x] ReAct 现在识别 `sql_query` 的结构化不可重试错误，标记动作失败并终止 Agent 循环；可重试错误仍交给模型纠错。SSE 保留失败步骤，最终响应使用服务端安全错误文案，避免模型在拒绝后续答或重复调用。
- [x] 回归验证 Core/API 定向测试 23 项通过；本地真实 Agent 请求对内部成本列只执行一次 `sql_query`，返回“查询包含当前身份不可访问的敏感字段。”并正常结束；接口耗时 19.5 秒。
- [x] Compose 增加 Core ReAct 文件只读挂载，仅重建 DB-GPT 容器；健康检查与 `/api/health` 均通过，PostgreSQL、Ollama 及其他容器未重建。
- [x] 历史多轮 scorecard（正确 0、错误 1、缺少结构化结果 3；见 `specs/020-react-stop-on-terminal-sql-error/evidence/multiturn-scorecard.json`）已由当前修复后的评测替代：四题本机实时 scorecard 4/4，无超时；仅证明固定合成问法，不代表通用模型多轮理解。
- [x] 更新通用 ReAct 提示词后最初的歧义澄清 live policy scorecard 为 0/3；随后增加本地电商数据库的服务端澄清门禁，缺指标/时间时不调用模型或 SQL，并真实复测三条澄清用例 3/3。其余拒绝类策略和非演示数据库仍需独立验收。
- [x] 修复本地测试 UI 的数据源发现和 ReAct 路由：无 OIDC 的测试栈原先因 `/api/v2/serve/datasources` 返回 401 而无法选库；授权合成数据源现只在无 Authorization、指定 SQLite fixture 与本地 demo 身份同时匹配时显示。UI 选择数据库却发送通用 `chat_react_agent` 时，服务端现按数据库上下文选择专用只读数据库工具集，避免模型调用不存在的 `query_order_count`。对“2026 年第二季度一共有多少笔已完成订单?”做真实 UI 验收，SQL 步骤成功、结构化结果与最终答案均为 `5`；页面未出现 `network error`。定向回归 17 项通过。该本地演示例外不代替真实 OIDC，通用模型 SQL 质量仍未通过验收。

## 2026-09-27 增量：企业 Text-to-SQL 离线回归复核

- [x] 复跑 `PYTHONPATH=packages/dbgpt-core/src:packages/dbgpt-serve/src:packages/dbgpt-ext/src .venv/bin/python -m pytest -q -o addopts='' examples/enterprise-text2sql`：200 项通过、2 项跳过。候选 SQL、语义指标、安全策略、报表任务和演示 API 离线回归均通过；出现 186 条既有依赖/API 弃用警告。
- [x] 复跑分析 UI：`npm test` 32 项通过，`npm run build` 成功（Vite 转换 650 个模块）；验证只生成本地忽略的 `dist/`，没有改动应用源码。
- [x] 离线套件本身不改变实时结果；独立 live 评测仍显示 50 题通用 SQL 精确匹配 0/50，多轮固定场景现为 4/4。生产身份、数据库权限及部署可观测验收仍待目标环境。

## 2026-09-27 增量：Agent 数据查询失败结果封口

- [x] 华南季度销售额/退款率真实 UI 联调暴露模型在 SQL 字段校验失败后仍生成无依据数值。数据库专用 ReAct 现跟踪 `sql_query` / `metric_query` 执行结果；本轮最近一次查询失败或未返回可验证结果时，最终回答改用工具提供的安全失败信息，后续成功结果才清除此失败状态。
- [x] 为直接及嵌套数据库工具结果补充分类回归；App 生命周期、路由和数据源鉴权定向回归 39 项通过，Ruff check/format 与 `git diff --check` 通过。仅重启 DB-GPT 测试容器后复测，健康接口 HTTP 200；华南问题以“本轮 SQL 纠错预算已用尽，不得继续重试。”结束，不再展示模型编造的销售额与退款率。
- [x] 新增目录白名单区域过滤及多指标单次 `metric_query` 编译路径后，工具真实返回华南 Q2 销售额 `77,000` 分、退款率 `6.1%`。修正结果封口对 `result.sql_result` 的识别，并让 ReAct 解析器兼容模型省略 JSON `Action Input`、改用 `Final Answer` 的终止格式；本地 Compose 只读挂载解析器变更。Core/App/Serve 定向回归 113 项通过。
- [x] 重建本地 DB-GPT 测试容器后，华南指标真实 UI 重跑成功：页面最终展示“华南区第二季度销售额为 77000 分，退款率为 6.1%”；指标工具执行成功，无 `ToolNotFound` 或误报查询失败。
- [x] 补齐 `step.result` 前端消费：校验结构化 SQL 结果后，在 Agent 执行面板生成结果表，并为多行“文本维度 + 数值指标”生成分类柱图或时间折线图；标量多指标仅展示表格，避免混合单位误画。后端会话历史保留同一份经过 SSE 序列化校验的结果。数据转换测试通过，App SSE/解析器定向回归 52 项通过。
- [x] `web/` 安装锁文件指定依赖后，`npm test` 全部通过（ReAct 13、结果呈现 7、SQL 结果转换 6）；Next production build 成功，页面静态生成完成。Next 配置跳过全量 TypeScript 检查；构建有既有 React Hooks lint warnings。
- [x] 独立生产构建页面 smoke：UI 可加载；将容器宿主映射 `5671` 临时转发到 Next 配置固定的 API 端口 `5670` 后，首页 datasource/任务接口正常，无 `Request error` / `Network Error`。临时 Next 和端口转发进程仅用于本地验收。
- [x] 图表类目筛选浏览器验收已完成：点击 `completed` 类目后表格只显示该类别，清除筛选恢复全部数据。DB-GPT live Agent 城市退款率结果表/图表、Next 代理下订单单轮问答和固定多轮场景也已通过；通用模型 SQL 质量与开放式多轮分析仍未通过验收。
- [x] 修复取消链路：Ollama 流式适配器新增异步 SDK 路径，生成器取消时关闭 SDK 响应流及 HTTP 客户端；DB-GPT 模型 API 的流式响应在断开时关闭底层生成器；Next 专用 `/api/agent-stream` 代理转发客户端 socket 断开并取消上游 SSE。真实 DB-GPT API 取消后未见 `llama-server` 子进程，Next 代理通过本地假 SSE 服务确认上游收到断连。之后经本地 Next 代理、DB-GPT、Ollama 对截图中的订单问题做真实联调：SSE 正常结束（13 个事件），SQL 结果和最终答案均为 `5`，无网络错误。Ollama、模型 API 和 Agent 生命周期定向 pytest 共 23 项通过，Ruff、ESLint、`npm test`（26 项）及 `git diff --check` 通过。Next 本次完整 production build 在静态页面生成阶段超时退出；Next dev 已编译并完成联调，之前完整 production build 曾成功。该 CPU 环境推理较慢，端到端约 5 分钟。
- [x] 按最新截图在本地 UI 重跑“2026 年第二季度一共有多少笔已完成订单？”，页面正常结束并显示 `5`；审计日志记录该 SQL 查询成功且返回一行，浏览器无 `network error`。Ollama `qwen3:1.7b` 全 CPU 推理耗时约 105 秒，是慢响应而非连接错误。
- [x] 华南固定场景已完成首问、最高退款率城市（含 live 结果图表）和广州销售额占比的多轮工具/结果验收；首问双指标以表格展示，单值占比不生成图表。
- [ ] 通用实时模型生成质量、开放式多轮理解、生产身份与数据库授权仍待继续处理。

## 2026-09-27 增量：Live Agent 评测超时隔离

- [x] `evaluate_agent.py` 将单题 socket timeout、HTTP 408/504 记录为脱敏 `timeout`，继续后续题目；在单题结果和分类/总 scorecard 记录耗时及超时数量。401/403 和其他 HTTP 错误仍终止整批，避免将身份/配置故障计为模型低分。
- [x] 回归验证覆盖 socket/网关超时后继续评分、保留前后题目结果、耗时/分类统计、异常内容与 token 不泄露，以及 401/403 仍失败。`examples/enterprise-text2sql` 全套回归 202 项通过、2 项跳过；Ruff check/format、`py_compile` 和 `git diff --check` 通过。README 已记录行为。
- [x] live scorecard 实测 15 秒单题上限时有 3 题记为 `timeout`，剩余题目仍继续请求和计分；同一批次中，首轮及同会话追问后仍继续到后续独立题并得到正确结果。提高上限后的 25 秒、60 秒多轮 scorecard 各为 4/4。该验证只覆盖固定合成数据集，不改变通用模型历史 0/50 结果。

## 2026-09-27 增量：Agent SSE 长耗时连接保活

- [x] `/api/agent-stream` 在等待 DB-GPT SSE 数据时每 15 秒发送 SSE 注释心跳，避免本地模型长时间无可见输出时浏览器或代理按空闲连接关闭请求；浏览器解析器会忽略注释帧。
- [x] UI 现在要求正常流包含 `done` 终止事件；意外 EOF 会提示连接中断、结束运行状态并将当前执行步骤标记失败，不再把未完成请求留在“正在思考”。
- [x] 对 16 秒静默上游做 Next API 代理 smoke，确认中间发出心跳且终止事件仍被转发；`npm test`、修改文件 ESLint 通过，Next dev 重启后 API 路由重新编译并返回预期 405。
- [x] 本机 Ollama 全 CPU 推理耗时约 9 分钟；对隔离会话重新打开历史后，执行步骤显示 SQL 查询成功、结果表与摘要均为 `5`，页面没有 `network error`。该过程证明慢响应可完成并恢复历史结果。
- [ ] 全项目 `npx tsc --noEmit` 仍被既有多处类型错误阻断。旧会话中的 `LLMServer Generate Error` 是历史失败记录，不代表新请求状态；更广泛的 live scorecard 和通用模型 SQL 准确率仍待验收。

## 2026-09-27 增量：区域销售图表查询正常收尾

- [x] 将本地 `ecommerce-demo` 的 2026 Q2 城市/区域销售额请求识别为已发布指标，只开放服务端 `metric_query`；离线路由回归覆盖城市维度、年份/季度和比较请求的拒绝条件。
- [x] 真实 UI 首轮复验拿到租户过滤后的结构化结果（广州 45,000 分、深圳 32,000 分）及图表，但 1.7B 模型在成功查询后仍额外生成总结，约 5 分钟后客户端断开且未收到 `done`。日志确认是慢速第二轮推理期间客户端关闭连接，不是 SQL 执行失败。
- [x] 区域销售指标查询改为单次工具调用；仅在服务端确认指标查询成功后使用固定收尾文案，查询失败仍走原有安全失败分支。不会改变其他数据库 Agent 的重试次数。
- [x] 修复后通过 Next UI、DB-GPT、Ollama 和授权演示数据库实测：回答正常结束，页面显示结果表（广州 45,000 分、深圳 32,000 分）和按销售额降序的柱状图，没有 `network error` /“响应连接中断”。后端结构化数据是结果依据；展开的 ReAct 过程轨迹仍可能展示模型生成的错误终止草稿，不作为查询结果或最终答案。
- [x] App 生命周期和数据库工作流定向回归共 23 项通过，Ruff 与 `git diff --check` 通过；重启本地测试容器后健康接口 HTTP 200。通用模型质量仍未达标（历史 50 题精确匹配 0/50），不据此关闭开放式问答验收。

## 2026-09-27 增量：华南退款率多轮追问

- [x] 同会话存在“第二季度华南区销售额和退款率”上下文时，将“哪个城市退款率最高”解析为 2026 Q2、South China、`refund_rate`、region 维度的服务端固定指标计划；模型误选 SQL 工具或参数时，服务端通过同一授权 `metric_query` 工具执行固定参数，不接受模型提供的 SQL。指标工具仍复用当前已授权 datasource、发布目录、tenant 范围、只读执行器和审计。
- [x] 真实 DB-GPT UI 两轮联调通过：首轮固定指标返回华南销售额 `77,000` 分、退款率 `6.1%`；追问的结构化结果为广州 `5.56%`、深圳 `6.88%`，最终回答深圳最高。执行面板显示 `metric_query` 和城市退款率结果表/柱状图，连接正常结束；一次未命中回退的尝试先安全失败，没有执行模型生成 SQL。
- [x] 增加历史上下文分类、结构化最高值汇总及模型误选工具/参数时固定指标回退回归；App 生命周期与数据库工作流定向回归 26 项通过，Ruff、`git diff --check` 通过。测试容器重启后健康接口 HTTP 200。
- [x] 扩展同一华南上下文的“广州销售额占华南区比例”追问：只查询发布的 `sales_amount`，按服务端 tenant/区域范围取各城市金额，再将完整、未截断的指标行转换为 `sales_share_pct` 结构化单值；缺城市、重复维度、负值、截断或缺列时拒绝计算。
- [x] 真实 UI 继续同会话追问后，最终回答为 `58.44%`；执行面板的单值结果表为 `sales_share_pct = 58.44`。一轮 smoke 连续覆盖华南首问、最高退款城市和广州销售占比两类追问，工具记录为固定参数 `metric_query`，页面正常收尾。
- [x] 扩展上下文分类、固定动作回退和销售占比结构化转换测试；App 生命周期与数据库工作流定向回归共 28 项通过，Ruff、`git diff --check` 通过。测试容器重启后健康接口 HTTP 200。
- [x] 订单数截图对应的旧会话重新打开后，执行面板显示只读查询成功、Q2 完成订单数为 `5`；截图中的 `network error` 是同会话中较早的一次失败尝试，当前展示的重跑结果正常。
- [x] 首次完整多轮评测为 `3/4`，唯一错误是退款率追问的金标准只写了最高城市一行，而执行器正确返回完整城市结果表；将金标准修正为广州 `5.56%`、深圳 `6.88%`。
- [x] 修正后以每题 300 秒超时上限完成真实多轮 scorecard：`4/4` 正确、无超时；单题耗时约 25–144 秒，波动发生在本地 Ollama CPU 推理阶段。此结果只覆盖固定合成多轮用例，不代表通用模型准确率、企业 OIDC 或生产授权验收通过。
- [x] 真实澄清策略复测发现“最近经营情况”会误执行 SQL，“最好商品”和缺少时间范围的最高退款率问题不能可靠澄清。现对本地 `ecommerce-demo` 缺少指标/期间的三类问法在服务端直接返回澄清并持久化会话；该路径不调用 LLM 或 SQL，不影响已有上下文或其他数据源。
- [x] 澄清用例 live policy scorecard `3/3`，无结构化 SQL 结果；澄清回归与固定华南多轮评测在新代码重启后分别为 `10 passed` 和 `4/4`。Ruff check、`py_compile`、`git diff --check` 通过，DB-GPT 健康接口 HTTP 200。
- [x] 本地 UI 重新打开深圳退款率追问后恢复广州 `5.56%`、深圳 `6.88%` 的结果表与图表，确认图表历史恢复正常。
- [x] SQL 结果图表类目点击现通过 AntV `onEvent` 的 `click` 图元事件筛选同一份表格数据；新增过滤函数回归。`web` 的 `npm test` 通过；页面结果组件/过滤工具 ESLint 无错误（保留原有 hook 警告）。共享图表组件文件另有未改动行的既有 `xField` unused ESLint 错误，`git diff --check` 通过。
- [x] 浏览器实测发现 G2 同一原生点击会通过 wildcard `onEvent` 回调多次，状态 toggle 当场抵消；按原生事件 `timeStamp` 去重后，新版 Next UI 实测点击 `completed` 柱只显示该类别的一行，点击“清除筛选”恢复两行。该次验收使用当前 DB-GPT SSE 历史结果和本地测试 API。
- [x] 电商单季度销售额固定指标路由现明确排除同比/去年同期/增长/增幅等中英文比较意图，避免将比较问题误当作已发布的单期销售额指标直接回答；数据库工作流回归 10 项通过，Ruff 与 `git diff --check` 通过。该边界只阻止不匹配的固定快捷路由，不证明通用 Agent 能正确回答同比分析。
- [x] 重新运行 ReAct dispatcher、业务字典上下文及数据库工作流定向套件，53 项通过；覆盖字典上下文拼接进主/子 Agent prompt。Ruff 与 `git diff --check` 通过。真实模型 SQL/语义正确率仍按 live scorecard 单独跟踪。

## 2026-09-28 增量：多轮 Agent timeout 恢复回归

- [x] live evaluator 新增同一 `conversation_group` 首题 socket timeout、后续追问继续计分的回归；确认两题共用 `conv_uid`、后续独立题目使用新会话、scorecard 仅将首题计为 timeout 且不泄露 token、异常文本或会话组名。`test_evaluate_agent.py` 22 项通过，Ruff check/format 与 `git diff --check` 通过。
- [x] 本地 DB-GPT live 多轮批次以 15 秒单题上限实测：4 题均继续写入 scorecard，其中 3 题标记 timeout，后续独立题仍完成并正确计分（1/4）；此前 25 秒和 60 秒批次各为 4/4。该结果验证超时后批次继续执行，不代表通用模型准确率或生产授权验收。
- [x] 根据最新截图在当前本地 UI 新建会话重测“2026 年第二季度一共有多少笔已完成订单？”：只读 `sql_query` 成功，租户/状态/季度条件完整，结果表与摘要均为 `5`，浏览器 SSE 正常收到 `done`，未出现 `network error`。截图中的失败暂未复现；缺少原失败会话标识与当时网络记录，不能确认其具体根因。

## 2026-09-28 增量：Live evaluator 拒绝不完整 SSE 结果

- [x] `evaluate_agent.py` 现要求 `/api/v1/chat/react-agent` 的 SSE 包含应用层 `done` 事件，才会将 SQL 结果或拒绝/澄清答案计分；意外 EOF 单列为 `incomplete_stream`，不会把仅收到 `step.result` 的部分流计为正确。
- [x] 成功 mock 响应现显式包含 `done`；新增 gold 与 policy 的缺少终止帧回归。`examples/enterprise-text2sql` 全套 205 项通过、2 项跳过；Ruff check/format 与 `git diff --check` 通过。测试有 186 条既有依赖/API 弃用警告。

## 2026-09-28 增量：图表筛选回调去重

- [x] G2 wildcard `onEvent` 对一次数据点点击发出多个带同一原生事件时间戳的事件；筛选状态原先逐次 toggle 后回到未筛选。现在同一时间戳最多处理一次，用户点击仍可再次点击同一柱以取消筛选。
- [x] 新版 Next 页面连接本地 DB-GPT API 实测：点击 `completed` 柱后只显示 `completed / 5` 一行并出现筛选状态；“清除筛选”恢复 `cancelled / 1` 和 `completed / 5` 两行。`web/npm test` 全部 26 项通过，ESLint 报告共享图表文件中既有未使用 `xField` 错误和右侧面板 2 条既有 Hook 警告；Prettier、Python Ruff、全套 Text-to-SQL 测试通过。

## 2026-09-28 增量：实时 Agent 金标准顺序比较

- [x] 修复 `evaluate_agent.py` 忽略 gold `order_sensitive` 声明的问题：无序结果按完整行多重集合比较（保留重复计数），月序列和 Top 3 等顺序敏感题继续逐行比较；自定义 dataset 未提供声明时默认顺序敏感。
- [x] 新增 q01 反序仍判正确、q47 Top 3 反序判错误的 live evaluator 回归。定向 `test_evaluate_agent.py` 26 项通过；`examples/enterprise-text2sql` 全套 207 项通过、2 项跳过；Ruff check/format、`py_compile` 和 `git diff --check` 通过。
- [x] 修正后重跑 50 题 live scorecard：正确 `1/50`、incorrect `28`、missing_result `21`、timeout `0`、incomplete_stream `0`。精确率仍很低，开放式 Text-to-SQL 尚未达标；这轮比旧报告有效，但仅代表本机 Qwen 3 1.7B、合成数据和当前一次抽样。
- [x] 对批次中标记为 missing_result 的 q01、q50 各做一次独立请求诊断：两次均观察到 HTTP 200、完整 `done` 事件和 `step.result/sql_result`；说明结果具有生成波动，单次重跑不能替代稳定质量验收。诊断仅记录事件类型/长度，不保存 SQL 或行值。
- [x] 旧的 2026-09-27 `0/50` 报告忽略了 46 题的无序语义，且早于 SSE 结构化 SQL 结果事件修复；其 30 个 incorrect 仅保留哈希，无法回溯排序差异，因此不与本次结果直接比较。
- [ ] 通用 SQL/指标选择质量仍未达验收线；需要在改善生成质量后用当前规则重跑 scorecard。不得将固定场景 4/4 或本轮 `1/50` 解释为生产模型、企业身份或生产授权验收。

## 2026-09-28 增量：签名 OIDC JWT 到 ReAct SQL 行范围集成回归

- [x] 新增 `test_oidc_react_agent_integration.py`：用 RSA 私钥签发测试 JWT，走 FastAPI 的真实 Bearer 依赖、PyJWT 签名/issuer/audience 校验、claim/role 映射和 `/v1/chat/react-agent` 路由；JWKS 客户端使用测试替身，不依赖外部 IdP。
- [x] 验证请求体伪造的 `admin`、tenant、region 和 `verified_execution_context` 不会覆盖令牌身份；路由服务端上下文来自已验签 claim。
- [x] 将路由产出的身份上下文送入主 Agent 和子 Agent 实际 SQL 工具，并在 SQLite 合成表上执行；两条路径都只返回令牌授权的 `tenant-a / north` 行，未返回其他区域或租户数据。缺少 Bearer、必需 claim 缺失和 issuer 不匹配均返回 401。
- [x] 新集成文件 4 项通过；定向组合测试中有 74 项通过。Ruff check/format 通过。
- [ ] 该回归验证真实 JWT 签名和默认 ReAct 工具链，但 IdP discovery/JWKS 网络获取、数据源 owner ACL 以及 PostgreSQL RLS 仍需在 Keycloak/PostgreSQL 集成环境验收；本测试的 JWKS 解析器和数据源连接授权入口使用替身。
- [x] 同一轮回归发现 2 个陈旧指标测试：mock 仍返回旧版 SQL 结果结构，区域 fixture 缺少 tenant 关联列且沿用旧输出列名。更新 mock 为结构化结果并补齐合成 tenant 数据后，sub-agent 全集 27 项通过；生产实现保持严格校验。
- [x] 本机测试 Compose 增加可选 `telemetry` profile：通过 overlay 启动 Jaeger OTLP/gRPC 与 DB-GPT exporter，实际 ReAct SQL 查询生成 1 条 `agent.sql_query` span；span 带 SQL 哈希、行数、耗时、actor 与授权策略元数据，未见原始 SQL 或结果值。DB-GPT 健康检查和 Jaeger API 均正常。
- [ ] 本机检视同时发现部分 Agent 框架级 trace span 可能含模型输入/输出；调试收集器必须限于合成数据。真实/敏感数据使用前仍需审计并脱敏这些 span，且尚无 Collector/OpenObserve 网络认证、TLS、留存和生产部署验收。

## 2026-09-28 增量：高置信指标路由服务端固定执行

- [x] 华南 KPI 首问和带明确年份的已发布区域销售额问题，不再只依赖提示词引导模型选择指标工具；服务端收到 ReAct `act` 后会将错误工具、错误参数或提前 `terminate` 统一替换为预先识别的 `metric_query` 和目录参数。执行仍经过指标目录、租户/区域授权、只读 SQL 执行和审计路径。
- [x] 扩展回退回归，覆盖模型给出普通 SQL 动作、提前 `terminate`、正确指标动作不重复执行；数据库工作流与 App 生命周期定向回归 29 项通过，Ruff check 与 `git diff --check` 通过。
- [x] 重启本地测试服务后，华南 KPI q41 单题 live scorecard 仍为正确（1/1）。这只是窄路由的回归，不证明总体准确率提升。
- [x] 当时通用 q03 订单计数单题重测为 incorrect，暴露出模型生成聚合结果不稳定；后续已在“本地电商季度订单总数固定查询”中通过窄范围服务端查询修复 q03/q04。修复后的完整 50 题结果见“本地电商季度订单总数固定查询”增量。

## 2026-09-28 增量：本地电商季度订单总数固定查询

- [x] live q03/q04 诊断显示订单计数仍依赖模型生成 SQL。对本地 `ecommerce-demo` 增加窄范围的第二季度完成/取消订单总数路由：仅接受无分组、无比较且未指定非 2026 年份的问题；服务端固定查询通过现有只读 SQL 工具执行，继续使用租户/区域策略、超时、行数限制及审计。
- [x] 回归覆盖完成/取消状态、其他年份、分组请求、其他数据源，以及模型提前 `terminate` 时的固定查询回退和相同查询不重复执行。数据库工作流与 App 生命周期定向测试 31 项通过；Ruff check 和 `git diff --check` 通过。
- [x] 重启现有 `dbgpt-develop-me-test-dbgpt-1` 容器（Compose 曾因项目名不一致未重启旧实例；旧进程已确认未加载新模块），健康状态恢复后 live q03/q04 均正确（2/2）。
- [x] 修复后完整 live scorecard 已保存至 `specs/012-live-react-sql-result/evidence/live-gold-scorecard-20260928-order-count-route.json`：正确 `3/50`、incorrect `28`、missing_result `19`、timeout/incomplete/invalid/truncated 均为 `0`；`order_counts` 类别 `2/3`，相较最近一次修复前完整基线 `1/50` 净增 2 题。q03/q04 均正确。
- [ ] 整体 Text-to-SQL 质量仍未达验收线：product_analysis、refunds、sales_aggregates、time_series 等类别本轮没有正确题；regional_sales 为 `1/10`。应优先基于逐题证据继续修复缺结果和错误聚合，再复跑完整 scorecard；不得将本次局部提升视为整体达标。

## 2026-09-28 增量：缺年份区域指标的服务端收尾

- [x] 实时失败诊断发现 q01/q02/q09 的请求完整结束但未产生结构化 SQL 结果，q10 则有结构化结果。演示数据业务上下文已明确第二季度对应 2026-04-01 至 2026-07-01；区域销售额请求可在未写年份时使用该默认期间。
- [x] 扩展已发布区域销售额路由以接受未指定年份或明确写 2026 的 Q2 请求；为区域已支付退款金额增加固定目录指标路由，显式参数为 `paid_refund_amount@1.0.0`、退款发生日期范围和 `region` 维度。模型只有最终回答而未执行查询时，服务端现执行固定指标并向 SSE 与会话历史写入工具步骤和结构化结果；查询仍经同一 SQL 权限、租户范围、超时和审计入口。
- [x] 分类/授权边界回归后，数据库工作流和 App 生命周期定向测试 32 项通过，Ruff、测试文件格式检查和 `git diff --check` 通过。重启本机 DB-GPT 测试容器后，q01 区域销售额和 q02 区域退款金额实时 scorecard 均正确（2/2）。
- [x] 上一份完整 50 题 scorecard（3/50）早于本次区域路由改动；q09 月度趋势和 q10 分地区订单数后续已按已发布指标/固定 SQL 路由修复，并分别通过实时测试。当前整体分数仍需完整重跑确认。

## 2026-09-28 增量：月度销售与区域订单数查询

- [x] 为已发布 `sales_amount` 增加服务端固定的 Q2 月度查询路由；Agent 指标结果把内部月分组键 `period` 对外命名为 `month`，与该维度名及金标准输出一致。为本地电商演示增加仅匹配 Q2 已完成订单数、按区域分组的固定 SQL；区域表使用 `tenant_id + region_id` 复合关联，执行继续通过 SQL 只读与授权网关。
- [x] 回归覆盖月度/区域订单数路由的年份、维度和指标边界，以及 metric compiler 的 `month` 输出别名。数据库工作流、App 生命周期与 metric query 定向测试 39 项通过；Ruff check、测试文件格式检查、`git diff --check` 通过。
- [x] 重启本机测试服务后，q09 月度销售额、q10 各地区完成订单数的实时 scorecard 均正确（2/2）。结合前一轮 q01/q02 和订单总数 q03/q04 的定向验证，这 6 个对应样例均已通过。
- [ ] q01/q02/q09/q10 路由改动后的完整 50 题 scorecard 尚未重跑；上一份完整 scorecard 为更早代码下的 3/50，仍不能代表当前总准确率。商品、客户、多指标/多轮问题仍需基于逐题结果继续修复。

## 2026-09-28 增量：Q2 商品类别与商品销量固定查询

- [x] 为 `ecommerce-demo` 的 Q2 商品分析增加窄范围固定查询分类：商品类别销售额、类别销量、商品销量。查询限定 2026 年 Q2 完成订单，订单明细与订单/商品均按 `tenant_id` 复合键关联，并固定经现有只读 `sql_query` 工具执行；分类器拒绝非 2026 年、非演示数据源、额外地区/月/客户维度、跨季度比较和同时请求多项指标。
- [x] Agent 主路由指令、模型动作修正及缺少数据库工具动作时的服务端兜底均接入该固定 SQL。App 生命周期、数据库工作流与指标查询定向测试 45 项通过；`examples/enterprise-text2sql` 全套 209 项通过、2 项跳过；Ruff check、格式检查、`py_compile` 与 `git diff --check` 通过。
- [x] 本机服务重启后，实时金标准 q11–q13 全部正确（3/3）；当前代码的完整 50 题复测继续跟踪总体质量。

## 2026-09-28 增量：Q2 单月订单与标量聚合路由

- [x] 为本地 `ecommerce-demo` 增加限于 Q2 的单月已完成订单数、售出商品种类数、最大/最小已完成订单金额、平均已支付退款金额固定查询；非演示数据源、非 2026 年、额外维度分组、逐月趋势、取消订单、跨季度比较及多项指标意图均不命中。商品种类数要求明确“多少种商品”语义，不将含糊的英文“products sold”猜成去重种类。商品明细关联订单时使用 `tenant_id + order_id` 复合键。
- [x] 固定查询接入 Agent 主路由指令、模型动作修正和最终服务端兜底，继续经现有只读/tenant-region SQL 工具执行。分类边界和主/子路由组合定向测试 45 项通过，Ruff、格式检查、`py_compile` 与 `git diff --check` 通过。
- [x] 更新本机 DB-GPT 后运行脱敏实时 scorecard：q11–q13 商品分析、q19–q21 单月订单数、q23 售出商品种数、q25–q27 标量金额共 `10/10` 正确；0 错误、0 缺结果、0 无效/截断/不完整、0 超时。逐题耗时约 45–64 秒；结果见 `specs/012-live-react-sql-result/evidence/live-gold-scorecard-20260928-q2-routes-targeted.json`。该结果只覆盖这 10 条合成数据题，不代表通用 SQL 质量或生产授权。
- [ ] 当前代码的完整 50 题总体质量未复测。本轮按用户要求只验证关键链路；此前启动的全量运行已停止且未生成 scorecard，不能作为当前总分。旧版 `3/50` scorecard 早于后续路由修复，仅在需要评估通用模型质量时再单独安排全量运行。

## 2026-09-28 增量：实时 Agent 重复运行稳定性评测

- [x] `evaluate_agent.py --runs 2..5` 可用独立会话重复运行同一金标准集，输出各轮结果以及逐题正确率、状态计数、不同结果哈希数和类别汇总；默认单轮的原有报告格式保持不变。重复评测只接收 evaluator 脱敏 scorecard，不持久化 SQL、答案、提示词或结果行值；policy scorecard 仍限定单轮。
- [x] 回归覆盖重复运行波动统计、不同题集拒绝、轮次会话隔离及 SQL/行值/token 不泄露，并验证多轮均值影响 CLI 退出码；`test_evaluate_agent.py` 29 项通过，`examples/enterprise-text2sql` 全套 210 项通过、2 项跳过；Ruff check/format、`py_compile` 与 `git diff --check` 通过。使用真实多轮数的稳定性结论仍需由目标 DB-GPT 服务运行 `--runs 2..5` 后产生，不能由 mock 回归替代。

## 2026-09-28 增量：Q2 关键查询最终代码验收

- [x] 按用户将验收范围限定为关键链路后，停止完整 50 题评测；该次运行未产生总 scorecard，不把空文件或旧版 `3/50` 结果作为当前总分。停止状态记录于 `specs/012-live-react-sql-result/evidence/live-gold-scorecard-20260928-q2-routes-full.json`。
- [x] 重启本机 DB-GPT 测试容器加载最终代码；针对 q11–q13、q19–q21、q23、q25–q27 的实时脱敏评测为 `10/10` 正确，0 错误、0 缺结果、0 无效/截断/不完整、0 超时。日志曾出现一次 Ollama runner 500，但最终 scorecard 中 10 题均正确。四个覆盖类别均为 100%；逐题状态及耗时见 `specs/012-live-react-sql-result/evidence/live-gold-scorecard-20260928-q2-routes-targeted-final.json`。这只证明固定合成问题的关键路径，不代表通用 SQL 能力或生产授权。
- [x] Q2 查询路由分类与拒绝边界回归 `test_database_workflow_prompt.py`：21 项通过；DB-GPT 测试容器健康。
- [ ] 通用实时 SQL 总体质量、生产身份/授权、PostgreSQL RLS、遥测部署与真实多轮稳定性仍待后续目标环境验收。

## 2026-09-28 增量：核心分析演示入口

- [x] 根目录新增 `CLAUDE.md`，明确产品核心闭环、Python/DB-GPT 技术路线、简历表述边界及用户当前暂停测试的要求。
- [x] DB-GPT 自然语言分析面板已实现四个快捷填入按钮：完成订单总数、月度销售额、商品类别销量、平均退款金额；点击只填入输入框，不自动提交。
- [x] 目录驱动单指标解析已通过行为回归；已验证与 Q2 商品分类、季度订单数、月度销售、区域订单数等固定场景路由互不误命中。历史 Q2 特例仍保留，用于尚未被指标目录覆盖的维度或多指标组合；当前不再为每道题增加新 SQL 特例。

## 2026-09-28 增量：目录驱动的自然语言指标入口

- [x] Agent 自然语言入口按当前数据源/角色读取已发布指标目录，使用名称和目录别名解析唯一指标；支持季度、月份、全年时间范围，目录可声明默认年份，维度限定为已发布区域或月份。多指标、比较、未支持分组/排序、缺失必要范围和不可用维度不进入快捷执行；毛利率仍受 admin 角色和 Schema 策略限制。
- [x] 指标目录支持受校验的可选别名和 `default_year` 字段；电商演示目录定义默认年份 2026，并补充中英文销售额、退款额、净销售额、退款率和毛利率表达。执行仍走 `metric_query` 确定性编译、只读 SQL 网关及现有授权/审计。
- [x] 增加目录路由行为回归，覆盖默认年份、名称/别名、月度维度、区域别名、角色过滤、多指标歧义、不支持分组/区域和比较意图；连同目录加载、指标编译、Agent 工作流和 App 生命周期定向回归共 80 项通过。Ruff、`py_compile`、JSON 解析及 `git diff --check` 通过。
- [x] 本机 DB-GPT 容器已重启并健康；默认年份指标问题的实时 Agent smoke 为 1/1 正确（77,000 分，约 33 秒）；商品类别分组问题 q11 为 1/1 正确（约 84 秒）；区域销售 q01 按销售额降序为 1/1 正确（约 49 秒）。当前完整 50 题 scorecard 未运行。

## 2026-09-28 增量：对话区显示结构化查询结果

- [ ] 已在 `ManusLeftPanel` 加入结构化 SQL 结果表格，并从每轮对话的 `execution.outputs` 读取结果，放在自然语言回答下方；右侧调试面板保持原实现。
- [x] 变更文件通过 Prettier 检查和 `git diff --check`。前端完整 `tsc --noEmit` 当前被仓库内多处既有类型错误阻断；浏览器运行验收尚未完成，因此不标记该 UI 项完成。

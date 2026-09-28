# DB-GPT 本机 Agent 测试环境

该目录只管理本机 Docker 测试栈，不复用根目录默认 Compose、不连接企业 IdP、也不使用外部 API 密钥。DB-GPT 和 Ollama 仅绑定 Docker 内网；DB-GPT UI 只发布到 `127.0.0.1:5671`。电商数据由仓库内合成 fixture 生成，作为只读卷挂进 Agent 容器。

## 目录约定

- `compose.yaml`：本测试栈的服务、端口与命名卷。
- `compose.telemetry.yaml`：可选的本机 Jaeger OTLP/gRPC trace 接收和 UI，不默认启动。
- `config/dbgpt-test-ollama.toml`：测试用 DB-GPT 配置；不放凭据。
- `README.md`：启动、验证与停止步骤。
- ReAct API、模型 API SSE 响应、ReAct SQL 工具和 Ollama 适配器源码以只读 bind mount 提供给 DB-GPT 容器，便于本机修复后重启验证，无需每次重建镜像。
- 数据库和模型文件只放 Docker named volumes，不提交到 Git。

## 启动

从仓库根目录执行：

```bash
bash docker/base/build_image.sh \
  --install-mode openai \
  --extras 'base,proxy_openai,proxy_ollama,storage_chromadb,datasource_postgres' \
  --dockerfile Dockerfile.test \
  --image-name dbgpt-develop-me-test \
  --use-tsinghua-ubuntu false

docker compose -p dbgpt-develop-me-test \
  -f docker/compose_examples/develop-me-test/compose.yaml \
  --profile seed run --rm fixture-seed

docker compose -p dbgpt-develop-me-test \
  -f docker/compose_examples/develop-me-test/compose.yaml up -d
```

首次启动会下载 Ollama 的 `qwen3:1.7b` 和 `qwen3-embedding:0.6b`。聊天模型使用较轻量的 1.7B 版本。测试中 `qwen3:4b` 在当前 CPU-only Docker VM 上执行原题约 12 分钟仍未返回结构化结果，因此不作为默认模型；已下载的 4B 模型保留在现有 Ollama volume 中，没有删除。Web UI 地址为 <http://127.0.0.1:5671>。DB-GPT 连接数据源时，可将已挂载的 fixture 登记为 SQLite 数据源，路径是 `/data/ecommerce.sqlite`。演示 datasource 名称使用 `ecommerce-demo`，与 ReAct 业务字典配置对应。

当前配置使用 DB-GPT 的本地开发身份，服务只绑定 `127.0.0.1`。本 Compose 显式允许该身份操作 `ecommerce-demo`，并把它绑定到只读挂载的 `/data/ecommerce.sqlite` 和固定 `tenant-a` 范围；该本地例外只用于合成数据演示，允许本地 admin 审批这一个固定数据源且照常写入审批审计，不是 OIDC，也不得复制到共享或生产环境。其他数据源仍走原来的双人审批和 OIDC/JWT 权限校验。该环境不证明生产租户隔离、数据库 grants/RLS 或企业 IdP 集成。敏感数据和正式凭据不得导入此环境。

### 可选：本机 Trace 收集

默认测试栈不启用外部 trace 收集。需要在本机查看 DB-GPT trace 时，增加 overlay 并启用 `telemetry` profile：

```bash
docker compose -p dbgpt-develop-me-test \
  -f docker/compose_examples/develop-me-test/compose.yaml \
  -f docker/compose_examples/develop-me-test/compose.telemetry.yaml \
  --profile telemetry up -d
```

Jaeger UI 地址为 <http://127.0.0.1:16687>。overlay 将 DB-GPT OTLP/gRPC exporter 指向同一 Compose 网络内的 Jaeger；停止时也使用相同两个 `-f` 参数和 `down`。此配置只用于本机合成数据调试，Jaeger 使用内存存储，容器停止后 trace 会清除；它不代表 OpenObserve、持久化、认证、TLS 或生产留存验收。当前 ReAct SQL span 记录查询哈希和执行元数据，但部分 Agent 框架 span 可能包含模型输入/输出；启用前只连接合成数据，不要用于真实或敏感数据。

首次使用前，在 DB-GPT「数据源」页面登记 SQLite 数据源：名称 `ecommerce-demo`、文件路径 `/data/ecommerce.sqlite`。然后使用本地演示审批 API 批准该固定数据源：

```bash
curl -X POST http://127.0.0.1:5671/api/v1/chat/db/ecommerce-demo/approval \
  -H 'Content-Type: application/json' \
  -d '{"decision":"approve","reason":"Local synthetic demo only"}'
```

批准后刷新页面，在数据源选择器中选中 `ecommerce-demo`，即可提问，例如“统计 2026 年第二季度各地区已完成订单的销售额，按销售额从高到低排序”。

需要测量真实 Agent 的合成数据结果时，在仓库根目录运行 50 题金标准评测：

```bash
DBGPT_EVAL_ACCESS_TOKEN=local-demo-only-not-a-credential \
DBGPT_AGENT_API_URL=http://127.0.0.1:5671 \
DBGPT_AGENT_DATABASE=ecommerce-demo \
python3 examples/enterprise-text2sql/evaluate_agent.py --timeout 120
```

此 Compose 未启用 OIDC，服务使用仅限本机合成数据的 DB-GPT 开发身份；占位值只用于满足评测 CLI 的非空参数检查，不能当作真实 access token 使用。评测报告只包含题目 ID、状态和结果哈希。

`Dockerfile.test` 是本地测试专用单阶段镜像，避免在磁盘空间有限的 Docker Desktop 中复制整套虚拟环境。正式构建仍使用默认 Dockerfile。

## 验证与停止

```bash
docker compose -p dbgpt-develop-me-test \
  -f docker/compose_examples/develop-me-test/compose.yaml ps

docker compose -p dbgpt-develop-me-test \
  -f docker/compose_examples/develop-me-test/compose.yaml logs --tail=100 dbgpt

docker compose -p dbgpt-develop-me-test \
  -f docker/compose_examples/develop-me-test/compose.yaml down
```

`down` 保留 named volumes，便于下次继续使用本机模型和 DB-GPT 元数据。

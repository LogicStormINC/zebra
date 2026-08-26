# Zebra × Trench 对接差距清单（P0 契约核对结果）

- 日期：2026-08-26
- 核对基线：Zebra `cloud-agent-trench@7a15fbca` × Trench `84e9946`
- 方法：逐项比对 `trench_ai_zebra_client.py` / `trench_ai_zebra_contract.py` /
  `trench_ai_zebra_event_map.py` 与 Zebra `task_routes.py` / `task_api.py` /
  `ag_ui_command.py` / `ag_ui_stream.py` / `host_auth.py` /
  `agent_security/host_grant.py` / `agent_storage/postgres/host_auth.py`

## 一、契约契合项（无需改动）

| # | 项 | 结论 |
|---|-----|------|
| C1 | `POST /tasks` | 契合。Trench 发 `{execute:false, network_profile:"none", policy_profile:"read_only", prompt, title, tool_profile:"general", workspace:"."}` + `Idempotency-Key`；Zebra 返回 200/201 `{task_id: <uuid>}`，与客户端 UUID 校验一致 |
| C2 | `GET /tasks/{id}` | 契合。返回 `{current_sequence: int}`，Zebra 另附 `task_id/session_id/status` 等字段，客户端只取所需 |
| C3 | `POST /agui/commands` | 契合。Zebra 返回 200/202 `{status:"accepted"\|"duplicate"}`；revision 冲突 409（客户端视为 `command_rejected`） |
| C4 | `GET /agui/threads/{uuid}/runs/{run}/stream` | 契合。路径解析要求 thread 为 UUID（=task_id）、runId 有界，与客户端 URL 构造一致 |
| C5 | SSE 事件集 | 兼容。Trench 映射 RUN_STARTED / TEXT_MESSAGE_CONTENT / TOOL_CALL_START / TOOL_CALL_RESULT / RUN_FINISHED / RUN_ERROR；Zebra 另发 TOOL_CALL_ARGS / STATE_SNAPSHOT / MESSAGES_SNAPSHOT，Trench 对未映射事件返回 None 安全忽略。ADR-026 引入的 `zebra_turn_failed` 错误码走通用 RUN_ERROR 路径，无破坏 |
| C6 | 模型网关 | 就绪。`configs/default.env` 默认 DeepSeek（flash executor / pro planner / reviewer profiles），`.env.local` 已有 `DEEPSEEK_API_KEY` |
| C7 | Host 注册表存储 | 就绪。PostgreSQL `upsert_registry / get_registry / list_registries / consume_grant / record_rejection / list_audit` 全套 API（`agent_storage/postgres/host_auth.py`） |

Grant 交换协议本体（两侧一致的消费方协议）：`POST {exchange_url}`，
Cookie 头 + `{audience:"zebra", runId, scopes:[agent.run+5 读 scope], threadId}`，
期望 2xx `{grant:"<jwt>"}`（≤8KB、无换行）。Zebra 验证侧要求 RS256/ES256、
`iss`/`aud` 与注册表绑定、`jwks_uri` 可解析、`jti` 单次消费、
`allowed_origins` 精确匹配（见 `HostGrantVerificationConfig`）。

## 二、差距项（需建设）

| # | 差距 | 影响 | 处置（本分支） |
|---|------|------|----------------|
| G1 | **Grant Exchange 签发服务不存在**——两侧代码库均无实现（Trench 原 Next.js BFF 内的 exchange 已随 CopilotKit 清场删除；Zebra 只做验证+消费） | 全链路无法建立；E2E 场景全部受阻 | 新建 `apps/host_grant_broker`：小 FastAPI 服务，`POST /exchange` 转发 Cookie 调 Trench `/api/trench-ai/auth/me` 验证会话后签发 RS256 JWT（iss/aud/jti/scopes/threadId/runId/短 TTL），`GET /.well-known/jwks.json` 发布公钥；密钥经环境注入 |
| G2 | **Host 注册无 operator 入口**——`upsert_registry` 仅测试调用，无 admin 路由/CLI | P1 无法登记 Trench issuer | 新建注册脚本（one-shot，直连 Zebra PostgreSQL upsert），参数：namespace、host_app_id、issuer、audience、jwks_uri、allowed_origins |
| G3 | **Trench business snapshot 视图不存在**（`TRENCH_E2E_BUSINESS_SNAPSHOT_URL`） | E2E `zero_writes` 场景受阻 | 验收环境 sidecar：只读连接 Trench PG，输出 `{"schema_version":"trench.business-snapshot.v1","tables":{...count/digest}}`；不进 Trench 产品代码 |
| G4 | **Zebra worker restart hook 不存在**（`ZEBRA_E2E_WORKER_RESTART_URL`） | E2E `worker_restart` 场景受阻 | 验收环境 sidecar：受共享密钥保护的 POST 端点，触发 worker 容器重启（docker socket 受限挂载）；不进 Zebra 产品 API |
| G5 | **HTTPS 硬性强制且无 localhost 豁免**——`_https_origin` 校验 issuer/jwks/origins 必须 https，Trench `ZEBRA_BFF_REQUIRE_HTTPS` 默认 true | 本地联调被阻 | 验收 compose 内置 TLS 终止（自签内部 CA + 本地域名，如 `zebra.local`/`trench.local`），CA 证书注入两侧信任链；豁免开关不使用 |

## 三、环境事实

- 本机 Docker 可用；Trench 本地依赖栈已在运行（`trench-postgres` up）。
- Trench 工作区存在 517 个未提交删除（OpenHarness/CopilotKit 清场），
  对接以 `84e9946` 提交内容为准；联调前建议 Trench 侧先提交清场。
- Trench 本地 `.env` 的 `ZEBRA_*` 全空（待 P2 填入）。

## 四、结论

五项差距全部属于**部署与验收基础设施**，不涉及两侧产品契约修改；
按 §二 处置列在本分支（`cloud-agent-trench`）建设后，P1 冒烟与 P3 E2E
即可执行。差距处置实现随阶段提交并回链本清单。

## 五、处置进展（2026-08-26，TRN-LINK-DEPLOY-01）

| 差距 | 状态 | 实现 |
|------|------|------|
| G1 Grant Broker | 已实现 | `apps/host_grant_broker`（exchange/JWKS/密钥生成）；测试用真实 `agent_security` 验证器闭环验证；本地进程冒烟三端点通过（含 fail-closed） |
| G2 注册入口 | 已实现 | `scripts/register_trench_host.py`；已对带 host authority 表的真实 PostgreSQL 冒烟成功 |
| G3 业务快照视图 | 已实现 | `tests/compose/trench_read_e2e/operator_sidecar.py` `GET /business-snapshot`（count+digest，`trench.business-snapshot.v1`） |
| G4 Worker 重启 hook | 已实现 | 同 sidecar `POST /worker-restart`（operator token + Docker Engine API over unix socket，仅接受 taskId/runId） |
| G5 本地 TLS | 已实现 | `docker/trench-acceptance/bootstrap.sh`（本地 CA + `*.zebra.local` 通配证书 + broker 密钥对）+ `docker/compose.trench-acceptance.yml`（broker/sidecar/caddy，已通过 `docker compose config` 校验） |

剩余环境依赖项（非代码缺口）：应用镜像构建与完整栈拉起、Trench 侧
`.env` 填值与 Trench 清场提交、`EMB-TRN-READ-E2E-01` 的 16 项真实输入。


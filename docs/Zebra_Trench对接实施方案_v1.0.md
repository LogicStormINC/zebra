# Zebra × Trench 对接实施方案 v1.0

- 分支：`cloud-agent-trench`（基于 `cloud-agent@a0cc2571`）
- 日期：2026-08-26
- 状态：提案（待 maintainer 批准后按阶段开工）
- 对接对象：Trench 仓库 `84e9946`（`merge: integrate Zebra Cloud Agent Trench stack`）

## 1. 项目背景

Zebra Agent 的产品定位是**云端 Agent 运行时服务**（控制面 + 无状态 Worker +
沙箱舰队），由业务系统通过签名授权消费；本地形态只是开发与回归基线。
Trench（金融认知基础设施）是第一个真实 Host Application 与验收环境。

两侧的对接工作已经各自推进到"临门一脚"：

- **Trench 侧（已提交）**：`/api/trench-ai/chat` 与 `/chat/stream` 的产品
  对话已委托 `ZebraStrategyRuntime`（未配置 fail-closed）；BFF 客户端实现了
  ensure task → 读 revision → 提交 AG-UI command → 换取一次性 Host Grant →
  SSE 流的完整链路；为 Zebra 回调暴露 5 个有界只读 Tool（HMAC 工作负载签名）。
  本地 `.env` 的 7 个 `ZEBRA_*` 变量全部为空，从未连过真实 Zebra。
- **Zebra 侧（cloud-agent 分支）**：AG-UI command/stream 端点、Host Grant
  授权与消费、Worker 侧 Host Tool Gateway 接线（`EMB-HOST-RUNTIME-01`）、
  跨服务验收 runner 与 16 项部署输入清单（`EMB-TRN-READ-E2E-01`，
  `tests/compose/trench_read_e2e/`）均已就绪；runner 在真实输入缺失时输出
  `blocked`，不伪造通过。

**缺口不在代码契约，而在"把真实的 Zebra 云端部署跑起来、把 Trench 的配置
指过来、按清单完成跨服务验收"**。本方案定义这一过程的目标、阶段、边界与
验收标准。全部工作落在 Zebra 仓库 `cloud-agent-trench` 分支；Trench 仓库
只做配置与验收配合，不改产品代码。

## 2. 术语解释

| 术语 | 含义 |
|------|------|
| Host / 宿主系统 | 消费 Zebra 的业务系统。本对接中 Host = Trench |
| Host Grant | 一次性、短时效、带 scope 的授权令牌（audience=zebra）。Trench BFF 用用户会话 Cookie 向 Zebra 换取，再以 Bearer 建立 SSE 流；单次使用，重放被拒 |
| Grant Exchange | Trench Cookie → Host Grant 的交换端点（`ZEBRA_HOST_GRANT_EXCHANGE_URL`，无默认值，必须显式配置） |
| AG-UI | Zebra 对外暴露的 Agent 交互协议（command 提交 + thread/run SSE 流），事件集含 `RUN_STARTED` / `TEXT_MESSAGE_CONTENT` / `TOOL_CALL_*` / `RUN_FINISHED` / `RUN_ERROR` |
| BFF | Backend-for-Frontend。Trench API 充当浏览器与 Zebra 之间的代理与授权边界，浏览器永不直连 Zebra |
| 只读 Tool | Zebra 回调 Trench 拉取业务数据的有界接口：`events.get_event` / `get_evidence` / `get_related_events` / `get_entity_timeline` / `get_topic` |
| 工作负载签名 | Zebra 回调 Trench 时的服务间认证：`x-zebra-workload-identity` 头 + `TRENCH_AI_HOST_TOOL_SHARED_SECRET` HMAC |
| opaque namespace | Trench 在 Zebra 侧的隔离命名空间，Zebra 不理解其内部语义 |
| policy/tool profile | 任务执行画像。Trench 固定提交 `policy_profile: read_only`、`tool_profile: general` |
| durable cursor / replay | SSE 断线后凭持久游标重连补齐事件的机制 |
| E2E runner | `tests/compose/trench_read_e2e/run_acceptance.py`，按 `runner_manifest.json` 的 9 个场景执行验收，输出证据文件 |
| 16 项部署输入 | manifest `required_environment` 列出的 16 个验收环境变量（Trench 侧 9 个、Zebra 侧 6 个、共享 1 个 session cookie） |

## 3. 业务边界

**归属划分（沿用两侧已有决策，本方案不改变）：**

| 关注点 | 归属 |
|--------|------|
| 用户身份、登录、会话、订阅计费 | Trench |
| Agent 执行、事件持久化、策略/工具裁决、沙箱 | Zebra |
| 聊天 UI、报告、分享 | Trench（策略工作台） |
| 模型选择与调用 | Zebra（Trench 不指定供应商） |
| 业务数据（events/capsules/行情） | Trench，Zebra 仅经只读 Tool 按范围读取 |

**硬性约束（违反即验收失败）：**

1. 浏览器不得直连 Zebra；一切流量经 Trench BFF。
2. Trench 的用户 Cookie/Authorization 不透传给 Zebra；只传换取的一次性
   Host Grant。
3. Host Grant 单次使用；重放必须被 Zebra 拒绝（E2E 场景 7）。
4. v1 只有只读 Tool，无写回 Trench 的能力。
5. 不引入第二套用户身份体系；Zebra 不感知 Trench 用户明细，只见 opaque
   namespace + grant scope。
6. Zebra 缺失/故障时 Trench 产品面 fail-closed（503/502），不回落本地
   Agent runtime。
7. 所有只读场景前后，Trench 业务数据快照必须不变（E2E 场景 9）。

## 4. 开发阶段

### P0 契约核对与差距冻结（0.5～1 天）

**目标**：在写任何部署脚本之前，逐项核对 Trench 客户端契约与 Zebra 现有
实现是否完全咬合，产出冻结的差距清单。

核对项（按 `trench_ai_zebra_contract.py` 与 `trench_ai_zebra_client.py`）：

- [ ] `POST {tasks_url}`（默认 `/tasks`）的请求/响应体、幂等 key 语义
- [ ] `POST {command_url}`（默认 `/agui/commands`）的 command payload
      （`policy_profile: read_only`、`tool_profile: general`、AG-UI mount）
- [ ] `GET {stream}/agui/threads/{task}/runs/{run}/stream` 路径与事件集，
      特别是 ADR-026 合入后 SSE 事件集是否新增了 Trench event map
      （`trench_ai_zebra_event_map.py`）未覆盖的事件类型
- [ ] Grant exchange：Trench 发送的 Cookie 形态、Zebra 侧
      `build_postgres_host_grant_authorizer` 期望的请求格式、scope 命名
      （`agent.run + event.read/evidence.read/entity.read/topic.read`）
- [ ] Zebra 侧 Host 注册表如何登记 Trench（allowlist、namespace、
      workload identity 密钥的分发方式）
- [ ] Trench `ZEBRA_BFF_REQUIRE_HTTPS`（默认开）与本地开发环境的 TLS 方案
- [ ] 16 项部署输入中两侧尚不存在的 operator 能力：
      `TRENCH_E2E_BUSINESS_SNAPSHOT_URL`（Trench 只读快照视图）、
      `ZEBRA_E2E_WORKER_RESTART_URL`（受保护的 Worker 重启 hook）

**产出**：`docs/Zebra_Trench对接差距清单.md`（逐项 契合/差距/修复卡）。

### P1 Zebra 云端单机部署（2～3 天）

**目标**：用仓库自带 compose 在验收机上跑起完整的 Zebra 云端栈，并完成
Trench 作为 Host 的注册，使一条人工 curl 链路可以走通
command → grant → stream。

内容：

1. `docker/compose.dependencies.yml`（PostgreSQL 17 / Redis / MinIO）+
   `compose.application.yml`（API + Worker + platform bundle）在独立验收机
   上拉起；确认 alembic 迁移与健康检查。
2. 模型网关配置：为 `read_only` 画像选择并配置模型 profile（候选：
   DeepSeek Flash/Pro，已具备 fail-closed 能力校验）。
3. Trench Host 注册：namespace、allowlist、Grant 签发密钥、workload
   identity HMAC 密钥的生成与登记（方式按 P0 核对结论：配置注入或迁移）。
4. TLS：内部 CA 或反代终止 TLS，满足 `REQUIRE_HTTPS`；开发机若豁免必须
   显式设置开关并在验收环境关闭豁免。
5. 人工冒烟脚本：以测试 Cookie 换 Grant → 提交 command → 读 SSE 到终态。

**验收**：见 §6 P1。

### P2 Trench BFF 接线与联调（2～3 天）

**目标**：Trench 本地/预发环境填入 7 个 `ZEBRA_*` 变量，策略工作台的
真实聊天流量第一次由 Zebra 产生；只读 Tool 回调链路验证。

内容：

1. Trench `.env` 填入 P1 部署的端点（agui/command/stream/tasks/grant）。
2. `TRENCH_AI_STRATEGY_RUNTIME=zebra` 后验证策略工作台：
   发问 → BFF → Zebra → SSE 增量渲染（ThoughtChain/过程事件）→ 终态。
3. 验证 Zebra 经 workload 签名调用 5 个只读 Tool，确认按用户/工作区/
   订阅 scope 过滤（用两个不同订阅的测试账号对照）。
4. fail-closed 演练：停掉 Zebra，确认 Trench 返回 503/502 而非回落。
5. 错误传播核对：Zebra `RUN_ERROR`、Tool 超时、Grant 过期在 Trench UI
   的呈现。

**验收**：见 §6 P2。本阶段不改 Trench 产品代码；发现 Trench 侧缺陷时
只登记问题单交 Trench 维护方（其工作区当前有 517 个未提交删除，正处于
OpenHarness 清场中，需先协调提交）。

### P3 跨服务验收执行（EMB-TRN-READ-E2E-01，2～4 天）

**目标**：在隔离验收环境注入 16 项部署输入，跑通 runner 全部 9 个场景，
产出合格证据，任务卡从 Locked → Done。

内容：

1. 补齐 P0 清单中缺失的 operator 能力（Trench 快照视图、Zebra Worker
   重启 hook；均为只读/受保护的运维端点）。
2. 隔离环境部署两侧，注入 manifest 全部 16 项变量；`TRENCH_E2E_SESSION_
   COOKIE` 只发给 Trench/BFF 与 Grant exchange。
3. `uv run python tests/compose/trench_read_e2e/run_acceptance.py`，
   9 场景（infrastructure / read_task / long_task / disconnect_replay /
   worker_restart / stop_resume / grant_replay / host_tool_failure /
   zero_writes）全部 `PASS`。
4. 证据归档到 `ZEBRA_TRENCH_READ_E2E_EVIDENCE_DIR`（只含场景状态、错误码、
   快照摘要，不含 Cookie/Grant/DSN/响应正文）。

**验收**：见 §6 P3。

### P4 生产切换与收口（2～3 天，依赖 P3 证据）

**目标**：生产环境接线、灰度切换、运行手册与回滚路径落地。

内容：

1. 生产 compose（Trench 侧 `docker/compose.prod.yml` 已约定只有 trench-api
   持有 Zebra/Host auth 配置，worker 不注入——沿用）。
2. `TRENCH_AI_STRATEGY_RUNTIME=zebra` 生产切换（灰度：先内部账号）。
3. 运行手册：健康巡检、Grant 密钥轮换、Worker 重启、事件回放、回滚到
   fail-closed（清空 `ZEBRA_AGUI_URL` 即回滚）。
4. 两侧文档收口：Trench `tasks/todo.md` 相关卡置 Done；Zebra
   `PROGRESS.md` / `AGENT_TASKS.md` 更新，F6/F7 Trench cutover chain
   解锁。

## 5. 阶段边界（各阶段明确不做的事）

| 阶段 | 不做 |
|------|------|
| P0 | 不改任何产品代码，不部署 |
| P1 | 不接 Trench；不做生产部署；不开启对外公网暴露（仅验收网段） |
| P2 | 不改 Trench 产品代码；不删 Trench 遗留 harness 代码（其清场由 Trench 侧自行收口）；不做性能压测 |
| P3 | 不用 mock/静态测试替代真实输入；缺输入只能 `blocked`；不做生产切换 |
| P4 | 不上线写 Tool；不做多区域/K8s；不引入 MCP 或第二期工具协议 |

全局不做（本期整个对接的非目标）：写回 Trench 的 Tool、浏览器直连 Zebra、
本地 Agent runtime fallback、第二身份体系、向量 RAG（Trench DECISIONS 已
排除）、CopilotKit 前端复活（Trench 已删除该方案，产品入口是策略工作台）。

## 6. 验收标准

**P1（部署就绪）**

- 依赖栈与应用栈容器全部 healthy；`/api/health` 绿。
- 人工冒烟：换 Grant → 提交 command → SSE 收到 `RUN_STARTED…RUN_FINISHED`
  完整序列；Grant 二次使用被拒。
- Trench Host 注册记录可在 Zebra 侧查询；workload 签名密钥两侧一致。

**P2（链路联通）**

- 策略工作台一次真实对话由 Zebra 完成：增量渲染、终态落库、刷新后可回放。
- 5 个只读 Tool 各至少一次真实回调成功，且按 scope 过滤正确。
- 停 Zebra → Trench 503/502，无本地回落；重启后自动恢复。

**P3（EMB-TRN-READ-E2E-01 达成）**

- runner 9 场景全 `PASS`，`result.json` 归档；任一场景失败即阶段不通过。
- 特别断言：grant_replay 被拒、zero_writes 快照摘要前后一致、
  disconnect_replay 用 durable cursor 补齐无丢失。

**P4（生产收口）**

- 生产灰度账号 72 小时无 P0/P1 故障；回滚演练一次成功。
- 两侧任务卡与进度文档全部更新；运行手册评审通过。

## 7. 风险

| # | 风险 | 影响 | 缓解 |
|---|------|------|------|
| R1 | 契约漂移：Trench 客户端按 08-23 契约编写，Zebra 此后合入 ADR-026（Turn 生命周期）等，事件集/语义可能演化 | SSE 事件无法映射或会话状态错乱 | P0 逐事件核对 event map；不一致处列差距卡修复，两侧同步 |
| R2 | Grant exchange 端点无默认值且涉及 Cookie 转发语义，最可能出现理解偏差 | 全链路无法建立 | P0 单独核对；P1 冒烟先以最小 curl 验证交换 |
| R3 | 16 项输入中 2 个 operator 能力（业务快照视图、Worker 重启 hook）可能两侧都未实现 | P3 无法执行 | P0 确认；缺失则在本分支以受保护运维端点补齐（只读/最小权限） |
| R4 | 本地开发 HTTPS 强制与 `REQUIRE_HTTPS` 默认值冲突 | 联调阻塞 | 统一内部 CA/反代 TLS；豁免开关仅限开发机并留痕 |
| R5 | 模型网关未配置或 profile 校验失败 → Worker 无法推理 | P2 阻塞 | P1 显式配置并验证 fail-closed 报错可见 |
| R6 | Trench 工作区 517 个未提交删除（清场中） | 联调基线不稳定 | P2 前要求 Trench 侧先提交清场；以提交后的 commit 为对接基线 |
| R7 | 长任务 vs BFF 5s 默认超时（`ZEBRA_BFF_TIMEOUT_MS`） | 长对话断流 | 核对该超时仅作用于建立阶段还是全程；必要时调大并验证 keepalive |
| R8 | 验收环境资源（两套 PG/Redis/对象存储 + Worker 沙箱） | 环境不可得 | 单机 compose 复用仓库既有编排；沙箱用 rootless OCI 档 |
| R9 | 密钥管理：Grant 签发与 HMAC 密钥在两仓间分发 | 泄露或轮换断裂 | 密钥只经部署环境注入，不入库不入日志；P4 手册含轮换步骤 |

## 8. 兼容性

1. **本地 Zebra（SQLite/Desktop/CLI）零影响**：全部工作在云端 profile，
   本地行为不变（仓库不变式）。
2. **platform-web 控制台零影响**：本分支已有的前端工作不受接线影响，
   且后续可用于运维视角观察 Trench 任务。
3. **Trench 遗留链路**：`/api/harness/*` 与 Capsule LLM 属 Trench 自有
   遗留，本对接不触碰；其 OpenHarness 清场与本期无关。
4. **协议版本**：AG-UI 事件集、只读 Tool 契约、Grant scope 命名以 P0
   冻结清单为准；此后 Zebra 侧任何破坏性变更需在 `docs/` 记录并同步
   Trench（Trench 客户端无版本协商机制，靠人工同步）。
5. **客户端集成面（CLIENT-*）**：cloud-agent 上已合入的 Client
   Integration Plane 与本对接正交；Trench 走 Host BFF 模式，不经
   Browser Client 模式，两者互不依赖。

## 9. 后续设计（本期不做，仅记录方向）

1. **写回能力**：Trench 作为 Host 的受控写 Tool（仍经签名授权与审批），
   依赖 Client Effect/审批面成熟后评估。
2. **Browser Client 模式**：若 Trench 未来需要前端直接消费 Zebra 的
   Generative UI/Client Effects，可评估走已合入的 Client Integration
   Plane（Frontend Capability Profiles），替代纯 BFF 代理。
3. **MCP 标准工具接口**：Trench 方案文档已把 MCP 列为二期可选；届时评估
   只读 Tool 是否迁移到 MCP 声明式清单。
4. **分析与执行 Worker**：DuckDB/Polars 分析型 Worker、交易系统消费
   状态层（Trench 战略文档 12 步路线图内容）。
5. **多 Host 复用**：以 Trench 验收经验沉淀 Host 接入 runbook 与注册
   流程模板，支撑第二个业务系统接入。
6. **Host Scoped Memory**：按 Host 隔离的 Agent 记忆（Trench 路线图项），
   需先在 Zebra 侧完成 memory 命名空间与 Host 绑定设计。

## 10. 里程碑与任务映射

| 阶段 | 对应任务卡 | 状态 |
|------|-----------|------|
| P0 | 新增 `TRN-LINK-CONTRACT-01`（本方案批准后登记） | 待登记 |
| P1 | 新增 `TRN-LINK-DEPLOY-01` | 待登记 |
| P2 | 新增 `TRN-LINK-BFF-01` | 待登记 |
| P3 | `EMB-TRN-READ-E2E-01`（已存在，Locked） | 执行 |
| P4 | `TRN-DEPLOY-01`（Trench 侧，Review）+ Zebra 侧收口卡 | 协同 |

所有 Zebra 侧工作单分支推进（`cloud-agent-trench`），按阶段小 PR 合回
`cloud-agent`；`main` 暂不维护，维持现状。

# CLOUD Lease、Fencing 与 Effect Delivery 联合验收记录 v1.0

## 1. 结论

`CLOUD-LEASE-01` 的微服务范围联合验收通过，可以进入 Review。

本结论证明：同一部署命名空间内，Session Lease、Event/Effect mutation、Outbox
发现与 Worker consumer 使用一致的 epoch/token/owner fence；过期执行不会自动重放
不确定外部 Effect。它不证明 exactly-once 外部执行，也不代表生产切换完成。

## 2. 验收基线

- 业务分支：隔离本地 `zebra-cloud-trench@2759345c`
- PostgreSQL：Docker Compose `postgres:17.5`
- 依赖层：`docker/compose.dependencies.yml`
- Zebra 应用容器：不在本卡范围
- Desktop：不在微服务主线范围

## 3. 组合证据

| 边界 | 真实服务证据 | 覆盖重点 |
| --- | ---: | --- |
| PostgreSQL Event/Projection + Lease | `34/34` | migration、epoch、restore、数据库时钟、并发 acquire、heartbeat、takeover、namespace |
| Fenced Effect/Outbox | `49/49` | 原子 schedule/terminal、SKIP LOCKED、fault rollback、stale fence、reconcile/retry、response loss |
| Worker consumer 联合矩阵 | `58/58` | 上述 PostgreSQL 文件 + Effect Guard + heartbeat、crash、uncertain、no-auto-replay |
| 微服务后端回归 | `1851 passed, 60 skipped` | Core、API、Worker、Storage、Integrations、Security；排除 Desktop 聚合门禁 |
| 微服务文件门禁 | `901` files | `apps/`、`packages/`、tests、scripts 与云端配置；排除 `UI/` |
| Release Eval | `10/10` | release gate score `1.00` |

宿主联合矩阵通过后，专用 PostgreSQL container、volume 与 network 均由 Compose
清理。测试日志明确输出 `ZEBRA_EFFECT_CONSUMER_POSTGRES_TEST_RESULT=PASS`。

## 4. 已验证语义

1. Lease acquire 先于 recovery；heartbeat 使用独立连接并传播失租。
2. epoch、token、owner 与 deployment namespace 共同构成写入 fence。
3. Event/Effect/Outbox schedule 与 terminal mutation 在 PostgreSQL 事务中校验 fence。
4. Outbox 使用 `SKIP LOCKED` 支持并发发现；idempotency key 冲突不会静默覆盖。
5. provider 成功而 terminal commit 未确认时进入 `uncertain`，不得自动重放。
6. terminal response 丢失时读取 durable terminal result，不重复调用 provider。
7. restore epoch 旋转后，旧 epoch claim、heartbeat、release 与 terminal write 均失败。
8. durable cancellation 赢得 finalization 竞争时保持 `CANCELLED`，不覆写为失败。

## 5. 明确不保证

- 不保证 exactly-once 外部执行；外部 provider 必须支持 operation/idempotency key。
- 不证明所有 Worker-owned aggregate 已完成 PostgreSQL fencing。
- 不包含 Redis live、Kafka/broker、Kubernetes、生产数据库角色或密钥轮换。
- 不包含运行时 backend selector、SQLite 到 PostgreSQL cutover 或生产流量。
- 不包含 Desktop、本地 Agent UI 或 Tauri 构建。

## 6. 后续门禁

`CLOUD-AGG-FENCE-01` 继续保持 Locked。激活前必须先盘点 Context lifecycle、
handoff/dispatch、Workspace/Task、Model/Tool run、provider continuation/history、
Artifact 与 delivery audit 的 PostgreSQL authority；再拆成 path-bounded cards。

在该门禁完成前，项目只能声明 Lease + Event/Effect delivery 闭环，不能声明完整
multi-Worker aggregate safety 或 private-cloud production readiness。

# ADR-023：Stateless Command 与 Revision 合同

状态：Accepted（`CLOUD-COMMAND-API-CON-01`）

## 决策

API/cloud 请求只提交一个 `SessionCommand` 意图，不在请求进程内创建
Harness、Runtime 或执行线程。命令包含：

- `session_id`、`command_id` 与受限的 `kind`（`run`、`resume`、`message`、
  `stop`、`cancel`、`suspend`）；
- `expected_revision`，对应 session Event stream 的当前 sequence；
- 必填且有长度上限的 `idempotency_key`；
- 可 JSON 序列化且有 64 KiB 上限的 provider-neutral payload。

被接受的命令以 `session_command_accepted` durable Event 表示，Worker 后续
消费该 intent 并产生真正的 session/runtime 事件。这个契约不把某个 provider、
HTTP 框架或 Runtime 能力带入 `agent-core`。

## Admission 语义

Admission 顺序固定为：

1. 已知 idempotency key 且 fingerprint 相同：`duplicate`，即使当前 revision
   已经前进也只返回原命令结果；
2. 已知 key 但 fingerprint 不同：`idempotency_conflict`；
3. 无已知 key 且 `expected_revision != current_revision`：`revision_conflict`；
4. 其余情况：`accepted`，并生成 `session_command_accepted` intent。

fingerprint 排除随机 `command_id`，但包含 session、kind、expected revision
和 payload，从而重试可以稳定去重、修改意图不能复用旧 key。

## 边界

- 这个 ADR 只冻结 core contract 与 deterministic admission；API route、
  Worker wake-up、跨进程控制和 PostgreSQL transaction 属于后续任务。
- local `execute=true` 兼容路径仍由现有 API 保持，不能被误认为 cloud
  command contract 已经激活。
- Event append、projection update 和 idempotency record 的原子组合由后续
  command-run 实现负责；本合同不声称已经完成生产部署。

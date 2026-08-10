# ADR-024：Event 提交后实时发布合同

状态：Accepted（`CLOUD-LIVE-WIRE-CON-01`）

## 决策

Session Event 仍由 SQLite/PostgreSQL append-only store 作为唯一事实源。实时
发布是提交成功后的 best-effort 传输，不得成为第二套状态源：

1. 先完成 canonical Event 的 durable append/commit；append 抛错时绝不 publish。
2. 只有 append 返回的 canonical Event 才允许交给 publisher；幂等重试返回同一
   Event 时可以再次 publish，consumer 必须按 `event_id`/durable sequence 去重。
3. publisher 失败不回滚已经提交的 Event，也不把 API/Worker 的业务操作改成失败；
   客户端通过 durable replay 收敛，失败应由 adapter 的 metrics/logging 观测。
4. SSE/Redis 使用 replay barrier：先 capture live cursor，再从 durable store 回放；
   live tail 仅接收 barrier 之后且 `sequence > durable_sequence` 的事件。Redis
   丢失或截断时必须重新 durable replay，不能声称“无事件”。

`PostCommitPublishingEventStore` 实现上述 direct `EventStorePort.append` 边界。
它不捕获 `BaseException`，也不吞掉 durable append 错误。

## PostgreSQL 事务边界

PostgreSQL 的 `append_event_in_transaction(...)`、Workspace/Context/Handoff/Effect
等 aggregate transaction 直接使用同一 connection。它们不能在事务尚未 commit
时向 Redis 发布，否则 rollback 后会出现幽灵 live event。本 ADR 只冻结提交后
发布语义；`CLOUD-LIVE-PUBLISH-01` 必须在共享 transaction/outbox composition
上接入 commit-success hook，并覆盖这些 transaction seam。仅给某个 API caller
补 publish 不满足合同。

## 降级与验证

本地默认不启用 live publisher，仍走原有 SQLite。启用 live 时，发布重复是允许
的，顺序和事实以 durable Event stream 为准。Focused contract tests prove：

- durable append 失败不会 publish；
- publisher 失败不会隐藏已提交 Event；
- publisher 收到 append 返回的 canonical Event；
- idempotent retry 可重复 publish 且由 consumer 去重。

# CA-HA-03 D3 设计稿：事件写入路径批量化（不动代码评审稿）

2026-11-10；Owner lukeding；状态 **设计稿，待批准后实施**。
前置证据：docs/CA-HA-03_capacity_decision.md 2026-11-09/10 各节（D2 考古终局）。

## 1. 问题（实测）

`PostgresEventStore.append()`（packages/agent-storage/src/agent_storage/postgres/events.py:38）
**每个事件一次独立连接+事务**：

```
连接检出（set_config×2）→ BEGIN → 幂等键 SELECT（:285）→ session_streams CAS UPDATE
→ INSERT session_events（触发 5+ 触发器：覆盖记账×2、字节界、投影源元数据、…）
→ COMMIT
```

（命令唤醒 outbox+咨询锁仅作用于 SESSION_COMMAND_ACCEPTED 事件，每任务一次，
不构成每事件成本；每事件成本 = 连接检出 + BEGIN/COMMIT + 3 条语句 + 触发器。）

101.7 实测（3/s 负载、v127 后）：幂等查证 83/s ≈ **每事件追加 ~4 次查证**；
每任务 ~15 事件 ≈ **60+ 次 DB 交互**。这是 3/s 距离的最后 ~40%。

## 2. 观察：事件天然成簇

任务生命周期事件呈突发簇（101.7 事件流时间戳）：

| 簇 | 事件 | 现状 |
|---|---|---|
| 准入簇 | session_created / task_prepared / session_command_accepted / user_message_received | 准入事务内已同事务（原子面） |
| **收尾簇** | answer_committed / turn_completed / memory_extraction_completed / session_completed | **逐事件独立事务 ×4** |
| 回合中 | plan/model_response/answer 各自时点 | 逐事件（时点分散，暂不批） |

收尾簇是最大的可批目标（每任务 4-5 事件一次写）。

## 3. 设计

### 3.1 Port 扩展：`append_batch`

`EventStorePort` 增加可选方法（默认实现=循环调 `append`，SQLite/内存实现零改动）：

```python
def append_batch(self, events: Sequence[SessionEvent]) -> tuple[SessionEvent, ...]:
    """同会话、sequence 连续、时间不减的原子批；返回规范化事件。"""
```

前置校验（不满足即 ValueError，调用方回退逐个 append）：
- 全部同 session_id；sequence 严格连续（first..first+n-1）；
- created_at 单调不减；幂等键互不相同（或均 None）。

### 3.2 PostgreSQL 原生批实现（每批 5 条语句）

1. **批量幂等预检**（1 次）：
   `SELECT … FROM session_events WHERE deployment_namespace=%s AND idempotency_key = ANY(%s)`
   命中者走既有 `ensure_idempotent_event_retry` 路径（批内只允许全部未命中或全部
   命中且与请求等价；混合批拆两段）。
2. **跨度 CAS**（1 次，替代每事件一次）：
   首事件 sequence==0 时先 INSERT…ON CONFLICT DO NOTHING 建流；
   `UPDATE session_streams SET current_version=%last
    WHERE … AND current_version=%first-1 RETURNING 1`
   失败→按既有语义分类（重放/冲突），整批走重试路径。
3. **unnest 多行 INSERT**（1 次往返，行序保持，触发器逐行照常）：
   `INSERT INTO session_events SELECT * FROM unnest($1::text[],$2::uuid[],…)`
4. COMMIT 一次。
   （唤醒 outbox 仅在批内含 SESSION_COMMAND_ACCEPTED 时照常逐条插入——每任务
   至多一条，无需批量化；设计上批实现复用 append_event_in_transaction 的语义
   分支以避免分叉。）

### 3.3 采纳点（按实测收益排序）

1. `apps/worker/.../execution_finalization.py` 收尾簇 → `append_batch`
2. 会话引导簇（若未在准入事务内）
3. 回合中事件保持逐个（时点分散，收益小）

### 3.4 语义变化与不变量

- **原子性增强**：收尾簇从"逐事件提交（中途崩溃留半簇）"变为全有/全无。
  收尾路径本就是幂等重跑设计（`ensure_idempotent_event_retry`），全无时重跑
  整簇——需回归确认 finalize 重试对"簇内部分已存在"与"全不存在"两态等价。
- 逐事件不变量全部保持：exactly-once（唯一索引+预检）、流 CAS 语义、触发器
  行为、唤醒投递（提交后 outbox 行为真源）。

## 4. 验证计划

- 单元/契约：批校验负例（跨会话/断序/时间回退/键重复）、混合命中拆段、
  CAS 失败分类、触发器行序、SQLite 默认实现等价性。
- 真实 PG 回归：收尾幂等重跑（含"半簇存在"构造）、并发批 CAS 竞争、
  make test/check 全绿。
- 101.7 实测门槛：每任务 DB 交互 60+ → **≤35**；带产接受 1.32 → **≥1.8/s**；
  达标后安排 3/s 专用复验窗口。

## 5. 风险与回滚

- 风险：finalize 重试语义（3.4）；unnest 类型对齐（jsonb/枚举数组）；
  唤醒批量化漏醒（批内只留最后事件——需确认消费者按 scope 水位唤醒而非逐事件）。
- 回滚：`append_batch` 默认实现=逐个 append，调用方一处开关即可回退；
  不含 schema 迁移。

## 6. 工作量估计

Port+PG 实现+测试 ≈ 1 天；finalization 采纳+回归 ≈ 半天；101.7 验证+窗口 ≈ 半天。

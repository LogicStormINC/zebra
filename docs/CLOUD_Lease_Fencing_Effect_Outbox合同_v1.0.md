# CLOUD Lease、Fencing 与 Effect Outbox 合同 v1.0

状态：`Review`
任务：`CLOUD-LEASE-PLAN-01`
适用范围：Zebra 单 deployment namespace 的 PostgreSQL control plane
依赖：`CLOUD-PG-01` Event/Projection 合同、现有 `EffectLedgerPort` 与 handoff
aggregate transaction 范式

## 1. 目的

本文固定多 Worker 下的执行权、陈旧写入拒绝、外部副作用调度和崩溃恢复合同。
它把原 `CLOUD-LEASE-01` 拆成四个可独立评审的实现切片，避免一个任务同时修改
Core、PostgreSQL、Tool Gateway 与 Worker 生命周期。

本文不承诺 exactly-once external effect。系统保证的是：

1. 同一 Session 同一时刻只有一个有效 Lease；
2. 本任务覆盖的 Worker Event/Effect 写入在事务内校验同一份 fence；
3. Effect intent、Event 与 Outbox 要么一起提交，要么都不提交；
4. durable intent 可以 at-least-once 被发现；
5. 无法证明未发生的外部 Effect 不自动重试，而进入 reconciliation。

## 2. 当前问题与修正边界

当前实现不能仅通过增加 `PostgresLeaseStore` 达成目标：

- `WorkerLease` 没有 epoch 或 fencing token；heartbeat/release 只比较
  `worker_id`，同名旧进程可能续租或释放后继者的 Lease；
- SQLite release 删除 Lease 行，ownership generation 随之消失；
- PostgreSQL Event sequence CAS 只证明 Event 顺序，不证明 Worker 仍有执行权；
- Worker 实际执行链没有周期 heartbeat，且 recover 发生在 acquire 之前；
- handoff facts 把 `checkpoint` 当作 `lease_fencing_token`；
- started Event、Effect ledger、外部调用和 terminal Event 分属多个事务；
- API idempotency 是副作用完成后的响应缓存，不是副作用 reservation；
- 现有 handoff outbox 是可借鉴的聚合范式，但不是通用 Effect 队列。

因此：

- 保留通用 `EventStorePort`。API/System Event 不强制持有 Worker Lease；
- 为 leased Worker 新增窄的 fenced mutation/Effect dispatch Port；
- 先修 Core Lease 合同，再实现 PostgreSQL Lease，然后实现 Effect Outbox，
  最后接入 Worker 消费和 heartbeat；
- 不新增全局 Unit of Work，也不把已有 handoff 表改造成通用队列。

## 3. 名词与不变量

### 3.1 Deployment namespace

v1 每个进程注入一个不可变的 `deployment_namespace`。所有 epoch、Lease、Effect、
Outbox 和 Event SQL key/predicate 都必须包含 namespace。跨 namespace 的相同
Session ID、token 或 idempotency key 没有任何权限。

### 3.2 Control-plane epoch

每个 namespace 只有一个当前 epoch，类型为 UUID：

```text
ControlPlaneEpoch = (deployment_namespace, epoch_uuid)
```

epoch 代表当前数据库控制面的恢复身份。正常进程重启不旋转 epoch；从备份/PITR
恢复并准备开放写端点时必须先旋转 epoch。所有恢复前取得的 Lease 与 Outbox claim
随即失效。

epoch bootstrap/rotation 只能由独立 migration/restore identity 执行；API/Worker runtime
role 只能读取当前 epoch，不能创建、修改或回退它。初次部署在 migration 后显式 bootstrap
namespace，restore 则在任何写端点开放前以新随机 UUID 原子旋转。

### 3.3 Lease fence

```text
LeaseFence = (
  control_plane_epoch: UUID,
  fencing_token: positive int,
  owner_instance_id: non-empty str,
)
```

`fencing_token` 在同一 epoch 和当前数据库 lineage 内，对
`(deployment_namespace, session_id)` 严格单调递增。每次首次 acquire、release 后重新
acquire、过期 takeover 都产生更大的 token；heartbeat 保持 token 不变。token 不因
release、普通进程重启、清理或归档而复用。

PITR 可能把裸 token 恢复到更小的历史值，因此不能承诺它跨 restore 全局单调。
授权比较始终使用完整 `(epoch, token, owner_instance_id)`；新随机 epoch 保证任何恢复前
fence tuple 永不重新有效。

### 3.4 Checkpoint

checkpoint 是 Worker 已确认处理到的 Event sequence，仅表示恢复进度：

- checkpoint 与 fencing token 是不同类型、不同字段；
- heartbeat 可以把 checkpoint 单调推进，但不得回退；
- checkpoint 相等或更大不授予任何写权限；
- handoff reserve/commit 必须保存和比较真实 `LeaseFence`，不能再使用 checkpoint。

## 4. Lease 状态机

### 4.1 数据模型最低要求

```text
control_plane_epochs(
  deployment_namespace primary key,
  epoch uuid not null,
  updated_at timestamptz not null
)

worker_leases(
  deployment_namespace,
  session_id,
  epoch uuid,
  fencing_token bigint,
  owner_instance_id,
  checkpoint bigint,
  acquired_at timestamptz,
  heartbeat_at timestamptz,
  expires_at timestamptz,
  released_at timestamptz null,
  primary key (deployment_namespace, session_id)
)
```

Lease 行在 release 后保留。v1 不建立历史表；当前行中的 token 是该 Session 在当前
数据库 lineage 可见的最高 generation。已释放状态由 `released_at` 表示。

### 4.2 时间权威

PostgreSQL Adapter 用数据库 transaction timestamp 计算过期：

```text
expires_at = database_now + validated_ttl
```

调用者只传 TTL duration，不传决定 ownership 的 wall clock。输入 TTL 必须大于零并
有配置上限。客户端时间可作为审计字段，但不得影响 acquire/takeover 判断。

SQLite local profile 可以使用注入 clock 保持确定性测试，但必须遵守相同状态机；
它不是 cloud-safe 实现，也不能作为 PostgreSQL 并发证据。

### 4.3 Acquire

`acquire(namespace, session_id, owner_instance_id, ttl, checkpoint)` 的单条事务语义：

- 行不存在：建立 token `1` 的 active Lease；
- 行已 release 或已由数据库时钟判定过期：token 加一，写入新 epoch/owner/times；
- 行 epoch 与当前 control-plane epoch 不同：旧 Lease 立即失效，不等待 TTL；以当前
  数据库 lineage 中可见的 token 加一发放新 fence；
- 行仍 active：无论请求者 owner instance ID 是否相同，都返回 `LeaseConflictError`；
- checkpoint 不得小于已持久化 checkpoint；调用者不能借 acquire 回退进度；
- 同 epoch 下并发 acquire 只允许一个事务成功。

active Lease 不允许“幂等 reacquire”。续租唯一入口是带完整 fence 的 heartbeat，
从而区分复用同一逻辑 Worker 名称的两个进程实例。

### 4.4 Heartbeat

heartbeat 必须以一个 SQL mutation 同时比较：

```text
namespace + session_id + epoch + fencing_token + owner_instance_id
+ released_at is null + expires_at > database_now
```

成功时仅推进 `heartbeat_at`、`expires_at` 和不回退的 checkpoint；不改变 token 或
`acquired_at`。影响零行返回 Core 定义的 `LeaseLostError`，不得先 get 再 update，
不得静默成功。

### 4.5 Release

release 使用与 heartbeat 相同的完整 CAS，并写 `released_at`，不删除行、不重置
token。影响零行返回 `LeaseLostError`。在清理原执行异常时，release 失败不得掩盖
原异常，但必须留下可观察诊断。

### 4.6 Worker 生命周期

最终 Worker 顺序必须是：

1. acquire Lease；
2. 在该 fence 下 recover Session；
3. 运行定时 heartbeat；
4. 每次模型调用、Event mutation、Effect schedule/terminal mutation 前确认尚未失租；
5. heartbeat 返回 `LeaseLostError` 后停止新的模型、Event 和外部 Effect；
6. 在覆盖完整执行生命周期的 `finally` 中尝试 fenced release。

仅调用 `get` 或缓存 Lease 对象不能证明当前所有权。

Worker 是同步阻塞执行模型，因此 heartbeat 由独立后台线程使用独立数据库连接完成；
不得依赖模型/tool 调用主动 yield。heartbeat interval 必须小于等于 TTL 的三分之一，
启动成功后才能进入 recover，release 前先停止并 join。线程把首次 `LeaseLostError` 或
不可恢复数据库错误写入线程安全 lost flag；主执行在每个新模型/Event/Effect 边界检查
该 flag。已经发出的外部调用不承诺可中断，但其返回后 terminal transaction 会再次
校验 fence，旧 owner 无法提交成功结果。

## 5. Fenced Worker mutation 边界

普通 API/System Event 继续使用 `EventStorePort`。leased Worker 使用一个聚焦的
aggregate Port，本任务覆盖的 Event/Effect mutation 在同一 PostgreSQL transaction 中
读取当前 epoch 并比较完整 Lease fence。旧 epoch、旧 token、错误 owner、已 release 或已过期均必须
影响零行并抛 `LeaseLostError`。

v1 不定义全局 Unit of Work。允许的聚合边界只有：

- Worker Event-only mutation：fence check + Event stream CAS + Event insert；
- Effect schedule：fence check + Event stream CAS + started Event + Effect reserve
  + Outbox pending；
- Effect terminal：fence check + Event stream CAS + terminal Event + Effect terminal
  + Outbox terminal。

Projection 是 Event 派生状态，不进入 Effect 原子提交承诺；它按现有 replay 合同恢复。

本合同不覆盖 ContextLifecycle、Handoff/dispatch、Workspace/Task、Model/Tool run、
provider continuation/history、Artifact 或 delivery-audit 等其他 Worker-owned aggregate。
它们仍由各自 Port 拥有 transaction，未来 PostgreSQL Adapter 必须在同一 transaction
内完成 fence conformance。上述合同及真实服务证据进入 `CLOUD-AGG-FENCE-01`，并是
任何“完整 multi-worker safe”或生产恢复结论的前置 gate。

## 6. Effect dispatch 与 Outbox

### 6.1 为什么需要独立 aggregate Port

现有 `EffectGuard` 的 inline 顺序是 reserve、mark executing、调用 provider、更新
ledger，外层另写 started/terminal Event。崩溃会留下无法判定的半状态。新的
`EffectDispatchPort` 直接依赖 Core typed contract，替换 agent-tools 中漂移的
`EffectLedgerLike[Any]`，但不扩展成任意 Store transaction API。

推荐最小操作：

```text
schedule(request, fence) -> EffectDispatch
claim(dispatch_id, fence, claim_ttl) -> EffectClaim
complete(claim, result, terminal_event) -> SessionEvent
fail_no_effect(claim, reason, terminal_event) -> SessionEvent
mark_uncertain(claim, evidence, terminal_event) -> SessionEvent
reconcile_expired(dispatch_id, old_claim, current_fence, evidence) -> EffectDispatch
resolve_uncertain(dispatch_id, current_fence, evidence, outcome) -> SessionEvent
retry_failed_no_effect(dispatch_id, current_fence, retry_key) -> EffectDispatch
mark_dead_letter(dispatch_id, current_fence, evidence) -> EffectDispatch
```

### 6.2 Schedule transaction

`schedule` 在一个 transaction 中：

1. 验证当前 Lease fence；
2. 对 Event stream 执行 expected-version CAS；
3. 写入 `TOOL_EXECUTION_STARTED`；
4. 以稳定 `EffectIdentity` reserve Effect；
5. 写入唯一 Outbox intent。

任一步失败全部 rollback。同一 `(namespace, root_session_id, ledger_key)` 的请求先比较
持久化的 Effect identity/request hash；同义重试直接返回原 dispatch 或 terminal result，
不再执行 Event expected-version CAS。不同语义复用同一 key 必须 fail closed。

### 6.3 Outbox 最低字段

```text
effect_outbox(
  deployment_namespace,
  dispatch_id,
  root_session_id,
  ledger_key,
  attempt,
  request_hash,
  effect_identity,
  safe_payload_or_artifact_ref,
  status,
  claim_epoch,
  claim_fencing_token,
  claim_owner_instance_id,
  claim_expires_at,
  intent_event_id,
  terminal_event_id,
  timestamps,
  unique (deployment_namespace, root_session_id, ledger_key, attempt)
)
```

Outbox 不保存原始凭据。payload 必须是 bounded typed value 或受治理 Artifact reference；
短期 credential 只能在实际执行时通过既有安全边界解析。

### 6.4 Claim 与 delivery

PostgreSQL consumer 用 `FOR UPDATE SKIP LOCKED` 查找 `pending` intent。claim transaction
同时校验 Session Lease fence，并把 Effect `reserved -> executing` 与 Outbox
`pending -> claimed` 原子提交。claim 自身也携带 epoch/token/owner/expiry；terminal
mutation 必须再次比较同一 claim 与当前 Lease fence。

外部调用在数据库 transaction 外执行。delivery 是 at-least-once discovery，不是
exactly-once effect。稳定 provider idempotency/operation ID 应被传入并只持久化可查询
标识或 hash；它增强 reconciliation，但不能替代本地 fence。

### 6.5 Terminal 状态

- `succeeded`：provider 有明确成功结果；原子写 Effect、Outbox、terminal Event；
- `failed_no_effect`：provider 明确证明调用未发生；允许显式重试策略重新调度；
- `uncertain`：调用可能发生但 durable receipt 未提交或 provider 不可查询；
- `dead_letter`：经人工策略判定不可继续处理，保留全部证据。

`executing` claim 过期不回到 `pending`。新 owner 先取得当前 Session Lease，再调用
`reconcile_expired`：transaction 锁定 dispatch，以旧 claim identity/status/expiry 做 CAS，
再校验新 owner 的当前 fence，记录 evidence 并把状态原子转为 `uncertain`。restore 后的
old-epoch claim 使用相同入口，不要求旧 fence 仍有效。该操作只改变 durable 状态，绝不
调用 provider 或自动重放。

provider 查询得到确定证据后，当前 owner 用 `resolve_uncertain` 把 uncertain 原子转为
`succeeded` 或 `failed_no_effect` 并写 terminal Event；不可查询时保持 uncertain。
`dead_letter` 只能由当前 owner 依据 operator-approved evidence 调用 `mark_dead_letter`，
不能成为静默超时转换。

初始 attempt 为 `1`。只有 `failed_no_effect` 可调用 `retry_failed_no_effect`：transaction
校验当前 fence 与旧 terminal attempt，用唯一 `retry_key` 原子创建 `attempt + 1` 的新
Effect attempt、started Event 和 pending Outbox；旧 attempt 永久保留。同一 retry key
幂等返回新 attempt，其他状态或不同语义复用 key 一律 fail closed。

### 6.6 Inbox 边界

v1 没有 broker 或外部 consumer，PostgreSQL Outbox 本身就是 Worker claim 的 durable
queue，因此不建立 generic inbox。未来引入 Redis/Kafka/外部投递时另开任务，并至少按
`(namespace, destination, message_id)` 与 Effect ledger identity 去重。

## 7. 崩溃与恢复矩阵

| 崩溃点 | Durable 状态 | 恢复行为 |
| --- | --- | --- |
| schedule transaction 前 | 无 intent | 调用者可用同一 ledger key 重试 |
| schedule transaction 中 | 全部 rollback | 不留下孤立 Event/Effect/Outbox |
| schedule 后、claim 前 | `reserved + pending` | 任一有效 owner 可 claim |
| claim 后、provider 前 | `executing + claimed` | 新 owner CAS 旧 claim 转 uncertain；能证明未调用才显式 retry |
| provider 成功后、terminal commit 前 | 可能已产生外部 Effect | 新 owner CAS 转 uncertain；按 provider operation ID 对账 |
| terminal commit 后、响应前 | 已 terminal | 同 key 重试返回持久化结果，不再调用 provider |
| restore 后旧 Worker 继续写 | epoch 不匹配 | 所有 fenced mutation 影响零行；旧 claim 失效 |

恢复流程先旋转 namespace epoch，再开放 API/Worker 写端点。旧 epoch Lease 不等待 TTL
即可被新 owner acquire。恢复后的 `pending` intent 可由新 owner claim；恢复前的
`claimed/executing` intent 必须由新 owner 通过 `reconcile_expired` 逐项转 uncertain 后
对账，不得批量重置为 pending。

## 8. 实现任务拆分

### 8.1 CLOUD-LEASE-CON-01 — Core Lease/fencing contract

Owned paths：Core Lease domain/Port/errors/exports、SQLite Lease conformance、handoff
fence facts、Worker claim 的机械合同适配，以及对应聚焦测试。交付 typed `LeaseFence`、
单调 checkpoint、完整 CAS 合同；修复 checkpoint 冒充 token。不得改 PostgreSQL 或
Effect execution。

Worker claim 的合同适配同时把顺序改为 acquire 后 recover；它不在本卡引入后台
heartbeat 或 Effect execution。

### 8.2 CLOUD-LEASE-PG-01 — PostgreSQL epoch and Lease Adapter

依赖 `CLOUD-LEASE-CON-01`。Owned paths：PostgreSQL migration、epoch/Lease modules、
storage exports 和真实 PostgreSQL tests。交付 DB-clock TTL、retained generation、
concurrent acquire、takeover、restore epoch rotation。不得接入 composition/Worker。

### 8.3 CLOUD-EFFECT-OUTBOX-01 — Fenced Effect dispatch aggregate

依赖前两卡。Owned paths：聚焦 Core dispatch contract/types、PostgreSQL Event
connection-aware primitive、Effect/Outbox modules/migration 和真实 PostgreSQL tests。
交付 schedule/claim/terminal/reconcile/retry 原子事务、SKIP LOCKED、crash matrix 与
reconciliation 状态。不得改 Tool Gateway/Worker。

### 8.4 CLOUD-EFFECT-CONSUMER-01 — Worker lifecycle and Tool integration

依赖前三卡。Owned paths：Worker loop/recovery/heartbeat/execution Event lifecycle、
agent-tools Effect guard 集成和聚焦 Worker tests。交付先 acquire 后 recover、后台 heartbeat、
失租停止、fenced release、provider operation ID 和 uncertain handling。不得新增 broker、
Redis live 或 cloud Store selector。

### 8.5 CLOUD-AGG-FENCE-01 — Full Worker aggregate fencing gate

该 gate 不在本任务中实现，也不能直接激活。它等待其余 authoritative Store 的
PostgreSQL Adapter 清单稳定后，再拆成按 aggregate/owned-path 隔离的 conformance 卡。
每个 ContextLifecycle、Handoff/dispatch、Workspace/Task、Model/Tool run、provider
continuation/history、Artifact 和 delivery-audit transaction 都必须在自己的 transaction
内校验当前 fence。全部真实 PostgreSQL stale-writer 测试通过前，不得声称完整
multi-worker safe。

父 `CLOUD-LEASE-01` 在四张卡全部 Done/merged、联合真实 PostgreSQL evidence 获批前
保持 `Locked`，不得用任一子卡的局部完成宣称父任务完成。它只关闭 Event/Effect
执行安全；完整 multi-worker safe 还依赖 `CLOUD-AGG-FENCE-01`。

## 9. 验收矩阵

### 9.1 Lease/fencing

- 两个不同或相同逻辑 Worker 名称的进程 instance 并发 acquire，仅一个成功；
- active Lease 不能 reacquire；heartbeat 保持 token 和 acquired time；
- 同一 epoch/database lineage 内，release/reacquire 与 expiry takeover 严格增加 token；
- old epoch/token、wrong owner instance、released/expired Lease mutation 影响零行；
- checkpoint 只能单调推进，且不授予 ownership；
- 调用者时钟偏移不改变 PostgreSQL takeover 时机；
- restore 旋转 epoch 后，恢复前所有 Lease 与 claim 立即失效；
- namespace negative tests 证明相同 ID/token 不能跨 namespace 使用。

### 9.2 Effect/Outbox

- 对 schedule transaction 每个 SQL 写点注入失败，不留下半状态；
- 同 ledger key 并发 schedule 只产生一个 Effect 与一个 Outbox；
- 两个 consumer 对同一 intent 只能 claim 一个；
- stale fence 的 claim 与 terminal mutation 全部失败；
- crash matrix 每个窗口都有真实 PostgreSQL 回归；
- `executing` expiry 不自动 replay，必须进入 reconciliation；
- 新 owner 能以旧 claim CAS + 当前 fence 原子转 uncertain 并留下 evidence；
- failed-no-effect retry 单调增加 attempt，重复 retry key 不创建新 attempt；
- terminal 成功后的重复请求返回原 `ToolResult`，provider 调用仍为一次；
- provider operation ID 可查询时完成 reconciliation，不可查询时保持人工处理；
- Event sequence CAS、Effect/Outbox 原子性和 namespace isolation 同时验证。

### 9.3 Worker

- Worker 先 acquire 再 recover，recover 失败仍尝试 fenced release；
- 长执行会 heartbeat；模拟 lease loss 后不再发起模型、Event 或 Effect；
- 任意执行异常进入 finally release，release loss 不掩盖原始错误；
- acquire/release generation 在 handoff reserve 与 commit 之间变化时 commit 失败。

## 10. 明确非目标

- Redis、Kafka、Temporal、generic inbox 或通用消息总线；
- generic Unit of Work、任意 Store transaction 暴露或跨数据库事务；
- SQLite/PostgreSQL dual-write 或在线 cutover；
- multi-namespace selector、多租户身份模型或 production rollout；
- 把 provider idempotency、API response cache 或 Event sequence 当作 Lease fence；
- 宣称外部副作用 exactly once。

## 11. 完成与解锁条件

本文通过 reader review 和文档一致性检查后，`CLOUD-LEASE-PLAN-01` 可进入 Review。
它只允许依次激活 `CLOUD-LEASE-CON-01`、`CLOUD-LEASE-PG-01`、
`CLOUD-EFFECT-OUTBOX-01`、`CLOUD-EFFECT-CONSUMER-01`；不会直接解锁父卡、
cloud composition、`CLOUD-AGG-FENCE-01`、Redis live 或生产流量。

# Zebra PostgreSQL Governed Memory 权威与迁移合同 v1.0

- 状态：`CLOUD-MEMORY-PG-PLAN-01` 冻结候选，2026-07-29
- 适用范围：`zebra-cloud-trench` 单 deployment namespace 云端控制面
- 不适用：Desktop、本地 SQLite、Host 业务身份目录、Mem0 内部历史

## 1. 结论

Zebra 的 `MemoryRecord` 生命周期事实必须先从进程本地 SQLite 迁移到
PostgreSQL，之后才能实现 Mem0 投递/删除账本。Mem0 继续只保存可删除、可重建的
派生语义索引；它的 UUID、向量、score 和 history 都不是 Zebra 事实。

当前 `MemoryStorePort.upsert()` 是无 revision 的最后写入者获胜操作，而 Review 的
真实流程跨 Memory、Event 与 Session Projection 多次落盘。把这一接口直接实现成
PostgreSQL 会保留并放大并发覆盖与半状态，因此云端实现不能只做 SQL 方言替换。

实施拆为三个串行卡：

1. `CLOUD-MEMORY-CON-01`：冻结显式 Memory mutation/aggregate contract；
2. `CLOUD-MEMORY-PG-01`：migration v10、PostgreSQL authority adapter 与原子事务；
3. `MEM-GW-DEL-01`：migration v11 派生投递/删除账本与 Mem0 consumer。

## 2. 当前事实与缺口

### 2.1 当前事实源

| 数据 | 当前事实源 | 云端状态 |
|---|---|---|
| Session Event | PostgreSQL `session_events` | 已完成 |
| Session Projection | PostgreSQL `session_projections` | 已完成 |
| Governed Memory | SQLite `memory_records` | 缺 PostgreSQL authority |
| 本地全文检索 | SQLite FTS5 | 仅本地派生索引 |
| Mem0 semantic index | Mem0 PostgreSQL/pgvector | 已验证 Adapter，仍为派生数据 |
| Mem0 provider ref | 尚无 durable Zebra mapping | `MEM-GW-DEL-01` Locked |

`MemoryStorePort` 仍是 Zebra 唯一受治理记忆入口。`AgentMemoryGatewayPort` 的 search
hit 只携带 Zebra `MemoryId` 和 provider evidence，调用方必须回到该 Store 重新检查
status、expiry、scope 和正文。

### 2.2 当前写入裂缝

Worker 完成一次 Session 时，现有路径会先直接 upsert candidates / expired / promoted
records，再返回对应 Memory Events。事件稍后才由外层 recorder 持久化。任一步崩溃
都可能得到“Memory 已变而 Event 未提交”或反向半状态。

API Review 当前依次执行：

1. get candidate；
2. list scope 中的 confirmed records；
3. 计算 duplicate/supersession；
4. upsert reviewed record；
5. upsert 每个 superseded record；
6. append review Event；
7. save Session Projection。

这不是一个并发安全事务。两个 Reviewer 可以同时基于相同 candidate 和 confirmed
集合作决定；中途失败也会暴露部分 supersession。

### 2.3 Scope 语义

`tenant_id`、`user_id` 和 `repo_id` 是 Memory 的业务可见性标签，不是 Zebra 的
Tenant/Organization 权威。云端每条记录与每条查询还必须先由构造时注入的
`deployment_namespace` 隔离。后续 Host authority 会把
`(authority_issuer, namespace_id)` 解析到该不透明 namespace；本卡不实现该目录。
在 Host verifier 落地前，v10/v11 可以完成 adapter 与单 namespace 测试，但不得启用
外部多租户 runtime composition 或宣称 tenant authorization 已闭合。

## 3. 权威模型

### 3.1 单一事实与派生数据

```text
PostgreSQL governed_memory_records  <- authoritative lifecycle and content
                |
                +-> session_events  <- immutable audit/execution evidence
                |
                +-> memory delivery outbox/ledger (v11)
                            |
                            +-> Mem0 REST / pgvector (rebuildable)
```

`governed_memory_records` 是 Memory 当前状态事实；Memory Event 是不可变审计与恢复
证据。两者在有 Event 的状态转换中必须同事务提交。Mem0 只消费已提交的 confirmed
事实，不能反向改变 confidence、status、text、visibility 或 expiry。

### 3.2 Identity 与 revision

- 主键：`(deployment_namespace, memory_id)`；
- 每条记录持有 `revision BIGINT >= 1`，每次事实变化严格加一；
- 创建请求携带稳定 `creation_key`，在 namespace 内唯一；
- creation/content/request digest 只覆盖稳定语义和 provenance；重试时重新生成的
  Memory/Event ID、Event sequence/时间、Memory lifecycle 业务时间和 Admin request 时间
  不改变 digest，首次提交的 receipt/Event 冻结实际 canonical 结果；Worker LeaseFence
  只决定本次执行权限，不属于 durable idempotency identity；
- update/review/delete 请求携带 `expected_revision`；影响多条 Memory 时逐行锁定并
  验证全部预期 revision，任一失败则零写入；
- source Session/Event 引用必须在同一 namespace；
- `created_at` 不可修改，`updated_at` 使用请求中已经冻结的业务时间并由 SQL 校验
  单调性；账本 claim/expiry 时间使用 PostgreSQL database time。

`MemoryRecord` 的公开 ID 不需要由 provider 或数据库生成。云端 operation request
单独承载 creation/idempotency key，避免把存储字段泄漏到领域实体。

云端 authority Port 还必须提供 management-only、cursor-based confirmed scan，供
v11 对一个精确 namespace/scope 做完整 rebuild。现有 `MemoryStorePort.list(limit<=500)`
不是遍历合同，不能被循环猜测成全量扫描。
首次 scan 必须建立一个逻辑快照；后续页只接受 Store 签发的 opaque snapshot token 与
position token，不能以可变 `updated_at` 充当跨页快照。scan scope 按 visibility 恰好
包含一个对应 repo/user/tenant identity，并拒绝额外 scope、text 或 source-session filter。
v10 使用无正文的持久 membership snapshot 支持跨实例/重启续扫：registry 保存 exact
scope digest、TTL 与操作审计，items 只保存 ordinal、Memory ID 和 captured revision。
翻页时重新验证当前 authority；已不再 confirmed 的项不返回，新 confirmed 由 v11 在
snapshot high-watermark 之后的 delivery 增量收敛。快照必须有每 namespace 数量上限和
显式 GC，不允许持有跨请求 PostgreSQL transaction/connection。cursor MAC 必须由部署级
稳定高熵密钥派生并显式注入 Store；不得从 DSN、数据库密码或 namespace 猜测生成，以保证
不同 API/Worker 实例使用不同连接身份时仍能安全续扫。

### 3.3 状态不变量

- `candidate -> confirmed | expired | deleted`；
- `confirmed -> superseded | expired | deleted`；
- `superseded | expired -> deleted`；
- `deleted` 为终态；
- `superseded` 必须引用同 namespace 已存在且未删除的 replacement；
- Memory type、visibility、业务 scope、source provenance、created_at 在创建后不可变；
- lifecycle update 不允许原地改 text/confidence；新的事实使用新 Memory ID 并显式
  supersede；
- 对于 `PROJECT_RULE`、`ARCHITECTURE_FACT`、`PROCEDURE`，同一 namespace、visibility、
  业务 scope 与 type 最多一个 active confirmed record。事务通过 scope advisory lock
  或等价确定性行锁串行化，而不是依赖应用层先 list。

删除后的 authority 行保留 ID、scope、status、revision、provenance digest 和时间，正文
清空或加密擦除。Event 与 delivery audit 不复制已删除正文。

Core contract 使用独立 `GovernedMemoryEntry` / tombstone view 表达已删除事实，不能用
强制非空 `text` 的 `MemoryRecord` 伪造空正文。兼容 `MemoryStorePort.get/list` 对 cloud
deleted rows 返回不可见（`get=None`、list 过滤），management authority Port 才可读无
正文 tombstone；本地 SQLite 行为不在本任务修改。

## 4. PostgreSQL v10 数据合同

v10 建议命名 `governed_memory_authority`，不修改 v1-v9 名称或 checksum。

### 4.1 `governed_memory_records`

最小字段：

- `deployment_namespace`, `memory_id`, `revision`；
- `memory_type`, nullable `text`, `confidence`, `status`, `visibility`；
- `tenant_id`, `user_id`, `repo_id`；
- `source_session_id`, `source_event_start`, `source_event_end`,
  `source_commit_sha`；
- `superseded_by`, `expires_at`, `created_at`, `updated_at`；
- `creation_key`, `content_digest`。

约束必须表达 Core 已有的不变量：visibility 对应 scope 非空、source range 成对且有序、
superseded_by 只出现在 superseded、时间有序、confidence 范围。`text IS NULL` 当且
仅当 status 是 deleted；其他状态要求 trim 后正文非空。FTS expression/partial index
明确排除 deleted。source Session 存在时使用 `(namespace, session_id)` 外键；
superseded 引用使用同 namespace 复合外键。

### 4.2 查询索引

- `(namespace, repo_id, status, updated_at DESC, created_at DESC, memory_id)`；
- 对 user/tenant scope 的等价索引；
- `(namespace, source_session_id, status, updated_at DESC, memory_id)`；
- scope + type 的 active confirmed 并发约束/锁键；
- PostgreSQL native `tsvector` + GIN 作为可重建搜索索引。

无 text query 时严格保持 `updated_at DESC, created_at DESC, memory_id ASC`。Text query
要求相同 scope/status/type/visibility 过滤、确定性 tie-break、bounded limit 和无正文
泄漏；SQLite BM25 与 PostgreSQL rank 数值不作为跨 backend 公共合同。固定 golden
fixtures 必须保持相同可发现集合，排序差异只能由明确的 backend-neutral rank 规则批准。

### 4.3 `governed_memory_operations`

v10 需要一个精简的 durable aggregate receipt，而不只依赖单条 Memory creation key。
每次 Worker/Admin aggregate 保存 namespace、operation ID、kind、request digest、状态、
anchor Event range、bounded canonical result JSON、result digest/schema 和时间；result
只含 committed Memory IDs/revisions、Event IDs/sequences、Session/Projection revision，
不保存正文或 provider payload。唯一键
`(namespace, operation_id)` 使相同 digest 返回 canonical receipt、不同 digest 冲突。

canonical replay 直接返回 receipt 冻结的 result payload 并验证 digest/anchor Event range；
不能读取后来已变化的 current Memory revision，也不能依赖调用方重建的随机
Event/Memory ID。receipt、Memory rows、Events 与 Projection 在同一事务提交，因此
数据库响应丢失后可安全读回原操作结果。

### 4.4 不新增的表

除上述 aggregate receipt 和无正文临时 scan membership 外，v10 不创建 Mem0
mapping/outbox、第二份 Memory projection、Redis cache、tenant directory 或 provider
history。scan membership 不是事实源，过期后可删除；v11 才拥有 delivery state，避免
Memory authority migration 与外部 Effect 生命周期在一个卡中扩张。

## 5. 原子事务

### 5.1 Worker candidate aggregate

Core 先把现有 candidate extraction、promotion 与 review 拆成无 I/O 的 deterministic
plan，返回待提交 Memory mutations + Events。SQLite compatibility wrapper 继续按原顺序
调用现有 `MemoryStorePort`，保持本地行为；PostgreSQL aggregate 只消费纯 plan，禁止在
事务前调用会自行 upsert 的现有 service。

输入必须包含完整 `WorkerMutationAuthority`、expected Session stream revision、稳定
operation key、candidate records 和对应 Events。一个 PostgreSQL transaction：

1. 验证 namespace + current LeaseFence；
2. 锁 Session stream，并验证 expected revision；
3. 按 creation key 幂等创建 Memory 或验证 canonical retry；
4. 应用受影响 confirmed Memory 的 revision CAS；
5. append Memory Events；
6. 保存 Event-derived Session/Workspace projections（仅当当前 Worker 聚合要求）；
7. commit。

lost response 后相同 operation key 返回数据库中的 canonical Memory/Event 结果；不同
内容复用 key 必须 conflict。stale Worker 零写入。

### 5.2 Administrative review aggregate

API Review 不伪造 Worker Lease。输入使用 `AdministrativeMutationCAS`，包含 Session、
expected stream revision、所有显式客户端目标的 expected Memory revisions、
operator/reason 和 operation ID。
事务锁定 candidate 与同 scope/type active confirmed 集合，重新计算 duplicate / supersede，
然后原子提交：reviewed candidate、所有 superseded rows、review Event、Session Projection。
事务内动态发现的 active set 不要求客户端提前提交 revision map；它在 deterministic scope
lock 下读取当前值并完成重算，避免把并发安全交给陈旧的应用层 list 结果。

重复 operation 返回 canonical result；两个并发 Reviewer 只有一个可以基于旧 revision
成功。bulk review 是多个独立可审计 command，响应明确逐项结果；不承诺跨五百条的
全批原子事务。

### 5.3 Read path

`get/list` 始终把 deployment namespace 放入 SQL predicate。Memory prompt admission 在
一次有界 read-only snapshot 中读取 confirmed、未过期、未删除记录；Mem0 hit 仍逐条
回到该 authority 校验。Read 不要求 Lease，也不隐式写或 rebuild。

## 6. SQLite 到 PostgreSQL 迁移

迁移是显式离线工具/运行手册，不在 Adapter constructor 中执行：

1. 停止本地 Memory 写入或取得一致 SQLite snapshot；
2. 先迁移/验证被引用的 Session stream，再校验每条 `MemoryRecord` 与业务 scope；
3. 为 legacy row 生成可重复的 import creation key 和 content digest；
4. 按原 `MemoryId` 幂等导入指定 deployment namespace；
5. 比较总数以及 status/visibility/type/scope 分组计数；
6. 对每个 source Session 抽样核对 Event provenance；
7. rebuild PostgreSQL FTS；
8. v11 完成后仅从 confirmed、未过期事实重建 Mem0；
9. 在完整 PostgreSQL `ControlPlaneStores` 切换前保持 SQLite profile 不变。

重复导入相同内容成功；同 creation key 或 Memory ID 的不同内容失败。导入工具不得
从 Mem0 反向恢复 Zebra 正文或 lifecycle。
缺少同 namespace source Session 的 legacy row 不得绕过复合引用：整次 preflight
失败并输出无正文的 quarantine report；先迁 Session 或由明确的数据治理流程处理后
才能重新导入，不能静默清空 provenance。

## 7. Mem0 delivery v11 边界

`MEM-GW-DEL-01` 只能在 v10 adapter 通过后开始。v11 ledger 至少保存 namespace、
Memory ID、Memory revision/content digest、operation kind、idempotency key、status、
provider ref、attempt/claim、无正文的 error evidence 和时间。

传给 Gateway 的 provider namespace 由受信 composition 按版本化 canonical envelope
构造：deployment namespace + visibility + exact business scope identity；ledger 仅保存
它的 digest。不得把 raw repo path、tenant/user label 或未经验证的请求字段直接当作
provider authorization boundary。

Mem0 duplicate POST 会生成不同 UUID，且已验证版本不能按 metadata 可靠查回。因此：

- Gateway mutation result 必须新增 provider-neutral certainty：`applied`、
  `definite_no_effect`、`unknown`。Consumer 不得解析 `detail` 字符串推断是否可重试；
- valid 2xx/provider ref 是 applied；请求发送前的 disabled/circuit/preflight failure
  与明确拒绝是 no-effect；timeout、连接中断、5xx、2xx invalid/oversized response 是
  unknown，因为 provider 可能已经提交；
- publish 响应丢失记为 `uncertain`，禁止自动重试；
- reconcile 不能猜测 provider ref；可选择明确 reset 派生 namespace 后从 PostgreSQL
  confirmed facts rebuild，或等待未来经过真实验证的 provider reconcile 能力；
- delete 通过 v11 mapping 解析 provider ref；provider 404 与成功都可收敛为已删除派生
  数据，但 Zebra deletion fact 必须先存在；
- Search admission 同时要求 active ledger mapping 的 provider ref 与 hit 完全一致，并
  从 v10 authority 重新验证 Memory 仍 confirmed、未过期且 scope 匹配；
- delivery consumer 使用自身 row claim/token/CAS，不复用 Session Worker Lease；
- search outage、delivery lag 或 Mem0 reset 都不能失败一个 Agent Run。

## 8. 实施任务拆分

### CLOUD-MEMORY-CON-01 — Governed Memory mutation contract

- Depends on: 本计划 Review；
- Owned paths: focused Core Memory authority request/result/Port modules、现有
  candidate/promotion/review 的 pure planning seams、compatibility wrappers and tests；
- Deliverable: creation key、record revision、tombstone view、Worker candidate aggregate、
  administrative review CAS、pure mutation plans、typed conflict/replay results；
- Non-goals: SQL、SQLite 改造、Mem0、API/Worker composition；
- Acceptance: stale/missing authority cannot form a valid cloud mutation request；local
  `MemoryStorePort` compatibility remains unchanged。

### CLOUD-MEMORY-PG-01 — PostgreSQL governed Memory authority

- Depends on: `CLOUD-MEMORY-CON-01` and integrated v1-v9；
- Migration: v10；
- Owned paths: focused PostgreSQL migration/Memory/operation-receipt modules, narrow API/Worker injection
  seams, migration tool/runner and real PostgreSQL tests；
- Acceptance: query parity, namespace isolation, revision CAS, concurrent review,
  candidate/Event/projection atomicity, lost-response replay, stale fence zero-write,
  import/rebuild and read-only behavior pass against PostgreSQL 17.5；
- Non-goals: Mem0 delivery, backend selector, Desktop, production cutover。

### MEM-GW-DEL-01 — Memory delivery and deletion ledger

- Depends on: `CLOUD-MEMORY-PG-01`, Mem0 Adapter and Lease/Effect baseline；
- Migration: v11；
- Owned paths: delivery ledger/consumer, Gateway lookup composition, reconciliation,
  rebuild and real PostgreSQL+Mem0 tests；
- Acceptance: canonical success retry, uncertain response-loss quarantine, no duplicate
  automatic publish, authoritative hit revalidation, no-content delete evidence and
  bounded rebuild all pass。

## 9. 验收矩阵

### Core

- invalid namespace/key/revision/status transition rejected；
- Worker and administrative authority cannot substitute for one another；
- changed payload under same idempotency key conflicts；
- deleted content cannot enter audit/result objects。

### PostgreSQL v10

- fresh v1-v10 and existing v1-v9 upgrade keep historical checksums；
- repo/user/tenant/source-session filters and stable no-text ordering match SQLite；
- FTS scope/status/limit safety and deterministic tie-break pass；
- same Memory ID in two namespaces is isolated；
- concurrent confirm/supersede/expire has one canonical winner；
- injected failure after each SQL step rolls back Memory, Event and Projection together；
- stale Lease/Session/Memory revision changes zero rows；
- lost acknowledgement returns canonical prior result；
- import is repeatable and conflicting legacy data fails closed；
- read-only role can get/list without epoch or Lease writes。

### v11 / Mem0

- publish success, disabled, outage, 429, schema drift and timeout；
- response loss becomes uncertain and does not retry publish；
- delete success/404/timeout retains no deleted text；
- stale/superseded/expired/deleted hits are removed before prompt admission；
- reset + rebuild emits only current confirmed, unexpired PostgreSQL facts；
- Mem0/Redis loss does not change governed Memory counts or fail Run。

当前 v11 PostgreSQL 子任务已在 `codex/mem-gw-del-pg-01` 实现并通过独立
Compose 证据：migration v11、metadata-only delivery ledger、同事务 authority
enqueue、claim/CAS、mapping 和 batch authority revalidation。它只在
`PostgresGovernedMemoryStore` 显式传入可信 `delivery_scope` 时启用；默认
Worker、本地 SQLite 和 Mem0 HTTP composition 不变。Reset/rebuild 与 runtime
consumer 仍由后续任务负责，不能据此宣称 v11/Mem0 生产启用。

## 10. 明确非目标

- 不把 Mem0、pgvector 或 Redis 变为 Memory fact source；
- 不在 Zebra 创建 Tenant/User/Organization 目录；
- 不修改本地 SQLite 行为或 Desktop；
- 不在 Adapter constructor 自动 migration/rebuild；
- 不宣称跨 PostgreSQL 与 Mem0 exactly-once；
- 不在本计划选择完整 cloud backend、Kubernetes、PITR/RPO/RTO 或生产凭据策略。

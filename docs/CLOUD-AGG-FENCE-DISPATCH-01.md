# CLOUD-AGG-FENCE-DISPATCH-01

## 状态

- 任务：Dispatch Stream Pointer And Replay Fencing
- 状态：`In Progress`
- Owner：`codex`
- 分支：`codex/cloud-agg-fence-dispatch-01`
- Worktree：`/Users/lukeding/.codex/worktrees/cloud-agg-fence-dispatch-01/zebra-agent`
- 基线：`zebra-cloud-trench@4a10883a`
- 父门：`CLOUD-AGG-FENCE-01` 继续 `Locked`
- 前置：`CLOUD-AGG-FENCE-HANDOFF-AUTH-01` 已在主线 `Done`

侧边栏 ChatGPT 在 AUTH-01 受控 fast-forward 合并到主线后返回
`IMPLEMENTATION-ACTIVATE-OK`，批准本卡从 `Locked` 进入 `In Progress`，且只
激活本卡。AUTH-01 的 authority、LeaseFence、request identity 和 CAS 结果是本卡
唯一的上游事实源；本卡不重做 reserve/abort，也不授权 Runtime、API/Worker profile、
应用 Compose 或父门。

## 目标与边界

在 PostgreSQL 持久化边界将 dispatch claim/ACK 绑定到：

- namespace、operation_id、expected stream revision 和 active pointer revision；
- 已合并的 WorkerMutationAuthority、当前 LeaseFence 和 claim owner/token；
- 可 claim/claimed 的期望状态及 replay-safe、namespace-safe zero-write 语义。

禁止新增第二套 authority、lease、claim 或 dispatch 事实源；禁止 migration/DDL、
API/Worker 启动选择、Runtime、Redis、Mem0、SQLite、Provider HTTP、CopilotKit/Trench、
生产部署和应用 Compose 改动。

## 验收矩阵

1. claim/ACK 复用 AUTH-01 authority 与 LeaseFence，且 operation、stream、pointer
   和 token 身份处于同一 canonical dispatch operation。
2. 错误 operation、namespace、owner、epoch、token、过期 LeaseFence、stale stream
   或 pointer revision 在任何 dispatch/pointer/Event/projection/audit 写入前拒绝。
3. 并发 claimant 最多一个有效 owner；替换或过期 owner 的旧 token 立即失效。
4. ACK 绑定有效 claim token、当前 authority/LeaseFence、stream/pointer revision 和
   claimed 状态；错误 ACK 保持所有状态零净变化。
5. 合法 claim retry 与 ACK replay 收敛到一个 canonical 结果，不产生重复终态副作用。
6. 覆盖跨 namespace、事务异常和 rollback；失败后合法 retry 能重新收敛。
7. AUTH-01 的 reserve/abort focused 回归保持通过，且无 migration/DDL diff。

## 计划验证

- 独立 PostgreSQL `17.5-alpine3.21` Compose runner，显式输出
  `ZEBRA_HANDOFF_DISPATCH_POSTGRES_TEST_RESULT=PASS`，记录版本、计数和清理结果。
- 覆盖两个并发 claimant、一胜者、stale claim、wrong-token ACK、stale authority、
  stale stream/pointer、跨 namespace、ACK replay、rollback 和 rollback 后 retry。
- changed-path Ruff、strict Mypy、`uv lock --check`、`bash -n`、Compose config、
  `git diff --check`，并保留根 `AGENTS.md` 的用户未提交状态。

## 当前实现证据

- `HandoffDispatch` 携带 operation、child stream、active pointer 和
  `WorkerMutationAuthority`；云端使用 `FencedHandoffDispatchStorePort`，本地
  SQLite 仍保留旧 Port 签名与行为。
- canonical claim retry（带 authority 或 revision）返回仍有效的原 token；
  legacy fence-only retry 继续返回 `None`。并发 ACK 在 dispatch 行锁上收敛为
  一个 `acked` 终态，不产生重复写入。
- 专用 Compose runner 已通过 `14/14`，输出
  `ZEBRA_HANDOFF_DISPATCH_POSTGRES_TEST_RESULT=PASS`，并清理容器、volume 与
  network；独立 Review/closeout 仍待完成，父门继续 `Locked`。

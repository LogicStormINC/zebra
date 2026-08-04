# CLOUD-AGG-FENCE-HANDOFF-AUTH-01

## 状态

- 任务：Handoff Reserve And Abort Authority
- 状态：`Review`
- Owner：`codex`
- 分支：`codex/cloud-agg-fence-handoff-auth-01`
- Worktree：`/Users/lukeding/.codex/worktrees/cloud-agg-fence-handoff-auth-01/zebra-agent`
- 基线：`zebra-cloud-trench@a765e068`
- 实现提交：`6a04f1cd03aea96d9d04ba702832d1fffb1292e1`
- 父门：`CLOUD-AGG-FENCE-01` 仍为 `Locked`
- dispatch successor：`CLOUD-AGG-FENCE-DISPATCH-01` 仍为 `Locked`

sidebar ChatGPT 已返回 `IMPLEMENTATION-ACTIVATE-OK`，批准本卡从 `Locked` 进入
`In Progress`，并限制在本文件、任务注册表声明的 Core/ PostgreSQL Handoff seam、
focused tests 和专用 runner。实现与证据已完成，等待独立 sidebar closeout；本记录
不授权 parent gate、dispatch、Runtime、API/Worker selector 或应用 Compose。

## 交付内容

1. `SessionHandoffAbortRequest` 携带 `AdministrativeMutationCAS` 和原始
   `HandoffOperation`，通过 cloud-only `SessionHandoffAbortPort` 暴露严格 abort seam；
   既有 `SessionHandoffPort` 及本地 SQLite 兼容行为未改变。
2. PostgreSQL reserve 在同一 transaction 内先锁定 Session Lease boundary，重新读取
   source stream、Workspace、LeaseFence、authority revision 和 task profile revision，
   再执行幂等 operation insert。active lease、stale stream/fence/workspace/authority
   或 task facts 在写入前失败。
3. PostgreSQL authorized abort 先锁定 operation，再校验 reservation/request identity、
   namespace、source session、expected stream CAS，随后锁定 Lease boundary 和 source
   facts，最后只允许 `preparing -> aborted` 的 CAS 更新。
4. stale cleanup 复用相同的 abort authority helper，并使用 `FOR UPDATE SKIP LOCKED`；
   与 commit 的竞争只能产生一个 terminal result。
5. source facts 在同时锁定 stream 与 Workspace 时按 stream -> Workspace 顺序加锁，
   与 Worker Event/projection 事务保持一致，避免反向锁顺序造成死锁。

## 验证证据

### PostgreSQL 17.5 Compose

命令：

```text
tests/compose/session_handoff_authority/run-postgres-tests.sh
```

结果：

```text
postgres:17.5-alpine3.21
15 passed in 4.09s
ZEBRA_HANDOFF_AUTH_POSTGRES_TEST_RESULT=PASS
```

矩阵覆盖同 key 并发 reserve 收敛、active lease/stale facts 零写入、workspace drift、
wrong namespace、reservation/request identity、stale CAS、authorized replay、
abort-vs-commit race、结果物化失败事务回滚和 aggregate row-count 约束。runner 退出
时移除 container、volume 和 network。

### 其他验证

- `uv run pytest -q tests/agent_storage/test_postgres_session_handoffs.py tests/agent_storage/test_postgres_session_handoff_authority.py tests/agent_core/test_session_handoff.py`：`14 passed, 15 skipped`（无 DSN 时的 PostgreSQL gate skip）。
- `uv run pytest -q tests/agent_storage/test_session_handoffs.py tests/agent_storage/test_postgres_handoff_dispatch.py tests/agent_storage/test_postgres_leases.py tests/agent_core/test_session_handoff.py`：`29 passed, 23 skipped`。
- 变更范围 Ruff：通过。
- 变更范围严格 Mypy：通过，7 个 source files 无问题。
- `uv lock --check`：通过。
- `bash -n tests/compose/session_handoff_authority/run-postgres-tests.sh`：通过。
- `docker compose --project-name zebra-session-handoff-authority-test --file tests/compose/session_handoff_authority/compose.yml config --quiet`：通过。
- `git diff --check`：通过。

## 边界与后续

- 本卡没有修改 migration/DDL、dispatch claim/ACK、API/Worker 启动选择、Runtime、
  Redis、Mem0、Provider HTTP、CopilotKit/Trench、Desktop 或应用 Compose。
- `CLOUD-AGG-FENCE-HANDOFF-DISPATCH-CON-01` 的审计结果仍为 `BLOCK-GAP`；本卡只关闭
  reserve/abort 缺口，不改变 dispatch successor 的 `Locked` 状态。
- 在独立 sidebar closeout 通过前，本卡不能标记 `Done`，不能解锁
  `CLOUD-AGG-FENCE-01`，也不能授权 successor 或运行态接线。

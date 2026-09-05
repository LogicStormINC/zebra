# Current task — RabbitMQ reliability (2026-09-05)

Approved isolated worktrees: `rabbitmq-reliability/zebra-agent` and
`rabbitmq-reliability/Trench`; original services remain unchanged.

1. Completed: stages 0/1 local contracts and broker evidence.
2. Completed: Stage 2 Trench Turn, 10/10 isolated acceptance.
3. Completed: Stage 3 Zebra command, 6/6 isolated acceptance; actual product,
   browser/file, broker restart, fallback/restore and process-fault evidence in
   `docs/rabbitmq_stage3_composition.md`.
4. Review: `RABBIT-SOURCE-SCOPE-01`, explicit source bindings and operator
   CAS backfill. Private/credential execution remains fail-closed.
5. Review: `RABBIT-SOURCE-SCHEDULE-01`, source-wide scheduling/fencing and
   atomic FetchCommand/source-Outbox admission; slice 6/6 and Stage 4 group 2
   accepted.
6. Review: `RABBIT-SOURCE-DELIVERY-01`, dedicated source relay/Inbox,
   bounded consumer/recovery/quarantine and opt-in restricted topology; Stage 4
   group 3 accepted. Stage 4 is now 2/7.
7. Review: `RABBIT-SOURCE-CUTOVER-01`, every old business fetch entry point now
   uses one default-off authority without double scheduling; Stage 4 group 4
   accepted. Stage 4 is now 3/7.
8. Review: `RABBIT-SOURCE-RESULT-01`, durable fenced fetch-result
   classification, safe diagnostics and bounded retry/recovery; Stage 4 group 5
   accepted. Stage 4 is now 4/7.
9. Review: `RABBIT-SOURCE-E2E-01`, real fixture HTTP fetch through
   PostgreSQL/Redis/RabbitMQ into authenticated history/timeline, including
   duplicate, Redis-rejection and cross-user isolation evidence; Stage 4 group 6
   accepted. Stage 4 is now 5/7.
10. Review: `RABBIT-SOURCE-COMPOSE-01`, default-off process composition,
    explicit cutover, actual-process fallback/restore/rollback and terminal
    database evidence; Stage 4 group 7 accepted. Stage 4 is now 6/7.
11. Review: `RABBIT-SOURCE-CREDENTIAL-REF-01`, existing credential identity,
    enabled state and platform validation with principal association and
    fail-closed drift; Stage 4 group 1 accepted. Stage 4 is now 7/7.
12. Review: `RABBIT-ROLLOUT-CAPACITY-01`, atomic admission/backlog bounds and
    frozen active-scope fair pickup accepted; Stage 5 is 1/8 (12.5%).
13. Review: Stage 5 group 2, default-off scope allowlist, physically separate
    side-effect-free bounded shadow lane and exact message/digest reconciliation;
    Stage 5 is 2/8 (25%).

Use `docs/AGENT_TASKS.md` for ownership and `docs/rabbitmq_completion.md` for
fixed acceptance counts. Implementation, isolated acceptance, commit/merge and
production activation remain separate. No commit or activation requested here.

## Prior task record — TRN-LINK (2026-08-26)

1. `completed` - P0 契约核对：7 项契合 / 5 项差距冻结
   （`docs/Zebra_Trench对接差距清单.md`）。
2. `completed` - G1 Host Grant Broker（`apps/host_grant_broker`）：
   RS256 签发（claim 集与 `HostSessionGrant` 精确一致，thread/run 经
   resource_refs 绑定）、JWKS 端点、Trench 会话验证（Cookie 只转发到
   `/api/trench-ai/me`）；8 个测试含真实验证器闭环。
3. `completed` - G2 Host 注册脚本（`scripts/register_trench_host.py`），
   已对真实 PostgreSQL host authority schema 冒烟。
4. `completed` - G3/G4 验收 operator sidecar（业务快照 + Worker 重启
   hook，token 保护，10 个测试）。
5. `completed` - G5 验收编排：`docker/compose.trench-acceptance.yml`
   （broker/sidecar/caddy TLS）+ `docker/trench-acceptance/bootstrap.sh`
   （密钥与本地 CA 生成，已实际执行）；`docker/Dockerfile` 增加 broker
   target。
6. `in_progress` - 全量回归验证与提交。
7. `blocked` - 应用镜像构建 + 完整栈拉起 + Trench `.env` 填值 +
   `EMB-TRN-READ-E2E-01` 16 输入执行（需 Trench 侧清场提交与真实
   部署输入，非代码缺口）。

下一步：等 Trench 侧提交清场后，按 `docs/Zebra_Trench对接实施方案_v1.0.md`
P1→P3 顺序拉栈、填配置、跑 runner。

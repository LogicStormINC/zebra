# TRN-LINK Trench 对接（cloud-agent-trench 分支，2026-08-26）

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

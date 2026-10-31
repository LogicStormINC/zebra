# CA-BASELINE-GATE-02 组合验收

2026-11-01；[机器收据](validation.json)。代码2b908448已按条件快进至本地cloud-agent；最终文档/证据提交随主线推送，不是部署。

- canonical92b308b（源实现439fb72）经git archive导出；源码来源和源验证见integrations/erpnext/SOURCE.md及其docs/evidence/ca-baseline-gate-02/。
- 最终完整make test11672通过/0失败/3161条件跳过；make check全部通过：尺寸4046/0、Ruff0、mypy1494、Eval30、产品与进度风险检查通过。
- 独立真实PG5通过，故障/恢复、角色槽、实际锁超时、schema拒绝及Worker能力到期；限1CPU/512MiB/PID128、数据tmpfs256MiB。
- 两次完整失败原日志单独保留：旧手工摘要投影和基线既有租约测试调度假设。修正不改生产实现；独立规格/质量复核通过，后者强制后台先续约再交接，20次实际重复通过。
- 原生01和HA02先前证据未覆盖。source SHA、日志SHA和资源前后清单单独记录。归属标签清理后仅原overdoze-dev-pg，未删除数据/持久卷/其他服务。
- 复现完整验证：uv sync --frozen --all-packages --group dev；nice10/OMP_NUM_THREADS=1/OPENBLAS_NUM_THREADS=1下串行make -j1 check与make -j1 test。
- PG单独执行：ZEBRA_HA_POSTGRES_ACCEPTANCE=1 uv run pytest -q tests/api/test_cloud_ha_health_postgres.py；fixture使用唯一自有容器并finally rm-fv，不能复用业务数据库。
- 非生产单PG功能验收不代表集群故障切换、生产30日SLO、真实IdP/ERP105或多租户容量；这些边界及条件跳过不冒充已验。无部署/生产迁移；HA03仅Ready。

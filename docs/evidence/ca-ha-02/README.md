# CA-HA-02候选验证

validation.json记录实际范围与未验证项，focused.txt只对应52个轻量定向测试，不是全量门禁。
expiry-red.txt是暂时撤去本分支新增能力到期守卫后的预期失败，随后已恢复并重跑通过。

复验使用当前worktree的apps/*/src与packages/*/src作为PYTHONPATH及MYPYPATH，
本地隔离venv复用已有依赖并仅安装锁定ag-ui-protocol1.0.0，未修改共享环境。

定向命令：

```sh
python -m pytest -q tests/api/test_cloud_ha_health.py tests/api/test_host_auth_http.py \
  tests/api/test_routes.py::test_route_adapter_handles_health \
  tests/worker/test_worker_health_observation.py tests/worker/test_loop.py \
  tests/worker/test_command_process.py
```

仅进程内HTTP/SQLite/假外部I/O及受控线程，所有所建线程/执行Future在用例结束关闭。
没有Docker/真实PG/Broker/外部模型/持续压测/部署/迁移；旧验收环境未重启。
完整make test/check与真实依赖/故障联合仍未运行，不据此解锁03或宣称生产HA。

## 后续候选复核

[review-validation.json](review-validation.json)记录输入6af4e5dd后的三项修复与58项定向复验。
原validation.json和52项日志保持不变，不将旧证据路径替换为新结果。
新增RED覆盖真实进展截止、记录耗时不可延长截止、符号链接与异常关闭漏清理；
FIFO负例在5s超时可杀并回收的子进程中执行，节点在finally删除，无Docker/数据库环境。
本轮同样没有全量门禁或真实PG/故障/UX容量验收，不据此解锁03。

## 完整门禁与真实PostgreSQL（2026-10-31）

[full-validation.json](full-validation.json)为当前状态：真实PG5项通过；完整make test为
11641通过/15失败/3155条件跳过，make check在16处尺寸违规失败。其余步骤补充串行执行，
Ruff4924错误，mypy1494源/Eval30及两个进度风险检查通过。全部失败已在干净e8a4f10b
精确复现：[对照](full-baseline-comparison.json)。基线失败不等于通过，不执行条件合并。
原52/58项证据不覆盖、不改写；本轮完整测试先执行，新增PG模块五项随后单独真实执行。
临时容器及时rm-fv，独立PG使用tmpfs且配额经inspect断言；仅原有overdoze-dev-pg留存。
无部署/生产迁移，03保持Locked。

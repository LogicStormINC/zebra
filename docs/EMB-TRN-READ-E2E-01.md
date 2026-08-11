# EMB-TRN-READ-E2E-01 跨服务只读验收

本卡只增加 Zebra 侧验收 runner 和证据格式，不修改 Trench 代码。runner
必须在真实部署输入齐全时才执行；缺少任一输入返回 `BLOCKED` 和非零退出码，
不能用 `skip` 或静态测试伪造通过。

## 验收边界

runner 覆盖以下真实边界：

1. Trench/Zebra HTTP health、两侧 PostgreSQL、Redis 和对象存储 health；
2. Trench Event Detail 的 BFF bootstrap、只读 Tool manifest 和
   `events.get_event`；
3. BFF AG-UI run、长任务终态、断线后使用 durable cursor 重连；
4. Worker restart operator hook 后重新 replay；
5. Zebra command-only `run`/`stop`/`resume` admission；
6. 单次 Host Grant replay rejection；
7. 有界 read Tool 错误；
8. Trench business snapshot 在所有只读场景前后保持相同。

脚本位置为 `tests/compose/trench_read_e2e/run_acceptance.py`，清单为
`tests/compose/trench_read_e2e/runner_manifest.json`。证据只写 scenario 状态、
错误码和快照摘要，不写 Cookie、Grant、DSN 或响应正文。

## 部署输入

必须由隔离验收环境注入清单中的环境变量。`TRENCH_E2E_SESSION_COOKIE` 只发给
Trench/BFF 和 Grant exchange；Zebra 请求只使用每次新交换得到的 Bearer Grant。
`TRENCH_E2E_BUSINESS_SNAPSHOT_URL` 是只读 operator view，返回：

```json
{"schema_version":"trench.business-snapshot.v1","tables":{"events":{"count":1,"digest":"..."}}}
```

runner 只 canonicalize `tables`，因此 view 不得包含时间戳、随机数或请求计数。
`ZEBRA_E2E_WORKER_RESTART_URL` 必须是受保护的 operator hook；它只接收
`taskId`/`runId`，不接受浏览器 Cookie。

## 当前执行结果

本分支只完成 runner、manifest、契约测试和本记录。当前机器没有上述真实部署
输入；执行 `uv run python tests/compose/trench_read_e2e/run_acceptance.py`
会写出 `status=blocked` 的 `result.json`，并列出缺失变量，故不宣称跨服务
E2E 通过。

另一个独立的接线风险仍需在真实环境解决：Zebra Worker 当前的
`build_worker_tool_gateway` 组合仍返回 `LocalToolGateway`，Host Tool Gateway
虽已有 typed contract/adapter，但尚未进入 Worker 的生产执行路径。因此本卡
不能把 Trench read Tool 的直接 HTTP 检查描述成完整的 Worker→Host Tool 链路；
接线应作为后续 Zebra 实现卡，而不是在本 runner 中绕过边界。

## 执行命令

```bash
uv run pytest -q tests/compose/trench_read_e2e/test_runner.py
uv run python tests/compose/trench_read_e2e/run_acceptance.py --list
uv run python tests/compose/trench_read_e2e/run_acceptance.py \
  --evidence-dir /tmp/zebra-trench-read-e2e
```

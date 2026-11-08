# Worker 提交确认超时的最小修复

日期：2026-10-28。任务：WORKER-COMMIT-CONFIRMATION-20261028。

## 根因与范围

PostgreSQL COMMIT 可能已经成功，但客户端在收到确认前超时。
原普通事件提交与已持久化事件投影路径直接抛出 TimeoutError，调用者无法区分
事务回滚和确认丢失；进度层随后可能将已有执行事实误分类为存储失败。
这是一条经真实 PostgreSQL 故障注入证明的风险路径，不宣称它解释所有历史事故。

复用两个共享提交入口，在 TimeoutError 后执行一次有界核对，不重复提交。
正常成功路径不增加查询。核对上限 1 秒，且不能突破原请求剩余期限。
不改变模型、高思考、v2、工具权限、搜索配置或 Trench 产品逻辑。

## 确认条件

- 重新核验 namespace、Session、预期序列和当前有效 LeaseFence。
- 流头必须恰好等于原 Event 序列；后续命令、取消或新 Turn 不允许被覆盖。
- 按原 event_id 读取并逐字段比较原 Event；读取前检查 payload 不超过 1 MiB。
- Session 和 Workspace 投影必须完整匹配本次提交的预期值。
- 对关联命令的启动/收尾边界，同时确认 started/handled 回执；收尾 pending
  必须已为 done。不从 Event 存在推断回执成功，旧/不完整回执保守拒绝确认。
- 核对末尾再次检查租约。核对只执行 SELECT（含共享锁），不补写任何事实。

确认成功返回原提交结果。无法确认抛出 WorkerCommitConfirmationPending，Worker
分类为 suspended / execution_commit_confirmation_pending / retryable=false。
不将不确定状态标记 completed，不重试模型、工具或原子写入。LeaseLostError
保留原优先级，不被包装成可继续执行的结果。

## 验证

隔离 PostgreSQL 17.5：60 passed、2 skipped（已有环境门控测试）；Ruff、目标模块
mypy、git diff --check 通过。新回归覆盖两个共享入口的提交确认丢失、回滚、后续
新事件、失效租约、确认读取失败、内容/投影不匹配、1 MiB 上限、父期限、正常
路径零额外确认，以及命令回执缺失。每次操作断言写入调用仅一次。

命令：

```sh
ZEBRA_TEST_POSTGRES_DSN=<isolated-postgres-dsn> .venv/bin/python -m pytest -q \
  tests/agent_storage/test_worker_commit_confirmation.py \
  tests/worker/test_commit_confirmation_errors.py \
  tests/agent_storage/test_postgres_workspaces.py \
  tests/worker/test_canonical_event_deadline.py \
  tests/worker/test_completion_recovery.py \
  tests/worker/test_execution_completion.py
```

候选镜像及运行中 Worker 均执行无网络、无模型检查，验证精确结果返回、异常暂停、
租约优先级及不重复写入。生产切换前要求有效租约、pending 命令、活动 Trench Turn
均为零。只替换 Worker 镜像，环境、安全配置、挂载和健康检查原样保留。

镜像：zebra-worker:commit-confirmation-20261028。
镜像 ID：sha256:5afd77012eed33bac6d61a251d16c5289d714d69f5a1c459c9ce14d51204b8dd。
数据库仍为 v105。两个受保护 Task 的事实哈希部署前后相同，所有 Trench Turn 的
请求、回答、状态、游标一致；其他服务容器配置与搜索/MCP 进程、冷却状态保持不变。

证据：.artifacts/worker-commit-confirmation-20261028/。
服务器回滚资料：/home/ubuntu/releases/20261028-commit-confirmation/，
deployment-plan.private.json 保存原 Compose 链；回滚仅恢复原 Worker 镜像。

## 明确边界

- 本次处理 TimeoutError，不把所有网络/数据库异常自动转成成功。
- 批量投影、外层工作单元最终 COMMIT 和其他聚合事务不在此次确认装饰器范围内。
- 原期限耗尽时不延长预算；无法确认就停止，不能承诺永远无暂停或失败。
- 数据库完全不可用时，暂停状态自身也可能暂时无法持久化；本修复不是全库容灾。
- 历史数据库锁竞争的具体持锁者仍未定位，未宣称已根治。
- 未重跑原 Run，没有新增模型、搜索请求或真实页面模型验收；完整仓库门禁未运行。

# Cloud Agent 通用强停

状态：Native 实现与隔离无模型验收完成；Cloud/Linux 显式启用。ERP、Trench 等业务只调用控制接口，
不实现进程终止、租约撤销或容器清理。本轮不部署线上、不运行原 Run、不请求模型或搜索。

## 接口

| 操作 | 接口 | 含义 |
| --- | --- | --- |
| 请求强停 | `POST /tasks/{task_id}/cancel`，`{"force":true}` | `202` 仅证明独立控制信号已持久化。 |
| 读取进度 | `GET /tasks/{task_id}/stop` | `200` 读取当前停止进度，不恢复或执行 Run。 |

每次请求均复用已验证的新鲜 Host Grant、`agent.run` 和当前 Task 的 issuer、应用、namespace、
principal、thread、workspace 校验。只限具体 Run 的 Grant 不得升级为整个 Task 的控制权限。
写入必须携带 `Idempotency-Key`（1–240 个可打印 ASCII 字符，不能为空白）；额外写入字段拒绝。

同一调用方、同一 key 返回原收据；同 key 不能改指另一 Task。不同 key 不重置已有停止操作。
原收据保持原样，进度 GET 返回最新状态。新鲜授权更新不会让已终止 Task 复活；继续业务必须显式新建
Task。普通取消和本地执行默认行为保持不变。

返回字段：`task_id`、`stop_id`、`request_accepted`、`state`、`resources_released`、
`execution`、`lease`、`sandbox`、`synchronization`、`error_code`。不返回 Grant、内部绑定或 PID。

| state | 含义 |
| --- | --- |
| `not_requested` | 尚无此 Task 的停止操作 |
| `requested` | 已持久化控制信号，尚未确认退出 |
| `stopping` | 正在终止、回收或同步 |
| `stopped` | 执行器退出、租约撤销、精确回收和权威状态同步均已确认 |
| `requires_reconciliation` | 证据不足或有界恢复耗尽；不假报释放，不重跑模型 |

只有完整确认才返回 `resources_released=true`；单独的 `done` 标签或取消文本不足以证明成功。
非法参数返回 400，权限拒绝返回 403/隐藏存在性的 404，幂等冲突返回 409。存储或提交响应不确定返回
503、`request_accepted=null`；调用方查询原操作，不能因此重发业务或模型任务。

[机器可读合同](contracts/cloud-force-stop-v1/contract.json)。业务适配器只负责新鲜授权、接口调用及状态展示。
已经完成的业务副作用不撤销；已送达外部供应商的请求不能保证被召回，未知结果不得自动重放。

## 闭环与边界

1. 复用 v117 无事件流 FK 的安全控制表，持久化 `watchdog/user_force_stop` 及不可变控制收据。
   受阻的 Session、事件流锁及 Redis 不参与停止准入。安全网其他写入者不能覆盖该标记。
2. Cloud Worker 显式使用独占执行器。启动/退出凭据按 Session + epoch + fencing token + owner
   持久化；控制监视/退出回执使用独立短超时连接，不借用任务的 I/O deadline/work unit；同一 fence 不能启动第二个执行器，旧执行器不能证明后继执行器退出。
3. `agent-runtime` 的私有 Linux supervisor 使用 subreaper 回收该执行器全部后代，包括另建进程组、
   双重 fork 的后代。只信任内核 ECHILD 确认后的私有退出收据；不扫描或杀共享 Worker、其他会话。
   未回收前保留子 PID 所有权，避免 reap 后 PID 重用误杀。
4. 独立推进器撤销租约，复用 `_target` / `_remove_exact` 的 daemon、ID、名称、标签与 scope 校验。
   Docker I/O 在 PostgreSQL 事务外。只清理记录在案的实例；保留工作区、成果和业务卷。
   未知创建结果继续保留义务，不能把一次查无容器当作永不晚到。
5. 资源终止/回收先于可能受阻的终态同步。同步复用有界命令读取及规范取消转换，保留 1 MiB 限制；
   已 completed/failed 的事实保持原样，只修复投影。活动 Turn/Session 写入原坐标的取消事实。
   并发的独立推进器互斥认领；崩溃后重入不重复取消、不重复业务执行。
6. 冻结委派链接及历史绑定验证子任务归属；跨 tenant、principal、workspace 或 issuer 的无效链接
   不传播停止。配置修订不能消除原 Task 的停止标记。推进时记住目标集合，避免租约撤销后遗失目标。

每批最多 4 个操作、8 次精确引擎操作；范围上限为 64 个委派 Task / 256 个活动或遗留资源分段。
达到范围上限、身份冲突、16 次无进展或 10 分钟未闭环时保留待核对状态。若规模超出这些上限，需增加
持久分页前沿和待处理索引，不能静默认证部分范围。控制收据/历史绑定须保留至对应 Task 结束归档。

进程隔离仅支持 Linux、原生 PostgreSQL 组合，默认不启用；未托管旧执行器、Worker 整体失联、内核不可杀
或退出收据缺失时不会宣称已释放资源。此验收不等于多机故障切换或生产 HA/SLA 认证。

## 配置与运行

Worker 沿用正常 Cloud 环境，设置 `ZEBRA_SESSION_PROCESS_FACTORY=default`。已有受信私有组合可设置
`module:factory`；该值由服务器配置，不从用户输入获取。实际子执行器复核配置摘要、namespace 和租约。
禁用时保持原执行路径。建议 Worker 容器启用 `init: true`。

独立进程使用相同的控制数据库、`ZEBRA_DEPLOYMENT_NAMESPACE`、受控 OCI endpoint/TLS 配置：

```sh
python -m zebra_agent_worker.runtime_cleanup_service
# 有界单批运行（仍不调用模型）
python -m zebra_agent_worker.runtime_cleanup_service --once
```

推进器只需要 Cloud/PostgreSQL 与 OCI 配置，不依赖模型密钥、搜索、S3 或 Memory Cursor 凭据。
启用隔离会增加每执行器两条生命周期收据、每活动执行器一条可重连的控制连接、0.5 秒一次元数据停止检查和子进程启动成本；不会逐 delta 写库。
高思考、v2、工具权限、DNS/SSRF 与请求取消路径不修改；本轮没有真实模型延迟或多机吞吐的收益声明。

## 无模型验收

主验收覆盖真实 PostgreSQL、真实 Linux `execute_isolated` 和 OCI 容器：

- 实际受信组合阶段卡死并持有 Session/stream 锁，另有逃逸进程组后代；控制信号仍能提交，全部后代被回收。
- 父 Worker 继续存活；另一会话的执行器、租约和已登记沙箱保持存活。
- 任务 I/O 已过期仍可停止；额外占住终态流锁，资源仍能先回收；接口保持同步待完成。释放锁后原操作同步闭环，重入不新增事件。
- 新鲜授权、越权、过期、Run 窄授权、重复 key、profile 修订、委派范围、迟到/错误 fence 回执及有界耗尽。
- 原有取消和精确清理回归包含错标签、失联创建写入、已缺失实例及晚到创建；完整完成结果不改为取消/失败。

运行前提供隔离 PG 的 `ZEBRA_TEST_POSTGRES_DSN`。真实容器测试额外显式设置
`ZEBRA_RUNTIME_CLEANUP_LIVE=1`、`ZEBRA_FORCE_STOP_LIVE=1`、
`ZEBRA_RUNTIME_CLEANUP_TEST_IMAGE`（已缓存、可运行 sleep 的镜像）、
`ZEBRA_FORCE_STOP_TEST_IMAGE`（与 uv.lock 依赖匹配的 Worker 镜像）、
`ZEBRA_FORCE_STOP_TEST_PG_CONTAINER`（已批准的隔离 PG 容器；共享其网络 namespace，不改变 PG 配置）。
日志不输出凭据，测试只删除自身带独立标记的容器/独有 schema，不下载镜像。

```sh
.venv/bin/pytest -q tests/agent_storage/test_postgres_force_stops.py \
  tests/agent_storage/test_postgres_force_stop_recovery.py \
  tests/agent_runtime/test_force_stop_live.py tests/api/test_cloud_force_stop_contract.py \
  tests/worker/test_session_process.py
```

本地验收镜像仅离线补齐了仓库已锁定/安装的 ag-ui-protocol 1.0.0，没有更改产品依赖。
旧草稿构建的部署镜像不包含最终闭环，不能直接拿来部署。

## 本轮验收记录（2026-10-30）

- 聚焦回归：99 passed / 2 skipped，117.98 秒。跳过的是既有 completion-reader 的
  两个可选 `header_scratch` 用例（未配置专用 DSN）；本次新增真实 PG/OCI 停止链路已运行。
- 实际私有执行器卡死并持有 Session/流锁；任务 I/O deadline 已过期，另有逃逸进程组子进程。
  请求后 2761.9 ms 确认退出；父 Worker 与另一 Task 的执行器、租约和沙箱仍在。
- 额外事件流锁阻止终态同步时，沙箱已清理且租约已撤销，但接口仍返回 pending/未释放。
  锁释放后原停止操作达到 `stopped`，四项证明完整；重复请求新增事件 0。
- Scoped Ruff、15 模块 mypy、runtime product boundary 通过。根 `make check` 被 15 个
  未改动的既有 ERP 文件大小超限阻断；没有扩大到这些文件的修复，也不声称全仓门禁全绿。
- 本地提交并集成 `cloud-agent`；不部署、不推送。上面的 opt-in 配置与独立回收器需在部署时
  显式启用；缺少退出证明时保守返回待核对，不能把旧运行时宣传成已具有强停闭环。

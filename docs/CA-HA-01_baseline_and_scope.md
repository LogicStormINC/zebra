# CA-HA-01 基线、依赖和后续范围

日期2026-10-31；状态：revision 2已完成单人文档复核，已授权合入并推送cloud-agent 1dd88bfd；非独立双人审查，未执行实现验证。
[DDD/SLO/F1合同](contracts/cloud-ha-v1/README.md) · [任务总表](CLOUD_HIGH_AVAILABILITY_TASKS_v1.md)。

## 1. 依赖核对

- CA-HA-00：GitHub cloud-agent d782039c，含摘取文档d7aabfaa与集成修正；本地主线已快进。
- 原f0762ca5仍在原分支保留；未直接merge其父97463d00a业务代码。
- 97463d00a通用强停候选尚未进入本次主线；04必须独立合入并重新验证，不能以历史99项
  定向验证替代当前集成树或生产证明。该文档方案不会触发其代码集成。
- 本卡只依赖00已集成，可在不运行服务的条件下明确合同；02–10全部保持Locked。
- HA实现启动前须另行授权、评审合同/路径并确认依赖进入cloud-agent，再领取Ready卡。

## 2. 本轮静态发现：确定事实与待验证项

| 编号 | 固定源位置 | 事实与实施含义 |
| --- | --- | --- |
| B-01 | apps/api/src/zebra_agent_api/api_status_mixin.py | health()固定200/ok，不证明依赖/准入就绪；02补合同与真实组合 |
| B-02 | deploy/helm/zebra-agent/templates/api-deployment.yaml；apps/api/src/zebra_agent_api/server.py | Helm直接启动uvicorn；池作用域在server.main入口。必须查清此组合是否绕过池，不能只见池文件就认定所有API请求有池保护 |
| B-03 | apps/worker/src/zebra_agent_worker/{loop,command_process_state}.py | migrated由持久cutover事实及发布/消费开关决定；不能把旧循环风险直接归因于新命令路径 |
| B-04 | apps/worker/src/zebra_agent_worker/worker_loop_service.py | 旧路径仅无ready时休眠，blocked候选是风险；03先复现实际启用路径，不能凭静态线索宣称故障已复现 |
| B-05 | packages/agent-storage/src/agent_storage/postgres/{leases,connection_pool,task_io}.py | 有完整fence与局部有界预算；需要计算全部进程/子执行器/控制路径总连接与失联恢复 |
| B-06 | deploy/helm/zebra-agent/templates/{api-deployment,worker-deployment}.yaml | API探针共用/health；Worker无探针、worker-id用release名；无跨节点分散。实例真实fence身份须另核对，不能直接判定ID冲突 |
| B-07 | apps/scheduler/src/zebra_agent_scheduler/main.py；postgres/task_schedule_firings.py | 复用原调度/领取；Helm未见Scheduler模板，需要多实例实际部署与原触发幂等证明 |
| B-08 | Runtime P5合同、SDK/BFF原GET合同 | 可复用原意图/unknown恢复；没有跨全部产品/生产故障域HA证据 |

未验证：生产K8s/云端拓扑、主备/备份、Redis角色及副本、对象持久策略、Broker撤销与缓存时限、
实际负载、网络RTT、各角色资源与连接数、真实cutover和隔离开关。上述未知项保持
阻塞相应验收，不填假参数或秘密，不启动Docker探测。

## 3. 后续文件边界清单

以下是可评审的候选写入范围，不是当前授权。现有文件已只读定位；“拟新增”为明确规划路径，
本轮不创建代码占位。某卡实际需要的文件应是该列表子集，扩展须先修卡。
每卡可更新自身合同/证据、注册表、PROGRESS和WORKLOG；禁止直接写另一个卡的实现。

| 卡 | 现有候选路径（相对仓库根） | 拟新增最小职责文件/证据 |
| --- | --- | --- |
| 02 | apps/api/src/zebra_agent_api/{http,http_host_auth,api_status_mixin,routes}.py；apps/worker/src/zebra_agent_worker/{main,loop,command_process,worker_loop_service}.py | apps/api/src/zebra_agent_api/health_readiness.py；apps/worker/src/zebra_agent_worker/worker_health.py；tests/api/test_cloud_ha_health.py；tests/worker/test_cloud_ha_health.py |
| 03 | apps/worker/src/zebra_agent_worker/worker_polling.py、worker_loop_service.py、command_process.py；packages/agent-storage/src/agent_storage/postgres/connection_pool.py、task_io.py；apps/api/src/zebra_agent_api/server.py；deploy/helm/zebra-agent/templates/api-deployment.yaml | tests/worker/test_cloud_ha_polling.py；tests/agent_storage/test_cloud_ha_budgets.py；入口池修复与08模板重叠须先合03、08只改剩余部分 |
| 04 | apps/worker/src/zebra_agent_worker/command_process.py；候选97463d00a的session_process.py、runtime_cleanup_service.py及agent-runtime/force_stop_cleanup.py、process_supervision.py尚未进入主线，当前只读依赖 | tests/worker/test_cloud_ha_drain.py；docs/evidence/ca-ha-04/；不授权将候选文件重复实现 |
| 05 | apps/worker/src/zebra_agent_worker/claims.py、recovery.py、lease_heartbeat.py；packages/agent-storage/src/agent_storage/postgres/leases.py | tests/worker/test_cloud_ha_takeover.py；tests/agent_storage/test_cloud_ha_fencing.py |
| 06 | packages/agent-storage/src/agent_storage/postgres/database.py、connection_pool.py、task_io.py；Redis/对象/身份精确子卡见下表，禁止整包写入 | tests/compose/cloud_ha_dependencies/；docs/runbooks/cloud-ha-dependencies.md；Redis/对象/Broker分子卡，不允许整包共享所有权 |
| 07 | apps/api/src/zebra_agent_api/ag_ui_checkpoint_tail.py、ag_ui_stream.py；apps/scheduler/src/zebra_agent_scheduler/main.py；packages/agent-storage/src/agent_storage/postgres/task_schedule_firings.py | tests/compose/cloud_ha_recovery/；跨仓库SDK/BFF必须先独立登记并冻结文件，当前无Go写权限 |
| 08 | deploy/helm/zebra-agent/values.yaml、values.schema.json；templates/api-deployment.yaml、worker-deployment.yaml、api-pdb.yaml、worker-pdb.yaml；tests/deploy/test_helm_chart.py | templates/scheduler-deployment.yaml；tests/deploy/test_cloud_ha_topology.py；不得写应用领域代码 |
| 09 | packages/agent-observability/src/agent_observability/execution_metrics.py、models.py | tests/compose/cloud_ha_capacity/；docs/runbooks/cloud-ha.md；实际已有指标不足才扩展，不新建并行指标服务 |
| 10 | scripts/build_release_evidence.py（仅实际证据格式需扩展时）；本合同/任务表 | tests/compose/cloud_ha_acceptance/；docs/evidence/ca-ha-10/；联合卡不授权修任意业务代码 |

06需先拆成以下互斥子卡再领取，所有子卡当前Locked：

| 子卡 | 候选现有写路径 | 复用/边界 |
| --- | --- | --- |
| 06A PostgreSQL | postgres/database.py、connection_pool.py、task_io.py（均在packages/agent-storage/src/agent_storage/下） | 03合入后再改；依赖基础设施主备隔离，应用不实现数据库选主 |
| 06B Redis | packages/agent-integrations/src/agent_integrations/redis_live_fanout.py、redis_live_fanout_async.py、redis_transient_capacity.py | live提示可补读不代表capacity授权/预算可降级；Redis memory/gateway.py归单独受影响路径，未确认使用不改 |
| 06C 对象 | packages/agent-storage/src/agent_storage/artifact_objects.py、artifact_object_reads.py、s3_error_mapping.py | 复用精确期望/原对象收据，不能以查无对象直接重传未知写入 |
| 06D 身份 | packages/agent-security/src/agent_security/jwt_adapter.py、host_grant.py；apps/api/src/zebra_agent_api/host_auth.py | 可用缓存不得扩大授权/撤销时效；Broker外部配置/部署先只读验证，不无差别改签发服务 |

上述子卡测试归tests/compose/cloud_ha_dependencies/，子卡须各自独占文件。
其他Host/BFF/对象类型的适配器若进入实际链路，先补精确路径与合同，再授权实施。
测试目录内仅允许该卡的故障驱动/断言/清单，不允许借测试包放生产实现。
核心domain/ports本轮均只读；若现有不变量不足，先独立领域合同卡，不在HTTP/Helm层补状态机。

## 4. 合同与启用矩阵

| 路径 | 静态可追踪 | 实际启用与限制 |
| --- | --- | --- |
| API factory/uvicorn与server.main | 可追踪组合入口 | Helm入口与池覆盖差异待03复核，不能直接加第二个全局池 |
| 旧Worker / migrated命令Worker | loop.py读取cutover与publish/consume flags | 两种模式都需兼容，生产cutover值未知 |
| 租约/Task I/O | 数据库时间/fence，部分独立deadline | 池/任务/控制分离须在当前组合证明 |
| 强停隔离 | 仅候选97463d00a代码/H证据 | 未合入，无当前部署启用证明；不自动开启 |
| 多副本/探针/拓扑 | 模板静态可见 | 副本数不代表跨节点或故障接管已验 |
| 身份/Readable/UI/审批 | 既有公开合同 | 凭据留BFF；续权、原GET和业务意图区别保持，不自动恢复过期权限 |

## 5. 交接与停止条件

本卡不冻结生产资源规格或认定环境达标；冻结的是E1目标、F1故障和测量合同。
修改E1、SLO、排除范围或不变量须提升合同revision，重新评审受影响验收。
本轮单人复核不冒称独立双人审查；01合入后02技术依赖满足，但当前仅[02前置文档](CA-HA-02_readiness_preflight.md)，无实现授权，仍Locked。
02/03共享Worker采样/控制接线，03须依赖02合入。02文件尺寸临界时仅抽取本职责，不能超限堆代码。
如需未合并强停实现、生产参数、重型环境或新domain行为，停在所属依赖，保留明确未验证项。
只允许轻量diff、JSON、链接、路径与任务一致性检查，完整make test/check未运行。

## 6. 本轮复核修正

revision 2修正执行fence与API控制CAS范围、原证明与可重建投影边界、
RTO探测/p99与DR水位口径、E1分型、故障子项重复次数、匿名健康最小信息与有界采样、
02真实HTTP鉴权/生命周期范围及02→03串行依赖。详见[复核记录](evidence/ca-ha-01/review.json)。

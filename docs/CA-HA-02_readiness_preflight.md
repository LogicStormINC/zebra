# CA-HA-02 任务与依赖核对（不实施）

日期2026-10-31；状态Locked：01 revision 2已合入并推送cloud-agent 1dd88bfd，技术前置满足，仍等待明确业务实现授权。
本轮只形成此文档，不领取In Progress，不创建代码占位，不运行环境。
依赖：[CA-HA-01 revision 2](contracts/cloud-ha-v1/README.md)、[逐卡范围](CA-HA-01_baseline_and_scope.md)。

## 1. 前置结论

- 00已合入cloud-agent d782039c；01复核以7e692719为输入，revision 2已随1dd88bfd合入主线。
- 02不依赖未合入的97463d00a强停实现；只观测现有退出/调度事实，不增加停止控制或接管动作。
- 03连接池/退避、04排空、06依赖HA、08探针部署均尚未实现。02不能声称这些能力已完成。
- 本轮授权只到复核/文档集成与依赖检查，不启动02业务实现；重型验收暂停指令继续有效。

## 2. DDD 与最小范围

复用既有状态/Ports，不新建HA聚合或平行健康权威。
API/Worker健康是技术观测，由apps适配并组合；当前Task授权、lease/fence、收据、
unknown、Coverage仍由原有上下文决定。一个Task等待审批/长工具调用不判整个Worker失活。

| 范围 | 精确候选文件 | 限定职责 |
| --- | --- | --- |
| API接线 | apps/api/src/zebra_agent_api/http.py、http_host_auth.py、routes.py、api_status_mixin.py | lifespan与精确GET路径接线、兼容/health、鉴权负面回归；不修改Task准入语义 |
| API新增 | apps/api/src/zebra_agent_api/health_readiness.py | 有界观测缓存/生命周期/非敏感状态，不查询完整历史，不建立第二全局池 |
| Worker接线 | apps/worker/src/zebra_agent_worker/main.py、loop.py、command_process.py、worker_loop_service.py | 既有控制tick、模式/能力与退出状态的观测，不改变调度/消费/恢复算法 |
| Worker新增 | apps/worker/src/zebra_agent_worker/worker_health.py | 进程本机只读快照与新鲜度；无公网端口/新业务控制面 |
| 回归 | tests/api/test_routes.py、test_host_auth_http.py、test_cloud_ha_health.py；tests/worker/test_loop.py、test_command_process.py、test_cloud_ha_health.py | 旧入口、实际HTTP鉴权链、两种Worker模式及状态新鲜度 |
| 文档证据 | docs/contracts/cloud-ha-v1/、docs/evidence/ca-ha-02/及注册表/进度/本卡 | 记录固定源、状态与未验证边界；有意义的新增测试须随实现提交 |

02禁止写packages/agent-core、agent-storage、业务BFF、Helm或强停候选文件。
需要新增底层Port/查询时先拆所属合同/适配器卡，更新依赖，不能在HTTP层写新领域规则。
03与02共享Worker接线文件，故03必须在02合入后再开始，不使用临时共享所有权。

静态尺寸：http.py/routes.py已500行，http_host_auth.py488、loop.py486、command_process.py488。
不得直接堆接线越过500行：仅抽取与健康组合直接相关的既有职责到上述专用模块，并保留
原测试与保护；不为省行删除鉴权/错误处理。若需更广职责拆分，先新任务，不扩大本卡。

## 3. API设计输入（当前未实现）

- 保持GET /health现有响应与消费者行为。
- 拟增GET /health/live：正常200，响应仅status=alive；不检查数据库/外部服务。
- 拟增GET /health/ready：200/status=ready；启动未完、缓存未知/过期、维护失败或排空时
  503/status=not_ready。公开响应不含依赖名、身份、实例、配置或拓扑；详细原因仅受控观测。
- 仅上述两个精确GET路径可无HostGrant探测。POST/相似前缀/任务路径仍按原鉴权执行，
  未实现方法应拒绝；不能用path.startswith('/health')形成匿名业务入口。
- 1s响应预算、观测最大年龄5s；后台依赖探测必须独立有界，DNS/libpq可能超时不得
  占住请求线程或无限创建后台线程。启动/退出须关闭本卡拥有的探测资源。
- 就绪只声明当前组合的可服务能力；依赖角色由实际配置决定，不要求所有可选插件/模型
  每次探针都在线。任一关键依赖无新鲜证据即不就绪，且服务端准入仍独立做当前门禁。

## 4. Worker与证明

区分进程响应、控制循环进展和可调度能力。快照初始unknown，采样者身份与当前进程绑定，
不能读取旧进程残留快照报ready；读取探针本身不能刷新更新时间。
旧循环和migrated模式均有确定性回归；生产cutover值未知，不能自动切换/启用新队列。
等待审批、空闲或合法长任务不应触发错误重启；控制无进展/能力失效不应靠独立假心跳掩盖。
SIGTERM只立即反映现有退出状态；真正排空/强停与资源证明仍归04，02不能假报resources_released。

## 5. 未来实施验收表

| 场景 | 必须结果 |
| --- | --- |
| 原/health、local/cloud、factory/真实HTTP入口 | 旧响应/认证行为保持；新增路由实际可到达，不仅直接调handler通过 |
| 匿名精确GET与恶意相似路径/方法 | 两个探针可访问，业务路径仍需当前权限，无信息泄露 |
| 启动、关键依赖失联/恢复、缓存过期 | 未知/过期503，恢复后新鲜200；不无限等待或重试业务 |
| 依赖阻塞/DNS慢、并发探针 | HTTP预算与后台队列有界，存活探针不连带失败 |
| 两Worker模式、长任务/HITL/空闲 | 存活/能力区分正确，不改变原Task、Run、Controller或收据 |
| 控制tick停滞、旧快照/进程重启、退出 | 不能假ready；读取不刷新，退出后不遗留本卡探测资源 |
| 文件边界与回退 | source≤500/test≤700；旧客户端不升级仍可用，不改历史证明 |

实施授权后先最小确定性回归，后完整make test/check和必要真实组合验证；禁止将mock健康
测试当生产HA证明。当前仅文档静态校验，不声称任何上述场景已运行/通过。

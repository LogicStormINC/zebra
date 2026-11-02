# CA-P7-03A：可信编排上下文与双工具授权

日期：2026-11-02。状态：Review，候选实现与定向验证通过，待主线接纳；基线 cloud-agent 1d3c21d3，独立分支
`codex/ca-p7-03a-trusted-context`。用户已授权本片，未授权生产启用或部署。

## 问题与范围

旧工具从模型参数读取 `_parent_task_id`、`_parent_binding_digest`、`_budget_*`、
`_parent_capabilities` 和 `_write_capabilities`；应用提案又用随机 UUID 替代真实父任务。
请求工具只有 run/node 坐标，未校验父任务归属；旧 request 返回随机 child ID，没有真实准入。
正常 Worker 入口未注入编排 runtime，因此本片不将这些潜在路径描述为现网已发生越权。

03A 修正工具到应用的信任边界，并修正共享资源校验器的空许可语义：空集合代表没有获准资源，不再放行任意 node resource_refs。03B 负责真实准入、持久预算与原收据，03C 接正常入口，
03D 做真实执行验收。本片不启用生产编排；既有普通任务与唤醒内部路径保持。

## DDD 用例与权威

- 上下文：Orchestration Control Plane；计划快照冻结真实 parent TaskId 与 binding digest。
- Actor：由 Worker 当前已认证/授权的父任务执行上下文绑定，模型不能声明。
- 命令：propose_plan 接计划内容；request_task 接 run_ref/node_key（仅坐标，不授予权限）。
- Domain：仍使用纯 PlanValidationContext/validate_plan，不读取 Worker、SQL 或全局配置。
- Application：每次两种命令都进入服务端授权 scope，获取当前权限/余额，再访问所属存储。
- Adapter：未来受信 Worker/PG 装配提供当前授权及事务连接；不是 HTTP/工具调用者注入。

## 最小实现

`OrchestrationRuntime(store, authorize=...)` 中的 authorize(action) 是受信应用装配端口，
每次调用返回 contextmanager，按 action 检查当前调用者执行该命令的权限，yield 不可变 OrchestrationAuthority：
真实父 UUID、binding digest、deployment_namespace、现有 PlanValidationContext。
缺少 scope/上下文、无效上下文或 namespace 与 store 不一致时失败关闭。
PlanValidationContext 的资源和发布角色集合在构造时冻结，避免外部可变集合别名改变权限。

工具不再传任何身份、预算或权限 kwargs；模型携带旧隐藏字段也不能覆盖服务端授权。
提案使用当前可信 validation 检查节点，再将同一真实 parent UUID/binding 封入快照。
请求在读取快照时核对 parent UUID 与 binding，namespace 由 scope 与 store 双重限制；
跨 namespace、同 namespace 跨 parent、旧 binding 均不得派发。

即使全部匹配，03A 的 request 也只返回类型化 dispatch-unavailable 失败：
无节点状态修改、无随机 child ID、无假成功。request 当前不实施节点 capability/预算再验证，
其无条件拒绝保证本片没有执行绕过；03B 开放前必须原子检查当前节点权限及预约/消费。
03B 必须用原持久准入收据替代该拒绝，
才能讨论开放。内部 loop 的 evaluate/complete_node 不冒充这两条 Agent Layer 授权命令。

## 当前授权与事务语义

scope 必须覆盖当前授权检查和该次读/写。未来持久 adapter 要把当前 task/binding/namespace、
权限、余额与写入线性化：同一有界数据库事务或已有等价 fencing，授权撤回与写入竞争有确定结果。
现有 PostgresOrchestrationStore 方法独立建连接；仅在外部套 contextmanager 不会自动共享事务。
B/C 必须提供实际绑定同连接/事务的 adapter 并用真实存储证明，不能直接接当前 store 宣称原子授权。
绑定到 runtime 的是 provider 而非一次性静态权限对象，不能缓存旧 context 当持续权限。

本片提供应用端口和确定性检查，不提供生产 PG 授权 adapter；不能据此声称已证明跨副本撤权。
测试内存 store/nullcontext 只验证调用契约，不能作为生产授权/事务实现。
不得持数据库锁调用外部准入。03B 的外部效果使用原意图和原收据对账；unknown 保留预约，
不能因断连/超时/重启释放额度或重新派发。03C 开放前需完成真实存储与跨进程验证。

`task_root_budget` 只读取批准的快照上限，本片不把它作为扣除既有预约/消费后的余额。
未来 provider 必须给出当前有效余额，验证聚合不能由工具参数扩大；预算并发预约与实际消费归03B。
无新增依赖、全局锁、进程内持久权威或队列，不声明 QPS/生产 HA。

## 兼容性

公开工具 schema 仍只描述计划内容或 run/node；旧隐藏授权参数从来不属于公开参数合同。
内部 runtime/port 的 propose 签名收窄，所有已知直接调用测试随之更新。
直接构造 runtime 而不绑定授权仍可用于内部观察/唤醒；两条外部命令默认拒绝。
旧快照/历史收据/Coverage 不迁移、不改写，不引入数据库 DDL。

## 本轮验收结果

最小回归必须覆盖：真实父 UUID/binding 精确保留；伪造身份/预算/权限无效；
缺失授权、撤权、namespace/parent/binding 不符双工具失败；请求拒绝无写；
scope 每次重新进入且异常时退出；无 runtime 普通工具路径仍失败关闭。

TDD：两条原始回归先失败（工具传模型授权 kwargs、随机父 ID），修复后通过；
资源安全补充的有效 red 为2失败/1通过，随后修复通过。首次夹具缺必填 max_parallelism 的
收集/结构错误已修正，不把它计作产品失败证据。
最终主代理独立执行 **161 passed in 1.93s**，包含整个 orchestration、工具、Worker wiring、
AG-UI projection 和架构边界。两轮只读规格/安全及质量评审均无剩余阻断。

实际命令（已有 Python 环境，PYTHONPATH 显式指向本工作树全部 packages/*/src、apps/*/src 及根目录）：

```bash
python -m pytest -q tests/agent_orchestration tests/agent_tools/test_orchestration_tools.py tests/worker/test_orchestration_wiring.py tests/agent_integrations/test_orchestration_projection_view.py tests/architecture/test_orchestration_boundaries.py
python -m ruff check <本片11个变更Python文件>
python -m mypy --follow-imports=silent <本片5个变更源文件>
git diff --check
```

Python 来自 `/Users/lukeding/.codex/worktrees/ca-p5-main-integration/zebra-agent/.venv/bin/python`；
已打印导入模块 __file__ 核对新工作树来源，不把旧 editable 安装的代码当候选。
Ruff 11文件通过，mypy5源通过；相对链接和diff检查通过。
未运行完整 make test/check、真实 PG/Worker/多副本或重型环境；没有部署/迁移。

[任务登记](AGENT_TASKS.md) · [当前进度](../PROGRESS.md)。

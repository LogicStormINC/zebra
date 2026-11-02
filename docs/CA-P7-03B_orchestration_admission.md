# CA-P7-03B：持久原准入、共享父预算与只读对账

日期：2026-11-02。状态：Review（候选实现与限定验证通过）；基线cloud-agent f7f74302（03A已授权整合）。
分支codex/ca-p7-03b-admission；无部署、生产迁移或03C正常入口装配。

## 不变量与权威

Orchestration应用拥有run/node准入意图及预算预约；Task/Event/Binding/RUN仍由原生现有
TaskAdmissionTransaction写入。模型只能给计划内容和run/node坐标，不能给父身份、子绑定或usage。
03A每次当前授权scope继续有效；03B实现数据库短事务，不把进程锁当跨副本权威。

原身份固定(namespace,parent Task,run,plan revision,node)，不随新工具调用/Attempt/重启变化。
完整snapshot摘要（不用旧投影plan_digest）及准入输入摘要、原child坐标和冻结parent binding必须一致；同身份异体拒绝。
同父Task所有run共享一个持久预算上限，pending/unknown按全额预约计费。

## 两个写事务与一次只读预检

第一阶段：进入当前受信授权，固定父/预算->run/node锁序，核对当前parent、binding、STOP及
节点权限/资源/预算。在同事务保存唯一原意图、child坐标/精确请求摘要和预约。
仅本次成功插入者拥有一次进入第二阶段的资格。既有原意图只读观察，不能因为prepared/404再派发。

第二阶段：重新核对当前授权与原冻结事实，复用现有atomic admission创建真实Task、Session、
Event、binding和初始RUN，将parent-child关系、node.child_task_id和原收据一起提交。
没有网络/模型调用在锁内；构造器只读可信快照/输入，不调用外部服务。
任一断点丢回复，只查询原请求；unknown保留原预约，不自动重跑/分配新child。
两阶段不得被调用方外层事务合并，ambient work unit须拒绝或明确排除。

复用现有PostgresDatabase + postgres_work_unit，借同namespace/DSN连接；
03A文档“每方法独立连接”指默认行为，已有work_unit可把嵌套adapter绑定同连接。
绑定同事务本身不授予权限，当前actor/parent权限仍由受信authorizer核对，默认无该装配则拒绝。

## 持久预算与结算

只新增明确父预算和节点原准入存储；不建立通用Saga/Repository/执行状态机。
固定父预算额度不随run变多而刷新；当前余额与持久可用额度均须覆盖本次新预约。authority另提供approved_budget当前总批准上限，
与扣除预约后的free余额分开；B必须显式提供，不能从静态余额猜测批准额。
第二阶段只使用已持有的原预约，不再重复索要一份free额度；仍检查所有已计费额度未超过当前批准。
`task_root_budget`快照上限不等于当前余额，不从模型参数取得任一额度。

终态结算只接受服务端可信usage来源。核对原child/binding/真实终态，实际消耗不得超过预约；当前child完整binding/lineage/node/终态/active segment在读取usage前后核对，
相同收据幂等，异体冲突。确认usage才将全额预约替换为实际支出并释放差额；
终态本身不证明零消耗，无usage时继续保留预约。真实Worker消费来源接线属03C，不伪称已上线。
通用Worker的BoundHostExecutionAuthorityResolver目前仍使用默认token/runtime额度，冻结较窄Host
限额不能证明实际消费已受限。因此B新增默认缺失的executor_budget_ready受信检查；
未接03C真实累计执行guard时拒绝新准入（不只隐藏UI按钮），测试用显式fixture检查代替。
03C必须完成跨Attempt不重置的token/time拒付/截止和可信usage来源，才能提供生产检查。

## 并发与恢复

父Task预算行锁限制同父竞争，不串行不同父任务。锁顺序、数据库statement/lock超时明确且有界，
外部接口不在锁内；可信child构造在事务外完成。
每事务lock_timeout=500ms、statement_timeout=3000ms；父原意图按索引SQL聚合为O(N)，
大父任务持续吞吐需在专门测量后升级事务计数，不声称当前达到生产高并发指标。节点原身份唯一约束兜底双连接/双进程；原结果查询仍检查当前权限与隔离。
STOP先提交时拒绝准入；并发STOP在最后检查后提交则由真实lineage的祖先STOP阻止child取得lease。
不让force_stop争用执行/事件锁；祖先查询现有32层上限保持，不能据此开放无界嵌套编排。
没有自动unknown重试或超时释放。迁移v120仅新增到一次性测试库，不改旧迁移/生产数据库。

## 验收

实施后记录：同节点并发唯一真实child（Task/binding/RUN/lineage/node一致），跨run预算不可超订，
同身份异体、越权/STOP/旧binding拒绝；准备后/提交后丢回复原只读对账、重启不重置；
usage重复/异体/超额/非终态/缺失的预约保持；异常阶段无部分child/假成功。
内存端口测试与真实PG分列，真实Worker/入口装配/生产HA保持03C/03D边界。


## 本轮验证与资源清理

- 主代理在最终源码独立运行：211 passed in14.47s，包含整个orchestration、工具/wiring/projection、
  架构边界、新真实PG准入以及旧orchestration/subagent/force-stop PG回归；不是生产Worker/HA验收。
- 变更9个Python文件Ruff通过，7源mypy --follow-imports=silent通过，链接/diff检查通过。
- 两轮只读规格/安全与预算评审均无剩余阻断。最初接口回归因缺admission参数失败，实施后通过；
  PG测试实际验证两个spawn进程、提交丢回复、回滚、原指纹冲突、预算跨run及tighten、usage异体、
  child状态/binding/segment变更拒绝和祖先STOP阻lease。
- 临时PG仅1CPU/512MiB/PID128/256MiB tmpfs；不启动完整旧环境。原dump、日志及unknown状态保存在
  `.artifacts/ca-p7-03b/`（本地私有证据），保存后精确移除owned容器，owner/run标签无残留。
- 没有执行完整make test/check、生产迁移、部署或实际模型/Worker消费；默认执行guard保持拒绝。

[机器验证记录](evidence/ca-p7-03b/validation.json)记录实际命令、源码哈希和清理边界。

# CA-P7-03C：普通Worker累计预算、可信usage与编排装配

日期：2026-11-02。状态：Review，功能候选待整合；分支codex/ca-p7-03c-worker-budget，基线7f1f499b。
03B已按用户授权整合。无部署、生产迁移或旧验收环境恢复。

## 03B整合事实

Native先有三笔已提交未推送的ERP文档（bc46c5db/08c93ce4/cadecdcb）。本轮命令未切入
新工作树，误先将这三笔文档推到cloud-agent；没有改业务代码或部署。随后正常merge03B381978f9，
仅PROGRESS/任务登记前置段冲突，保留两侧新增内容，源文件hash逐一与03B已验证证据一致。
整合commit7f1f499b已推cloud-agent，本地cloud-agent也ff到该提交。Overdoze main已ff到e34ecc4，
无关AGENTS.md字节保持。没有重写历史、删除引用或将历史211项验证冒充本轮实跑。

## 约束与所有权

Task/Event/Effect/Lease/预算事实属Native；Overdoze只管理意图与契约消费，不读Native业务表。
普通Worker预算以namespace+Task为主键，Attempt、Worker替换、lease代际和重启不能生成新额度。
执行模型、工具和使用回执的来源是受信运行时/transport，不是模型文字/客户端参数。
Domain仍独立于HTTP与SQL；具体应用用例和ports定义预算预约/结算，原Postgres适配及work_unit执行。

## 持久预算

每次真实模型发送前保存独立原预约，网络在锁外；响应丢失、缺usage、无效usage、解析失败或流中断
保留原预约。相同原请求不自动重发，重复原回执幂等、异体冲突。不能用新Attempt绕过unknown。

当前没有生产可信输入token counter：ModelTokenCounterPort无实际实现，字符估算/传输JSON字节
不能证明provider最终模板token上界。新增受信请求检查能力必须绑定最终exact bytes、请求摘要、
输入上界、输出上限及counter合同；实际发送必须与受检内容相同。未知provider/图像/服务端续接
无证明时失败关闭。没有此能力则executor readiness拒绝，不用fixture True或估算伪装生产证明。

provider usage必须校验非bool整数、非负、输入/输出/总数一致且不超过原预约；不从文本推测。
Task全部Attempt共享支出和pending预约；工具call稳定ID只计一次，unknown工具不能当零。
绑定/权限变化只能进一步收紧，不能擦掉历史消费或刷新原额度。

时间采用保守的首次执行数据库时间起算的Task绝对deadline，包含等待/恢复；不按新Attempt刷新。
每次模型/工具/Runtime边界检查当前fence、binding、STOP和剩余时间，实际I/O携带剩余deadline，
stream回调和结果提交也检查。超时/断连不能推断远端效果未发生，原预约继续保留。
这不是声称外部provider物理计算可被瞬间撤回；后续效果/输出须拒绝，未知远端只对账。

## 正常入口与可信usage

真实orchestrator由受信已发布Definition/Version/digest确认，不以模型自报/profile字符串授权。
普通非orchestrator无编排工具端口；child使用真实发布角色snapshot、原binding和初始RUN。
03B authorize每个短事务检查当前parent/lease/STOP并读取批准上限与真实free余额，独立写阶段不嵌入外层事务。

实际budget guard及可信请求计数能力就绪才可向03B提供executor readiness。
usage_reader只在真实child终态、原binding/lineage/segment不漂移且所有调用均有确定回执时返回usage；
缺失/unknown仍返回None，03B不释放预约。默认外部模型若缺受信计数合同仍不开放。

## 完成、失败与恢复

原run/revision/node/child坐标固定，终态更新CAS，同终态重复幂等、不同终态冲突。
持久化scheduler失败传播/阻塞/skip决策；retry_once不得偷偷为同节点派发第二个孩子。
结算恢复有界，独立于delegation terminal标志，不能因为usage晚到而永久丢掉重试入口。
生产synthesize要求当前持久gate证据，缺证据或失败拒绝；模型自报完成不能替代工具/审核事实。

## 验收边界

主代理独立聚合 **333 passed / 0 failed / 0 skipped（35.53s）**，Ruff通过，24个变更源文件mypy通过；
验证前后所有变更Python文件SHA一致。命令/哈希见[机器证据](evidence/ca-p7-03c/validation.json)。
覆盖普通Worker累计额度/零限额/父子共享、两spawn进程争用、Attempt/重启、unknown模型/工具、
严格usage/stream、时间截止、真实Registry角色/版本、普通入口装配、原revision终态CAS、失败策略、
active-segment rollover晚到usage及原委派/强停回归。最终源码安全复核无范围内阻断。

真实部分：独立PostgreSQL、Task/Lease/Registry/准入/账本与实际模型gateway类；外部wire为MockTransport，
输入计数能力为显式fixture；SessionExecutionService用例的Runtime/context/progress/recorders/finalization
仍为既有fixture。不能把局部正常入口接线冒充完整Worker进程/跨仓实际模型执行验收。
当前生产装配未安装可信counter，亦未安装持久完成gate producer/reader；因此默认外部模型/最终synthesis
仍分别拒绝。后续必须提供实际可信能力与03D跨仓证据，P7整体不关闭。

v121为本候选新增迁移；开发期间候选修订用独立新测试库验证，不改任何已应用migration ledger/checksum。
唯一owned PG已停止并精确移除（含其可重建卷），全部三个测试库原收据/unknown通过pg_dumpall、日志、
资源inspect保存在工作树.artifacts/ca-p7-03c；dump SHA和零残留见机器证据。没有恢复旧环境、
修改业务容器、部署或生产迁移。清理后磁盘可用133GiB、memory_pressure free68%。

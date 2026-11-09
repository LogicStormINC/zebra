# CA-P3-02F — Readable 值的原生绑定准入与恢复

2026-10-22；Owner Luke Ding。依赖已发布 CA-P3-02E。
[机器合同](contracts/client-state-admission/contract.json) · [证据](evidence/ca-p3-02f/validation.json)。

## 复用和边界

已有 AG-UI RunAgentInput.state、原生 Profile schema/ClientSession/RunBinding、
SessionCommand CAS/幂等、持久命令事件与 Worker Context 恢复能够承载页面值。
本片复用这些路径，不新增上传接口、数据库表、执行聚合、Go 代理或浏览器原生凭据。
客户端状态是经过校验的交互输入，仍是不可信上下文，不是业务事实、工具权限或 Coverage 证明。

本片是 SDK 值通道的原生前置：既有 Hook 仍只上传名称/revision，未改其代码或旧 pin。
可信 BFF/SDK 命令提交、模型实际消费和真实产品云身份需随后独立验收。
本片不部署、不迁移生产数据、不发布 npm、不整合主线。

## 公开协议

`GET /capabilities/runtime` 增加 `client_state_admission_contract_version`：Client Plane 可用为 1，否则 0。
复用 `POST /agui/commands` 或 `/agui/threads/{threadId}/runs/{runId}/commands`，
原有 action/threadId/runId/expectedRevision/Idempotency-Key 和 RunAgentInput 形态保持。
有界 `input.state` 为 readable 名称到页面值的映射；不能混入服务端配置域。

input.forwardedProps 严格允许以下字段：

| 字段 | 来源/约束 |
| --- | --- |
| clientStateVersion | 整数 1，布尔值和未知版本拒绝 |
| frontendAppId、clientSessionId | 所属原生 Session 的公开定位事实 |
| uiRevision | 当前实际 mount 与 Session 的整数 revision |
| profileDigest | Session 固定且仍 published 的 Profile |
| mountedSnapshotDigest | 当前 mount、Session 指针与 RunBinding 的同一摘要 |
| clientBindingDigest | 当前精确 Task/Run/Session binding 摘要 |

BFF 通过专用 X-Zebra-Client-Session 提供原生 Session credential；cloud 另外要求已有独立验签的
HostGrant 与当前签名主体、Host/namespace/Origin，以及 agent.run 的精确 Task/Run 权限。
秘密不能放 forwardedProps，未知字段拒绝。Key/公开 ID/digest/版本字段本身均不授予访问权。
Profile 不按 latest 查找，也不能借用其它产品/App 的绑定。
输入 state 的名称必须已经 mount；声明的工具同时受 mount 与 RunBinding.allowed_actions 限制，
值继续按固定 Profile 的 readable schema 和每项字节预算校验。
本协议不授予 Controller；UI Effect 仍独立受原生租约/fence/当前 Task 权限约束，
状态输入不选择、接管或替换 Worker 的 Controller。

## 校验、持久化和恢复

原始 JSON 在协议模型归一化之前限制为对象、有限数值、最多 64 KiB、32 层和 4096 个值/容器节点，
避免 NaN 变为 null 后静默接受，或在脱敏/递归 schema 校验前耗尽资源。
新输入还拒绝 NUL 和非 UTF-8 Unicode 标量文本，避免 JSONB 写入失败；合法中文、Emoji 与组合字符保持原值。该规则不追溯修改历史快照。
复用一份 Core 原生敏感键脱敏规则，不另造 Go/JS 摘要或脱敏权威；这不是通用内容秘密检测。
业务 BFF/开发者仍须按 Profile 只提供允许进入模型的页面字段，不上传凭据。
命令 state 和 client.state_snapshot 仅保存脱敏值及原生摘要、redacted_keys 和明确的版本事实。
合法 __redacted__ 哨兵可进入 Worker 恢复和不可信 Context；未脱敏原值仍拒绝。
新输入先验证原始 schema，再把负零及整数值浮点数按 JSON 十进制字面量规范化为整数，
随后复核每项/总字节预算、计算摘要并持久化，避免 PostgreSQL JSONB 改写数值表示后恢复摘要漂移。
普通非整数有限浮点数保留；不更改历史状态摘要算法，也不自动修复既有不一致历史。
空快照明确替换 Context 和 /client 投影，不复活前一次页面值。

请求结构上限只控制新的输入，不追溯套用到旧事件恢复。旧事件、Task/Bundle/Profile/收据与
Coverage 不重写；仍使用原来的历史字节预算、摘要复核与原始秘密拒绝规则。
local legacy/headless 路径保留。cloud 的显式前端挂载命令必须升级版本 1，
不能在缺少版本、凭据、有效 Session 或 Client Plane 时静默降级为成功。
无前端声明的服务端配置 state 保持原本含义。

## 并发与故障承诺

Session、mount、Profile、RunBinding 和 Task 是现有独立权威，只读查询不持新锁、不新增状态写入。
混合或陈旧事实拒绝；依赖故障返回 503，不把不可用改成空状态/成功。
随后仍由现有命令 CAS/幂等和提交授权决定命令事件的提交；重放同一命令不追加第二次事件。
这是准入时观察的不可变交互快照，不是跨库线性化、零撤销窗口或持续跟踪最新 UI 的保证。
快照进入历史后不因页面 remount 改写，实际动作继续由当前执行权限检查。
只读原生 Registry，不新增业务 HTTP 调用或全局锁；沿用已有 Registry 连接/查询期限，
不把局部状态预算或 API 多副本、SQLite 重开证明称作端到端期限/生产 HA。
准入 capability 也不是 Worker fleet 版本证明；脱敏恢复需选择同一兼容 release 的 API/Core/Worker，
不能把新 API 与仍含旧恢复缺陷的 Worker 混用并宣称已验收。

## 验证

API 旧实现先复现 16 项失败；定向回归覆盖绑定/凭据/版本/权限委托/依赖失败和有界 JSON。
真实 SQLite SessionCommand 写入、事件重开、幂等重放、Worker 恢复及 Context 编译验证脱敏/稳定快照；
注册与挂载事实在此组 API 测试中使用现有内存 registry fixture，不作为 PostgreSQL/云身份联调证明。
历史结构较宽快照仍能恢复；空快照 AG-UI 投影明确清除。另以独享 PG17 的只读 JSONB 往返复现旧数字摘要漂移，再验证新准入、相同摘要和 Worker 恢复；
不执行表创建或迁移，且不把此项称为 PG Registry/命令事务/HA 验收。最终 make test/check 结果见正式证据。
后续通过已固定合同接 SDK/BFF 值提交，不把当前名称登记或本前置检查标作产品全链路完成。

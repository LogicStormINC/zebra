# CA-P3-02G — SDK/BFF Readable 值提交与联合验收

2026-10-22；Owner Luke Ding。[合同](contracts/sdk-readable-commands/contract.json) · [证据](evidence/ca-p3-02g/validation.json)。

## 责任与不变量

复用已发布 fb72ef6f 的 client-state-admission/1、surface metadata/1、SDK 挂载调度、
原生 SessionCommand CAS/幂等事件和 Worker Context。没有新上传接口、执行聚合、Go 代理或表。
SDK 注册表管理页面值生命周期；业务 BFF 管当前业务身份、Origin/CSRF 和资源映射，持有原生凭据。
Python 继续决定绑定、Profile schema、脱敏、摘要、持久命令与执行；SDK 不重算原生摘要。
页面值属于不可信上下文，不能充当业务事实、工具授权、Controller 或 Coverage 证明。

| 不变量 | 检查位置 | 失败行为 |
| --- | --- | --- |
| 显式 bff + clientStateVersion1 + surfaceMetadataVersion1 | SDK 配置/原生 capability | 拒绝；不回退 |
| 名称唯一、值是有界 JSON、更新/卸载随 Hook 生命周期 | 注册与命令快照 | 拒绝重复、畸形或缺失值；卸载清空 |
| 实际挂载完成后捕获值；重挂载等在途命令结束 | 原 Runtime mount/jobs | 有界排空；不混合新旧绑定 |
| 当前身份/Origin/资源有效，公开观察与私有映射一致 | 可信 BFF | 拒绝调用方授权/转发字段 |
| 绑定、CAS、幂等及最终提交权限由原生决定 | 原命令链 | 原生错误；未知不伪装成功 |

跨 SDK/BFF/原生没有新分布式事务；翻译后仍由原生再检。
这是观察快照，不保证跨库线性化撤销、持续最新 UI 或零撤销窗口。
Controller 的租约/fence/收据权限不受本片扩张。

## 开发者使用

已有业务登录/接入流程返回无秘密 BFF 配置，明确两项版本均为 1。
`useZebraReadable('app.ui.route', {route, selectedId})` 登记值；更新重挂载，卸载移除。
`useZebraReadableCommand()` 返回一次提交函数：

```ts
const submit = useZebraReadableCommand();
await submit({action: 'run', expectedRevision: currentNativeRevision,
  idempotencyKey: crypto.randomUUID(), input: {messages: []}});
```

expectedRevision 来自当前 Task/Segment 的可信读取，不能拿 UI revision 代替。
只接受 run/resume；resume 必须提供原生 resume 输入，run 不接受 resume。
浏览器 input 只允许 messages/resume，SDK 填 state 和当前公开观察；不能加入 tools、state、
forwardedProps 或目标标识。消息内容继续由原生 AG-UI 输入合同验证。

BFF 固定同源资源路由先检查当前身份和资源权限、Origin/CSRF，读取私有映射，
确认 Runtime client_state_admission_contract_version=1，再调用
`nativeReadableCommand(body, trustedSurface)`。函数仅做严格字段/观察匹配翻译，
不提供登录、授权、HTTP 转发或凭据托管，不能直接当生产 BFF。
BFF 保留 Idempotency-Key，以服务器持有的 Session credential 与 cloud HostGrant 调现有命令；
原生 duplicate 对应同一 commandId，可映射为 accepted。只返回 status/commandId，禁止返回秘密。

accepted 只证明持久意图已接纳，不代表模型执行或完成。409 不自动改 revision 或重发。
网络、5xx、超时、缺少合法 commandId 和畸形成功响应均为 unknown；SDK 不重试并断开，不释放 Controller。
可信 BFF 必须用原始请求及同一幂等身份对账，不能拿新页面值当原请求重试；本片未新增持久对账器。
浏览器不存储页面值、原生 Token、Grant 或 fence；既有收据恢复存储语义保持。

## 数据与兼容

注册与提交时复制 JSON，拒绝 undefined、Date、函数、非有限数、循环、稀疏数组和非法文本。
预算为 64 KiB、32 层、4096 节点；原生仍是最终 schema/字节预算/脱敏与 canonical 摘要权威。
这不是通用秘密内容检测；开发者必须只登记允许进入模型的字段。
空快照明确清除原生 Context 与投影；后续 UI 更新不改写历史命令。
旧未协商 legacy/BFF 保留 names/revision 行为；旧 SDK/pin/证据、原生生产 Python、历史和 Coverage 不改写。

## 验收与限制

SDK 回归覆盖注册/名称切换/StrictMode/复制/卸载、排空、严格字段与错误/unknown。
完整 verify 含 131 测试、React18/19 消费、包检查、Chromium/WebKit 和 Next hydration。
联合验收使用独享 PG17 注册/挂载/Effect 事务、真实 SQLite Task/命令事件；
每次读取重开适配器，再走当前 Worker recovery/ContextCompiler。
两个浏览器各验证 3 个值快照、幂等不重复追加、陈旧 CAS/伪造观察拒绝、历史稳定及空状态清除；
既有各 2 个动作、收据重放与 2 个恢复命令继续验证，秘密不进入 BFF 响应/DOM/存储。

这是参考 Cookie 登录、local compatibility 原生权威、单主机私有映射；
不等于生产业务 IdP/Go Broker/cloud 签名身份、共享 CAS 多副本 BFF、完整模型 harness 或 HA 认证。
参考 BFF busy guard 仅覆盖单进程测试；生产须复用业务自己的共享 CAS/会话及失败对账协议。
可选 Docker/浏览器验收不隐式加入普通 make test/check。
不部署、不执行生产迁移、不发布 npm、不整合主线；Overdoze 消费 pin 单独验收。

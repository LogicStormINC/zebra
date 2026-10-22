# CA-P3-02E — SDK 同步挂载与原生浏览器验收

Owner Luke Ding；2026-10-22。依赖已发布 CA-P3-02D，保持 Python Runtime 执行权威。
[机器合同](contracts/sdk-surface-sync/contract.json) · [验证记录](evidence/ca-p3-02e/validation.json)。

## 接入与 DDD 边界

业务 BFF 通过公开原生 client-surface 接口管理所属 Session/Task/Run；
原生 Session credential、HostGrant 和 Controller fence 只在可信服务端保管。
浏览器使用既有相对 BFF 路径、业务 HttpOnly Cookie 与公开绑定事实，不直连原生秘密接口。
新增 `surfaceMetadataVersion: 1` 显式启用同步协议，必须传实际准入后的 `initialUiRevision`、
Profile、Task/Run/Binding 和原生 canonical action digest map，不能固定 fixture 数值或浏览器重算摘要。
角色字段仅为显示/行为提示，业务 BFF 和原生当前权限仍是授权边界。
BFF 必须先确认所选同一 native release 的 `client_surface_metadata_contract_version` 为 1，
未支持时拒绝本协议接入，不自动回退到忽略 metadata 的旧模式。

本片不创建新聚合、身份体系、Go 执行代理或存储表。SDK 复用现有状态存储、动作注册、
回执重试与 mount 合并机制。未协商 BFF 与旧 DI/legacy/SSE 行为保留；
旧模式不会消费新原生 metadata，真实 D 接入应显式选择本协议。

## 生命周期与故障处理

1. 首次实际 SDK mount 完成前暂停动作、poll、heartbeat。
2. mount 开始即暂停新工作，等待已开始的动作、poll、heartbeat 及其回执完成，最多 5 秒。
3. 持久 pending receipt 或重启遗留 inflight 未明确对账时拒绝 remount，保留原记录。
4. 排空后递增 UI revision，向 BFF 发出一次 mount，BFF 使用所属目标调用组合原生接口。
5. BFF 在原生调用前记录未知窗口，成功后先持久保存新的 fence/绑定，再回传严格公开字段。
6. SDK 有界读取最多 64 KiB/4096 chunks，校验字段白名单、版本、Profile/UI/绑定 ID/角色、
   snapshot 相等、binding revision 前进、摘要改变与 canonical map 收窄，再替换本地绑定坐标。
7. 非法、超时、失败或未知响应会断开，不自动重试 mount 或 release。BFF 必须通过可信流程处理未知状态。

正常卸载仍释放当前 Controller；已经未知断开的 runtime 不因 React 错误处理再次释放。
旧 action digest 的 Effect 不能在新绑定执行；原生 fence/当前授权仍会最终拒绝过期操作。
SDK 只排空自己跟踪的工作，不保证跨 Tab、外部未取出的 Effect 或任意刷新时 UI exactly-once。
JS handler 无法强制撤回；超过排空期限即断开，保留恢复信息，业务负责幂等动作和人工/可信对账。

## BFF 实施要求

同一 surface 的 mount、heartbeat、receipt、release 必须使用同一当前服务端映射并串行协调。
生产映射需要共享持久 CAS/租约和当前业务身份、Origin、资源、撤销验证；不能用进程内锁提供 HA。
原生组合 mount/bind/lease 仍是独立提交；响应只证明当前观察，不是未来权限或跨请求线性化承诺。
未知结果禁止自动重试或使用旧 fence；Observer 切换须显式处理旧 Controller，不能靠角色字段释放。

`native-surface-bff.mjs` 仅为隔离单主机验收参考：私有 JSON 先 fsync 再 rename，
每请求重读，进程内 busy 返回 409；它的扩展上限是单主机，无多副本一致性保证，生产应改用共享 CAS 存储。
fixture Cookie 登录不是业务 IdP，native test/local compatibility 身份也不是 Go Broker/HostGrant 云验收。
无请求中日志输出秘密；临时文件 0600，容器和临时目录只清理本次拥有的资源。

## 验证与后续

SDK 回归覆盖新绑定实际执行、挂载暂停、非法/秘密字段、旧工作排空、未知恢复、首次挂载门禁、
旧绑定拒绝、超长响应与迟到成功不复活。保留全部旧 SDK 包、React 消费和浏览器矩阵。
可运行 `volta run --node 22.23.1 pnpm -C sdks/typescript verify`。

先构建 SDK 后运行 `volta run --node 22.23.1 pnpm -C sdks/typescript test:native-surface`：
自动创建独享 PG17，真实 Python RouteAdapter HTTP、PG Session/Binding/Lease/Effect/Receipt、
Worker ClientToolGateway 调度、React StrictMode hooks，Chromium/WebKit 执行动作、
原生提交后响应丢失重试、同名动作 remount、秘密隔离和业务会话失效。
持久 resume command 的产生不等于完整 Worker harness/模型消费完成。

前端管理页面保持 mock；历史数据、Coverage、Python 生产源、既有合同和证据均不重写。
后续真实业务 BFF + Go Broker 云身份、共享存储多副本/故障恢复及 readable value 上下文消费需独立验收。
本片不部署、不执行生产迁移、不发布 npm、不整合 main/cloud-agent。

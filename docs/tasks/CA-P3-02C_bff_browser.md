# CA-P3-02C — 显式 BFF 浏览器 SDK 模式

2026-10-22；Owner Luke Ding；独立功能分支，管理前端mock保持，不部署/迁移。

## 设计、不变量和权威

复用ZebraClientRuntime的注册、Effect去重、UI revision、待发收据与停止机制。
新增mode=bff显式配置；原有mode省略/legacy与原生Session credential/fence配置保持。
BFF配置只含公开Session/Task/Run/Binding/Profile事实、controller展示位、同源相对surface URL和可选存储/fetch。
不创建假credential通过旧校验；BFF模式禁止提供原生secret、HostGrant或SSE配置。
不增身份Token，业务登录/HttpOnly Cookie及CSRF由业务BFF提供，Agent三字段认证合同保持。

业务BFF必须独立验证当前业务登录/Agent身份/Origin与CSRF，将surface locator映射到服务端固定的
产品/App/Session/Task/Run和Controller资格；浏览器所有ID/role/body都不是授权。
BFF自行换取每请求HostGrant，注入原生Session credential/fence并调用既有原生公开接口。
只返回脱敏公开事实，不向浏览器返回原生secret。Go管理服务不进入逐次工具执行循环。
本片提供浏览器SDK协议与隔离BFF wire fixture，不提供通用生产BFF或共享数据库中的业务会话映射。

## 浏览器请求和生命周期

baseUrl必须是有界的同源相对surface前缀，无query/hash/编码/跳转路径。
只允许本Session的mount/effects/heartbeat/release和合法Effect receipt路径/方法；
禁止Authorization、Cookie、Origin、Host、X-Zebra-Client-Session、X-Zebra-Client-Fence等手动凭据/代理头。
浏览器使用same-origin Cookie/fetch mode、redirect=error、no-store和每请求5秒期限。
业务BFF仍需独立限制路由、请求/响应大小与当前授权，SDK校验不是服务端安全边界。
BFF v1只轮询，不默默复用未经定义的流协议；legacy SSE保留。

UI状态是connecting/ready/unavailable/stopped，独立于原生执行/Controller权威。
已注册mount完成、pending读取成功后才能ready；依赖失败进入unavailable，认证/资源拒绝停止。
React订阅实际runtime状态，不能仅因start Promise resolve就宣称ready。
状态公开联合类型新增unavailable，旧三态穷举调用者需要适配；旧DI必填secret类型保留。
Observer heartbeat只续Session，不携Controller坐标或申领围栏。
轮询/heartbeat各至多一个活动周期；收据保留原有限重试、同effect/key/result、未知结果不重做动作。
请求deadline不能当成执行已失败；业务写入unknown仍需原业务操作ID对账。
sessionStorage去重/待发结果仍是每tab恢复提示，不是授权；不可用时只有内存去重，不提供跨刷新exactly-once。

## 本片验收和后续

先红绿回归BFF无原生secret、错误就绪、跨Origin/路径/方法、无权停止与Observer。
SDK编译/已有单测/包与消费兼容门禁、Chromium/WebKit实际Hook注册/动作/回执/错误恢复，
再根make test/check及源码/Coverage保持。浏览器使用独立同源BFF wire fixture，
不将fixture响应当作真实IdP/Runtime/Worker/Eval/Coverage证据。

Readable只保留现有名称和revision注册，不增加值上传、上下文消费或完整多Run列表承诺。
原生公开admission当前不直接返回actionContractDigests map；真实接入还须补原生公开摘要事实，
明确Hook再次mount与RunBinding/Controller fence的同步；不能盲算Python摘要或使用fixture常量冒充。
BFF应把真实admission.ui_revision传为initialUiRevision，并按原生事实同步绑定/围栏，不隐式沿用旧摘要。
后续先补上述原生metadata/生命周期与真实业务BFF持久映射，再补Readable值schema/权限/字节/有效期/消费合同，
再做成对Python Runtime/浏览器/断线/unknown全链路；完整P3、P4分发和P5部署仍后续。

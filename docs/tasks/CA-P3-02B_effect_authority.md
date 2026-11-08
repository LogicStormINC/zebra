# CA-P3-02B — UI Effect 的当前 Task/Run 授权

2026-10-22；Owner Luke Ding；CA-P3-02A之后的独立前置，前端保持mock，未部署。
[任务](AGENT_TASKS.md) · [公开语义合同](contracts/client-effect-authority/contract.json)。

## 缺口和修复

Client Session绑定签名主体/Host/namespace/Origin，并不证明当前HostGrant允许读取或提交
该Session所有Task/Run的Effect。此前Effect列表、详情和回执只检验Session归属，
同一主体换成其它线程、Run或签发者的已验签上下文，仍可读取原参数或提交收据。

复用ClientEffectRequest不可变task_id/run_id和已有task_access_response，在共同的Effect适配模块
检查当前签名principal、Host/namespace/Origin、issuer、opaque thread与精确Run；
三个入口都使用同一检查，授权发生在序列化参数、解析回执和调用收据服务之前。
这是现有原生执行上下文的不变量，不新建聚合、状态机、存储表或Go权限模型。

## 公开入口

- GET /v1/client-sessions/{sessionId}/effects：当前授权的有界pending集合。
- GET /v1/client-effects/{effectId}：当前授权的状态/摘要/期限；无业务结果正文。
- POST /v1/client-effects/{effectId}/receipts：当前授权加既有Controller/fence/收据规则。

cloud请求必须同时携带新的有效HostGrant和同一签名主体的X-Zebra-Client-Session。
要求agent.run，不能只凭event.read或旧Session凭据继承Task执行授权；Authorization仍专用于HostGrant。
回执另外保留Idempotency-Key与X-Zebra-Client-Fence。BFF不得把浏览器提供的Host/URL/Session/fence
当作可信路由，也不能让Publishable Key、identity_key或bootstrap binding ID替代认证。

列表先验证签名scope，即使没有pending记录也不静默接受无权请求。
既有最多50条候选逐项授权，404资源不匹配仅省略，不返回其参数、数量或ID；
403/409/503等授权/投影依赖错误中止整个响应，不把数据库错误当成空列表。
同一请求相同Task/Run复用一次检查，后续请求重新读取，不能跨请求缓存授权。
50是原始候选上限，不是完整分页；前50条都属于其它Run时可能暂时看不到后续授权项。
需要完整多Run轮询时另立有界scoped存储游标合同，不能把本片宣称为完整列表。
详情/回执404统一unknown_effect，不泄露该Effect对应的Task身份。

## 结果对账与兼容

收据仍由现有ClientEffectReceiptService和PostgreSQL原子Port处理，原有请求摘要、Controller fence、
UI revision、expiry、语义一致性和receipt/terminal/resume command事务不变。
已提交的历史收据重放也重新核对当前Task/Run授权；不会因重放而回放业务动作或创建第二个恢复命令。
授权属于请求预检；本片不声称与TaskBinding并发更新处于同一原子事务。
若要求提交时强撤权，需另行扩展原生原子Port；既有收据原子性不等于跨聚合撤权线性化。
回执HTTP响应丢失后，在当前授权下读取原Effect状态，必要时重发同一effect/idempotency key及一致结果。
详情接口不返回已存结果，不能据此重建丢失的业务返回值；业务unknown仍需自己的操作ID和结果查询。
本片只证明恢复命令耐久入队，不证明Worker消费后完成任务，也不证明浏览器动作真实发生。

本地开发保留原Session授权路径；已有数据/历史收据/Coverage不改写，不新增迁移或默认授权。
缺少当前TaskBinding归属证明的旧cloud Effect按404拒绝，不靠旧Session凭据、自动回填或猜测主体绕过；
上线前盘点这类旧任务，单独制定受权接入/历史读取方案，本片不生产迁移。
生产依赖本检查前必须升级/排空所有处理Effect的旧API/BFF副本；混用旧二进制仍有旧入口风险。
既有Profile撤销只对已声明的准入路径生效，本片不新增运行中Effect立即取消或推送撤销保证。
已签HostGrant仍有自身有效期窗口，平台撤销不等于原生立即失效。

## 验证和下一片

[机器证据](evidence/ca-p3-02b/validation.json)记录红绿回归、真实PG和完整门禁。
专项使用实际Broker签名的基础grant，经已验签上下文故障注入验证边界；
不是针对线上IdP/BFF的认证验收。PG专项使用新建独享容器，真实TaskBinding/Effect/Receipt/Controller存储，
Tenant Session投影与Profile组合保留测试fixture；替换适配器证明持久事实，不冒充完整独立进程恢复。
并发两组连接只证明此事务幂等，不是生产HA/QPS。

Overdoze应固定本合同及源码，再认领可信产品BFF、实际React Hook挂载和值/动作传输、
浏览器UI Effect/Receipt、断线恢复与unknown对账；管理前端mock保持。
SDK库存中的list错误折叠为空、Readable仅注册名称而未见值上传、浏览器SDK凭据/服务端保管的映射，
必须在该片逐项明确合同并验证，不把Provider ready或旧npm源码版本当成实际接入完成。

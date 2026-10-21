# CA-P3-02A — 产品级前端 Profile 与可信 BFF 准入

2026-10-22；Owner Luke Ding；功能分支交付，未部署。
[任务](AGENT_TASKS.md) · [机器合同](contracts/frontend-profile-management/contract.json)。

## 权威与不变量

原生 FrontendCapabilityProfileVersion 拥有不可变内容摘要与生命周期，FrontendCapabilityBinding
固定 Host/namespace/App/版本。现有 FrontendProfileService 与 PostgreSQL registry 保持权威。
平台只提交管理意图和观察当前事实；业务 BFF 保管 HostGrant、Client Session credential 与 Controller fence。
Publishable Key、identity_key、bootstrap binding ID、Tab/Document ID 都不是这些凭据。

新增 `GET/PUT /management/v1/host-frontend-profile`，认证复用独立 `rthm_` 凭据与
X-Runtime-Deployment/Audience/Product/Environment/Trust-Revision 全部精确匹配。
原有凭据没有自动增加权限；私有 Host 管理批准必须显式添加
`frontend-profile.read` / `frontend-profile.write` 和 `frontendProfile` 原生 JSON。
批准精确固定一个 App/Revision/内容，最多沿用16KiB私有文件预算；HTTP不能上传替换该批准。
普通 HostGrant 和平台万能 operator 凭据都不能替代本批准。
配置轮换必须推进原有持久批准 CAS；旧副本指纹不匹配时拒绝读、写和收据重放。

PUT 固定 `{expectedRevision,operationId,active}`；operationId 为规范 UUID。
active=true 使用原生服务发布批准的不可变版本并绑定当前 Host，false 撤销批准版本。
已撤销版本不可恢复；新版本要显式批准新修订，再 CAS 绑定。
管理修订与原生绑定修订分别增长，不混用；未知写入结果先重发同一 operationId 对账，禁止改ID盲重试。
原生专用 operator 路由保持运维兼容；其权限不下放给 Go。

## 当前查询和历史

响应含 contractVersion、管理 revision、replayed、active、available、profile、approvedProfile、binding、observedAt。
active表示当前绑定的Profile仍published且等于精确批准；available还要求当前原生Host registry active。
初始管理revision=0、profile/binding=null；旧operator登记的记录不会因此自动归属新产品。
第一次显式操作登记App归属；同deployment namespace下同App不能被另一产品/环境/Host接管。
不同Target需要不同App或独立deployment namespace；原生App本来就是该命名空间内的全局标识。
已有其它Host/namespace绑定的历史共享App会拒绝首次纳管或新的产品级写入；原始绑定/能力不删除，先用独立App。
旧operator保存Binding与产品级写入共用App事务锁；即便并发，也不能让新增跨Host绑定与产品级全局撤销同时提交。
已成功操作的只读receipt重放仍可对账，不回放副作用，不将历史active误当当前有效。

读取权限仅查询批准App。历史操作receipt可能仍显示曾active；必须GET重新读取当前有效性。
当前读取是提交时观察，不承诺下一请求仍有效；真正Session/mount/bind仍重新检查原生当前状态。
不会把Profile管理收据当成Bundle发布、Task授权、Coverage或UI已执行证明。

## 可信 BFF 与执行准入

1. 业务BFF验证自己的登录/CSRF/实际Origin并使用当前平台Agent access。
2. 通过平台bootstrap/current检查当前App、身份family、Target、Origin和精确Profile。
3. 使用既有generic Broker和当前业务授权桥换取短期、资源收窄的HostGrant。
4. 原生HTTP验签/检查当前Host登记/Origin/重放账本；签名sub必须等于ClientSessionGrant.user_ref。
5. 原生 `/v1/tasks/{task}/runs/{run}/client-surface` 复用已有Task/Run资源授权、Profile当前状态、
   Session创建、mount收窄、RunBinding和单Controller fence；原始client-bindings入口同样检查Task/Run。
6. 已有Session凭据再次使用时仍要求当前签名主体相同；Controller续期/释放还检查当前Task/Run资源。

新检查只在cloud入口要求实际VerifiedHostGrant；本地开发行为保持。
会话TTL与短期HostGrant期限不同；长会话不延长Host权限，每个后续BFF请求仍需新的当前Host授权。
Host到期不应用时钟偏移宽限来继续创建/使用Client Session；平台logout之后已签Grant的残余窗口仍存在。
Profile撤销阻止新挂载/绑定；不声称自动停止所有已执行Task或撤销所有运行中的业务副作用。
Session打开与挂载/绑定原有部分提交语义保留。丢失一次性credential响应视为unknown；
不自动重开、不缓存秘密，不回退为controller成功。孤立Session按TTL到期。

## 存储、并发与升级

v112仅新增frontend_profile_management及其receipt审计表，原Profile/Task/Event/Coverage数据不重写。
复用原Host批准事务锁，再锁App、归属、原生Profile/Binding；现有原生服务通过transaction work unit借用同一事务，
CAS、原生变更和receipt原子提交。最终COMMIT失败不返回成功；不在事务内调用网络。
每App最多4096保留操作收据，历史不会自动删除；提高上限前需要归档方案。
8槽/实例、5秒总期限和既有有界DB I/O；Host范围串行是已知吞吐上限，没有生产HA/QPS证明。

显式运行既有migrate工具应用v112，再按Host管理审批工具推进批准；启动不DDL、不自动补权。
关闭新路由/删除配置actions字段前保留历史与旧批准；旧程序不认识frontendProfile时须移除此配置字段，
旧副本不能继续接收新接入流量。生产迁移和部署仍需独立授权。

## 验证

本轮实际验证记录见[evidence](evidence/ca-p3-02a/validation.json)。
专项覆盖独享PG、两个HTTP实例、CAS竞争、权限/批准轮换、不可变归属、审计失败整笔回滚、
已签名主体与Session凭据隔离、Task/Run和Controller边界。
全量make test/check的真实计数与依赖跳过分开记录；不将临时环境验收称为生产或浏览器UI效果验收。

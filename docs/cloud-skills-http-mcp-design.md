# Cloud Agent Skill 与 HTTP MCP 技术方案

- 文档编号：CLOUD-EXT-HTTP-DESIGN-01
- 日期：2026-09-06
- 状态：方案已获用户批准，正在分阶段实施；完整能力尚未交付
- 基线：cloud-agent-trench@c0bf8798
- 业务范围：独立 Cloud Agent，首个消费方为 Trench
- 已确认决定（2026-09-08 补充）：云端 MCP 支持 Streamable HTTP 与远程 legacy SSE，不支持 stdio

## 1. 目标与边界
2026-09-08 产品交互澄清：用户在设置中配置、授权并启用 MCP 一次，
AI 自主决定是否调用以及选择哪个工具。Task/Turn 身份与执行记录由系统
自动维护，不新增用户手动绑定任务、会话或逐个工具的前置操作。
后台继续校验当前用户归属、撤销和执行权限；这些校验不等于人工选工具。

交付用户可以安装、授权、选择和撤销的 Skill/MCP 能力，沿用现有 Session、Turn、Worker、Tool Gateway、Policy、Broker、Event Store、Artifact Store 与 RabbitMQ。

Skill 是过程知识，不是新增权限；MCP 是外部能力协议，不是业务授权替代品。Trench 订阅、历史与文件访问仍走已有 Host Grant 和原生工具。

### 1.1 本期交付

- 不可变 Skill 包、版本管理、用户/工作区安装、按需读取、受控脚本使用。
- Streamable HTTP / 远程 SSE MCP 连接、工具目录、资源读取、显式 Prompt 附加、凭证托管。
- 多租户授权、能力快照、Worker 恢复、撤销、错误提示和浏览器闭环。
- API Key/Bearer 与 OAuth 两类认证；按服务要求配置，不强迫公共无认证服务使用 OAuth。
- 实时正文不受扩展加载阻塞；过程记录完成后默认折叠。

### 1.2 明确不做

- 不接受 command、args、stdio、子进程、npx/uvx 启动配置；不实现 HTTP-to-stdio 桥接。
- 不自动探测或降级传输；远程 SSE 必须显式设置 transport=sse。
- 不建设 Skill 商店、自动抓取 Git 仓库、任意依赖安装、跨租户公共资源市场。
- 不宣称支持所有 MCP 协议版本或实验扩展；unsupported capability 必须显式报告。
- 不通过此次交付删除本地 CLI 的既有 stdio 实现；云端入口必须拒绝，不能回落到本地混合配置。
- 暂不启用 MCP sampling、服务端任意执行、后台资源订阅、实验性异步 Tasks 扩展；需要这些能力的服务显示不兼容。

选择 HTTP-only 是为了接入远程服务，不把第三方进程、依赖安装与生命周期托管引入云端。用户于 2026-09-08 批准兼容远程旧 SSE；这不开放 stdio。

## 2. 代码基线与复用清单

| 现有位置 | 现状 | 本次处理 |
|---|---|---|
| agent_tools/skills.py | skills.list/read、引用文件读取、内容标记不可信 | 复用契约，替换云端目录来源 |
| agent_tools/skills_catalog.py、skills_scope.py | 本地包发现、作用域、摘要 | 复用校验；不把文件系统 scope 当租户授权 |
| agent_storage/skills_state.py、API skills_admin.py | SQLite 启停和本地目录管理 | 本地不变；Cloud 使用 PostgreSQL 安装关系 |
| worker/tool_gateway_runtime.py | 已装配 Skill/MCP；Skill 状态来自 SQLite，MCP 来自进程配置 | 从本轮能力快照装配 HTTP-only 连接与包 |
| agent_runtime/mcp_http.py | 单次 JSON-RPC/有限 SSE 解析 | 完成受测 Streamable HTTP 子集，不沿用“一个 SSE 消息就是最终结果”假设 |
| agent_runtime/mcp_pool.py | 熔断与退避包装 | 复用状态逻辑；不等同于跨租户安全的长连接池 |
| agent_runtime/mcp_routing.py | stdio/HTTP 混合路由 | 本地保留；Cloud 不调用混合配置入口 |
| agent_core/domain/mcp.py | MCP 工具允许集合 | 保留，增加连接身份与快照映射 |
| API session_payloads.py | 已有 MCP allowlist 字段 | 服务端解析安装/连接后求交集，禁止客户端自行赋权 |

实际路径以 packages/<package>/src/ 与 apps/<app>/src/ 为前缀。以上是源码检查，不代表现有实现已通过本设计的云端验收。

特别注意：当前协议常量支持 2025-06-18、2025-11-25；环境配置当前限制最多 3 个 MCP server。新连接配额独立配置，不能通过直接放大该全局配置限额冒充云端管理。

## 3. 组件分工

```text
Trench UI → Trench BFF → Cloud API（身份与管理权限）
                          ├─ PostgreSQL：安装/连接/版本/快照/执行记录
                          ├─ Artifact Store：Skill 包与大结果
                          └─ Outbox → RabbitMQ：校验/目录刷新/健康检查

Turn admission → 冻结能力快照 → Worker → Tool Gateway → Policy
                                      ├─ Skill：只读包 / 沙箱脚本
                                      ├─ HTTP MCP：Broker 代理出口
                                      └─ Trench Host Tools：现有业务授权
```

- agent-core：身份绑定、快照、调用状态和 Ports；不引入 HTTP/数据库依赖。
- agent-tools：Skill/MCP 工具描述、参数边界、结果投影；不负责取得用户凭证。
- agent-storage：安装与快照持久化、唯一约束、乐观锁、Outbox；复用现有迁移机制。
- agent-runtime：Skill 只读挂载、HTTP 协议与沙箱运行；网络出口使用 Broker 认可的目标。
- agent-security：权限求交、凭证引用、调用时撤销检查、审批与网络策略。
- apps/api、apps/worker：认证和装配，不承载领域规则。
- Trench：用户管理页面和 BFF；不复制 Cloud 的凭证或安装事实源。

优先扩展现有 Broker 进程和接口，不先新建独立 MCP 微服务。吞吐或网络边界需要拆进程时，保留同一授权契约。

## 4. 身份与数据模型

以下为建议逻辑表名，实施时映射到既有命名和迁移规则；不得重复建设已有凭证/事件表。

统一身份键：namespace_id + principal_ref + workspace_ref。全部由已验证身份和服务端映射产生，不能相信请求 body 的 user_id。对象 ID 不等于访问权限。

| 逻辑对象 | 主要字段 | 约束 |
|---|---|---|
| skill_packages | id、publisher_scope、owner_ref、name、status | 名称只在发布作用域唯一；ID 不可变 |
| skill_versions | package_id、version、digest、artifact_ref、manifest、validation_state | unique(package_id, version)；发布后内容不可变 |
| skill_installations | id、namespace、workspace、principal、version_id、enabled、revision | 安装显式固定版本；无跨用户默认继承 |
| mcp_connections | id、namespace、workspace、principal、endpoint、auth_mode、credential_ref、config_revision、enabled | transport 为 streamable_http 或 sse；拒绝未知执行配置 |
| mcp_catalog_versions | connection_id、config_revision、digest、protocol_version、tools/resources/prompts metadata、fetched_at | 不可变目录快照；失败不能清空最后一个有效目录 |
| turn_extension_snapshots | turn_id、digest、installation/version refs、connection/catalog refs、effective permissions | 与 Turn admission 同事务写入或关联 |
| extension_operations | id、kind、owner scope、status、idempotency_key、result_ref、error_code | 后台管理任务；复用已有通用操作表优先 |

调用执行记录优先扩展现有 tool_call 与幂等账本，不再建第二套执行事实源。记录 connection_id、catalog_digest、credential_revision、request_digest、status、external_request_ref。

数据库要求：作用域查询条件不可缺失；创建和启停有 revision；更新使用 If-Match；游标分页；外键和归属复核；删除使用软删除并保留审计所需版本。

共享规则：管理员发布不等于对所有用户授权。工作区共享连接必须有显式成员权限和共享服务账号声明；个人 OAuth 连接不能被隐式转换为共享账号。

## 5. Skill 发布与使用

### 5.1 包格式和校验

必须包含根 SKILL.md；可包含 references、templates、assets、scripts。继续兼容现有 name/description 元数据；云端发布 manifest 另外保存版本、digest、入口、建议依赖和发布身份。

初始可配置上限：压缩包 10 MiB、解压 50 MiB、1000 个文件、目录深度 8；SKILL.md 读取遵守现有有界输出限制。超过限制返回明确错误，不静默截断安装内容。

解压在隔离临时目录：拒绝绝对路径、..、符号/硬链接逃逸、设备文件、重复覆盖路径及异常压缩比例。生成规范化清单及内容摘要后才能发布。失败包不可安装；日志不记录文件正文。

包路径不是用户可猜测的公开下载 URL。私有包读取经授权 Artifact Store；缓存仅共享不可变 bytes，不共享租户可见性。

内部发布切片 EXT-SKILL-01B 复用现有 ArtifactObjectStorePort 的不可变写入与
核验回执，不伪造 Session、Turn 或工具调用。ZIP 完整校验后，先向 PostgreSQL
登记 publishing 版本及确定的对象期望，再写对象；仅匹配的回执能使其变为 ready。
写对象后进程中断，记录仍保留 publishing；相同输入可安全重试，不自动删除可能
已成功写入的对象。对象存储故障不能把版本标为 ready。
名称和版本在完整归属范围内唯一；版本标签优先使用 SKILL.md 的 version，缺失
时使用内容摘要。同一标签要求内容及 ZIP 原始字节不可变（重打包也可能冲突），
更新应更换标签。对象 ID 还包含 deployment 和完整用户作用域，不能跨用户复用
可见性。此内部链路不是公开上传接口；操作队列、拒绝记录、撤销、安装和授权下载
仍需后续接入，不能仅凭内部 ready 状态开放浏览器或 Agent 访问。

### 5.2 生命周期

uploading → validating → ready / rejected；ready 版本不可覆盖，只能发布新版本。
安装 enabled/disabled 独立于发布状态；撤销危险版本有紧急 revoked 状态。
普通升级影响下一轮；已有轮次固定版本。紧急撤销在下一次读取/执行处生效，不保证撤回已经泄露给外部的内容。

### 5.3 Agent 使用

1. 向模型提供当前有权限的有界元数据目录，不注入所有说明全文。
2. 用户显式选择，或 Agent 根据任务通过 skills.list/read 按需使用。
3. Skill 依赖只产生诊断：缺失 MCP/权限需提示，不自动安装、不自动授权。
4. 安装对象 ID 映射唯一工具可读名称；同名不同来源要求消歧，不静默覆盖。
5. 读取时记录 version/digest；参考文件仍受同一包根边界约束。

### 5.4 脚本

Skill scripts 只读挂载到现有沙箱，通过现有受控执行工具调用。不能在共享 Worker 主机直接执行。依赖使用已有固定运行镜像；缺失依赖提示 unsupported_runtime，不在线安装。
Skill 本身不能提升 tool_profile/network_profile，不能获得 Broker 原始凭证。生成文件经既有 files.publish 和用户授权下载链路，不创建第二套 MinIO 文件分发系统。

## 6. HTTP MCP 连接与协议

### 6.1 创建请求

```json
{
  "display_name": "团队知识库",
  "endpoint": "https://knowledge.example.com/mcp",
  "transport": "streamable_http",
  "auth_mode": "oauth",
  "visibility": "personal"
}
```

严格 schema 禁止 command、args、stdio、shell、env、任意 Host/Authorization header。自定义 API Key header 仅允许 Broker 的管理员审核认证模板，防止请求头注入。
云端生产仅 HTTPS；开发 localhost HTTP 必须是管理员预登记出口，不能由普通租户开启。用户浏览器 localhost 与云端 Worker localhost 不是同一机器，界面要解释部署位置。

### 6.2 协议兼容矩阵

Streamable HTTP 基线固定 2025-11-25，保留已受测 2025-06-18 协商；远程 legacy SSE 使用 2024-11-05。它不是“自动跟随最新版”的承诺。其他版本进入单独兼容评审。

| 能力 | 本期策略 |
|---|---|
| initialize / initialized / version negotiation | 必需；不支持版本明确失败 |
| tools/list（分页）、tools/call | 必需；有界目录、JSON Schema 校验 |
| JSON 与 SSE POST 响应 | 均支持；按 JSON-RPC id 找到最终响应，不将 progress 当结果 |
| Session ID / protocol header | 按协商管理，保密保存；Session 不是身份凭证 |
| GET SSE / replay cursor | 服务支持时恢复原请求结果；405 视为不支持可选恢复 |
| progress / cancellation | 映射公开进度；取消不等于外部写操作回滚 |
| resources/list/read、templates | 只读按需，有界内容；URI 不自动转为任意网络访问 |
| prompts/list/get | 仅用户显式附加；不提升为系统指令 |
| sampling、未知 server request | 不宣告能力，返回明确不支持；不后台调用模型 |
| elicitation | 本期不宣告；OAuth 走连接授权 UI，不伪装成聊天收集密码 |
| legacy SSE | 显式配置；GET 事件流 + 同源 HTTPS POST；不重连重放工具调用 |
| stdio | 拒绝，不降级、不代理 |

协议解析和恢复细节以固定版本规范与契约测试为准：[Streamable HTTP](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)。

### 6.3 发现、目录冻结与名称

连接测试在后台校验 endpoint、认证、协议、目录与 schema 大小。状态维度分开：配置 enabled、认证 authorized/required/expired、健康 healthy/degraded/unreachable；认证失败不等于用户停用。

工具名使用服务端生成的短 connection alias，并维护到 connection_id + 原始工具名的不可变映射，兼容现有 mcp.<server>.<tool> 命名限制。禁止截断后重名、与原生工具冲突。
目录变更生成新 digest，下一轮使用；当前调用必须使用已冻结 schema。刷新或目录变更通知发现相关条目变化后，旧快照调用返回 catalog_changed；原工具被删除则返回 tool_unavailable，不自动改绑。
冻结的是本地授权、名称映射和参数契约，不是远端实现。服务端没有版本固定机制时，无法保证发现所有同名实现变化；不为此每轮增加全目录探测。需要严格固定的高风险服务必须提供版本化 endpoint 或版本契约，否则不开放该写能力。

MCP readOnly/destructive 等 annotations 只作建议，不能单独决定授权。未分类工具默认需要审批，管理员可以审核成只读或有限写能力。

## 7. 凭证与网络安全

### 7.1 API Key 与 OAuth

凭证只能进入 Broker 的秘密写入接口；普通 GET、目录、事件、Skill、沙箱和模型上下文只出现 credential_ref。
API Key 输入成功即遮蔽，不回显。OAuth 使用服务端授权会话，绑定用户、工作区、连接、state、PKCE 和精确 redirect URI；回调必须验证绑定和过期时间。

授权元数据发现、scope/audience/resource 参数和令牌刷新遵循选定版本。初期支持元数据发现与预登记 client；不要求任意服务的动态注册都可成功。失败时给出所缺管理员配置。
刷新按 credential_ref 加锁，避免多个 Worker 同时轮换 refresh token。令牌加密、轮换、删除和审计复用 Broker 机制；不存在适配器时显式列为实现缺口，不用数据库明文代替。
禁止浏览器 Cookie、Trench Token 或非目标服务 Token Passthrough。[授权规范](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)

### 7.2 出口

普通用户连接禁止回环、链路本地、云元数据、私有网段和非批准端口；企业私网经管理员出口注册绑定。
DNS 校验和实际连接目标必须一致，防止重绑定；TLS 校验原始 hostname；禁止未校验重定向。OAuth metadata/JWKS/token endpoint 同样适用，不只检查 MCP URL。
证书失败不允许 verify=false 降级。不同目标之间不复用 Authorization header。[安全说明](https://modelcontextprotocol.io/docs/2025-11-25/tutorials/security/security_best_practices)

## 8. 本轮能力快照与调用授权

有效能力 = 用户可用安装/连接 ∩ 工作区策略 ∩ Host 授权 ∩ Task 允许集合 ∩ 工具风险规则。

快照包含 Skill version/digest、连接 config revision、目录 digest、允许工具、网络出口和权限 ceiling；不包含明文凭证。
在现有已验证 execution binding 中绑定 snapshot digest，Worker 校验归属与摘要后才装配。仅由服务端数据库字段填写，拒绝客户端任意 snapshot_ref。
每次读取私有包或调用 MCP 再检查当前成员归属、对象 ACL、enabled/revoked、Host/Task 授权与凭证状态；快照是权限上限，不能保留已经撤销的权限。
resources/read 与 prompts/get 使用独立允许集合，并经过同样的归属、撤销和内容边界检查，不能因 tools allowlist 为空而默认放行。
启用和升级从下一轮生效；停用、移除成员、收紧权限及紧急撤销立即阻止后续读取/调用，不保证中止已经发往外部的操作。

首次接入旧会话：下一轮重新生成快照，但不能越过既有 Task authority ceiling。若现有 Task 不允许该新工具，需通过现有受控权限更新流程；没有该流程则提示显式创建新会话，不静默扩大权限。

缓存键至少包含 namespace、principal、workspace、connection、config/catalog revision、credential revision；不要仅用 server URL。Socket/Session 初期按执行轮次独享，元数据按身份缓存。先避免串用户，再评估复用会话。

## 9. 运行、重试与恢复

调用状态：prepared → dispatched → succeeded / failed / cancelled / outcome_unknown。
外部调用前持久化 prepared/dispatch intent；即使在网络发送前崩溃，也不能仅凭“没有成功结果”判定未执行。
已完成调用从账本恢复，不重复执行。写操作发生不确定断线时进入 outcome_unknown：支持上游业务幂等键或结果查询才能自动核对；JSON-RPC id 本身不是业务幂等保证。
只读操作可有界重试；默认最多 2 次并遵守总 deadline、退避及服务端限流。工具 annotations 未审核时不能被用于开启写操作自动重试。

Worker 恢复时重新取得短期授权并加载同一 snapshot；连接消失返回明确错误。支持 SSE replay 时恢复原流，不把重连做成第二次 tools/call。Session 过期后的重新初始化也不能自动重放未知写请求。
用户关闭网页只断开观察；取消走现有取消命令。外部不支持取消时说明“已停止等待，外部结果尚不确定”。

## 10. 性能与用户体验

- 未启用扩展的轮次不进行 Skill 扫盘、MCP 探测、OAuth 发现。
- Skill 元数据与包缓存；目录通过后台刷新，不在每次对话同步拉全部 tools/list。
- 首次使用连接才初始化；单个 MCP 故障不影响其他连接和不相关普通回答。
- 模型正文 delta 直接沿现有流式事件链路追加；工具开始、Skill 切换不触发 answer_reset。
- 过程信息可实时保留，UI 默认折叠；结束后格式化过程，不能拿过程总结替换正文。
- 大工具结果形成受权 artifact，模型只读有界摘要及引用；下载复用现有用户隔离链路。

初始工程目标（不是已测结果）：热路径扩展解析 p95 < 100ms；关闭扩展时 p95 首字延迟回归 < 5%；本地首个公开事件收到后 DOM 更新 < 200ms。指标必须分别测客户端与服务端。
初始 deadline：连接建立 5s、目录刷新 15s、工具默认 30s；管理员可允许单工具最长 120s。以上受本轮总预算约束，不能多层重试相乘。

RabbitMQ 仅承载包校验、目录刷新、健康检查等后台操作。DB Outbox 保证提交后可发布；消费者幂等、失败重试与死信沿用现有机制。不新增每 token 队列或另一条工具执行事实链路。

## 11. 管理 API（拟定，尚不存在）

统一使用现有认证与响应风格，下列 /v1/extensions 为设计前缀，实施前检查路由冲突。

| 方法与路径 | 意图 | 关键行为 |
|---|---|---|
| POST /skills/uploads | 上传 Skill 包 | 202 + operation_id；私有上传令牌有时效和体积限制 |
| GET /skills、GET /skills/{id}/versions | 有权限的目录/版本 | 游标分页，不泄露他人包存在性 |
| POST /skill-installations | 固定版本安装 | 校验包可见性/使用权限、安装管理权限、包 ready、依赖诊断 |
| GET /skill-installations | 已安装列表 | 按当前作用域分页，返回固定版本和启停状态 |
| PATCH /skill-installations/{id} | 升级/启停 | If-Match；启用/升级下一轮生效，停用阻止后续调用 |
| DELETE /skill-installations/{id} | 卸载 | 软删除，阻止后续读取/执行，保留历史版本引用 |
| GET /mcp-connections、GET /mcp-connections/{id} | 连接列表与详情 | 当前归属范围，无凭证正文 |
| POST /mcp-connections | 创建 HTTP 连接 | transport 枚举 streamable_http、sse |
| PATCH /mcp-connections/{id} | 修改/停用 | If-Match；变更地址需重新验证，不转移旧凭证 |
| POST /mcp-connections/{id}/credentials | 写入凭证 | Broker 托管，仅返回引用和状态 |
| POST /mcp-connections/{id}/authorize | 发起 OAuth | 返回短期授权 URL，不返回 token |
| GET /mcp-oauth/callback | 授权回调 | 校验 state/PKCE/归属，不使用 body 身份 |
| POST /mcp-connections/{id}/test、/refresh | 测试/刷新 | 202，后台幂等，失败保留旧目录 |
| GET /mcp-connections/{id}/catalog | 目录详情 | 当前可见工具和兼容状态 |
| DELETE /mcp-connections/{id} | 撤销并软删除 | 立即禁止新调用，尝试上游撤销 |
| GET /operations/{id} | 后台操作状态 | 归属检查，错误可操作 |
| GET /turns/{id}/extensions | 本轮能力快照 | 只读、无凭证；不可用于客户端赋权 |

创建/后台动作接受 Idempotency-Key；同 key 不同内容返回 409。未知对象和越权对象统一 404；无身份 401；版本冲突 409；不支持配置 422。
管理操作和 Agent 工具授权分开：能使用某连接不意味着能查看凭证、修改连接或给其他人授权。

管理身份从验签后的 `iss/sub/namespace_id/workspace_ref` 构造，不接受请求体、
查询参数或对象路径传入身份。现有 `HostContextEnvelope` 不保留 iss/sub；实施时
在 `VerifiedHostGrant` 保留这些已验证字段，不改变旧会话上下文的序列化或摘要。
读取要求 `extensions.read`，修改要求 `extensions.manage`，不从 `agent.run`
隐式扩权。Broker 仍必须显式批准新 scope；身份不足时拒绝，不使用共享管理员兜底。

只读接口先以显式 `ExtensionStore` 装配接入，未装配及 local profile 不开放。
接口不返回内部作用域、凭证引用或 Skill 的存储引用；响应禁止缓存。
列表参数仅支持有界 limit/cursor，重复参数和额外身份参数拒绝。
后续生产开关/迁移检查、写操作幂等、BFF 和页面接入分别验证；只读接口存在
不代表上传、安装、OAuth 或 Agent 执行已开放。

只读生产装配开关为 `ZEBRA_CLOUD_EXTENSIONS_READ_ENABLED`，默认 false，
只在 cloud/production profile 使用。开启前部署匹配的 PostgreSQL schema；
启动时复用 checksum/schema 校验，仅检查不执行迁移。使用同一 control-plane
deployment namespace 和已解析的 DSN，不以单独 URL 或共享管理员选择用户。
该开关不授予 `extensions.read`，也不启用 Skill/MCP 执行、写接口或 OAuth。

启停写入使用独立 `ZEBRA_CLOUD_EXTENSIONS_MANAGE_ENABLED`，默认 false。
初始 PATCH 只接受 `{"enabled": true/false}`，不能传入版本、凭证或身份。
管理权限独立要求 `extensions.manage`；默认存储仍需只读装配开关。
GET 详情提供强 ETag（如 `"1"`），PATCH 必须携带对应 If-Match；缺失返回
428，版本冲突返回 409。使用同一 scoped CAS 持久化，不自动重试覆盖别人的
修改。包上传、升级、卸载和运行时撤销仍属后续交付。

连接创建切片 EXT-API-02B 复用上述管理开关与权限，POST 仅接受 endpoint、
transport（默认 streamable_http）、auth_mode（默认 none），不能注入归属、
凭证、ID、授权状态或 enabled。新记录默认停用；需要认证的连接为 pending，
none 为 not_required，均不代表网络可达或 Agent 已可调用。
Idempotency-Key 必须是单个 1–128 字节可见 ASCII 值（不含空格）。首次创建
返回 201、Location 和 ETag；相同 key 与相同规范化配置返回 200 和当前版本。
同 key 不同配置返回 409。比较依据是不可变的首个修订，而非当前配置；因此
创建响应丢失后即使连接已被启停，重试也不会新建记录或覆盖后续修改。
复用 scoped 配置主键及首版记录，不引入另一个幂等账本。未来软删除必须保留
该首版绑定，并明确拒绝已删除对象的重放，不能复用旧 key 复活连接。

错误结构：code、message、retryable、action、operation_id（可选）。action 只能是服务端批准的 UI 动作枚举，不直接打开 MCP 返回的任意 URL。
错误码至少覆盖 authorization_required、authorization_expired、connection_unreachable、unsupported_transport、unsupported_protocol、tool_unavailable、approval_required、permission_denied、outcome_unknown、skill_dependency_missing。

## 12. 前端与 Trench 接入

在现有设置对话框左侧增加“Skills”和“MCP”两个独立管理部分，沿用现有视觉和组件；不是另建一个与设置割裂的管理应用。
Skills 展示已安装版本、启停、升级、卸载、上传校验结果；MCP 展示连接列表、HTTP 地址、授权/健康状态、测试、重新授权与删除。
列表展示所属范围和缺失配置；包含加载、空列表、失败重试、保存中、防重复提交、修改冲突、卸载/删除确认及服务端回读。普通用户不必理解 MCP 协议字段。
会话允许选择已安装技能和已授权连接；默认只在已有授权范围内自动选择。来源权限继续由 Trench 签发，不能通过连接设置扩大订阅历史。
审批与 OAuth 在独立 UI 完成；聊天中只提示“需要授权”“等待确认”，不要求粘贴 Cookie 或 Token。
Trench BFF 以已验证用户身份调用 Cloud 管理接口；禁止使用一个管理员身份代理所有用户操作。安装、启停、重新授权完成后 UI 查询服务端状态，不仅更新本地缓存。

## 13. 迁移、发布与回滚

1. 增量迁移表/索引，先部署只读兼容代码；现有任务不需要新字段也可运行。
2. Cloud 默认 extensions_enabled=false；灰度按 namespace/workspace，不全局开放。
3. 管理员显式导入审核后的本地 Skill 包；不扫描开发机 home 或自动导入所有私有 Skill。
4. 旧环境 MCP 配置不自动迁移成公共连接。Cloud 启动发现 stdio 配置应报出配置错误；不能默默执行或静默忽略。
5. 分别灰度 Skill、HTTP MCP 只读、MCP 写审批与 OAuth；每阶段保留普通聊天回归。
6. 回滚关闭新 admission 开关；已执行外部写操作不可回滚。保留快照和账本用于核对，不能删除表来“清理”。

已接纳轮次使用与快照 schema 兼容的 Worker；不兼容 Worker 不领取任务。部署回滚需让旧 schema 任务完成或显式中断后恢复，不能丢弃元数据。
紧急撤销与普通 feature flag 分开：紧急撤销立即阻止后续调用，普通关闭只停止新接纳。

## 14. 实施任务拆分

以下是候选任务，不代表已领取或已实现。每项实施前在 AGENT_TASKS 登记唯一人类 owner、分支和精确 Owned paths。

| 任务 | 交付 | 依赖 | 主要路径边界 |
|---|---|---|---|
| EXT-CON-01 | 身份、安装、快照与错误契约 | 本文评审 | agent-core、契约测试 |
| EXT-STORE-01 | PG 迁移、Outbox、版本约束 | CON | agent-storage、迁移测试 |
| EXT-SKILL-01 | 校验、版本发布、目录解析、缓存挂载 | STORE | agent-tools、agent-runtime |
| EXT-MCP-HTTP-01 | 协议子集、目录、结果/会话恢复 | CON | agent-runtime/mcp_*、协议测试 |
| EXT-AUTH-01 | Broker 连接授权、OAuth、出口、撤销 | STORE | agent-security、Broker composition |
| EXT-WORKER-01 | 冻结绑定、HTTP-only 装配、恢复/审批 | SKILL、HTTP、AUTH | Worker、execution binding |
| EXT-API-01 | 管理路由、身份、幂等与操作状态 | STORE、AUTH | API adapters |
| EXT-TRN-01 | BFF、管理页面、会话选择、配置提示 | API、WORKER | 单独 Trench 分支与任务 |
| EXT-QA-01 | 多用户、故障、性能、浏览器验收 | 以上全部 | 集成测试与验收文档 |

不通过一项超大“扩展平台”任务开放全部目录；共享契约先落地，后续各任务只改明确边界。

## 15. 验收矩阵与完成定义

| 用例 | 必须观察到的证据 |
|---|---|
| Skill 安装后 Agent 使用 | list/read 事件含版本摘要；实际按 Skill 调工具；文件可授权下载 |
| HTTP MCP 读工具 | 实际 initialize/list/call 与成功结果；不是目录截图 |
| HTTP MCP 写工具 | 审批或明确授权、一次外部副作用、账本终态 |
| 两个用户同 URL 不同账号 | 数据/凭证/Session/缓存/资源不可串用；越权枚举一致拒绝 |
| 上传恶意包 | traversal、symlink、zip bomb、同名覆盖均不可发布 |
| stdio 配置 | 管理 API 与云端装配均拒绝；无子进程启动 |
| OAuth 过期/撤销 | 正确提示、单次刷新、停止新调用；日志无秘密 |
| 已发现服务 schema 变更 | 新轮采用新目录；受影响旧快照明确失败，不改绑工具；不宣称固定远端实现 |
| SSE 多帧/断线 | 不把进度当结果；不重复写调用；可恢复或 outcome_unknown |
| Worker 发送后崩溃 | 恢复不造成第二次写副作用；无法确认则显式未知 |
| 普通聊天与长正文 | 扩展关闭无额外外连；正文逐步增长、不因工具清空 |
| Skill/连接卸载 | UI 与服务端一致；保留历史证据；后续调用被拒 |

验证分层报告：确定性测试、完整质量门禁、真实 HTTP 服务集成、Trench 浏览器、部署环境验收。任何层级未完成都必须标注，不以 HTTP 200、进程退出或“工具名称出现”代替完整闭环。

## 16. 评审检查问题

1. 新加入工程师能否仅凭本文区分“已存在”与“待实现”？
2. 为什么 stdio 不支持，而 SSE 响应仍需支持？
3. 用户安装 Skill 后为什么不能自动获得外部写权限？
4. Worker 在外部写成功、落库前崩溃如何处理？
5. 相同 MCP endpoint 的两名用户为何不会共享身份？
6. 禁用扩展后现有 Trench 流式链路是否保持原状？
7. OAuth 回调如何证明属于原用户和原连接？
8. 升级 Skill 和紧急撤销对在途任务有什么不同？

本文不要求用户再提供技术选项才能实施；配额、deadline 和具体 OAuth 服务兼容范围是初始建议，进入实现任务时用实测与契约样例收敛。

## 17. 实施证据与剩余边界（2026-09-06）

2026-09-08：`EXT-AUTH-01B` 增加 Broker 内部 token 加密组件，复用 SecretStore
取得显式版本的 Base64 256-bit 密钥。AES-GCM 使用随机 96-bit nonce，关联数据
绑定 deployment、完整 ExtensionScope、connection、精确 endpoint、auth mode、
credential ref/revision 及密钥 handle/version。密钥轮换使用新的不可变 handle，
保留旧密钥时可读取旧密文；删除旧密钥后失败关闭，不缓存解密密钥或明文。
输入为最多 16 KiB 的可见 ASCII token，返回既有隐藏 value repr 的 SecretMaterial。
仅验证加密绑定，不证明用户授权、有效期或撤销状态；没有持久化、公开接口、
OAuth 刷新令牌管理或 Worker 装配。生产密钥仍须由独立秘密服务配置，不能将本地
明文 SecretStore 作为云端凭证数据库。实现依据：[AEAD](https://cryptography.io/en/latest/hazmat/primitives/aead/)。

2026-09-08：`EXT-AUTH-01A` 收紧共享 MCP HTTPS 出口。保留既有 DNS 预检，
实际建连时再次解析并验证全部地址，然后直接以选定的数字 IP 建立 socket，
不再把域名交回连接层解析。TLS 仍使用原 hostname，默认校验证书与域名；
显式关闭环境代理，拒绝 tunnel，继续禁止 redirect。IPv4/IPv6 均覆盖。
首次地址连接失败直接返回错误，不做请求重放；失败 socket 关闭。
这是出口基础切片，不是 Broker 凭证交付：仍缺管理员私网出口注册、OAuth
各端点装配、DNS/慢速响应的完整总 deadline、云端调用授权与真实外部验收。

2026-09-08：`EXT-MCP-HTTP-01B` 将 HTTP resources/list、resources/read、
prompts/list、prompts/get 接入既有共享发现与显式选择流程，不再跳过 HTTP 服务。
空资源选择不产生网络请求；重名连接在网络访问前拒绝；资源正文仍须匹配原 URI，
且为有界文本。Prompt 需要显式 ID 与声明参数，仅允许 user/assistant 文本消息，
拒绝服务端 instructions 与 system 角色。复用现有分页和大小限制，不新增依赖。
这些测试使用模拟 HTTP 响应驱动真实传输适配器，不等于外部服务或浏览器验收。
资源模板、用户凭证 Broker、云端调用授权及设置页联调仍未由此切片交付。

2026-09-08：`EXT-MCP-HTTP-01A` 修复共享 HTTP 传输的响应分帧。
POST 的 SSE 按事件解析，跳过通知，按请求 ID 接收结果后立即关闭响应；
累计字节受限，错配、非法 JSON、缺少最终响应均失败，不重放 tools/call。
初始化返回的 Session ID 限制为可见 ASCII 并保存在实例内，后续请求携带该 ID
和协商协议版本；初始化通知失败向上传递。网络异常公开文本不包含底层详情。
此步骤不提供 GET replay、公开进度转发、云端凭证 Broker、严格 socket 总时限、
DNS 连接目标固定或 Worker MCP 装配；这些仍是后续交付条件。

当前上传切片 EXT-API-03A：显式注入 SkillPublicationService 后，云端读取/管理
开关与已验证 extensions.manage 授权共同开放 POST /v1/extensions/skill-packages。
请求为 application/zip 原始字节，10 MiB 上限、30 秒正文接收期限，拒绝压缩
编码和查询参数；只接受一个有界 Idempotency-Key。v53 迁移将 key 的摘要与
确切身份、部署、包版本及 ZIP 字节摘要在发布预约事务内绑定，冲突不能留下
另一份发布记录。已上传但尚未 ready 的同字节重试可继续；返回 200 表示已经
核验 ready，不区分首次或幂等重试，不宣称异步操作已完成。
Location 指向 GET /v1/extensions/skill-packages/{skill_id}/versions/{version_id}，
要求 extensions.read；仅返回包元数据与状态，不含 Artifact 引用、回执、正文
或归属键。默认无服务注入，不自动创建 S3 客户端或开启部署；生产对象存储装配
仍是独立待办，迁移只在测试临时 schema 执行。此入口不接受 stdio 或执行脚本。

当前读取切片 EXT-SKILL-02A：云端目录仅接受可信装配传入的固定轮次快照，
同时校验显式 scope、deployment、session、turn；只读取快照列出的已启用且
修订未漂移的安装。实际私有包必须通过对象 SHA/大小、ZIP 校验和完整清单/
内容摘要复核，再由现有 skills.list/read 有界返回，不扫描或解压到宿主机。
此目录是不可变读取适配器，不是权限授予器：调用方必须先验证快照已被该轮次
接纳，并在每次工具调用前进行实时授权/撤销检查。尚未接入这些步骤的 Worker
不能直接启用该适配器；本切片不改变运行中的 Agent 权限。
适配器只加载快照中显式选择的包，顺序核验且总展开内容不超过 50 MiB；
读取包和 ZIP 校验在线程中执行，无进程共享可见性缓存。当前为预加载适配器，
并非懒加载优化已经完成。Worker 装配仍需安排有界异步准备/按需加载及进度事件，
验证首段正文不被扩展准备阻塞后才能启用。

当前安装切片 EXT-API-02C：`POST /v1/extensions/skill-installations` 仅接受
`skill_id` 和 `version_id`，要求管理授权与 Idempotency-Key。服务端从同一
数据库、同一部署绑定的发布存储读取 ready 版本；未知、其他用户或尚未发布
完成的版本一致拒绝，客户端不能指定文件引用、摘要、身份或初始启用状态。
首次安装默认禁用；相同 key 重试返回当前修订，不恢复旧启停值；不同版本
复用 key 返回冲突。当前 ready 不可撤销，因此可以先读发布状态再创建安装；
引入撤销/删除前，必须把生命周期校验纳入安装事务，不能沿用此假设。
本切片不增加数据库迁移，也不接通 Worker 或前端设置页。

按用户要求在当前分支实施，不创建隔离工作树，不覆盖既有修改。

| 切片 | 当前证据 | 不代表什么 |
|---|---|---|
| EXT-CON-01 | 33 契约测试、670 核心测试；独立规格/质量审查通过 | 不是 API、授权或 Agent 可用性验收 |
| EXT-STORE-01A | 38 项真实 PostgreSQL 临时 schema 测试；配置 CAS、隔离、历史版本、分页与回滚；独立审查通过 | 不是完整 EXT-STORE-01；未启用生产迁移 |
| EXT-SKILL-01A | 57 项内存 ZIP 校验测试；实际解压大小、CRC、路径冲突及缓冲边界；独立审查通过 | 未发布包、挂载或执行脚本 |
| EXT-SKILL-01B | 内部 ZIP 校验、PG 登记、不可变对象发布与 ready 回执；59 项 PG/MinIO 及相关回归通过，独立复审通过 | 未开放上传 API、安装、挂载或执行脚本 |
| EXT-SKILL-02A | 固定轮次私有包核验与现有工具读取；135 项定向、67 项 PG/MinIO 及相关回归通过 | 未装配 Worker 或实时授权；预加载不等于首段延迟优化 |
| EXT-AUTH-01A | 41 项身份/权限/JWT 测试；保留已验签 iss/sub，显式管理权限；独立审查通过 | 未接管理路由、Broker scope 或 OAuth |
| EXT-API-01A | 显式装配只读安装/连接列表与详情；53 项 HTTP/认证测试，独立审查通过 | 尚未生产装配；无写接口、BFF 或设置页 |
| EXT-API-01B | 默认关闭的云端 PostgreSQL 只读装配；119 项定向测试，启动惰性回归及独立审查通过 | 未启用实际部署开关或执行业务迁移 |
| EXT-API-02A | 已有配置启停 PATCH、If-Match/CAS；114 项定向和 40 项真实 PostgreSQL 测试通过，独立审查通过 | 无创建/上传/删除，不代表 Worker 实时撤销 |
| EXT-API-02B | MCP 幂等创建；83 项定向回归、47 项真实 PostgreSQL 验证，含并发和 HTTP 回读；独立复审通过 | 尚未接凭证、外部 HTTP MCP 服务或 Trench 设置页 |
| EXT-API-02C | 安装已发布私有 Skill 版本；114 项定向测试、66 项 PG/MinIO 及相关回归，独立审查通过 | 默认禁用；未接上传、Worker 使用或设置页 |
| EXT-API-03A | 有界 ZIP 上传、幂等发布和授权详情；125 项定向、75 项 PG/MinIO 及相关回归，独立审查通过 | 显式注入才可用；未启用生产对象存储装配或设置页 |
| EXT-API-03B | 默认关闭的正常云端发布装配；129 项定向、77 项 PG/MinIO 及相关回归，独立审查通过 | 未打开实际环境开关；不代表 Worker 或设置页已可用 |
| EXT-STORE-01B | 不可变轮次扩展快照；94 项真实 PG/MinIO 相关回归及独立审查通过 | 尚未接入 Turn admission 或 Worker，不是执行授权 |
| EXT-WORKER-01A | 默认关闭的云 Worker 精确快照恢复；最终 59 项定向、51 项真实 PG、全量 3922/826 和独立规格/质量审查通过 | Review；未加载 Skill 包、注册工具或执行 MCP |
| EXT-WORKER-01B | 精确恢复的云 Skill 接入 typed list/read；86/35、全量 3945/830；Mypy 878 sources；独立质量复审通过 | 默认关闭；Review，无 MCP/凭证/UI/部署 |

配置存储位于 agent_storage.postgres.extensions.PostgresExtensionStore，迁移 v51 仅增量添加配置头与历史修订表。它不解析凭证，也不自动扫描本地 Skills。
迁移 v52 增量添加内部 Skill 发布记录，文件字节复用现有对象存储；只在测试临时 schema 验证迁移，未升级业务数据库。启用新代码前仍须遵守既有 schema 部署检查。
契约采用现有身份命名 principal_id/workspace_id，并额外绑定 authority_issuer；与本文逻辑字段 principal_ref/workspace_ref 语义对应。认证方式和授权状态独立存储。

当前装配切片 EXT-API-03B：正常云端 HTTP 启动通过独立默认关闭的
`ZEBRA_CLOUD_SKILLS_PUBLISH_ENABLED` 接通发布服务；必须同时开启
`ZEBRA_CLOUD_EXTENSIONS_READ_ENABLED`，上传还需管理开关与有效管理授权。
启动仅解析一次既有 CloudCompositionSettings，共用控制面 DSN、部署命名空间
和私有对象存储实例，不新增桶、凭证或第二套文件存储。数据库必须已完成既有
迁移，启动只检查 schema，不自动升级。自动装配拒绝同时注入独立 stores 或
extension_store，避免无法确认身份边界的混合装配；需要测试适配器时仍可显式
注入发布服务，由调用方负责完整装配。local 与默认关闭路径保持原行为。
此切片只接通 API 发布路径，不向 Worker 授予执行权限；实际环境未开启开关。

当前持久化切片 EXT-STORE-01B：每个部署、完整用户作用域、session、turn
只能保存一份不可变 ExtensionSnapshot；相同内容重试幂等，不同版本/权限冲突。
读取必须提供可信绑定中的预期摘要，并复核数据库 payload 的身份、轮次和摘要。
紧凑索引包含全部七个身份坐标，每次查询仍比较原始字段，不把摘要当作身份。
迁移 v54 只在测试创建的 schema 验证，不自动更新业务数据库。

这里保存的是轮次输入事实，不是“已获准执行”的证明。尚未和 Turn admission
事务关联，也没有增加接受客户端 snapshot 的 API。后续必须在现有任务授权上限
内由服务端选取版本、绑定摘要并验签，不能直接改变旧 TaskBindingSnapshot 的
摘要算法来隐式扩大旧任务权限。Worker 恢复加载同一快照后仍需逐次实时授权；
安装被停用后，不允许凭历史快照绕过当前状态。现有本地 Skill/MCP 装配不变。

当前 Worker 恢复切片 EXT-WORKER-01A：只有云端 PostgreSQL Worker 且显式开启
`ZEBRA_CLOUD_EXTENSION_WORKER_ENABLED` 时，才装配同一 DSN、同一 deployment
namespace 的 `PostgresExtensionSnapshotStore`；其余路径传入 `None`，在读取 Task
ceiling 或 snapshot 前直接返回。显式启用但当前 nonlegacy Turn 没有绑定时，只执行
一次精确坐标的布尔存在性探针，防止删除绑定字段降级；不会信任或返回库内 digest。
消息物化保留 `SESSION_COMMAND_ACCEPTED` 中由服务端
确定的 extension Turn 和 digest，Worker 只从 durable accepted-command 与其唯一的
human-message materialization 恢复当前绑定，不接受客户端坐标。

执行准备先独立加载正常 `TaskBindingSnapshot`，再由扩展 authority 解析 root Task
ceiling，并要求 task id、binding digest 及完整 binding 对象精确一致。随后从冻结 Host
binding 的已验签 issuer、namespace、唯一 principal 和 workspace 构造 scope，按完整
scope/session/Turn/expected digest 读取不可变 snapshot，并再次校验返回坐标、摘要与
Skill ID 不超过冻结 ceiling。任何缺失、篡改、歧义、跨租户或包含 MCP 的快照都在
Attempt authority 持久化、模型调用和工具执行之前失败。浏览器 origin 只保留为 Host
上下文来源，不再冒充 JWT issuer；重启/重试使用同一 durable binding。

本切片只建立可信恢复边界。它不加载 Skill 包、不注册 Skill 工具、不调用 MCP，
不处理凭证/UI，也不打开实际部署开关。验证为定向 32 项、真实 PostgreSQL 相关
59 项通过（1 项环境门控跳过）、全量 3903 项通过/816 项跳过及完整 `make check`；
独立规格与质量审查尚待完成。

规格审查补充：实际 RabbitMQ Worker 不经过旧 `SessionCommandConsumer`，而是由
`handoff_command` 在租约事务中调用 canonical `append_command_message`。该路径现在
解析 accepted command 契约，普通消息使用服务端冻结的 extension Turn；clarification
不创建新 Turn。Worker 以 accepted Event 的 `causation_id` 为首选关联，同时复核
`command-input:{event_id}`、事件类型/actor、正文和 clarification id；旧
`{idempotency_key}:message` 只保留兼容。已完成的历史绑定会先验证关联完整性再忽略，
不会阻断第二个绑定 Turn。缺失、篡改或歧义关联继续在模型/工具前失败。
真实 PostgreSQL 覆盖 normal、restart、correlation missing/tamper、clarification 和
连续两个绑定 Turn；定向 13 项、相关矩阵 68 项、全量 3904/821 及完整质量门通过。

质量审查补充：Rabbit 物化与 Worker 的绑定恢复现在共用 Core accepted-command
完整性校验，重建原始命令并核对 fingerprint、session、idempotency。API pending
判断同时识别生产 causation 和 canonical key，只把无 causation 的旧 key 当兼容路径。
Worker 合并两类候选并按 Event ID 去重，逐个验证所有历史绑定；不同 Event 同时声称
canonical/legacy 关联、历史正文缺失或篡改都会在扩展读取与执行前失败。服务外定向
50 项、专用真实 PostgreSQL API/Rabbit/恢复链路 16 项通过；任务仍等待独立复审。

最终质量补充将 canonical/legacy 关联收敛为单一严格谓词，并在读取绑定含义前完成
accepted payload 类型校验。API 与 Worker 均先一次遍历构建 Event/correlation 索引，
再按 accepted 命令 O(1) 查找候选；100/120 条长历史的操作计数测试证明没有逐命令
重扫。partial、非 MESSAGE、错误 causation，以及删除两个绑定字段但快照仍存在的
状态都会在模型与工具执行前失败关闭。
API 索引保留候选列表而非覆盖重复值，并要求 accepted Event ID 唯一；严格关联候选
按 Event ID 去重后必须恰好一个，否则拒绝后续接纳。最终证据：定向 59 项、真实
PostgreSQL 51 项、全量 3922/826，以及文件大小、
Ruff、876 个源文件的 strict Mypy、Eval 10/10 和 diff 检查全部通过。

当前 Worker Skill 切片 EXT-WORKER-01B：独立默认关闭的
`ZEBRA_CLOUD_SKILL_WORKER_ENABLED` 只允许 PostgreSQL 云 Worker 启用，并强制依赖
前一切片的精确扩展快照恢复。正常 composition 复用同一 DSN、deployment namespace
和私有对象存储；工具输入只能来自 `PreparedWorkerContext.extension`，不会从请求端
重新推导。local、关闭路径和无绑定历史不会创建云 catalog 或读取发布/对象状态。

已有 typed `skills.list/read` 通过窄 catalog 注入点复用。每次调用都按完整 scope
重新读取 snapshot 内每个安装和钉扎发布，停用、修订/版本变化、非 ready、缺失或
跨租户状态一律失败关闭。list 只读取元数据；read 才按需读取一个对象版本，并在
ready publication receipt 的精确 `object_version` 上做版本读取，再在内存中复核
对象大小/SHA、ZIP manifest/content digest、名称、描述、版本标签和有界
canonical UTF-8 路径。归档不落盘、不解压到宿主，也不执行 scripts。重启与重试从
同一不可变 snapshot 恢复相同版本。实际 PostgreSQL/MinIO/Rabbit Worker 测试覆盖
正常 `build_worker_loop_service` 云组合及 broker-only CommandWorkerProcess 的真实
发布/消费、模型工具广告/执行、双租户、重启、撤销、receipt 版本和对象篡改；测试
没有在服务创建后注入私有 extension/task-binding 字段。

Worker live authorization is now a bounded exact-scope batch contract: list
uses one PostgreSQL statement/transaction and read uses the same statement both
before and after object/ZIP verification. The second result must equal the
first frozen installation/publication/receipt set; otherwise the provisional
content is discarded. Gateway construction is metadata-only and the normal
synchronous Worker path does not allocate a bridge thread. Unknown cloud store
or object-adapter exceptions are logged with their original traceback and
translated at that narrow boundary to a fixed chained `backend_unavailable`
failure, so parallel ToolResult and durable/client metadata cannot expose
backend credentials.

尚待完成：目录查询与后台操作、安装升级/卸载、凭证 Broker/OAuth、HTTP MCP 协议完善与网络出口、其余管理 API、Trench 设置两部分及浏览器/真实 Agent 验收。不能从上述默认关闭的 Worker 测试推断生产环境已启用。

当前接纳切片 EXT-ADMIT-01A：独立且默认关闭的
`ZEBRA_CLOUD_EXTENSION_TURN_ADMISSION_ENABLED` 只对通过正常消息端点授权、携带
真实 `VerifiedHostGrant` 和 `agent.run` 的云端 message 生效；它不要求或授予
`extensions.read/manage`。每次接纳先把当前 Segment 解析回根 Task，读取其不可变
TaskBindingSnapshot 和冻结的 `skill_components`；VerifiedHostGrant 的 issuer、
namespace、workspace 和唯一 principal 必须精确连续。没有 Skill ceiling 的旧 Task
选择零项，而不是获得后来安装的 Skill。服务端只在该 ceiling 内按完整身份作用域
分页读取当前 Skill 配置，只选 enabled 安装，并以 4 页、400 条扫描、32 个启用项
为硬上限，越界整体拒绝。客户端提供 snapshot、snapshot_ref、digest 或 turn 坐标
均被拒绝。

接纳事务复用 v54：在 PostgreSQL 中锁定并复核所选配置修订后，同一事务写入
`SESSION_COMMAND_ACCEPTED`、既有 command wakeup/RabbitMQ Outbox，以及不可变
ExtensionSnapshot。事件 payload 中的 turn 使用既有 UUID/legacy 校验，digest 是
可信绑定。重复 Idempotency-Key 在重新选择前返回原事件，因此配置改变后仍复用
原绑定；修订漂移、快照冲突和 stream CAS 失败均不会留下事件、Outbox 或快照孤儿。
普通 message 在上一条 accepted command 尚未物化时会被拒绝，避免两个待处理命令
绑定同一个确定性 Turn。clarification 延续只绑定当前 WAITING_INPUT Turn；如果该
Turn 已有可信 accepted-command 绑定，就按原 digest 读取同一不可变 snapshot，不再
按实时配置重选。实时停用或撤销仍由后续执行授权拒绝，不因历史快照而放行。
此快照仍只是输入钉扎，不是调用授权；Worker、Skill 载入和 MCP 网络执行未启用。

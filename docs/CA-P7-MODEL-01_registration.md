# Cloud Agent 模型修订注册 v1

管理接口已有实现候选，Worker 重启及跨仓验收待验证。运行时复用现有 `RuntimeProviderProfile`、原生 pin 和 Bundle Assembly。管理操作不执行模型调用。

| 操作 | 方法和路径 | 权限 |
| --- | --- | --- |
| 注册或重放 | `PUT /v1/management/model-profile-registrations/{operationId}` | `model-profile.register` |
| 查询原操作 | `GET /v1/management/model-profile-registrations/{operationId}` | `model-profile.registration.read` |

两个入口使用现有管理 scope headers 和独立的 action 授权。PUT 使用 `x-runtime-model-profile-contract: cloud-agent.model-profile-registration/1`。scope 绑定 deployment、product、environment、audience 与当前 trust revision。原操作 ID 为 UUID。授权检查先于读取或写入。无有效凭据返回 401，作用域或操作权限不符返回 403，授权作用域内未知原操作返回 404。

PUT 正文包含 `modelConfigId`、正整数 `revision`、`model` 和 `approvedProviderProfile`。后者为部署已批准的 profile 完整 pin。运行时从批准目录解析 endpoint、协议、凭据引用和执行限制，并校验请求模型在其允许列表中。首期复用部署批准的接入参数，平台模型目录中的地址和协议须与该批准项一致。新增接入地址或凭据引用仍需目标部署批准。

同一 scope 和 operationId 的同一规范请求返回原回执。相同 operationId 的不同请求返回 409。同一 scope、modelConfigId 和 revision 的内容由数据库唯一约束固定。另一 operationId 提交同一修订且内容一致时可得到绑定同一原生 pin 的回执。不同内容返回 409。成功回执包含 `operationId`、`modelConfigId`、`revision`、`profilePin` 和 `model`。错误响应使用有界原因码。

在一个短事务中保存原生不可变 profile 与原操作回执。profile 沿用既有规范摘要，限制为所注册的模型，原生 ID 由作用域与模型配置身份派生，版本由修订派生。存储以作用域和完整 pin 查询。Bundle 校验、发布及正常 Worker 从共享持久存储解析该 pin。既有部署目录 pin 保持兼容。凭据仍由 Worker 按原生 profile 中的批准引用解析。查询结果、Bundle 和回执只携带安全元数据。

验收依次覆盖同操作重放、同修订竞争、跨作用域拒绝、未知原操作、提交后丢响应及重启查询。再验证 API 和 Worker 都能解析同一固定修订，替换修订和伪造摘要均拒绝。最后经 Overdoze 目录和草稿 CAS 发布两个 Agent，验证两个 Release 绑定同一 pin，并保留旧 Release 对原修订的解析。

发布管理入口支持 `cloud-agent.publication-approvals/1` 私有配置，包含最多 16 份既有单 Definition 批准。各批准共享同一 scope，凭据摘要、actor 和 Definition ID 分别唯一。HTTP 入口按凭据选择批准。原操作按 actor 隔离。旧单条配置仍兼容。脚本评估及其他无凭据选择器的入口继续使用单条配置。真实 PostgreSQL 回归验证同一 Target 物化两个 Definition，A 查询 B 原操作返回 404。

Worker 的旧快照回归另覆盖模型 API Key 轮换。任务快照持久化后替换批准环境变量的合成值，新 Worker 向受控 HTTP 传输发送新凭据，仍使用原端点、模型和固定 pin。两个值均未出现在事件中。部署目录与已注册 profile 两种路径均通过。该检查使用 SQLite 快照和受控传输。

PUT 支持 `expectedConnectionDigest`，其值为批准 profile 的 `[base_url, api_key_env]` 规范 JSON 的 SHA-256。首次注册时任一字段不匹配返回 409，原操作不落库。该字段计入原请求摘要，缺省时保留旧调用的摘要规则。

Registered provider profiles can carry an optional display name from the model catalog revision. The profile digest covers a present label. Legacy profiles omit it on serialization and business discovery falls back to the provider model name.

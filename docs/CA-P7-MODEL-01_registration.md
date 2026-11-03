# Cloud Agent 模型修订注册 v1

状态为待实现合同。运行时复用现有 `RuntimeProviderProfile`、原生 pin 和 Bundle Assembly。管理操作不执行模型调用。

| 操作 | 方法和路径 | 权限 |
| --- | --- | --- |
| 注册或重放 | `PUT /v1/management/model-profile-registrations/{operationId}` | `model-profile.register` |
| 查询原操作 | `GET /v1/management/model-profile-registrations/{operationId}` | `model-profile.registration.read` |

两个入口使用现有管理 scope headers 和独立的 action 授权。scope 绑定 deployment、product、environment、audience 与当前 trust revision。原操作 ID 为 UUID。授权检查先于读取或写入。无有效凭据返回 401，作用域或操作权限不符返回 403，授权作用域内未知原操作返回 404。

PUT 正文包含 `modelConfigId`、正整数 `revision`、`model` 和 `approvedProviderProfile`。后者为部署已批准的 profile 完整 pin。运行时从批准目录解析 endpoint、协议、凭据引用和执行限制，并校验请求模型在其允许列表中。首期复用部署批准的接入参数，平台模型目录中的地址和协议须与该批准项一致。新增接入地址或凭据引用仍需目标部署批准。

同一 scope 和 operationId 的同一规范请求返回原回执。相同 operationId 的不同请求返回 409。同一 scope、modelConfigId 和 revision 的内容由数据库唯一约束固定。另一 operationId 提交同一修订且内容一致时可得到绑定同一原生 pin 的回执。不同内容返回 409。成功回执包含 `operationId`、`modelConfigId`、`revision`、`profilePin` 和 `model`。错误响应使用有界原因码。

在一个短事务中保存原生不可变 profile 与原操作回执。profile 沿用既有规范摘要，限制为所注册的模型，原生 ID 由作用域与模型配置身份派生，版本由修订派生。存储以作用域和完整 pin 查询。Bundle 校验、发布及正常 Worker 从共享持久存储解析该 pin。既有部署目录 pin 保持兼容。凭据仍由 Worker 按原生 profile 中的批准引用解析。查询结果、Bundle 和回执只携带安全元数据。

验收依次覆盖同操作重放、同修订竞争、跨作用域拒绝、未知原操作、提交后丢响应及重启查询。再验证 API 和 Worker 都能解析同一固定修订，替换修订和伪造摘要均拒绝。最后经 Overdoze 目录和草稿 CAS 发布两个 Agent，验证两个 Release 绑定同一 pin，并保留旧 Release 对原修订的解析。

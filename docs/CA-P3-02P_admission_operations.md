# CA-P3-02P：Task 与 Client Surface 原操作收据

状态：Review，完整 make test/check及API/真实PG通过，最终消费者固定发布来源联合另记。依赖已发布 O76ba18d7；对应 Overdoze OD-P3-01M。

## 所有权与兼容

Native 拥有 Task、Client Session、mount、Controller 和执行历史；业务 BFF 拥有业务原请求、CAS、加密凭据与当前业务权限。
复用已有 PostgreSQL IdempotencyStorePort 两个不可变 action 的唯一插入，不引入通用操作框架、表或迁移；schema 尾仍113。
SQLite 新合同503；旧 Task/surface、审批、Worker、历史快照和 Coverage 行为不变。新入口仅支持 execute=false 的显式 Task 创建。

## 公开合同 client-admission-operation/1

`POST /v1/admission-operations/{operation}`，operation 为 UUID：

```json
{"kind":"task_create","task":"","run":"","payload":{"prompt":"…","execute":false}}
```

kind 另支持 surface_open / surface_mount，须给精确 task UUID、run；payload 是原 client-surface 请求，不能改成查询当前状态后生成的新请求。
打开包含 grant/mount/scope/controller；挂载包含 mount/scope/controller 并带原 X-Zebra-Client-Session。新入口不绕过现有准入校验。
体最多65536字节；整数限 ±9007199254740991，拒绝浮点；保留 Unicode 原文。当前 HostGrant 仍经标准签名验证、授权及一次消费。

两个请求头均只在可信 BFF↔Native TLS 上传输，禁止下发浏览器或日志：

- X-Zebra-Admission-Key：BFF 为原操作生成的32字节随机密钥，64位小写 hex；Native 不持久保存原值。
- X-Zebra-Admission-Hash：GET 必须与原 request_hash 匹配。POST 由 Native 独立计算，不信任调用者摘要。

hash = SHA256(排序键、紧凑 UTF-8 JSON：kind/task/run/payload/key_hash/credential_hash)，后两项是 SHA256(原32字节 key) 与 SHA256(原 Client credential UTF-8，创建/打开为空)。
原操作持久 scope 包含部署 namespace、Host/workspace/principal、签名 issuer/subject、Origin、全部 resource refs（含原 thread/run）；不绑定临时 Grant ID，允许当前新签名查询。Task 内部幂等键也使用完整 scope，不能用同 UUID 跨 Thread/issuer 串收据。

同 URI `GET` 无 body/query，只查原收据。需要当前相同精确 scope 的 HostGrant、原恢复 key/hash；mount 还需同原 Client credential。
打开/挂载的当前 Host/Task/Run/Profile 绑定、已发布 Profile 都要重新检查；mount 当前 Client Session 亦重验。读取不要求再次领取 Controller。

| 状态 | 含义 |
| --- | --- |
| not_observed | 无该 scope 原 claim；不证明未提交，不授权重发 |
| unknown | 有原 claim，无完整结果；保持阻断，不接管、不修复 |
| completed | 有确切原结果，含 operation/request_hash/response_status/sealed_response |
| 409 / 401 / 403 | 原输入/密钥/credential 冲突或当前授权拒绝，不补成功 |

sealed_response = Base64(12字节随机 nonce + AES-256-GCM(原 response JSON, key, AAD=request_hash UTF-8))。
Native 数据库只留摘要、有限路由/Profile 元数据及密文，绝不存明文 bearer/fence/recovery key；BFF 必须验证 operation/hash/AEAD 和有界原响应，再登记引用。
原生错误响应也封存为原结果；completed 不等于准入成功，BFF 不得用错误收据进入下一阶段。

## 一次分发和故障边界

1. 当前授权与输入检查后，唯一保存 client-admission-v1-claim，包含随机胜出 nonce；事务先提交。
2. 仅第一次确实保存该 nonce 的调用执行既有 Task 或 surface 组合。重复 POST 只查结果，绝不第二次调用组合。
3. 原结果加密，唯一保存 client-admission-v1-result，当前授权再检查后返回。GET 仅索引读取这两条原记录。
4. 请求 deadline2秒，存储沿既有 task I/O 有界连接/超时；不持锁跨准入流程或外部调用，无全局串行锁。

既有 surface 是多个原生提交，不能宣称新增跨组件原子性。若 claim 后、任何效果前后、结果落盘前中断，可能永久 unknown；无原收据时禁止从当前 Task/Controller 猜测或重新领取，人工非提交证明/处置另立任务。
业务 BFF 响应丢失但 Native 原结果已保存，可在任意副本 GET 解密同一原响应；fence 原值不重签、不轮换。
密钥遗失同样拒绝，不生成替代 key。原 claim/result 无自动过期/清理；容量与留存需生产运营方案，不能称生产 HA 已验收。

## 验证与交付

[证据](evidence/ca-p3-02p/validation.json)。真实共享PG验证并发唯一分发、不可变密文收据、冲突、效果后崩溃永不接管；API验证新 SQLite 禁用、读参数和数字边界、UTF-8与内部 scope。
消费者另以固定已发布来源进行实际 OIDC/签名云/共享业务PG、双BFF进程/重启、三处响应丢失、SDK/Worker联合。该隔离环境不代表客户产品、生产 sandbox、容量或数据库 HA。
生产启用前保留旧接口兼容，但业务写路由必须排空/隔离会绕过原日志的旧BFF；不自动导入历史单机记录。无部署、生产迁移、主线合并或 npm 发布。

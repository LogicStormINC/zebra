# CA-P3-02I — 原请求映射、unknown 对账与 SDK 恢复

2026-10-22，Owner Luke Ding。[合同](contracts/sdk-command-recovery/contract.json) · [证据](evidence/ca-p3-02i/validation.json)。

## 依赖与责任

复用已发布 H `be9f7cd2` 的只读 `client-command-receipts/1`，不改写旧合同。
发现旧 AG-UI POST 会选择当前 Segment，因此本片增加可选 `X-Zebra-Command-Segment` 前置条件：
格式错误400、与解析出的当前 Segment 不同409；匹配后向既有命令服务传递该已解析 Segment。
capabilities 新增 `client_command_segment_precondition_contract_version=1`。无 header 的旧流程保持。
业务 BFF 必须先确认该能力与收据1，再原样传原 Segment header；旧 Runtime 忽略 header 不能冒充可恢复。
没有新原生状态表、迁移、执行状态机或 Coverage 改动。

业务 BFF 请求日志属于业务自己的数据库；Overdoze 新增可复用 Go 库，管理进程不挂载执行代理。
Runtime 仍拥有 Task/命令接纳/执行权威。SDK 的持久标识不是授权、请求原文或命令状态权威。

## DDD 与一致性

| 所属对象 | 不变量/事务 | 外部引用与协作 |
| --- | --- | --- |
| 业务 BFF 原请求日志 | tenant+resource+key 唯一，subject/原Runtime引用/原Target/请求指纹与独立原生key不可变；unknown1→accepted2 CAS | 只记原生 ID、原 key、SHA256 指纹与接纳观察，不复制 Runtime 聚合 |
| SDK 待对账标识 | 验证请求后、发出 POST 前持久化；一次提交，未知保留 | 同源 Cookie BFF 只读对账；不拥有权限 |
| 原生接纳收据 | 当前 Session/主体/Task/Run 授权，按原 Segment+key 查询 | 沿用 H，不要求当前旧挂载仍可执行 |

BFF 短事务提交唯一 claim 后才外呼；无跨 HTTP 的 DB 锁。
浏览器 UUID 仅定位日志；原生 key 由含业务范围/坐标/原文指纹的固定版本摘要形成并独立持久化，
H 对账使用落库原Runtime引用和原生 key，不从最新Runtime、新页面值、当前算法或浏览器 UUID 猜测。
崩溃发生在 claim 与 POST 之间时也保留 unknown：原生没有非提交证明/原子保留协议，不能安全自动补发。
已缓存 accepted 仍重新调用 H 验当前原生权限；不提供跨业务库/原生库线性化撤销或零撤销窗口。

## 开发者接入与交互

1. 业务 BFF 当前业务登录/identity_key 映射、资源权限及 Origin/CSRF 独立成立；仅服务器拥有原生凭据。
2. bootstrap 协商 `mode=bff`、`surfaceMetadataVersion=1`、`clientStateVersion=1`、`commandRecoveryVersion=1`。
3. SDK 需要可用的 sessionStorage（或显式 Storage）。新模式 key 为规范小写非零 UUID；旧模式规则不变。
4. 提交前同步挂载、校验/复制有界 JSON，再存原 key。BFF 将可信坐标和原请求指纹唯一落库，最多转发一次。
5. 正常 accepted 清除标识；网络/5xx/畸形成功/不确定错误保留标识并 disconnect，不释放原控制权、不重试 POST。
6. 重载发现标识时 Runtime 在 Provider 启动前停止，阻止挂载、轮询、心跳和释放；恢复 Hook 仍可用。
7. `runtime.readableCommandRecovery` / `useZebraReadableCommandRecovery()` 返回可空接口，调用 `pending()`，
   再显式 `reconcile(key)`。发同源 GET `.../commands/receipt`，只带原 Idempotency-Key，无 body/query。
8. BFF 从原持久映射取坐标，当前业务授权后调 H；not_observed/缺失映射返回 unknown，错误不伪装成功。
9. accepted 只返回原 commandId、清除对应标识。该 Runtime 保持停止；重新取得当前 bootstrap，替换 Provider/config 或新建 Runtime，再挂载。

标识最多16个/2048字符，只含不透明 UUID；不保存页面值/消息/原生Token/fence。
拒绝损坏存储、配额失败和畸形/额外字段的对账响应；不会静默清理未知请求。
标识只保证当前 tab 的刷新恢复，不覆盖清空存储/换设备；共享业务日志仍是事实源，跨设备发现另行实现。
accepted 仅证明接纳，不证明模型执行完成、业务成功或 Coverage 证明。

## 验收边界与后续

SDK core/React StrictMode 检查重载、坏存储、并发、畸形回执、不自动启动/释放、原值不落浏览器存储。
完整 verify 包含包消费、React18/19、Chromium/WebKit 和 Next hydration。
双浏览器成对验收使用实际打包 SDK、参考 Cookie BFF、独立 Go 进程、业务专用 PG database、原生 HTTP，
丢失原生成功响应后重启 Go 进程，再重载浏览器、查询原命令、重新 bootstrap/挂载；命令数保持1，历史值和重开 Worker Context 保留。
该验收中原生注册表是真实 PG，Task/命令沿用本地 SQLite 权威；Cookie/私有桥为夹具，不是生产业务 IdP/签名 cloud 或完整模型 harness。
Go 同时验证真实 PG 多实例唯一性/CAS、claim 前后崩溃、回执已提交但确认丢失、当前撤销和背压。
具体最终门禁/保持摘要见证据。管理前端 mock、历史、旧 pin 和 Coverage 保留；不关闭 P3 总体验收。
后续独立推进生产业务 IdP、跨设备发现/人工处置、无法观察请求的权威终结协议、共享持久发现、撤销与多副本容量/HA 验收。
不部署、不执行生产迁移、不发布 npm、不合并主线。

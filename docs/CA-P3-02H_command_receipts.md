# CA-P3-02H — 当前授权的命令接纳收据查询

2026-10-22；Owner Luke Ding。[合同](contracts/client-command-receipts/contract.json) · [验证证据](evidence/ca-p3-02h/validation.json)。

## 任务与 DDD 边界

G 已发布 SDK/BFF Readable 值提交，但 unknown 后缺少公开查询原命令的接口。
先补原生只读前置，不直接开启 P4；BFF 持久原请求映射和 SDK 恢复独立实施。
SessionCommand 接纳事件仍为事实源；Core 定义只读 Port/不可变收据，Storage 适配现有表，API 只编排当前授权。
不增加聚合、状态表、数据库迁移、Worker 执行路径、Go 代理或新依赖。

## 开发者接口

`GET /agui/threads/{taskId}/runs/{runId}/command-receipt`，无 body/query。
可信 BFF 提交 `X-Zebra-Client-Session`、原 `Idempotency-Key` 和 `X-Zebra-Command-Segment`。
Key 必须为原始 1–256 个可见 ASCII 字符；Segment 必须是原命令 Segment UUID。
不得从当前 activeSegment 猜测，不得换 key、Run、Session 或用新页面值重发。
cloud 还须独立验证的当前 HostGrant/主体；原生凭据始终留在服务器。
capabilities 中 `client_command_receipt_contract_version=1` 表示已装配完整客户端平台和收据读取 Port。

| 结果 | 意义与消费者行为 |
| --- | --- |
| 200 accepted + commandId | 原命令持久接纳；仅保存原 commandId，继续按已有执行观察协议查询 |
| 200 not_observed | 尚未观察到匹配事实；保留 unknown，不代表未提交，不允许自动重发 |
| 400 / 405 | 输入或方法错误；不重试变更命令 |
| 401 / 403 / 404 | 当前身份或资源不允许观察；不回退历史凭据/其他 Session |
| 409 | 既有 Task 投影尚未就绪；保持 unknown，不重发变更命令 |
| 503 / 网络失败 | 查询不可用；保持 unknown，不伪装 not_observed |

BFF 必须从可信持久映射取得原 Task/Run/Segment/Session/key，并重新检查业务身份、Origin/CSRF 与资源权限。
本片没有实现该映射、HTTP 代理、浏览器新路由或 SDK reconnect；不能仅凭接口存在宣布断线续接完成。

## 授权与并发

查询前后复用当前 ClientSession 和 Task/Run `agent.run`，原 Segment 必须归属该 Task。
只认相同 ClientSession、Task、Run 的 admission1 接纳事件；旧版和不匹配记录不提升为成功。
查询历史收据不要求当前挂载、Profile 或 Controller 仍有效；它不授予新执行权。
权限跨注册表和事件库分别观察，不提供跨库线性化撤销；第二次授权失败不披露收据。
权限/dependency 错误保留错误语义，异常内容不返回调用方。

## 性能、数据与兼容

SQLite/PG 使用现有 Segment+幂等键唯一索引，PG 显式包含 deployment namespace。
查询 LIMIT 1，只选最多37字符的 command_id，不把整个事件/页面值/消息读入 Python，不做历史分页扫描回退。
数据库仍需解析匹配行 JSON；不宣称磁盘读取字节与该事件大小无关。
PG 优化器可为小表选择其他现有索引；大命令数据测试确认原幂等键索引可用。
handler 内 ClientSession/Task 复核和收据读取共享现有两秒 task_io_deadline，PG 连接/语句沿用原生有界 I/O；没有新锁、队列或持久写入。
HTTP HostGrant 预检另用原有两秒预算，不宣称端到端请求仅需两秒。
SQLite 保留本地开发连接行为；两秒预算不宣称覆盖 DNS/OS 调度或整个系统硬实时上限。
原历史、SDK、已有合同/证据、Coverage 及证明机制不变，不修复/重写旧命令。

## 验收与后续

实际 SQLite 接纳/重开/重复 GET 不写事件、ASGI GET header/body/query、当前 Session/Task 复核、
错误依赖/缺失 Port/cloud 缺少主体、不同资源/旧版本回归；独享 PG17 两 reader/namespace/索引查询。
另用真实PG调用收据handler，验证有界数据库连接正向、独占表锁超时返回503、释放锁后恢复；
该项Session/Task授权使用本地SQLite夹具，不等于签名cloud正向或多副本验收。
完整 make test/check 与保护文件摘要另见证据；可选 PG 默认门禁中跳过，另行独享运行。
测试 cloud 缺失主体只证明拒绝，不证明真实业务 IdP/cloud 签名正向联调。
下一片：可信 BFF 的原请求持久化与 unknown 查询映射，再补 SDK 恢复和真实联合验收。
多副本共享 CAS、生产 IdP、完整 Worker 模型、HA/容量仍需独立验收；P3 总任务不关闭。
无部署、生产迁移、npm 发布或主线整合。

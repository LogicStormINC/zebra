# CA-P3-03F：业务 BFF Surface SDK

配对 OD-P3-01AD，依赖已发布 E/D，复用 public metadata 校验和有界 JSON 读取。Python Runtime、Worker、存储和原生 HTTP 不变。

## 显式流程

`createBFFSurface({path, storage, fetch?})` 不发网络请求。路径绑定业务登录、产品及文档；BFF 独立核验当前业务身份/平台注册/权限。

1. `submit(captured, admissionRevision)` 只发送已注册 action/readable 名称；Readable input 值留给后续独立命令。先持久 operation/stage，再一次 POST。
2. `inspect(operation?)` 显式 GET 原 Surface 收据；known201 转 recorded。unknown/拒绝/网络错误保留原定位符，不自动重发。
3. `install(mappingRevision)` 仅 recorded 允许；先持久 install/expected，再一次 POST。未知结果之后只能 inspect/observe 的 GET /installed。
4. `discover()` 找回服务器当前原操作；不会覆盖其他 pending。清空本地后先 discover 再显式 observe 当前映射，不补发安装。
5. installed 校验公开元数据和当前 Task/Run/client/mappingRevision，清除 pending；调用方自行通过现有 SDK adopt，另行 RUN。没有自动 Controller、挂载或执行。

## 合同及失败边界

浏览器版本1精确六字段：version/status/operation/revision/surface/binding。Surface 十一公开字段复用 validateSurfaceMetadata；binding 仅 mappingRevision/taskId/runId/clientSessionId。unknown/clear/rejected 不携带元数据；recorded 是历史收据，installed 是一次当前授权下的状态观察，不是持久安装操作收据或永久权限。

同源凭据模式、禁止跳转、no-store、10秒 Abort、64KiB响应、16KiB请求。元数据/正文/Readable值/Native凭据/fence不进入 SDK storage。存储不可靠、阶段不符、忙、非法DTO/秘密字段/错误revision全部停止，不自动重试或生成新意图。

本地 pending 是单 storage instance 的协调；多个独立 SDK 实例/设备最终由 BFF 共享 CAS/原操作门禁裁决，不宣称浏览器分布式锁。网络收据、映射、RUN、Worker/外部效果分别举证；缺失不是非提交证明。

## 验证

7个新增确定性用例覆盖：双阶段回复丢失/重建GET、定位符丢失发现与只读映射观察、unknown/拒绝/缺映射、存储失败、严格DTO与秘密/摘要、revision及竞争保护、同源传输/名称/注册值隔离。SDK check与172测试通过。根make test/check和最终固定源消费者证据单独记录，不把候选运行当发布源验收。

未部署、未迁移、未main合并、未npm发布；历史/原收据/Coverage及旧客户端保持。

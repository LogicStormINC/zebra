# CA-P3-02O：原生审批原操作收据与 Controller 当前性

状态：Review，完整门禁通过；[最终证据](evidence/ca-p3-02o/validation.json)。依赖已发布 N047fad79；供 Overdoze OD-P3-01L 通过公开 HTTP 消费。

## DDD 与合同

Native 独占 Task/Run/段、Controller、审批决定、继续执行命令和执行历史；BFF 的业务身份/映射/原请求日志不进入 Native 数据库。
本片复用核心 ApprovalDecisionService、SessionCommand、投影和已有事件唯一键，不新增通用 Operation 引擎、数据库表或迁移。旧审批入口、SDK 和旧合同不变。

- `GET /v1/tasks/{task}/runs/{run}/client-authority`：要求原段头 `X-Zebra-Command-Segment`、当前 HostGrant、Client Session 和 Controller fence。返回合同1、精确 Task/Run/段/Client/Profile 及 controller=true；不返回凭据。允许已绑定但尚未提交首个 Run 命令的合法挂载，不能因此获得审批权。
- `POST /v1/tasks/{task}/runs/{run}/approval-operations/{operation}`：operation 为原 UUID；体只含 decision(approve/reject)、expected_revision、operator、reason。当前 Task/规范 Run/原段、Profile、Client 和 Controller 均须匹配。
- 同 URI `GET`：无 body/query；按原段和 UUID 读取原决定，要求当前 Host/Task/Run/Client/Profile 授权，但不要求旧 Controller 仍持有 fence。不根据“当前已批准”推断原请求成功。
- 完成收据固定 status、operation、decision、request_hash、event_id、sequence；不存在只返回 not_observed，不证明未提交，也不授权重新 POST。
- request_hash：SHA256(精确 version/task/run/segment/client/operation + 原请求字段的排序键、紧凑 UTF-8 JSON)。不含凭据；operator/reason 原输入纳入 hash，事件展示仍用核心规则。Go 消费方独立比对同一请求，不能只相信 status。
- `/capabilities/runtime` 的 client_approval_operation_contract_version，仅在完整客户端组件及支持该 Port 的持久 PG 事件存储中为1。未实现的 SQLite 新路径拒绝，原本地审批保留。

## 原子性、并发与恢复

新路径在有界 task I/O 预算内锁既有 session_streams 唯一行，复用原生 PostgreSQL transaction work unit；锁内重新读当前授权、原收据和期望投影版本。
一个短事务原子追加审批事件、更新 Session/Workspace 投影，并在 approve 时追加 N 定义的 trusted approval-resume 命令及既有 wakeup。Worker 仍独立消费未投影命令。
不调用旧命令入口的全 Session 事件加载，也不在事务中请求 IdP/Broker/模型。锁等待1500ms、整请求4秒；单行索引查询、固定字段及8KiB事件 payload 上限。

决定或继续执行失败时整事务回滚；提交结果未知只允许 GET 原收据。重复 UUID 相同文档只读取原事实，异文档冲突，不能追加第二审批/继续执行。不同 UUID 的同版本审批由原生 Session CAS 拒绝；BFF 还必须持久阻断未知槽的新 UUID。
读取永不修复投影/补命令/重试写入。提交后再查当前授权，撤销或不确定时拒绝返回完成；原事件仍保留以供后续受权观察。

## 验证与升级边界

API 输入/会话/原段/Run/Observer 门禁专项、真实独享 PG 两副本原 UUID 幂等、原收据只读、异文档冲突，以及模拟继续执行崩溃的决定/投影整事务回滚。
实际签名云/BFF/SDK/Worker 联合证据由 L 在发布 pin 后独立记录；伪造 _current 的存储专项不能被称为真实云授权证明。完整 make test/check 与实际结果见机器证据。

无历史事件、原收据或 Coverage 重写；无 schema 变更，不运行生产迁移或部署。先升级提供新端点的 Native，再启用新 BFF 消费；旧副本能力不足拒绝，不 fallback 旧审批或自动换 UUID。保留原契约，允许旧消费者继续使用旧接口。
真实产品/供应商、存储故障切换、HA容量和生产发布仍需独立验收。

## 最终验证回执

最终 make test：11046通过、3029条件跳过（1276.76秒）；make check：1403类型文件、30eval、文件边界3413文件/零违规。API13专项通过，独享真实PG3通过/零跳过，包含reject和禁止完整历史读取。
首轮全量11045通过/3028跳过，唯一失败是capabilities精确字典尚未包含新字段的0；先扩展Owned paths再补明确0断言，保持精确比较，补拒绝事务专项后全部门禁重跑。该失败轮次不算全绿。
旧4671个文件中4661字节相同，既有schema/migrations、历史收据/Coverage及原工作树保留。未发布L候选签名云/双浏览器联合通过不替代发布来源证据；后者由L固定本提交后独立记录。

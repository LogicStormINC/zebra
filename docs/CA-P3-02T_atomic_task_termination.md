# CA-P3-02T — Atomic non-executing Task admission and termination
- Status: Review; make test 11066 passed/3048 conditional skips; make check passed; 32 focused (20 API +12 real PG), no skips; candidate Chromium/WebKit atomic Task joint passed. Published-source consumer joint remains separate. Dependencies audited: published S8f44e5af/P302d9922; user-authorized stacked continuation, dependencies not merged main.
- Human owner: Luke Ding; executor: Codex; branch codex/ca-p3-02t-atomic-task-termination.
- Owned paths: apps/api/src/zebra_agent_api/{client_admission*.py,task_api.py}; packages/agent-storage/src/agent_storage/postgres/admission_atomic_surface.py; tests/{api/test_client_admission*,agent_storage/test_admission*}; docs/CA-P3-02T_atomic_task_termination.md; docs/evidence/ca-p3-02t/; docs/{AGENT_TASKS.md,实施任务拆解与阶段验收.md}; PROGRESS.md; WORKLOG.md; task_plan.md.
- Boundary before code: new atomic-task/1 only task_create execute=false; reuse native atomic Task admission, exact same-PG adapters and frozen authority; reject Workspace allocation, attachments/MCP and Coverage/Worker execution. Prepare definition/manifest before effect locks; audit/manifest/claim/stop excluded. Business Task/Session/events/projections/index/binding plus sealed result share commit fence. Active lock=pending; durable STOP plus free execution lock and absent atomic result=noncommit, never absence alone. Old protocols and unknown unchanged.
- DDD: Native owns effects and proof; BFF freezes protocol in encrypted original intent, shared CAS and one termination POST with GET-only unknown recovery. Credentials remain BFF. No automatic resend/new UUID/pending clearance/Controller reclaim.
- Validation: actual PG atomicity/stop/commit/crash, strict public HTTP and current authority, both make test/check; fixed published producer joint where feasible; docs/evidence/scoped push. Preserve frontend mock/history/original receipts/Coverage. No deployment/production migration/main merge/npm/HA claim.

## Transaction and proof boundary

Task creation reuses existing native domain bootstrap and atomic admission. Preparation may freeze a Host manifest outside the effect transaction; this is excluded from business noncommit. No external I/O is allowed while effect locks are held. New protocol is immutable in the original canonical hash and cannot upgrade old operations. Version 3 proof uses a separate task-termination endpoint; pending/unresolved are not proof; committed never proves noncommit. A terminated proof does not authorize retry, pending clearance or Controller reclaim.

## 准入和安全终止流程

1. 可信BFF在新原请求上选择`atomic-task/1`，把协议、原UUID、精确输入和恢复密钥封入现有共享加密日志；CAS提交unknown后仅派发一次POST。协议参与双方规范hash，不能改变协议重发旧请求。
2. Native复用当前签名HostGrant/主体资源边界，提交唯一原claim。新协议只允许`task_create`、`execute=false`，无已有Task/Run。旧协议保持原行为。
3. 在业务锁之外解析输入、解析Definition快照、冻结Host manifest。拒绝附件、MCP资源/提示词/工具、workspace_source和coverage_admission，不派发Worker或模型。manifest冻结和认证审计可能已提交，明确排除在业务非提交证明之外。
4. 精确同Native PG/namespace装配；复用PostgresTaskAdmissionTransaction和既有SessionBootstrapService，既有事件、Session/Workspace投影、Task索引、不可变binding和session.create幂等记录，与密封外层原收据在同一借用事务中提交。根Task/active segment沿用同Session UUID和bootstrap sequence，不调用读适配器的独立只读事务，也不重建索引。
5. 在原执行FENCE锁下做本地PG写入；提交前取得同原claim锁重查STOP。STOP先胜则全部业务写入和原收据回滚；提交先胜则效果与原收据共同持久化。READ COMMITTED保证看见先提交STOP。
6. 独立业务处置授权通过后，BFF先持久化原终止意图，再仅一次`POST /v1/admission-operations/{operation}/task-termination`。后续跨副本/重启只GET这个原操作；不清pending、不换UUID、不重新领取Controller。
7. Native终止POST写唯一STOP后短锁探测。执行持锁时pending；只有拿到执行/claim锁、有持久STOP且无同事务原收据，才返回terminated/非提交证明。单纯缺少收据、超时、进程断连或租约过期都不构成证明。已提交返回committed，读取原完成收据。

## 公开合同与兼容

原POST header：`X-Zebra-Admission-Protocol: atomic-task/1`。新证明端点固定九字段：contract_version=3、operation、request_hash、kind、state、recorded_at、non_commit_proven、retry_allowed=false、controller_reclaim_allowed=false。
terminated/committed时间必须为原STOP/原收据数据库时间；pending/unresolved/unsupported为空时间，not_observed为空kind。状态与布尔严格匹配；BFF拒绝旧版本、错误hash/原UUID/kind、null/缺失布尔和扩展字段。
`/atomic-termination`仍只认atomic-surface/1，不能给Task补发版本2证明；`/termination`保留版本1。旧claims、pre-dispatch已开始和历史部分提交永不升级；原完成收据与观察合同保留。
版本3仅证明本原操作的上述PG业务写入未提交；不证明整个系统无影响，不证明其他Task/历史操作未发生，不是授权重试的离线凭证。

## DDD、并发与范围

Native拥有Task准入事务和非提交事实；业务BFF拥有原操作意图、共享CAS、凭据密文和独立人工处置权限；Go只调用公开HTTPS，不读写Native表。没有新增Saga/全局操作框架、依赖或迁移。
复用按原操作索引的短行锁；effect事务沿用2秒请求预算，探测NOWAIT；无外部HTTP/人工审批/模型等待持锁，无进程锁或超时推断替代PG事实。凭据仅在BFF，前端保持mock；历史数据、原收据、Coverage及旧已发布合同不变。
真实业务IdP/产品账号、生产数据库故障转移/QPS/HA、execute=true/外部效果安全终止、历史部分提交补偿仍开放；不部署、不做生产迁移、不合并main。

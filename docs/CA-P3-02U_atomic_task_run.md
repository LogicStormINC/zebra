# CA-P3-02U — Atomic Task plus initial RUN admission
- Status: Review; make test 11072 passed/3050 conditional skips; make check passed; 40 focused (26 API +14 real PG), no skips; candidate Chromium/WebKit atomic Task joint passed. Published-source consumer joint remains separate. Dependencies audited: published T3c4009f7/Q5c4e93f; user-authorized stacked continuation, dependencies not merged main.
- Human owner: Luke Ding; executor: Codex; branch codex/ca-p3-02u-atomic-task-run.
- Owned paths: apps/api/src/zebra_agent_api/{client_admission*.py,session_queue.py,coverage_http_admission.py}; packages/agent-storage/src/agent_storage/postgres/admission_atomic_surface.py; tests/{api/test_client_admission*,agent_storage/test_admission*}; docs/CA-P3-02U_atomic_task_run.md; docs/evidence/ca-p3-02u/; docs/{AGENT_TASKS.md,实施任务拆解与阶段验收.md}; PROGRESS.md; WORKLOG.md; task_plan.md.
- Boundary BEFORE code: new atomic-task-run/1 only task_create execute=true, exact signed Run resource frozen in original. Task/bootstrap/projections/binding/first RUN command/native PG wakeup and sealed receipt share commit. STOP wins before commit: after execution lock released, prove this admission did not commit. Commit wins: committed, never Worker stopped/noncommit; cancellation/compensation of already-running/external effects remains unsupported. Reject attachments/MCP/allocation/Coverage execution; old protocols never upgraded. Preparation manifest/audit/claim/STOP excluded. No automatic resend, new UUID, pending clearance or Controller reclaim.
- DDD: Native owns Task/RUN/Worker authority and proof; BFF owns encrypted original intent, shared CAS and independently authorized one termination POST then GET-only recovery. Credentials stay BFF; existing Worker only sees committed commands; reuse native transaction and queue contracts, no new coordinator/queue/dependency/schema.
- Acceptance: real PG committed/uncommitted command visibility and wakeup rollback, stop/commit/error, exact Run/auth/version guards; fixed published-source SDK/OIDC/signed cloud/same-run Worker Chromium/WebKit joint; both make test/check, formal evidence and scoped push. Preserve mock/history/original receipts/Coverage; no deployment/production migration/main merge/npm/production HA claim.


## 范围与证明矩阵（实施前固定）

| 原操作与当前事实 | 可报告的事实 |
| --- | --- |
| 新atomic-task-run/1、task_create、execute=true，Run ID与当前签名HostGrant唯一run资源精确一致 | Task及首条RUN准入；不是Worker就绪或执行成功 |
| 原Task/RUN SQL仍持执行门闩 | pending，non_commit_proven=false |
| STOP已持久，获得原执行/claim锁，确认同事务原收据不存在 | terminated，证明此原操作的Task/RUN业务准入未提交 |
| Task、RUN及原收据已提交 | committed，不能证明Worker已停止、未开始或外部效果不存在 |
| 未写STOP，仅缺原收据/网络超时/进程断连 | unresolved/unknown，不能推断非提交 |
| 旧协议或已发生的历史部分提交、已运行Worker/脚本/模型/外部效果 | 本协议不提供回滚/非提交证明，不升级，不自动补偿或重放 |

非提交范围只覆盖这个原UUID/hash的Task、bootstrap事件、Session/Workspace投影、索引/快照、首条RUN和原生PG命令发现/唤醒记录；密封原完成收据同事务。其他操作、认证审计、manifest准备、原claim/FENCE/STOP和BFF处置意图排除在外。

## 交互和一致性

1. 可信BFF在新原请求选择`atomic-task-run/1`，冻结协议、精确Run、execute=true输入、原UUID和恢复密钥，业务共享PG先CAS提交unknown再只派发一次POST。凭据不下发浏览器。
2. Native先验证签名主体/当前Host资源；body.run必须匹配唯一已签名run资源，不允许先准入再补Run ID。解析Definition/manifest在业务锁外。附件/MCP/workspace_source/coverage_admission仍拒绝；旧路径不变。
3. 复用SessionBootstrapService、既有首条RUN构造和PostgresTaskAdmissionTransaction。在同一短PG事务先写bootstrap/投影/绑定，尾随唯一SESSION_COMMAND_ACCEPTED RUN，保持Session投影在bootstrap revision；Task索引包含命令sequence，后续Worker独占消费。Run ID从原请求固定进事件payload与原响应，不在恢复时生成。
4. 复用原生命令发现与Broker outbox的同事务写入，Worker/relay通过普通已提交视图发现；事务未提交时二者不可见。没有事务内Worker调用或Broker网络发布，也不修改现有Worker的授权、Bundle兼容、Lease和Coverage门禁。
5. 所有业务写入与密封原响应共同提交，提交前在同原claim门禁重查STOP。STOP先胜则共同回滚；提交先胜则只报告committed。停止不是撤回已提交Task/RUN，也不是“Worker已停止”。
6. 具备独立业务处置权限的操作者显式请求原终止意图，持久化后一次POST；pending/unknown后只GET，跨副本/重启使用同原记录。证明不清pending、不自动重发、不重新领取Controller。

## 公开合同与兼容

原入口header `X-Zebra-Admission-Protocol: atomic-task-run/1`；kind=task_create、task为空、run为已授权精确ID、payload.execute=true。协议和run进入规范hash及不可变claim。不能改旧原请求的协议/execute/run后重发。
`POST|GET /v1/admission-operations/{operation}/task-run-termination` 返回固定九字段、contract_version=4；operation/request_hash/kind/state/recorded_at/non_commit_proven/retry_allowed=false/controller_reclaim_allowed=false。
状态、时间和布尔规则复用原子合同，但版本不能降级。旧v1/v2/v3端点不为新协议签发证明；新端点对旧claim为unsupported。原完成收据保持原始密封字节，GET不重建或重排RUN。
原响应201/status=queued/executed=false与持久command，另含精确run_id；Task current_sequence包含命令，active_segment_sequence保留bootstrap revision。accepted/queued均不代表Worker执行/取消成功。
Coverage的既有首RUN默认payload/严格能力检查与证明机制保持原行为；新可选run参数仅由新非Coverage准入使用，不把普通RUN冒充Coverage认证。

## DDD、并发与验收边界

Native拥有Task命令、Worker派发、提交及证明；Go/BFF只拥有原操作意图、密文、CAS及人工处置授权，调用公开HTTPS，不访问Native表。不新增队列、协调器、依赖或schema迁移。
复用按原操作行锁、READ COMMITTED提交门禁、2秒PG请求预算与NOWAIT终止探测。保留原生命令容量/顺序门禁；启用rollout时的namespace容量锁是既有吞吐限制，不作为高并发/HA证明。无网络/模型/人工等待持SQL锁；无强杀线程或租约超时推断。
验收分别覆盖真实PG命令/outbox可见性和回滚、提交先胜、版本/Run/授权拒绝、Coverage默认格式；以及固定发布源SDK/OIDC/签名cloud/同次Worker与真实RUN SQL暂停后的双BFF/双浏览器恢复。
生产IdP/账号、生产HA/QPS、已提交Worker的安全停止、任意外部效果非提交证明与历史部分提交补偿仍开放。保留mock/历史/原收据/Coverage；不部署、不执行生产迁移、不合并main或发布npm。

公开联合中SDK/Worker正向沿用Q既有流程；新U单独验证真实Task/RUN未提交窗口和回滚证明，提交后发现由真实PG验证。新U已提交至Worker的完整正向交付仍按后续独立任务验收，不将同场旧流程成功替代该证明。

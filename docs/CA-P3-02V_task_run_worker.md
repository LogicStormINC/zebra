# CA-P3-02V — Committed Task/RUN to Worker positive joint acceptance
- Status: Review; fresh make test 11072 passed/3050 conditional skips; make check passed; 40 focused real-PG/API cases passed without skips; candidate Chromium/WebKit new protocol canonical RUN to actual Worker terminal answer passed. Final published-source consumer joint is separate. Dependencies: published R6b7e84e/U6e197f0; explicit user-authorized stacked continuation, not merged main.
- Human owner Luke Ding; executor Codex; branch codex/ca-p3-02v-task-run-worker.
- Owned paths: docs/CA-P3-02V_task_run_worker.md; docs/evidence/ca-p3-02v/; docs/{AGENT_TASKS.md,实施任务拆解与阶段验收.md}; PROGRESS.md; WORKLOG.md; task_plan.md.
- Boundary BEFORE code: reuse atomic-task-run/1 without new production protocol/schema. One original encrypted BFF Task+RUN request, lost reply and GET-only recovery across replicas/restart; committed canonical RUN consumed by actual SessionCommandConsumer/Worker, exact Task/Run/command and terminal answer. Queued receipt is admission only; terminal execution facts separately observed; post-commit termination only committed/non_commit=false, never cancellation or external-effect absence. Keep prior precommit rollback scenario. No unknown resend/new UUID/Controller reclaim; credentials stay BFF.
- DDD: business BFF owns intent/current identity/CAS/receipt recovery; Native owns command consumption/leases/events/results. Owned controlled model may answer prompt-only for this new Task; existing SDK Readable/UI approval flow remains independently checked, not substituted for new protocol Worker proof. No direct execute call, fake receipt or event insertion. No production changes unless a traced defect requires a separately expanded claim.
- Acceptance: full gates both repositories, published-source frozen joint in Chromium/WebKit, exact original receipt preserved after Worker and postcommit termination. Preserve mock/history/original receipts/Coverage; no deployment/production migration/main merge/npm/HA claim.


## 依赖、领域边界及证明范围

上一片R/U发布了`atomic-task-run/1`，仅完成提交可见性和提交前终止。原SDK同次Readable/审批/UI Effect/Worker属于旧分步Task/RUN，不作为新协议正向证据。本片不更改生产合同、Worker或数据库schema，使用真实公开准入、已安装的SessionCommandConsumer/SessionExecutionService及共享PG收据。
依赖已推送但尚未合并main；按用户本次要求堆叠继续，未擅自合并。管理前端仍mock；业务凭据只在Go BFF保存。Native执行事实与业务恢复意图分别拥有，不跨写数据库。

| 证据 | 能证明 | 不能证明 |
| --- | --- | --- |
| 原UUID/hash的201密封准入收据，status=queued/executed=false | Task、精确签名Run及首条RUN命令原子准入 | Worker已执行或已成功 |
| 实际SessionCommandConsumer消费同segment的run；事件command_id/run_id匹配原收据 | 已提交的同一RUN实际交给Worker | 仅凭消费返回值不能证明业务完成 |
| 同segment completed、唯一answer_committed及真实录制TLS模型响应 | 本次受控prompt-only Task已产生终态结果 | 任意真实产品、外部效果、脚本/Coverage或生产HA |
| 已提交后调用原task-run-termination，v4/state=committed/non_commit=false | 原准入已提交，终止入口不撤回它 | Worker取消、外部效果不存在或安全非提交 |
| 提交前持锁pending，STOP胜后回滚及GET terminated | 原R/U范围内此准入未提交 | 任意其他操作或准备manifest/审计/claim/STOP写入未发生 |

## 交互流程

1. 既有受控OIDC登录/平台注册/签名云/SDK业务UI流程按原有方式完成。随后显式创建一个新测试slot、原UUID、Thread/Run；同原Tab/Document复用当前注册授权，不替换unknown，不领取Controller。
2. 暂停测试Worker消费。Go BFF共享存储先提交原unknown，再以精确签名Run发送一次新协议Task execute=true；Native正常提交，但测试传输故意丢失响应。
3. 第二BFF发现同原pending，新UUID写入被拒。在BFF仍unknown但Native已提交时，独立处置权限只发一次终止POST，v4返回committed/non_commit=false；不撤回已提交RUN。BFF已完成的原操作不允许新建终止意图（409），已存在意图仍可读。随后重启第一BFF，两副本只GET原操作，恢复完全一致原收据。queued收据的executed仍为false。恢复不是第二次POST。
4. Native公开Task header返回segment；测试观察器只记录这些ID用于读取执行事实，不创建/修改执行事件，不直接调用execute_session。
5. 核对原终止证明及准入收据彼此独立。此时Worker尚未消费，committed尤其不能当作“Worker已停止”。
6. 释放消费暂停，真实SessionCommandConsumer通过正常已提交事件扫描消费；严格cloud Worker、当前签名快照、lease及默认执行门禁保持。独立受控模型只对此新Task的特殊提示返回ATOMIC_RUN_COMPLETE，不调用UI工具。断言原command_id/run_id、唯一命令、唯一答案和真实模型请求。
7. Worker完成后再次重启BFF，GET原准入收据逐字段不变、GET原终止证明不变；事件ID和模型次数不增加。原已有Controller/fence未改变。当前业务拒绝时收据读也拒绝。
8. 保留R/U提交前pending/rollback非提交分支，以及独立SDK业务Readable/审批/UI Effect/Worker流程；两者与新协议prompt-only执行分别报告，不混为新协议UI端到端验收。

## 并发、恢复及兼容

不新增持锁网络调用、队列、协调器或依赖。测试暂停仅控制消费循环，不持SQL锁等待模型。共享PG/CAS、持久原操作、授权前后检查、HTTP预算及既有namespace容量限制保持；单宿主临时验收不证明生产QPS/HA。未知不自动重发、不换UUID、不清pending、不重新领取Controller；准入收据在执行后仍是原准入事实。
不改旧pin、协议、迁移、执行代码、历史数据、原收据和Coverage证明机制。新验收pin独立固定发布源码与实际import/二进制，旧验收证据保持历史版本。
未覆盖：新协议首次RUN与SDK UI Readable在消费前的业务协调、真实厂商/产品账号、生产故障转移、已运行Worker安全取消及外部副作用非提交；这些须独立任务，不由本片结果推断。

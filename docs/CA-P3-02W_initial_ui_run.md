# CA-P3-02W — Initial SDK Readable/Surface and Task/RUN atomic admission
- Status: Review; make test 11075 passed/3052 conditional skips; make check passed;45 focused real-PG/API cases (no skips); SDK full check and 153 tests passed. Candidate Chromium/WebKit same NEW initial UI/Readable/RUN -> Worker/approval/DOM/receipt/terminal and v5 rollback passed; old SDK/UI/U compatibility candidate passed. Published-source consumer acceptance recorded separately. Dependencies: published S65ce92c/V1dba5fd6 and U atomic Task/RUN; user-authorized stacked continuation, not merged main.
- Human owner Luke Ding; executor Codex; branch codex/ca-p3-02w-initial-ui-run.
- Owned paths: apps/api/src/zebra_agent_api/{client_admission*.py,session_queue.py}; sdks/typescript/packages/client-core/src/; sdks/typescript/packages/client-core/tests/; tests/{api/test_client_admission*,agent_storage/test_admission*}; docs/CA-P3-02W_initial_ui_run.md; docs/evidence/ca-p3-02w/; docs/{AGENT_TASKS.md,实施任务拆解与阶段验收.md}; PROGRESS.md; WORKLOG.md; task_plan.md.
- Boundary BEFORE code: new opt-in atomic-task-run-surface/1. SDK prepares handlers/names and bounded Readable values before Task submit. Native uses same PG transaction for Task/bootstrap/binding, current published Profile/Surface/Controller, redacted initial Client State in sole first RUN, wakeup and sealed original result; no Worker/model/network under lock. Worker only sees committed ready input, no new Worker wait/timeout/retry mechanism. SDK adopts original public metadata without mount/reclaim; credentials stay encrypted in BFF original journal. Old protocols/receipts unchanged.
- DDD: Native owns execution snapshots/atomicity/current authorization/Controller; BFF owns exact original intention and CAS/recovery; SDK owns browser handlers and input capture. Unknown only original GET across replicas/restart; never resend/new UUID/reclaim. Abort rolls back Task/Surface/RUN with original result; committed never means Worker cancelled/noncommit. Exclude preparation manifest/audit/claim/STOP; reject attachments/MCP/workspace allocation/Coverage execution.
- Acceptance: Native guard/rollback and real PG, SDK local adoption validation; fixed published-source OIDC/platform/BFF/SDK same NEW TaskRun actual Readable -> Worker -> approval -> business UI -> receipt -> terminal; no test Worker hold as readiness substitute. Both make test/check, docs/evidence and scoped push. Preserve mock/history/old receipts/Coverage; no deploy/production migration/main merge/npm/HA claim.


## 依赖、选择与DDD边界

S/V只验证新Task/RUN的prompt-only执行，业务UI仍用旧分步准入。提交后再挂载Surface或再发一次同Run的RUN会产生消费竞态及重复锚点，不能靠BFF局部锁、浏览器速度或测试hold-worker解决。
本片选择新显式协议`atomic-task-run-surface/1`：复用现有原子提交门禁，将初始Task、Surface/Controller、Native校验和脱敏后的Readable状态、唯一首条RUN及密封原收据共同提交。Worker和SDK客户端均复用已发布Client State v1/Profile/审批/Effect合同，不增加执行循环中的控制面依赖或Worker等待轮询。普通U协议、旧unknown及旧原收据不升级。
Native拥有执行事实、Profile权限、快照、Controller与提交证明；Go BFF拥有当前业务认证、平台注册门禁、原意图/CAS/密文和恢复；SDK拥有浏览器处理器、Readable捕获和公开绑定接管。Go不访问Native库，不将内部领域模型/凭据下发浏览器。
依赖S/V已推送但未合并main，本次按用户授权堆叠继续；不执行主线整合。

## 新公开请求及交互

原准入入口保持`POST /v1/admission-operations/{operation}`，header选择新协议。kind=task_create、task空、run为当前HostGrant签名的唯一精确Run。payload严格为三个对象：

```json
{"task":{"prompt":"业务问题","workspace":"/workspace","execute":true},"surface":{"grant":{},"mount":{},"task_capability_scope":["app.ui.item.open"],"controller":true},"input":{"state":{"app.ui.route":{"route":"/business/items/item-42"}}}}
```

surface.grant/mount复用既有公开Client Surface类型，包含业务身份、Origin、已发布Profile和挂载名；示例空grant/mount不是合法完整授权。仅BFF可填写服务器凭据与信任字段。task仍拒绝附件、MCP、workspace_source及Coverage执行。input仅接受state，禁用任意forwardedProps/线程/Run/凭据/模型工具覆盖；Readable值及原操作规范JSON保留整数/安全JSON/64KiB总体边界。

1. SDK在Task派发前将实际UI处理器注册到MountedActionRegistry，再调用`prepareInitialClientSurface(registry, readables)`。返回捕获时刻的JSON副本与挂载名，处理器函数留在浏览器；非法能力名/重复/过大/非有限或非安全整数JSON失败。值捕获后修改不改变原快照。
2. 业务同源BFF校验当前登录、平台注册、Origin/Tab/Document；共享业务PG先CAS持久化unknown，冻结完整task/surface/input/精确Run/协议/原UUID和恢复密钥，再发一次HTTPS。grant来自BFF当前身份，不能相信浏览器替代身份。
3. Native在事务外准备Definition/manifest；同事务创建Task/事件/绑定，再按当前Profile创建Surface/Controller并挂载/绑定。服务器从新Surface元数据构造forwardedProps，复用AG-UI现有准入校验和脱敏，不接受调用方注入client元数据。
4. Native将经过校验的`client.state_snapshot`、client_session_id、Profile/UI/snapshot/binding摘要写入唯一首条RUN，普通事件追加使命令发现/outbox（启用时）与原收据同事务提交。任何Surface/Readable/容量/授权/收据错误共同回滚，不先发布唤醒或直接执行Worker。
5. Worker只能从已提交视图发现该命令。实际SessionCommandConsumer/SessionExecutionService按既有严格cloud/Lease/Client v1/审批门禁执行，首个模型上下文已含脱敏Readable和有效UI工具。Worker无需等待浏览器另一次RUN或控制面就绪开关。
6. 原201包含Task/精确Run/command及surface（含Native session credential/fence），仅经密封收据给可信BFF并存入共享加密journal。BFF向浏览器只投影既有PublicClientSurfaceMetadata和配置；不能把原响应或原请求直接透传给页面。queued/executed=false是准入事实，不是执行成功。
7. SDK本地注册相同处理器/Readable后`adoptInitialSurface(publicMetadata, originalMountOptions)`，校验Profile/Run绑定/动作摘要/UI修订及本地名称；只允许首次、未停止、无unknown的实例接管。调用不发送mount、不重领Controller、不轮换fence。随后start只接入现有心跳/效果通道。不要再次submitReadableCommand(run)启动这个已有RUN。
8. 请求结果未知时，第二BFF发现同原操作，新UUID不能越过pending；重启后只GET同原密封收据，恢复同Task/Run/Surface/fence并本地接管。原收据可能仍queued，而Worker已进入等待审批；原收据的sequence不是最新命令CAS版本，后续独立命令须另查当前前提，不能改写原收据。
9. 同Run批准实际UI操作；原审批响应丢失后两BFF/重启只GET原审批，Effect持久收据使真实Worker恢复至终态。当前业务拒绝、错误Origin/fence仍失败；未知不自动重发/重领。

捕获表达的是该原命令的输入时刻，不保证浏览器永远存活或UI不变化。UI挂载/修订变化需既有显式mount/新修订流程；旧unknown未对账前不得用新输入覆盖。任意页面崩溃后的UI执行仍遵守既有Effect unknown/receipt规则，不能宣称跨系统万能exactly-once。

## 事务、权限读取和高可用边界

新路径沿用同DSN/namespace/线程的短work unit、原claim提交门禁、2秒预算和NOWAIT终止观察；不持锁等待HTTP/模型/人工。原子Surface要求精确Native PG适配器；Definition/manifest准备、审计、原claim/FENCE/STOP及业务BFF意图排除在非提交证明外。
实际联合发现Task授权和Task/Session查询原来通过独立task-I/O连接，看不到新未提交Task。只让明确的Task/Session身份查询选择`join_work_unit`或现有精确借用；普通readonly header/proof快照保持独立连接与原隔离级别。不能将所有读取隐式加入写事务：既有审批回归证明它会破坏readonly快照配置。真实PG检查同事务可见、其他线程/namespace不可见，默认独立读取仍不可见。
跨BFF原意图、映射、凭据和收据使用已有共享PG/CAS；浏览器和单宿主测试gateway缓存不是持久权威。沿用现有namespace命令容量锁与吞吐上限，不据此宣称QPS/HA已验证。没有新依赖或schema迁移。

## 证明矩阵与兼容

| 观察 | 可报告 | 不可推断 |
| --- | --- | --- |
| 密封原201，queued/executed=false | Task/Surface/脱敏首RUN同次原子准入 | Worker已完成或UI已执行 |
| 同原command/run的Worker输入、审批、唯一UI效果、持久收据及answer_committed | 本次受控业务UI端到端执行 | 任意真实厂商/产品、生产HA或外部副作用均可回滚 |
| 未声明Readable在Surface后被拒，原事务退出，显式STOP及GET v5 terminated | 此新原操作的Task/Surface/首RUN/原收据未提交 | 准备manifest/审计/STOP等均未发生或可以重发 |
| 持锁pending | 无非提交证明 | 不可按超时推断回滚 |
| 原收据已提交，v5 committed/non_commit=false | 此准入已提交 | Worker已取消、UI未发生或任意外部效果不存在 |

新增`POST|GET /v1/admission-operations/{operation}/task-surface-termination`，固定九字段contract_version=5。旧v1–v4不为新协议签发证明，新v5不升级旧claim。终止意图仍须独立处置权限，仅unknown原请求可新建，一次POST后GET；证明不清pending、不授予重发/重领。
旧U Task/RUN、普通Surface、历史记录/收据/Coverage与旧pin保持。SDK只新增准备/本地接管API；原mount/ReadableCommand行为不改。index原已到500行，将既有公开依赖类型移到独立类型文件并从原入口重导出；不是接口改名。Worker未改，支持矩阵为已验收Client State v1/Profile的固定版本；未知或更早Worker混部能力不由本片证明。
未验证生产账号/IdP厂商、生产存储故障切换/QPS、任意外部效果安全取消/非提交，以及多轮新Run产品流程。前端mock保持，无部署、生产迁移、main合并或npm发布。

## SDK接入示例（业务BFF路由由产品实现）

```javascript
import {MountedActionRegistry,prepareInitialClientSurface,ZebraClientRuntime} from '@zebra-agent/client-core';
const handlers = new MountedActionRegistry();
handlers.mount('app.ui.item.open', args => businessUI.openItem(args.itemId));
const prepared = prepareInitialClientSurface(handlers, {'app.ui.route': {route: location.pathname}});
// 产品BFF固定原操作/CAS并执行上述原子准入；未知时不重调create，只查原收据。
const boot = await businessBFF.createInitialTask(prepared);
const runtime = ZebraClientRuntime.fromConfig(boot.config); // BFF模式，无Native秘密
for (const name of prepared.mountedActions) runtime.registry.mount(name, args => handlers.dispatch(name,args));
for (const name of prepared.mountedReadables) runtime.mountReadable(name,prepared.input.state[name]);
runtime.adoptInitialSurface(boot.publicSurface, {
 frontendAppId: boot.profile.appId,profileRevision: boot.profile.revision,
 profileDigest: boot.profile.digest,mountedActions: prepared.mountedActions,mountedReadables: prepared.mountedReadables,
});
await runtime.start(); // 不再mount，也不再发送首条run
```

businessUI/businessBFF与boot外层字段为产品示例，不是新增平台HTTP入口；runtime config及publicSurface复用公开SDK类型。业务BFF只投影公开字段，Native surface凭据留在共享加密存储。业务UI实际变化须遵守修订/重挂载及Effect原收据协议，不把后来的DOM状态冒充已经提交的初始快照。

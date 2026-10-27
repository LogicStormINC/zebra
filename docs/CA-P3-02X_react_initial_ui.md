# CA-P3-02X — Explicit React initial Surface consumer
- Status: Review; fresh make test 11075 passed/3052 conditional skips; make check passed; SDK check and156 tests passed, focused React4 passed. Candidate packed React Chromium/WebKit same initial TaskRun/Readable/Worker/approval/DOM/receipt/terminal and real owner unmount passed. Python/Worker/storage/core SDK unchanged; published-source consumer result recorded separately. Dependencies audited: published T01e23b2/W5947d3a1; user-authorized stacked continuation, not merged main.
- Human owner Luke Ding; executor Codex; branch codex/ca-p3-02x-react-initial-ui.
- Owned paths: sdks/typescript/packages/react/{src/,tests/,README.md}; docs/CA-P3-02X_react_initial_ui.md; docs/evidence/ca-p3-02x/; docs/{AGENT_TASKS.md,实施任务拆解与阶段验收.md}; PROGRESS.md; WORKLOG.md; task_plan.md.
- Boundary BEFORE code: React preparation Hooks register actual typed handlers/Readable values in a committed UI before explicit capture. Reuse core prepare/adopt and native atomic-task-run-surface/1 v5; no Python/Go production protocol, storage or Worker change. Capture once; unknown uses original BFF GET, never another capture/automatic bootstrap/remount/Controller reclaim. StrictMode transient cleanup cannot dispatch or stop a later live instance. Registration/value drift after capture fails closed; explicit UI revision and multi-Run belong later tasks.
- DDD: React owns ephemeral page registration/lifecycle; BFF retains current identity/CAS/encrypted original and credentials; Native owns authorization/immutable Task/Surface/RUN/receipts/Worker. No dummy Runtime/identity or remote call before user action. Old Provider/Hooks keep legacy behavior; new initial Hooks are explicit opt-in.
- Acceptance: StrictMode setup-cleanup, duplicate registration, immutable state, capture-once, schema validation, stale/late response and real unmount; actual packed React Chromium/WebKit SDK/OIDC/BFF same initial TaskRun -> Worker approval/UI/receipt/terminal and original GET-only recovery; same-source old core consumer regression. Both make test/check, SDK full check/test, docs/evidence then scoped push. Preserve mock/history/original receipts/Coverage; no deploy/production migration/main merge/npm/production HA claim.


## 决策与DDD边界

T/W已提供原子初始UI/Readable/RUN及core prepare/adopt，原React Provider自动scheduleMount不适用于首条原子RUN。本片新增显式初始Hook，不静默切换旧Provider，不构造虚假Runtime/Task/身份，也不增加Python协议、Worker逻辑、数据库或Go业务模块。
React只拥有单次已提交页面的临时注册和生命周期；BFF继续拥有认证、原意图/CAS、加密凭据与恢复；Native仍拥有Profile授权、不可变事件/收据及Worker。复用W `atomic-task-run-surface/1`、v5终止与Client State v1，schema113不变。依赖T/W已发布未合并main，本轮用户授权堆叠继续，不擅自整合main。

## SDK接口与交互

- `useZebraInitialSurface()`：产生该页面实例的稳定准备对象；无HTTP、自动bootstrap、Token保存或定时重试。
- `useZebraInitialAction(surface,name,{parameters,result,handler})`：提交阶段注册实际处理器，重复名失败。Zod校验参数/返回值。schema应保持引用稳定；handler使用最近已提交React闭包，未提交render不能替换执行函数。
- `useZebraInitialReadable(surface,name,value)`：复用core安全JSON/整数/名称/大小校验，提交阶段登记和复制值。重复名失败，render不创建服务端事实。
- `surface.capture()`：仅已提交、仍挂载且未捕获的页面可调用一次；返回JSON副本。StrictMode预演、SSR、未提交render没有派发权。必须由明确用户操作/应用命令触发，不能放入自动Effect中启动任务。
- `surface.adopt(runtime,publicMetadata,profile)`：使用原快照及处理器复用core adopt；无mount/fence轮换。BFF只下发公开元数据，凭据留BFF。调用方随后显式start，认证生命周期复用createAuthenticatedRuntime。

```tsx
const surface = useZebraInitialSurface();
useZebraInitialReadable(surface, 'app.ui.route', {route});
useZebraInitialAction(surface, 'app.ui.item.open', {
 parameters: stableParameters, result: stableResult, handler: openBusinessItem,
});
// 用户明确开始；认证先完成，prepared只捕获一次并保留为原请求。
const prepared = surface.capture();
const boot = await businessBFF.createInitialTask(prepared);
const runtime = ZebraClientRuntime.fromConfig(boot.config);
surface.adopt(runtime,boot.publicSurface,boot.profile);
await runtime.start();
```

businessBFF/boot外层为产品组合示例，不是新增平台HTTP入口。boot.profile使用frontendAppId/profileRevision/profileDigest。真实浏览器验收通过既有同源认证门面、平台注册、签名Broker和BFF原请求journal，未用Hook作为认证或权限判断。

首个请求响应丢失时，React保留同一已捕获页面，BFF先跨副本/重启GET原收据。明确确认原操作后接管同一Task/Run/Surface/fence，不再capture、不再Native POST。临时Node缓存清空不重建Native事实。清除页面状态、换Document或跨React根转移同一Controller，不在本片自动恢复范围。

## 生命周期与失败边界

StrictMode模拟setup/cleanup不做网络动作，owner清理通过代际微任务确认实际卸载。注册/值在layout提交阶段生效，未提交render不能宣称UI已就绪。捕获后Readable/名称/schema生命周期变化使准备对象永久失效；已接管runtime停止，不能自动mount或将新值写入首条原命令。显式修订、多轮新Run和页面转移后续独立实现。
未接管的迟到、重复或不匹配实例只disconnect本地工作，不能stop导致误释放当前Controller。对同一个已接管实例的重复adopt只拒绝，不断开当前owner。已知接管owner真实卸载/漂移才停止它的runtime；这仍不证明Native已取消或任意外部效果未发生。原始捕获失败后不得生成新UUID掩盖unknown；新Hook实例也不能越过BFF持久pending。
处理器代码不序列化；Native Profile/参数/效果/receipt仍是服务端权威。回调自身应校验当前业务对象及合法性。输入快照只表示capture时刻，不保证页面永远存活。无网络/模型等待持数据库锁；没有新增共享状态、队列或生产吞吐/HA承诺。

## 验收与兼容

打包实际React/ReactDOM/client-core在Chromium和WebKit运行StrictMode，真实Hook注册业务记录和值；同新TaskRun的Readonly值进入Worker，人工批准后React状态提交DOM效果，持久receipt恢复Worker终态。原准入丢响应、双BFF/重启只GET、SDK接管不发mount/重复RUN；真实React根卸载使已知运行实例停止。
同时固定同一发布Native源码与二进制运行旧core SDK/分步UI/U正向和回滚，保留既有Provider/Hook行为。对新Hook执行StrictMode、capture-once、数据副本、重复注册、变化失效、迟到实例不释放活跃Controller的定向测试和SDK完整check/test。两仓库完整make test/check后更新证据、提交推送。
证据区分准备/准入收据、执行终态和v5终止观察；queued不是执行成功，committed不是取消。未知不自动重发或重领。保留mock、历史数据、原收据、Coverage和旧pin；无部署、生产迁移、main合并、npm发布。真实产品/厂商、生产HA、多轮/显式修订及外部副作用安全取消不由本片证明。

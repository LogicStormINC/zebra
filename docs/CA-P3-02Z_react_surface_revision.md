# CA-P3-02Z — Explicit React same-Run Surface revision adoption
- Status: Review; fresh make test 11075 passed/3052 conditional skips and make check passed after filesystem recovery; SDK check/158 tests and6 focused React cases passed. Candidate Chromium/WebKit actual new React owner capture -> BFF original GET/current mapping -> zero-HTTP adoption -> current heartbeat/unmount passed. Runtime/Worker/core SDK/schema unchanged; final published-source consumer separate. No second Worker/new Run claim. dependencies audited 2026-10-26: published V6c544bb0/Y38c4711b; user-authorized stacked continuation, not main integration.
- Human owner Luke Ding; executor Codex; branch codex/ca-p3-02z-react-surface-revision.
- Owned paths: sdks/typescript/packages/react/{src/,tests/,README.md}; docs/CA-P3-02Z_react_surface_revision.md; docs/evidence/ca-p3-02z/; docs/{AGENT_TASKS.md,实施任务拆解与阶段验收.md}; PROGRESS.md; WORKLOG.md; task_plan.md.
- Boundary BEFORE code: new explicit React owner after old owner unmount; reuse initial committed capture/typed registry/lifecycle. New useZebraSurfaceRevision pins immutable prior public config/metadata and exposes its preparation surface plus explicit adoption from public config, constructing only the real new runtime. Require same BFF base/Task/Run/Client/binding/Profile, next UI revision, greater binding revision/new digest and no action authority expansion. BFF exact original mount/GET-only recovery/current mapping precedes adoption; SDK adoption makes no mount/Controller request. Late/unmounted/changed page fails closed. No automatic resurrection, multi-Run, old Provider upgrade, Python/core SDK/Worker/schema/Go production change or new dependency.
- DDD: React owns ephemeral committed UI and real runtime lifetime; BFF owns encrypted originals/auth/CAS/current mapping; Native owns Profile/Surface/Controller, original results and Worker. Credentials stay BFF. Unknown never automatic resend/new UUID/reclaim; new explicit authorized revision may rotate fence once, recovery never does.
- Acceptance: StrictMode/capture-once/immutable prior and next-target checks, duplicate/late/stale/drift/unmount regressions, SDK check/full tests. Packed actual React Chromium/WebKit first Worker/UI terminal -> new committed revision page and new Readable capture -> one BFF mount/lost reply/two-replica restart original GET/current mapping CAS -> real SDK local adoption/current poll/owner unmount; same-source old core flow. Both make test/check, docs/evidence/scoped push. Preserve mock/history/original receipts/Coverage; no deploy/production migration/main merge/npm/production HA claim. New revision input is captured locally; no second Worker/new Run execution claim.

## 依赖和决策

V/Y已验证atomic-task-run-surface/1原始首轮至atomic-surface/1显式同Run修订的持久祖先、丢响应只GET与当前映射CAS；仍缺真实React新页面接管。旧InitialSurface在捕获后变化会永久失效并停止owner，旧Provider会自动scheduleMount，因此不能直接自动恢复它们。本片新增显式新owner的useZebraSurfaceRevision，复用初始Hook注册、不可变capture与本地adopt；旧行为不变，不新增通用状态机/自动重试/认证管理器或Native协议。

DDD：React只拥有已提交页面的注册、值和真实runtime生命周期；业务BFF拥有当前业务身份、加密原操作、CAS和当前映射；Native拥有Profile/绑定/fence/不可变收据及Worker。公开标识只是观察，不授予权限。浏览器没有bearer/refresh/HostGrant/session credential/fence，所有请求仍经同源BFF重新检查身份和Native当前权威。

## SDK与交互

```tsx
const revision = useZebraSurfaceRevision({
 config: previousPublicConfig, publicMetadata: previousMetadata, profile,
});
useZebraInitialReadable(revision.surface, 'app.ui.route', {route});
useZebraInitialAction(revision.surface, 'app.ui.item.open', {
 parameters: stableParameters, result: stableResult, handler: openCurrentItem,
});
// 旧owner已停止；新页面提交后，由明确业务命令执行一次。
const prepared = revision.surface.capture();
// BFF记录一次显式修订，unknown时只GET同原请求，不再capture/POST。
const receipt = await productBFF.explicitRevision(prepared);
// BFF确认原201并通过当前Native权威观察安装/解析映射；仅回公开数据。
const runtime = revision.adopt(receipt.publicConfig, receipt.publicMetadata, profile);
await runtime.start();
```

productBFF/receipt外层是产品组合示例，不是新管理HTTP接口。调用方负责在修订前停止/卸载旧owner，且仅在当前业务登录仍有效时挂载新页面；退出业务登录要卸载新owner。Hook不证明旧Worker已取消，不能把旧请求unknown当作创建新owner或新操作的理由。

本片限定BFF Controller、Surface Metadata v1、Client State v1；已启用commandRecovery v1的原标记继续保留。新Hook的surface直接复用已有initial Hooks；StrictMode提交前没有网络或派发权，capture只一次。基线只复制公开坐标、Profile和metadata，不保留调用方可变对象、fetch或Storage。基线变化要求新的明确owner，不能原地改旧基线。接管固定相同BFF相对路径、Task/Run/Client/binding、Profile ID/修订/digest与协议版本；UI修订必须恰好+1，binding_revision递增且digest变化，动作授权不得超出原集合/合同digest。新实际runtime由公开config构造，复用core校验和原命令pending标记检查，再adopt；此调用没有HTTP、mount、Controller领取或自动start。

新业务Readable值在capture时复制，返回副本修改不污染runtime输入。捕获之后值、名称、schema生命周期漂移仍失败关闭，不能改写在途原请求。处理器使用最近已提交React闭包和Zod校验，未提交render不能替换回调。重复adopt创建的未拥有实例只本地disconnect，不释放活跃实例；迟到到已卸载owner的结果也只拒绝/本地断开。真实owner卸载/漂移才停止已接管runtime并按既有机制释放。释放不证明外部效果未发生或Worker已停止。

## 公开验收和兼容

先完成真实React首轮Readable/Worker/人工审批/DOM/持久receipt/终态并卸载旧owner；新StrictMode页面显示新route，Hook capture与DOM一致。可信BFF一次显式mount后丢响应，原请求在双BFF重启后只GET恢复，当前映射CAS完成；将严格投影的公开metadata/config交给新Hook。本地adopt及重复adopt无HTTP，真实start轮询和heartbeat证明当前映射可用；真实卸载发一次release。初始Task/RUN与修订原收据摘要保持，不用新UUID/重发/重领掩盖unknown。

测试gateway单宿主Node缓存只是已确认原收据与当前Go/Native映射的临时投影，不是持久权威；每个SDK请求仍走现有共享PG映射和当前身份校验。源码/实际Python导入/SDK包/Go源/二进制冻结，Chromium与WebKit运行新流程，并在同发布源运行旧core完整兼容流程。SDK确定性回归覆盖精确目标/Profile/修订/授权拒绝、capture副本/一次性、迟到/重复、漂移、unmount和pending原命令标记保留。

本片证明新UI修订接管与当前心跳，不证明新值已进入第二个Worker或多轮新Run已执行；新Readable命令编码由SDK回归单独验证。多轮Run/旧Provider组合/跨Document或跨设备UI转移、已提交Worker与外部效果安全取消、生产HA/QPS/真实厂商账号继续独立验收。无Python Runtime/core SDK/Worker/schema/Go生产改动或新依赖；保留前端mock、历史数据、原收据、Coverage和旧pin，无部署/生产迁移/main合并/npm发布。

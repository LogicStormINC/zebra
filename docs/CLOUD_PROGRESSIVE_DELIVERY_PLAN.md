# Cloud progressive delivery implementation plan

> For agentic workers: execute with subagent-driven-development using disjoint
> owned paths, spec review followed by quality review. Keep all unchecked items
> open; focused tests, builds and health checks do not prove live closure.

Goal: implement the user-approved 2026-10-03 thirteen-section progressive delivery
design across Zebra Harness, AG-UI, reusable React packages and Trench, and prove
every requirement with current code and runtime evidence.

Architecture: Zebra's durable event stream owns execution and public output.
The Harness publishes truthful lifecycle/milestone messages when the main model
is silent; optional bounded model expression consumes confirmed public facts.
Trench supplies business facts and projects ordered output without replanning.
Existing SSE, leases, quality gates, model gateway and renderers are reused.

Tech stack: Python 3.12, PostgreSQL, existing Model Gateway and AG-UI, TypeScript,
React, existing Markdown/media/chart packages, Trench FastAPI and Next.js.

## Ownership and activation

- Human owner: Luke Ding. Zebra branch: `cloud-agent-trench`; Trench: `main`,
  both explicitly selected by the user. Preserve their existing dirty changes.
- Main implementation: Zebra core, integrations, Worker composition, progress
  configuration, tests, governance and acceptance runners.
- Delegated SDK implementation: `sdks/typescript/packages/{ui-contracts,react}`.
- Host implementation after SDK contract: Trench API/Turn and frontend adapters,
  source/history tool facts, package lock/vendor integration and focused tests.
- No service restart: user operates existing process/container restarts.
  Builds and runnable activation instructions are part of this task.
- Registry publication, push and deployment are independent explicit actions;
  packed local SDK delivery is required for this acceptance boundary.

## Fixed public output contract

New durable event `public_output` projects as `CUSTOM zebra.public_output`.
Payload: `schema_version=1`, `attempt_number`, `output_id`, `kind` (status,
commentary, result), `phase`, `origin` (system, model), `content` (bounded),
`status` (complete), optional `model_call_id`, `evidence_refs`, `media_refs`,
`replaces_output_id`. It contains public facts, never private reasoning or raw
tool arguments. Each output uses the event sequence for ordering and stable ID
for replay. Final authority remains existing `ANSWER_COMMITTED` and terminal
events. Existing model deltas keep their message ID and provisional status.

Trench projects the new event as `public_output` and persists ordered items in
Turn metadata, preserving legacy `public_updates` and final `answer`. Tool and
model output items use their stable activity/message identity. SDK adds optional
ordered `items` to `AgentConversationTurn`, falling back to legacy work/message
fields when absent. A Turn's final commit confirms the selected message rather
than appending duplicate content/media.

## Chunk 1: Harness and public event contract

Files: `packages/agent-core/src/agent_core/{domain/events.py,contracts/events.py,
contracts/public_output.py,harness/public_output.py,harness/model_step.py,
harness/sequential_loop.py,harness/tool_execution.py,harness/final_completion.py}`;
`apps/worker/src/zebra_agent_worker/execution_context.py`; focused tests.

- [ ] Add a validated bounded public-output payload and backward-compatible
  projection; reject invalid IDs, oversized output and undeclared fields.
- [ ] Publish fact-based first-tool/milestone/failure/verification messages even
  when model tool loops contain only `Tool calls proposed.`. Simple direct
  answers have no redundant preamble; batch milestones do not narrate each call.
- [ ] Preserve execution and publication authority, cancellation, attempts and
  side-effect uncertainty; no implicit command/tool retries or approvals bypass.
- [ ] Add bounded optional expression with tools disabled, compact public input,
  explicit timeout/output/call budgets, separate usage evidence and fact fallback.
- [ ] Persist pacing/checkpoint state so recovery cannot duplicate milestones.
- [ ] Add truthful long-wait state driven by actual lifecycle and configurable
  deadlines, distinguishing business progress, transport heartbeat and receipt.
- [ ] Run relevant core/Worker/event tests and `make check`; review all callers.

## Chunk 2: Ordered reusable conversation UI

Files: `sdks/typescript/packages/ui-contracts/src/index.ts`, React conversation
timeline and associated styles/tests, existing content renderer as necessary.

- [ ] Extend Turn contract with optional ordered items for message, activity and
  status; keep legacy callers and public exports compatible.
- [ ] Render commentary, work, partial results, media and final summary in actual
  order with stable keyed nodes and explicit provisional/revision semantics.
- [ ] Preserve loaded image/chart nodes and video playback on commit/reconnect;
  media failure is isolated. Render validated complete chart specs only.
- [ ] Preserve scroll intent and expose current work compactly; call the tool
  section execution process, not private thinking. Accessible status announcements
  operate on complete messages rather than every token.
- [ ] Run SDK tests/build/package/consumer/browser checks, pack updated artifacts
  and prove Trench consumes those exact packages.

## Chunk 3: Trench host contract and execution efficiency

Files: Trench `services/api/src/trench_api/trench_ai_{zebra_event_map,turn_store,
turn_content,zebra_contract}.py`, relevant source/history tool modules and tests;
frontend strategy message/Turn projection, hook and assistant renderer/tests.

- [ ] Map/deduplicate new output, activities, model text and rich content into
  ordered items with durable snapshot watermarks; preserve old histories.
- [ ] Expose structured public business facts from successful reads; fact output
  never implies complete coverage when only a page/sample was read.
- [ ] Inspect summary intake: counts first, light summaries next, deduplicate
  without dropping conflicting evidence, full text on demand; retain raw data.
- [ ] Reuse bounded parallel safe reads and source/global limits; no blind write
  concurrency or per-token queue jobs.
- [ ] Stream first useful results before final completion; correction links and
  source/media validity preserve quality gates and explicit operational receipts.
- [ ] Recover observation only on reconnect/refresh, never resubmit; preserve
  terminal/attempt/conversation isolation and history beyond snapshot bounds.
- [ ] Run paired API and frontend regressions, types/lint and production build.

## Chunk 4: Timing, resource limits and recovery evidence

- [ ] Replace full Task hydration with true seek pages, at most 256 events plus
  a byte ceiling. Header/binding lookup must not fetch all historical bodies.
- [ ] Restore from versioned scalar checkpoint headers and keyed state cells,
  not a copy of all history. Checkpoints precede the resume anchor; silent events
  still advance source progress. Revisited Segments retain their prior state.
- [ ] Persist immutable Task positions alongside canonical Events. Legal late
  predecessor metadata gets new tail positions; index rebuild cannot renumber.
- [ ] Bounded resumable legacy backfill preserves valid existing positions;
  conflicting or ambiguous mappings fail explicitly. Page frontend history and
  preserve the visible reading anchor and active media/player nodes.
- [ ] First chunk immediate and timer-based flush works during provider silence;
  bounded buffers/backpressure and slow-client isolation are verified.
- [ ] Centralize pacing and budgets, freeze their version per task; preserve user
  selected main reasoning intensity while separate short expression is bounded.
- [ ] Record submit, admission, execution, first meaningful output, first useful
  result, final commit, relay and browser paint with named measurement endpoints;
  do not subtract unsynchronized wall clocks as end-to-end latency.
- [ ] Verify cancellation, rate limits, unknown writes, stale Worker/attempt
  output, duplicate replay, EOF, late ACK and multi-user/slow-client isolation.

## Chunk 5: Real acceptance and completion audit

Baseline: real Turn `96531da3-ee81-452c-b33e-724c954dddb9`: 122.568s total,
88.066s first public text, 29 tools, 10 model calls, zero public updates.

- [ ] Build exact SDK packages, API/Worker images and frontend, record source
  digest/version/config and prepare user-operated activation commands.
- [ ] Confirm running digests before replay; tests/build/health are separate.
- [ ] Repeat simple answer, multi-source summary, model-tool-only, slow tool,
  partial failure, image/video/chart, revision and true forced SSE interruption.
- [ ] Verify refresh/navigation, Worker recovery, cancellation, permission and
  unknown-write boundaries, concurrency and complete terminal cleanup.
- [ ] Capture browser screenshots/events/timing and recovery traces, including
  sample counts; verify video stays inline without object storage download.
- [ ] Targets in healthy representative conditions: feedback <=1s; persisted
  execution/milestone to visible P95 <=1s; relay-to-paint P95 <=500ms; first
  meaningful communication P95 <=8s. Around 20s without useful output requires
  accurate wait/recovery state. Report raw samples when percentiles are weak.
- [ ] Audit each approved requirement against current authoritative evidence;
  publish baseline comparison and explicit remaining gaps. Mark the goal complete
  only after all required code, checks, packaging and activated live gates pass.

## Verification commands

Use `uv run pytest -q` with focused files first, `make check`, `make test` for
cross-package closure. SDK: supported Node 24, `pnpm verify` from
`sdks/typescript`. Trench: `pdm run pytest` for relevant API paths, frontend
existing test script, `pnpm exec tsc --noEmit`, lint and production build, then
the repository's full gate. Exact runtime/fault commands and observed results
will be recorded as each path is implemented; absent inputs must fail clearly.

## Evidence ledger

Latest 2026-10-03 audit supersedes the historical counts in the table: the last
full Zebra run was RED (5482 pass/196 fail/1170 skips) and predates later fixture
and source fixes; no fresh full pass is established. Last `make check` was GREEN
before the scalar header follow-up. SDK full verify was GREEN before subsequent
consumer edits. Real isolated PostgreSQL Task-I/O/auth/HTTP checks passed 42 with
one S3-environment skip; the scope is not object-body cancellation or live Host
acceptance. Latest targeted header matrix passed 14. Current fixture, Host and
fact fixes still require a joint full rerun. Runtime image identity, activation,
all fourteen live cases and healthy timing samples remain unproved. Keep all
checkboxes open until their full acceptance scope is proven.

Implementation has started. All boxes are initially open. Prior transport/media
fixes are reusable groundwork, not proof of this plan's completion.

### 2026-10-03 current evidence

| Boundary | Evidence | Remaining gate |
| --- | --- | --- |
| Core/provider/Worker | Last full suite 5042 passed, 915 skips; latest make check: Ruff, 1016 typed files, 30/30 evals; Effect 46 tests and 41 independent probes approved | Latest full gates, bounded replay and activated runtime |
| Reusable SDK | Spec and quality reviews passed; 24 focused timeline/chart tests; full verify passes package/React 18/19 Vite/Next/Chromium/WebKit checks | Actual activated multi-service media delivery and playback |
| Trench Host | Last full API 794/frontend 254 passed; latest navigation/hook 56 passed; exact five tarball/lock/installed-byte checks and prior build/mock browser pass | Same-key return re-review, latest full gates/build and actual runtime |
| Delivery/runtime | Baseline first public text 88.066s; new frontend and API/Worker build preparation | Running image identity confirmation, user activation, 14 live/fault cases and timing distribution |

Optional model expression currently orders complete verified fact strings using
a closed lead-in vocabulary, rather than inventing paraphrases. This preserves
qualifiers and coverage. Free-form paraphrasing would require an entailment
gate. Long provider/tool execution stays outside the per-recorder mutation
guard; sequence-bound Artifact staging and relational receipt commits stay
inside it. The guard is per task, not a global throughput lock.

## 完整系统方案：十三个不可拆开的验收面

### 1. 输出体验与真相边界

目标不是把最终答案切成若干字符，也不是展示隐藏思维链。用户应连续看到：
请求已受理、当前实际工作、已确认发现、必要的异常说明、核验中的结果和最终交付。
简单问题直接回答；需要工具的任务才出现工作说明。评论必须来自真实执行状态或
已确认回执，不能根据计时器编造“正在搜索”“已经找到”等业务进展。
状态、公开交流、局部结果、最终确认分别建模，不以心跳或“思考中”代替有效反馈。

### 2. 单一执行权威

Zebra 拥有 Task、Run、Attempt、事件顺序、工具权限、执行回执和最终答案提交。
Trench 拥有业务数据、用户隔离、业务查询与前端投影，不另建规划器或旁路 Agent。
所有对外输出先持久化、再推送；取消或旧租约失效后不得继续发布。
新增展示机制不改变原有权限、审批、未知写入结果处理和主模型推理强度。

### 3. 可恢复的公开输出协议

复用 `public_output`、`MODEL_RESPONSE_*`、`ANSWER_COMMITTED` 和 AG-UI。
每个公开片段具有稳定 output/message ID、事件序号、Attempt 和策略版本。
修订使用明确替换关系；最终确认沿用结果身份，不能重复追加已展示媒体。
一个持久事件产生多条 SSE 消息时，每帧必须有独立的可恢复位置：旧事件级游标
仍兼容；新游标增加可选 `frame_index`，并验证其确实属于该事件和当前 Run。

### 4. Harness 主动且真实的交流

主模型产生的自然工作说明优先使用。当模型只给工具调用时，Harness 提供简短
开场、首个有意义发现、批量回执摘要、异常边界和验证状态。
工具摘要来自 Host 返回的结构化公开事实，包含覆盖范围、数量与缺失说明。
计时器只报告当前请求/执行尚未结束，不把等待说成成功，也不把部分样本说成全部。
恢复时按已覆盖回执去重，不依赖之前批次恰好相同。

### 5. 流式正文的真实刷新

首个文本片段立即交付，后续以字符阈值或真实定时器刷新，供应商暂停时也能冲刷
已缓冲正文。缓冲有上限，慢消费者采用惰性编码，不预先编码整个历史。
流式正文与公开交流共用同一持久顺序；provider reasoning 内容不作为正文输出。
断流恢复只继续观察已有 Task，不重新提交任务或重复执行工具。

### 6. 主模型与可选表达辅助

主模型仍承担推理、选工具和答案生成；默认不增加表达辅助调用。
需要时，辅助仅处理已确认公开事实，无工具、无 thinking，单次总期限最多 2 秒、
最多 128 输出 token、每次执行最多 2 次，输入最多 2048 字符。
先持久化可读的事实回退，再尝试辅助。超时、解析失败、预算用尽时保留回退。
辅助计费单独记录，不进入后续对话、记忆、标题或任务决策。
当前实现仅重新组织完整事实和闭集引导语，不声称自由改写具有语义等价保障。
同步注入 client、已有 event loop 或不可取消的线程 DNS 路径关闭辅助，主模型不受影响。

### 7. 信息获取效率

多源摘要采用数量/覆盖范围优先、轻量摘要其次、必要时全文的链路。
合并重复证据，但保留相互冲突的记录，不删除原始业务内容。
沿用安全只读并行及来源级/全局限额；不能为加速而并发未知写操作。
不把每个 token 变为 RabbitMQ 任务。消息队列负责执行调度而非 UI 打字效果。
浏览器、Host Relay 和 Worker 分别测量，避免把查询慢误诊为渲染慢。

### 8. 强制有界历史与检查点恢复

Task位置永久绑定原Event。前序Segment标题/记忆迟到追加保持原Session归属，在Task
尾部分配新位置，不能插到已发布子Segment之前。源Event旁保存不可变位置事实；
task_event_index只是可重建投影。事件事务先取得所有必要Session/stream/lease边界，
再取得Task串行边界；保留现有fence/CAS和幂等身份。索引缺口可修复，冲突必须报错。

API索引seek分页，每页最多256事件并限制字节；不能fetchall再切片，或读取Task时
隐式全量重建。检查点包含版本化标量头和按键状态单元，不复制历史。恢复从游标前
检查点读取有界后缀，重访前序Segment不重复Run start，无公开帧事件也推进读取水位。
老历史有界可继续回填，保留已有有效位置；时间戳不能推断提交顺序。伪造游标、
旧版本、冲突及大事件都有显式策略。前端分页历史并限制挂载，保留阅读及播放节点。
1千/1万/10万事件、多Segment、检查点边界、索引缺口与1/10/50/100观察者是必需验收。

### 9. 可复用前端组件库

`ui-contracts` 提供可选有序 Turn items；`react` 展示状态、交流、工具活动与内容。
Host 只适配业务协议，不复制一套聊天渲染器。老 messages/work 字段继续兼容。
按稳定 key 保留图片、视频、图表节点；部分结果、修订和最终确认不能导致媒体重建。
图表校验、序列化和请求失败仅降级单个图表，正文和其他媒体继续可见。
图片/视频/图表复用已验证渲染器；在线嵌入播放不强制下载到对象存储。
不承诺绕过网站 DRM、登录、跨域或禁止内嵌规则；这些情况明确显示原因与来源入口。

### 10. 用户交互与无障碍

用户看历史时不强制滚动到底部，展示“有新内容”入口；在底部时平滑跟随。
工具区使用“执行过程”，不把公开工具活动标为私有思考过程。
只对完整公开消息做无障碍播报，不逐 token 播报，不播报恢复的旧消息。
切换会话先隔离旧 Turn，再加载新历史；相同文本前缀也不能混淆历史和实时输出。
导航意图同步撤销旧请求权限；提交、队列、反馈、删除、重命名、置顶、报告和错误
回调共用视图身份。A->B->A及A->新会话->A在key未改变时也恢复观察，不重新提任务。
Agent 的时间线建议展示成可点击入口，不自行把用户带离聊天。

### 11. 故障、并发与资源

重连以真实游标与持久快照水位去重；EOF、暂停、确认回执延迟、取消和旧 Attempt
输出均有回归案例。接管恢复不能重复发布批量发现或重新执行未知结果的写操作。
同一 recorder 的准备/提交/接收与定时器追加串行；耗时 provider I/O 在锁外。
公开输出默认 64 条、每条最多 4000 字符，pending receipts 最多 32，文本缓冲
最多 65536 字符。每个执行最多一个等待 timer；终态清理 timer/监听器/请求。
API已切换到有界观察路径；后台持久调度、最新回归和真实运行尚待联合验证，
不能仅凭模块组合或局部测试宣称第8项完成。
次生清理异常不能覆盖原始故障；原始取消保持停止，未知写结果不盲目重试。
Run总预算跨接管保留；终态区分完成、部分完成、失败、取消、等待输入和受阻。

### 12. 指标与用户可感知目标

浏览器同一 `performance.now()` 时间域记录提交、受理、首次公开正文、首次有用
结果、最终确认、relay 接收、React commit 和双 RAF paint-ready。
历史恢复、后台标签页、被合并/覆盖的帧单独标记，不混入健康实时延迟。
paint-ready 是近似绘制机会，不是图像解码、视频播放或物理屏幕完成时间。
样本缓存最多 128 Turns / 256 events；跨页面受理样本最多保留 30 秒。
健康代表性样本目标：受理反馈 <=1 秒；执行里程碑至可见 P95 <=1 秒；
relay 至 paint-ready P95 <=500 毫秒；首次有效交流 P95 <=8 秒。
约20秒无有效进展提供准确等待状态。至少100个健康样本用于P95，故障样本分开；
受理、心跳和泛化“处理中”不冒充有效交流，不用一次快结果冒充P95。

### 13. 联合交付与完成判定

代码、SDK 包、Trench 安装包、前端 BUILD_ID、API/Worker 镜像和生效配置必须一致。
构建与现有进程重启分开：依用户要求，重启由用户操作；运行镜像 ID 比对后再验收。
完整验收包含简单回答、多源、纯工具循环、慢工具、部分失败、图文视频图表、修订、
逐帧真正断流、刷新/导航、Worker 接管、取消、权限/未知写入、并发和终态清理。
使用实际 Host 数据、真实浏览器和故障注入；不能把单元测试、模拟 UI 或 `/health`
返回 200 当作全部完成。每项保留截图、事件/游标、时间样本与异常记录。
只有所有必需项通过并且没有未解决的高优先级审查问题，才能声称 100%。

实际14项验收逐项记录输入、期望、事件/游标、浏览器截图、指标与清理证据：

1. 简单回答直接交付，无多余开场，只有一份最终提交。
2. 多来源先交付带覆盖范围的发现，不能把一页当成全部。
3. 主模型只调工具时仍有真实Harness反馈，恢复不重复发布。
4. 慢模型/工具下刷新已缓冲正文，等待状态准确。
5. 单源失败继续可用路径，保留部分结果与失败边界。
6. 图片在任务结束前出现，单图失败不破坏正文。
7. 官方或直链在线视频内嵌播放，不强制对象存储。
8. 合法完整图表及Markdown/LaTeX混合显示，故障隔离。
9. 结果修订/最终确认保持内容身份、播放器与阅读锚点。
10. 每帧断流/EOF/重连补发完整，不重复工具执行。
11. 刷新/快速导航/延迟ACK/返回同一key仅恢复观察。
12. Worker接管不重置预算、不重复工具或里程碑。
13. 取消/审批/权限拒绝/未知写结果按权威回执闭合。
14. 并发长历史有界、慢观察者隔离、终态资源清理。

固定源码及dirty摘要、锁文件、SDK精确字节、BUILD_ID、镜像ID、脱敏配置和迁移版本，
再核对实际运行。用户重启既有服务；缺少激活/真实验收不以构建、模拟UI或健康替代。

### 2026-10-03 final proposal closure requirements

These clarify the same thirteen acceptance faces, not a second plan:

- Dependency/admission waiting does not consume or reset transient-failure retry
  budget. Confirmed source append/closure wakes dependency waits, while exhausted
  failures and integrity problems stay capped. Prove seven failures followed by
  dependency waiting and a real source append in both native stores.
- Native PostgreSQL Handoff assigns the parent commit before child receive in the
  same transaction, preserving the common lock order, fences, immutable positions
  and bounded adoption. Do not repair this by changing already-published positions.
- An observation GET verifies current access without renewing execution bindings;
  command admission/explicit authenticated renewal retains execution authority.
  Cover a queued Task with an expired admission grant independently of SSE reads.
- Durable projection budget/integrity/exhausted failures reach the exact anchored
  observer scope as typed observation problems; heartbeats never mask dead work.
  Unknown Run anchors stay not-ready; an observation problem is not a Task failure.
- Task/header/checkpoint I/O must be genuinely bounded at adapter connection, SQL,
  lock, transaction/commit and cancellation boundaries; a to_thread/wait_for timeout
  alone is not cancellation. Reuse existing drivers and scoped settings, not global
  database timeout changes. Test connection loss, locks and cleanup in isolated PG.
- Frontend bounds include live/optimistic Turn growth, not only historical cache;
  preserve final-result retrieval and active media. Serialized-cache budgets do not
  prove process heap limits. Rerun all gates after the last source change.
- First meaningful communication is task-specific verified work or evidence,
  distinct from receipt/wait/keepalive. Measure first useful result separately.

Latest plan-only audit is evidence progress: queue wake cap, native Handoff order
and forced read-only cloud GET are still RED; projection-error propagation and
whole-operation I/O bounds remain unproved. The explicit goal continuation resumes
implementation, not application migration/restarts or publication.

### Latest plan-only audit and resumed implementation

The latest review supersedes the stale RED summary above: queue native-store
checks passed and v68 is frozen at
`a08e29f23387b57b0ed740702c65bedee740384226363e3d919f7689dc36201f`.
Required closure remains Task-scoped actual I/O, renewal/cancel lifecycle,
namespace/frame/deadline PostgreSQL probes, latest gates/builds and activated live
acceptance. A 200 foreign-scope test is unresolved fixture-or-production evidence,
not yet a confirmed data leak. Renewal code has not passed fresh full Host gates.
Execution resumes on the explicit full-goal continuation; no application restart,
migration, commit or publication is inferred.

### Latest final-plan continuation requirements

The explicit goal continuation resumes implementation after the plan-only audit.
Task-specific communication and first useful result remain separate evidence:
receipt, tool name and wait text must not satisfy meaningful-communication SLOs.
Precision authorization resolves the durable Task binding's opaque Host thread,
never equating it to the Task UUID. Renewal preserves that thread while validating
new Run targets separately; GETs do not renew, create or backfill Tasks. Entire
pre-Grant I/O and atomic replay consumption need a shared bounded deadline and
unknown-commit handling. Local targeted passes do not replace fresh full gates,
offline migration execution, exact builds or activated fourteen-case acceptance.

### Latest ultimate-plan execution boundary

The user's full-goal continuation resumes the same plan after read-only review.
Four legacy GET surfaces reproduced implicit Task adoption; scalar indexed
Session-to-Task reads must replace it without hydrating/backfilling history.
Dependency-unavailable history reads must not become empty business results or
meaningful findings. Task-specific communication and useful business results
require distinct verified bases, not a nonblank summary or renamed metric.
Main-model communication stays primary; no new planner, default narration model,
or weakened publication/authorization gate is introduced. Five disjoint lanes
cover resource binding, pre-Grant I/O, native legacy migration, process cleanup,
and public fact semantics. Fresh full gates, exact artifact/runtime identity and
all activated live/timing checks remain required; existing services are still
restarted by the user. No application migration, commit/push or publication.

### Current unified proposal execution

The current user goal resumes the thirteen-section proposal as one joint release,
not independent partial launches. Three concrete residuals are now reproduced:
old Trench Task-to-Host identity is overwritten on rebinding; frequent title,
cancel and clarification reads still call the full Task endpoint despite the
new scalar header; public read facts admit only Trench history/detail shapes.
Implement a persistent indexed runtime-domain/Task-to-Host identity with
transactional CAS writes, migrate hot reads to the scalar header, and extend
bounded operation evidence without weakening legacy verified-read semantics.
Persisted usage/attachment paging, actual object-body I/O cancellation, full
gates, exact packages/builds, activated fourteen-case acceptance and healthy P95
samples remain in the same required scope. No existing application DB migration,
  restart, commit, push or registry publication is authorized by this continuation.

### Current ultimate proposal: residuals and unchanged completion scope

The latest user-approved proposal retains all thirteen faces and fourteen live
cases. Reproduced source failures/partial content must not become empty verified
results. Task-specific public facts must extend beyond Trench history while
generic execution receipts remain non-meaningful. Worker execution/progress
recovery needs bounded typed state, not whole-history hydration or a last-N cut.
Usage/attachment summaries need persisted frontiers and paged indexes; snapshot
GETs are read-only. Native media cancellation, exact installed/build/runtime
identities, latest full gates and at least 100 representative healthy timing
samples remain mandatory. This continuation authorizes implementation and safe
isolated verification, not existing application DB migration/restarts or release
publication. Keep incomplete/live-unverified items open.

### 2026-10-04 continuation evidence

Fresh `make check` is green: file-size gate 2360 files, Ruff, Mypy 1074 source
files, deterministic eval 30/30. Native web composition uses explicit optional
cancellation parameters; the zero-argument injected factory remains compatible.
Native cancellation: 49 passed. Isolated real PostgreSQL lease expiry/takeover:
two passed, covering legacy and v2 transport; old publication is independently
rejected by the DB fence, native TLS and child processes are closed, and the new
Worker publishes. Related media/Worker matrix: 53 passed; native HTTP/unknown
commit matrix: six passed. These counts overlap and must not be summed.

The new full-suite run retains its log under
`/tmp/zebra-progress-validation-20261004-eyv7fq/full-tests.log`; only its terminal
result can supersede previous full-gate evidence. It finished 6173 passed,
1232 skipped, one failed in 746.71 seconds. The v2 offline test still patched
ordinary DNS rather than the new cancellable child boundary, so real DNS's
proxy fake-IP was correctly blocked by SSRF. The existing injected CrawlGateway
resolver now isolates the test; both authority tests pass, additionally requiring
one successful tool completion and no failure. Production SSRF/native DNS is
unchanged. Latest full rerun is `full-tests-after-dns-regression.log` in the same
directory and is not yet a terminal result. Actual Worker input recovery
still calls whole-history reads in `recovery.py`, `execution_recovery.py` and
`context_materialization.py`. Public projection/progress checkpoints are not
execution-input checkpoints: they omit user Task state, continuation, budget and
approval state. Do not replace these reads with a last-N window or silently
discard older conversation constraints. Persisted, fenced input frontiers and
bounded preparation are still required before marking that requirement done.
Actual joint fourteen-case execution, representative timing and user-operated
runtime activation remain required; no restart or release is inferred.

Application build completed without starting services. Built image IDs:
API `3c22eb6998966b6ccbcf1546af7834d7039155a0210a95ee7adc2af5a0a079a5`,
Worker `030254686e0d027830542d9965f3a41815c2725e6f53b86fbf7de5020d3d5d7b`,
migrate `6779fe09404893d0d1a67324151dbf16fcebaebec2134cd02cc9c309461fcbd3`.
An isolated no-network Worker image probe imports the public-output module and
matches local `execution.py` SHA256
`e6867c9dc111eb547af80a381d823bf46d9bc2683f82ab59541d082b78a1dc71`
and `web_tools.py` SHA256
`972ff204c339748b72efeeb76bab1656c8100119d7f651d0bb6bab41d7fdae35`.
These are amd64 images on the arm64 development host. The application Worker
still runs image `2d7c87ffaf795838ad98b8d212c6ee28d4925d6f584e1a203d930ffbbe825899`;
build verification is not activation or joint acceptance. Scratch authenticated
Host/API/Worker/Broker/browser composition is now registered for the QA lane.

The post-DNS full suite passed 6174, skipped 1232 in 732.52 seconds. Independent
review then reproduced secondary cleanup cancellation causing an unbounded
native `communicate()` wait. The production repair independently attempts group
kill (including raw POSIX fallback), process kill, pipe closure and a shared
0.5-second bounded reap, retaining the primary exception. Six real RED-to-GREEN
probes include descendant socket closure. Latest related matrix: 65 passed,
zero skipped, 51.26 seconds, including actual PostgreSQL expiry/takeover.
Protocol-only isolated preflight/runner regressions currently pass 42 with one
environment-gated skip; this is not any of the fourteen actual cases.
Latest full run is `full-tests-after-native-cleanup.log` and latest image build
is `application-build-after-native-cleanup.log` in the same evidence directory.
Both must finish and byte identity be rechecked before superseding prior build
and full-gate results. Whole-input recovery, live fourteen cases and timing are
still open; no application restart/migration or publication.

Post-cleanup build completed: API
`185f84dd30c5b20849aa8d7aab2f65b71bcebf74edc7f8a0d6a7a1609cf99c8c`,
Worker `3eb1a54304856d606d7673e4c7d2a4b301cc5e21c9ab7d5288f8ac112dbf3b2a`,
migrate `30a7c92b9245686638ef83829e7aa00461d0263822e872f53e6ae4cf82a21bfb`.
No-network Worker image probe matches local web gateway SHA256
`b1be009749fb2ca0639a08d51dc00ce9cdd5cdc45c05f35bb547ae2949a17e1e`.
New isolation/joint runner strict typing passes with
`MYPYPATH=tests/compose/trench_read_e2e .venv/bin/mypy --strict
--explicit-package-bases --follow-imports=silent` and those two files. Browser
entry syntax passes. The scratch Compose topology and actual simple-answer
execution are not implemented/verified; other thirteen cases and timing remain
open. The post-cleanup full suite subsequently completed: 6188 passed, 1232
environment-gated skips, 733.79 seconds. This precedes the next P0 edits.

### All-P0 continuation (2026-10-04)

The current user requests completion of every P0 before a remaining-work report.
The existing task/owner/branch remain authoritative. Main integrates shared
contracts/composition and four disjoint lanes cover:

- Fenced canonical Session pages and primary/model-tool index recovery, with a
  captured highwater and persistent coverage; no whole-history claim replay.
- Exact execution-input preparation, with bounded pages and durable prefix
  advancement. Never replace prior user constraints with an arbitrary last-N
  cut. Capacity failures remain explicit rather than successful truncation.
- Persisted watermarked usage and indexed attachment pages. GETs never repair
  data or hydrate historical payloads; explicit preparation owns backfill.
- Disposable actual Trench/Host/Zebra/Worker/broker/storage/browser topology and
  real simple-answer acceptance, isolated from the user's application instances.

Only a typed, strictly advancing committed prefix may continue preparation in
the same lease. Missing dependencies do not qualify; retrying a whole execution
after a model/tool effect is forbidden. Exact input capacity is 2048 retained
events/1 MiB: exceeding it fails explicitly, never silently loses constraints.
Cloud full Task GET also uses persisted canonical Turn fields, including the
actual duplicate-ID lookup alias. Old derived state is rebuilt by bounded
background preparation, not by GET. Shared native workspace reads and all lease
acquire/renew/release paths are deadline-bounded; local compatibility remains.

P0 implementation and isolated verification are closed against frozen sources:

- `make test`: 6346 passed, 1273 environment-gated skips, 858.70s.
- Explicit PostgreSQL recovery/input/summary/native GET/lease matrix: 46 passed,
  no skips, 102.90s. The GET observation excludes composition startup, still
  forbids writes/history body reads and requires TaskIO connections.
- `make check`: file boundaries, Ruff, 1093 typed source files and 30 evals pass.
- Trench: 47 backend contracts, 373 frontend tests and frontend typecheck pass.
- Real isolated simple answer: current API/Worker/Broker source identity matches
  1093 files; paired Host matches 518 files; native 72–74 migration checksums,
  same-Run durable head/frozen policy and unique final commit pass. Eight SSE
  frames include text before the final; no fixture routes or synthetic tools.

Evidence root: `/tmp/zebra-p0-closure-20261004-uVMAj2`; final runtime proof is
`qa-frozen-v2/joint-result.json` with `scope=simple_answer_only` and
`full_goal_passed=false`. Images were built, not activated in the user's app.

Remaining whole-plan work, in order:

1. Activate application migrations 72–74 and current images under the user's
   restart workflow; verify installed SDK/Host and runtime identity together.
2. Finish the other thirteen actual scenarios: multi-source, tool-only, slow
   execution, partial failure, image, inline video, chart/Markdown/LaTeX,
   revision, frame disconnect, navigation, Worker takeover, authority and
   bounded concurrency. Existing deterministic tests are not live proof.
3. Collect at least 100 healthy timing samples and evaluate P95/admission,
   first useful text and relay-to-paint-ready budgets. This one sample measured
   1.40s admission feedback, 17.36s first text and 19–26.5ms relay-to-paint-ready;
   two animation frames are not physical screen latency.
4. Add durable semantic capsules for inputs beyond the explicit ceiling without
   discarding user constraints; finish remaining background whole-history paths.
5. Prove post-answer Worker/lease cleanup, then perform release/package/install
   acceptance and publication only when explicitly authorized.

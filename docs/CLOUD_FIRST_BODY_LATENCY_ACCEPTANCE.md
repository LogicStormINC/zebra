# Cloud first-body latency acceptance

2026-10-15. Core implementation locally active. Focused quality/Provider repairs and actual-page provisional rendering now accepted; a stable 3-second send-to-body target is not achieved. Earlier evidence and failures remain below as historical snapshots. No push/publication/remote deployment.

## TRACE / DRAFT component

Reused existing Provider first-public-text metadata and temporary phase diagnostics, not per-frame PG events. Native real long response baseline: Provider TTFT1861ms; first allowed Redis draft to API SSE delivery about1.8ms. Official built ZebraClientRuntime→ConversationStreamReducer→AgentMessageList received real authorized v2 SSE, showed Draft, then replaced the same message with committed final. Browser first observation→first body DOM3.60ms; provisional DOM precedes committed DOM4357.60ms. Existing common coalescer/Reader/reducer production path did not need a fix.

The final display proof Run610e3472-b5da-430e-9540-63eb3efdcc11 was accepted while idle Worker was temporarily paused so observer could be ready; Worker resumed normally. Its25.6s initial wait is explicitly excluded from startup-performance claims. Other attempts that attached after completion only prove recovery, not live TTFT. Failed fixed-grant reconnect attempt retained; normal Broker fresh-grant exchange fixes diagnostic authentication, not server authorization.

Diagnostics example supports real observer-only SSE through fixed loopback GET proxy. No controller fence/receipts/business writes; effects are synthetic empty and heartbeat locally503, so client effects are not accepted by this proof. Grant remains in parent/proxy memory; each upstream connection uses existing Host Broker with active-account/workspace validation and original delegated ceiling. No origin spoofing or auth weakening.

Evidence in .artifacts/first-body-latency-20261015/: real-draft-proof.png, real-draft-timing.safe.json, draft-proof-unpause.safe.json, trace-worker.safe.json, trace-api.safe.json. Targeted35 Worker/Reader/coalescer checks and built-export observer/proxy checks recorded separately. Full real startup pairs remain the final stage.

## LAZY allocation slice, 2026-10-15

Eligible cloud materialized Host context uses explicit DeferredRuntime; all policy-approved local tools prepare once. Workspace materialization and context validation remain unchanged. No fabricated handle/authority; late preparation reads current recorder and uses existing fence/instance lifecycle. Config defaults false; local acceptance candidate explicitly true.

67 focused regressions plus 4 lifecycle regressions passed. SPEC/QUALITY GO after fixing reentrant close cleanup and suspend/resume handle updates. Ruff excluding private diagnostic artifacts passed; mypy all 1278 source files and eval30 passed. Literal make check encountered 251 lint errors in untracked private diagnostic scripts; no production source lint errors, no unrelated fixture repairs.

Native PostgreSQL and real gVisor: pure close 0 instances, 2 shell commands 1 allocation, all instances removed; 2428.51ms for allocate/execute/cleanup, no model calls. Native proof used an isolated random schema, dropped only that fixture schema.

Real new Run 472f302f-a375-4b32-ad75-4d986f02bbd4: transient_v2, completed, 1 main model round, 0 tools, 0 runtime_instances. Created-to-model-event 3079.919ms. Compared to earlier exploratory 5715.624–6621.878ms, this is promising but is not controlled paired distribution. Candidate diagnostics remain temporary pending consolidated measurement and normal-entrypoint activation.

## Shared address resolution, 2026-10-15

Measured cold task-I/O address resolver children cost58–69ms. Execution-input/replay/draft-proof adapters now receive the existing same-DSN TaskIoConnections from composition. Address TTL/environment/service-file invalidation remain existing30s behavior; each connection, transaction, snapshot and authorization read remains fresh. Raw binding/manifest loaders outside deadline were audited and left unchanged.

43 focused passed; 2 native skips not claimed; 1 existing missing-Redis fixture deselected. New concentrated regression proves one resolver across3 phases,4 fresh connections,2 fresh RR READONLY snapshots and DSN mismatch rejection. Ruff/mypy1278 pass; SPEC/QUALITY GO. This does not explain all API admission time. API diagnostic observed an actual command request209.587ms and Host binding renewal126.593ms; preceding Broker/consumer delay must be kept separate.

## Final local measurements and activation

40 fresh real-model requests:20 pure replies,20 read-only sandbox tasks; Flash/high unchanged, v2, isolated new conversations. Batches alternate eager/lazy groups under the same node and background services. Samples are exploratory, not randomized production experiments or SLA percentiles. No user original Run was re-executed. Two initial lazy-only samples predate resolver reuse; keep them separate.

| Pure-reply sample | n | Run→model event p50 / sample p95 | Run→actual HTTP p50 / sample p95 | Run→first generated body p50 / sample p95 |
| --- | ---: | --- | --- | --- |
| Eager before resolver reuse |5|4671.54 /5289.84ms|4997.59 /5622.30ms|5413.26 /6402.55ms|
| Eager, current source, flag off |5|3513.37 /4419.33ms|not captured|not captured|
| Current source, lazy flag on |8|1811.73 /2296.37ms|2195.58 /2586.55ms|2911.80 /3394.58ms|

Same-source flag comparison reduces Run→model-event median48.43%. The combined exploratory before/after HTTP median falls56.07%; do not conflate these comparisons. Accepted canonical command→actual HTTP is1351.69ms median/1887.69ms sample p95 in the8 current-source pure samples. Provider HTTP→first public body667.09ms median/1058.72ms sample p95. This is generated body, not browser arrival. BFF snapshot polling total median5744.90ms is formal completion observation and not first-body DOM.

All20 pure requests completed with one main model request, zero tools. Each eligible lazy pure request used zero runtime_instances; eager pure requests created one. All20 sandbox requests performed exactly one actual command.run; one instance each, all removed. Native PG/gVisor proof separately verifies allocation and two actual commands share one instance. The actual tool-result arrival median is7437.10ms eager(current-source,n5) versus7151.05ms lazy(current-source,n8), with max7946.26 versus8158.57ms. Allocation moved to the first tool; no claim that all tool tasks become faster.

### Retained failures and quality gate risk

Canonical terminal state:35 completed/5 failed. All failures are sandbox final-response paths:2 eager_shared and3 lazy_shared, HTTP400 normalized invalid_request on a later model request after the command succeeded. They are retained in the denominator; do not claim40 successful E2E. Runtime instances were removed in all40 requests.

Read-only source/event triage of118e4d9f-94b0-4f22-93f3-4914bdecced2 proves the third request is an existing quality revision: the test wording“只报告输出”contains“报告”, so task_contracts.py infers a structured deliverable with minimum160 characters. evaluate_answer rejects the short correct response as deliverable_too_shallow; final_completion appends quality feedback and invokes the model again. This also occurs with defer=false. At this baseline point the bounded provider response was unavailable; the subsequent focused repair below proves the missing empty reasoning field with a controlled Provider400/200 pair. Error metadata default1model/0tools is not the actual durable count; this Run has3 requests and1 successful tool call. This pre-existing production issue remains open and prevents an unqualified full E2E acceptance claim.

### Browser adapter correction and remaining proof

Normal-service long-body Run d7b438a1-8ff1-4e29-9d8d-19c935fadb89 completed v2, but used web.search/web.fetch despite the no-tool test instruction; it is not a valid pure-response startup sample. Its pre-fix first visible Markdown was17.705s, and no fast-page claim is derived from it.

Inspection found the Trench acceptance adapter classified transient_draft as collapsible work; answerStarted then hid it. Commit2aff921 on Trench codex/latency-draft-adapter-01 excludes only provisional answer items from workMessageIds, retaining commentary/evidence collapse. The new regression fails before the guard and all19 projection tests pass after. This is an adapter display fix, not a Trench-specific Cloud architecture optimization. Existing public SDK real first-draft observation→DOM3.60ms proof remains a separate accepted component.

The final live-page check after this guard is not accepted: Chrome debugging commands repeatedly timed out, reset/rebind/reload did not restore the connection, and native input finally reported noWindowsAvailable. Independent IAB correctly reaches the login page and lacks the existing authenticated Chrome session. No synthetic credentials, authorization bypass, browser restart or replay of the original Run was used to claim success. Browser paint timing after the adapter fix remains open.

### Installed state and gates

Cloud commits18071b18,e6c2bed1,593565d2 locally integrated into cloud-agent-trench. Worker image1ddf79d7742ffdd3f55ce618f962bb22e48da0b09a929cd3deaab9bead77d463; normal zebra-agent-worker entrypoint, API restored to uvicorn normal entrypoint/image6660332971a360052943d01d8f429ed0f5e95f5b7220e58060248228a7d0bc7f. No temporary trace composition remains active. Normal docker/trench-acceptance.env sets defer_provision=true; v2 remains enabled. All15 owned live source hashes match accepted source and integrated primary. The independent Web/DNS repair in base Worker98612d73 is preserved.

Final make check on accepted source passes:3062 files size gate, Ruff, mypy1278, eval30. Private diagnostics were temporarily moved out of the source scan and restored; no lint rule was weakened. Initial make-check failure from private scratch scripts is retained. Official5-package pnpm verify passes under supported Node24.19.0:103 tests, package audit, React18/19 Vite/Next consumers, Chromium/WebKit and hydration. Initial pnpm subprocess used Node20.10 despite outer shell22; its4 environment-only failures were corrected by explicit supported runtime, without fixture edits. This verifies the current primary SDK working copy, including separately owned UI work; that unrelated code was not committed by this task.

Four owned authenticated observer proxy listeners were stopped. Diagnostic API/Worker monkeypatches are inactive. Original user data and unrelated dirty files remain. No push, remote deployment or npm publication. STOP/full v1-v2 SQL80% remains a distinct unaccepted gate; this latency experiment does not establish total SQL reduction.

## Exact next acceptance work

1. With a functioning authenticated browser connection, observe a fresh ordinary draft before canonical completion and capture actual send→body DOM after adapter2aff921. Do not replay old Runs or count placeholder/status text.
2. Isolate the existing quality-revision Provider400 with a bounded private diagnostic response capture, preserving credentials and original Runs; address its root cause in a focused follow-up. Do not claim empty reasoning caused it without provider evidence.
3. Preserve the current locally active latency improvements while these final E2E items remain open. No further broad fixture or testing-infrastructure cleanup is required by this slice.


## QUALITY-PROVIDER-REPAIR-01 (2026-10-15)

Two production files changed. infer_task_contract no longer treats the ambiguous bare Chinese verb 报告 as sufficient evidence for a long structured document. The original command prompt now accepts the correct short result; explicit Host length/structure contracts and explicit detailed Markdown requests still enforce their requirements. No new question router, dependency or model call was added.

The DeepSeek serializer discarded returned empty reasoning_content on non-tool assistant candidates. A quality revision appends SYSTEM feedback in the same user turn, where the provider requires that field to be replayed. A controlled Flash/high/thinking request with identical tool history and SYSTEM feedback returns HTTP400 when the candidate field is missing (176ms), HTTP200 when the exact empty field is present (116ms). A new USER feedback control accepts both, isolating the same-turn boundary. These first-event probes prove admission only. The earliest legacy-default Pro probe was stopped and excluded; it is not Flash performance evidence.

The fix preserves every returned string, including empty and whitespace, in the existing provider-private field. It does not invent missing reasoning, relax missing required tool reasoning, disable thinking or expose reasoning in public serialization. Both streaming and nonstreaming regressions first reproduced400 and now pass. After local activation, the real production gateway completed the controlled same-turn continuation in both modes:3270.06ms nonstream and2885.74ms stream, zero tools requested. These are full model completions, not early-closed admission probes or browser timings.

Validation:71 focused quality/provider regressions pass; make check passes (3062 files, Ruff, mypy1278, eval30). No unrelated fixtures were changed. Worker image4436ee7fa90988ca2a5ce01c019743eb210c1bfdc277b8cf3cfa6cb4ca2ecf9f layers only the two repaired source files on the prior normal image1ddf79d7. All17 source hashes match (15 latency files plus2 repairs); defer_provision remains true and API image/normal entrypoint remain unchanged. The earlier paired latency measurements remain historical evidence, not a new performance distribution for this fix.

Page acceptance is still pending: after the user restored the connection, Chrome tabs can be enumerated but Runtime.evaluate and focus commands time out before a usable page control session; native input also has no observable effect. The old completed conversation remains readable after reload, and no original Run was replayed. A fresh logged-in page with working control is needed for actual send-to-visible-body timing and canonical completion reconciliation. No placeholder, replay or backend-only timing is counted as that proof.


## Real page acceptance after browser restart (2026-10-15)

Chrome control recovered after user restart. A fresh actual-page fictitious-story request64753bdc-ead1-4f51-b14c-c633b9f04499 exposed a second instance of the same quality inference defect: 不检索事实 was classified as research and 不列执行计划 demanded structure. It displayed provisional body at18.604s but ultimately suspended for verified_evidence after2 model calls,0 tools. This failure is retained; neither it nor any original Run was replayed. Provider candidate TTFT13.278s shows this was not just transport waiting.

The shared inference entry point now excludes bounded Chinese negated clauses before heuristic requirements, preserving length parsing first and explicit Host overrides. Punctuation and contrast stop the exclusion, so later affirmative research/structure requirements remain. This deliberately bounded heuristic is not a semantic question router. The regression reproduces the original failure, verifies the positive contrast cases and preserves 不超过100字. No new classifier/model/dependency or unrelated fixture edits.

Four fresh post-fix requests reconciled against canonical Cloud events and Trench terminal state:

| Sample | Canonical state | Main model calls / tools / instances | Actual page send-to-first-visible-body |
| --- | --- | --- | --- |
| Same fictitious story c88afcc1 | completed v2 |1 /0 /0|14.334s|
| Short reply via normal BFF ed2a521d | completed v2 |1 /0 /0|not measured|
| Actual command cf489d89 | completed v2 |2 /1 /1 removed|not measured|
| Short reply via actual page e292a8f5 | completed v2 |1 /0 /0|5.5175s|

The command actually ran python -c print(1+1), stdout2, exit0. No extra quality-revision model round or Provider400 occurred. BFF polling totals7.499s pure/16.216s command are terminal-observation times, not first body. The story's first visible draft contained79 characters and was aria-busy=true,1.686s before durable answer_committed. Short first draft was0.141s before answer_committed. MutationObserver checks nonempty visible .strategy-markdown; placeholders and collapsed work do not count. The first-nonbusy timer field is not treated as canonical completion; PostgreSQL terminal events are authoritative. Screenshot files capture final pages; first-draft timing is observer evidence, not a screenshot taken during drafting.

Latency remains bounded by actual provider behavior: story Run→model-event4.748s, provider first-public-text8.764s with1052 reasoning tokens, actual page body14.334s. Short actual page Run→model-event2.803s, provider first-public-text1.916s, page body5.518s. These are a few new samples, not a new distribution or a same-prompt comparison against the earlier40-run cohort. Existing historical48.43% pre-model median benefit is not recomputed. Long high-thinking output can still exceed9–12s; no stable3s page SLA or complete latency optimization claim.

Final focused checks:108 tests (72 quality/provider plus36 existing intent/negation/artifact) pass. make check passes3063 size files, Ruff, mypy1278 and eval30. Normal Worker imageb3f64784dd8ab3a86b2fb1b62e21548528c95777666dd21e021342f26153e54c; all17 source hashes verified, including every previously accepted latency file. API unchanged; defer_provision and v2 remain enabled. Temporary page timing listeners and batch globals removed, no trace monkeypatches or service overrides introduced. Evidence: .artifacts/quality-provider-repair-20261015/{fixed-story-page-timing.safe.json,fixed-story-db.safe.json,repaired-pair-db.safe.json,short-page-timing.safe.json,short-page-db.safe.json,fixed-story-final.png,short-page-final.png}. STOP/full paired SQL80% remains outside this acceptance.


## FIRST-BODY-CAUSE-01: why public body still waits (2026-10-15)

Read-only investigation; production source, defaults, services and all latency gains unchanged. Two additional fresh same-story, Flash/general requests used normal authenticated BFF with high and none; no original Run replay. Both canonical completed/transient_v2, one model request, zero tools, zero runtime instances and zero retries. Only these test requests selected different effort; page default stayed high. Dynamic Host context differs slightly (4792 vs4769 input tokens), so this is one directional diagnostic pair, not an exact-byte randomized benchmark or quality-equivalence evaluation.

| Provider metric | high603d46e7 | noneb8a23335 |
| --- | ---: | ---: |
| First SSE event |2020ms|912ms|
| First public text |13186ms|1887ms|
| Reasoning tokens |1677|not reported (thinking disabled)|
| Total model call |14998ms|6765ms|
| Input / cached tokens |4792 /512|4769 /0|
| Run→model-request event |2951ms|2179ms|

Provider first-public-text falls85.69%,11.299s in this pair. That is not an85.69% browser speedup: the pair did not measure DOM arrival. none had zero prompt-cache hits and nevertheless much earlier body; cache warmth alone cannot explain the observed difference. Official DeepSeek thinking mode sends reasoning before the public answer: https://api-docs.deepseek.com/guides/thinking_mode/ . Source confirms private reasoning is accumulated separately, public content emitted immediately; no private reasoning is displayed as body.

Original successful actual-page storyc88afcc1,14.334s:

| Timeline span | Duration |
| --- | ---: |
| Actual send→Trench Run row |0.148s|
| Run→Cloud session-created timestamp |0.792s|
| Cloud session-created→accepted command |1.320s|
| Accepted command→model-request event |2.637s|
| Provider stream start→first public text |8.764s|
| Remaining event persistence/call initialization/delivery/DOM combined |0.674s|

First four spans total4.896s. The0.674s is a remainder, not an isolated browser or Redis measurement: model_request_started is emitted before durable sink return, public callback authorization and actual HTTP; exact HTTP wall start was not captured on this normal-service sample. Provider time uses monotonic timers; cross-service wall timestamps need this boundary caveat. The story provider first-event was1.298s, then7.466s until first body, with1052 reasoning tokens. Short pagee292a8f5:3.038s send→model-event,1.916s provider first-body,0.564s combined remainder =5.518s. Both already had zero sandboxes, so OCI cold start does not explain these waits. Worker warm-up or host contention could explain part of the remaining platform variation; neither has been independently isolated here.

Source details: Trench strategy-chat-input.tsx defaults high and strategy-chat-api.ts sends high when omitted; Cloud task_recovery._model_invocation_policy maps that explicit effort to thinking enabled. Thus one directly answering model call may still think for seconds: tool/research routing and per-request Provider reasoning budget are different controls. Existing Cloud none policy reaches thinking disabled without new dependencies. AUTO currently resolves the selected profile; it is not proof of provider-side adaptive thinking.

Timing audit corrected an attribution risk: HARNESS_ATTEMPT_STARTED, EXECUTION_AUTHORITY_RESOLVED and MEMORY_CONTEXT_SELECTED reuse started_at/as_of. Their identical timestamps are not three stage-completion times. Do not label the next2.497s as solely orchestrator work. MODEL_REQUEST_STARTED precedes public-call setup and HTTP. TextDeltaCoalescer emits the first content chunk immediately; its0.1s later coalescing interval cannot explain8–13s before provider content. About4.8–5.5k input tokens remain even for small requests, mostly advertised tool schemas; this is a secondary candidate, not a measured cause of the long reasoning gap.

Next minimal work: (1) keep explicit user high unchanged; define a Cloud invocation-budget policy before changing defaults, with a fast first call and agent-driven escalation for tasks needing deeper work, avoiding an extra classification model round; independently evaluate quality/tool escalation, not just speed. (2) For remaining2–5s platform overhead, reuse bounded temporary tracing at Host/Broker admission, Worker input/context recovery, recorder append, public-call authorization and actual HTTP start. Measure monotonic spans/fresh DB connections; preserve all fresh authority checks and do not widen into fixture repairs or a warm-pool framework. This task makes no production optimization or stable3s guarantee.

Evidence: .artifacts/first-body-cause-20261015/{thinking-pair.safe.json,pair-browser.safe.json,none-final-page.png}; previous actual-page evidence remains under quality-provider-repair-20261015. Temporary diagnostic batch global removed. No service restart, source change, new dependency or full-suite rerun was required for this read-only investigation.


## PLATFORM-PRE-MODEL-TRACE-01: bounded startup trace (2026-10-15)

Three fresh Flash/high/general short acknowledgements completed canonically in transient_v2 with1 main model request,0 tools and0 runtime instances each:24a81c38,f82de93c,4590b156. Temporary startup launchers layered on the exact accepted Workerb3f64784/API66603329; original production files/defaults were unchanged. Phase timers use monotonic clocks; SQL records contain fingerprints/table names/callers and timing only, no parameters, credentials, reasoning or body. Two broad samples followed by one targeted connection/substage sample; no fixture work or new production instrumentation.

| Span | Trace1 | Trace2 | Trace3 |
| --- | ---: | ---: | ---: |
| Trench Run→Cloud /tasks entry |819ms|342ms|649ms|
| Cloud /tasks handler |280ms|215ms|241ms|
| Between task response and command entry |106ms|51ms|59ms|
| Cloud command handler |228ms|191ms|208ms|
| Command HTTP response→Worker execution entry |267ms|253ms|283ms|
| Worker execution entry→actual Provider stream start |1355ms|1227ms|1410ms|
| Run→actual Provider stream start |3055ms|2279ms|2850ms|

Host-binding renewal123–208ms occurs separately and may overlap Worker work; do not add it again. Trench Run started_at_ms is assigned by mark_running after receiving accepted execution evidence, not a dispatch-claim timestamp, so it cannot isolate Host queue time. Dispatcher source polls every250ms, but the342–819ms pre-/tasks span includes Host preparation/Broker/transport too; exact subattribution is still open. The old4.896s send→model-event spike did not reproduce here; these differently bounded trace samples do not prove a new performance improvement or identify that old spike's exact cause.

Worker stages (inclusive; nested subphases must not be double-counted): progress recovery74–101ms; input recovery271–306ms; context preparation424–518ms; runtime-session identity22–32ms; deferred composition0.04–0.20ms; tool gateway7–18ms; orchestrator45–56ms; public-call authorization123–141ms. This disproves a seconds-long orchestrator-construction or sandbox-provisioning explanation for these samples.

The targeted third sample attributes436.69ms to91 physical TaskIoConnections.connect calls, and570.84ms to566 Cursor.execute calls before the first Provider HTTP. The 91 matched resolver invocations all open fresh bounded TaskIoConnection objects (source verified); DNS itself totals only6.96ms. Query and connect timing comprise about71% of the1410ms Worker span, subject to diagnostic overhead. These are instrumented cursor-method calls, including transaction/session/authority work; they are not a complete server statement counter, not total Run SQL, not the Trench/API query count and not per-delta persistence. NoSQL80% claim follows from them. The other two samples also observe566 cursor calls/91 Task I/O connects; query execution totals534–572ms. Independent ordinary/pool database borrows are not counted as those91 Task I/O connects.

Repeated sources:32 assert_current_lease_fence epoch checks (plus64 lease/clock cursor calls),22 session→task mapping reads,16 task-header reads and repeated progress/head/event pages. This is fixed startup cost, even when no tools run. Existing DNS address reuse works; bounded Task I/O intentionally bypasses the ordinary process pool and opens fresh connections. Enabling the existing pool flag alone therefore does not solve it, and dropping fresh fence/STOP/authority checks would be incorrect.

Context preparation480.60ms in the targeted sample: bound binding load4.15ms; authority persistence/recovery228.14ms (includes one88.81ms input refresh); actual materialize_worker_context9.92ms; a later independent input refresh105.78ms, plus memory event persistence/recovery and remaining glue. The bottleneck is state refresh and its storage protocol, not expensive memory selection or document compilation. The two input refreshes straddle canonical writes and cannot simply be replaced by stale cached facts.

Minimal next implementation candidate stays in Cloud Agent: first narrow to execution-input recovery and its existing bounded reader/connection boundaries. Reuse a socket or batch reads only within one existing short operation, preserve its cumulative deadline and separate fresh transactions/authority reads, close/discard on errors and stop; no attempt-lifetime authority cache, no transaction across Provider wait. Retain commit-time fence/epoch/control checks. Validate a meaningful storage/lease/STOP regression plus a few real short samples, then address the context path if measured gains justify it. The measured per-stage costs bound possible savings; no promised one-second or percentage reduction before implementation. Host dispatch remains a separate adapter observation, not a Trench-specific Cloud redesign.

All diagnostic services removed: exact saved images, original entrypoints and original six-file normal composition restored and healthy. All17 accepted source hashes verified, defer_provision and v2 retained. Temporary page driver globals removed; final page shows 接入完毕. Evidence under .artifacts/platform-pre-model-20261015: summary.safe.json, canonical.safe.json, worker/api-trace-pass1/pass2.safe.json, normal-restored.safe.json, completed-page.png. No new production source, dependency or full-suite run; only private launchers and durable findings changed.


## INPUT-MEMBERSHIP-01: minimal native input-transaction repair (2026-10-15)

ExecutionInputStore previously opened a separate Task-port connection to map Session→Task, then queried the same native membership again inside read/read_page/advance. All three PG paths now resolve namespace-qualified canonical membership once through the existing read_task_id_for_session helper on their own operation's connection. No cross-operation socket or authority result cache, no new pool or dependency. Each operation retains its native transaction/deadline. advance retains the lease-boundary lock and both fence validations; membership now resolves after the first fenced lock. SQLite retains its task-port/namespace membership validation and the original _key(lease) compatibility entry.

The new native regression first failed because identity escaped the input transaction. It now proves read/page/advance/read each uses one distinct operation connection, no external Task-port lookup, correct state advancement, and foreign namespace refusal. Four existing native CAS/forgery/expiry/actual-lock-deadline cases passed. The103 other local/frontier/compaction/core cases passed; one old internal caller exposed the changed private signature, fixed by preserving the original optional-connection entry rather than editing its fixture, and its focused rerun passed. Thus109 distinct relevant cases validated. Final make check passes (3063 size files, Ruff, mypy1278, eval30); no unrelated tests repaired.

Two fresh Flash/high/general short requests were traced with the same temporary launchers as baseline: f01a3a62 and ddc2d33d. Both canonicalcompleted/transient_v2,1 model,0 tools,0 OCI. Deterministic pre-HTTP observations:

| Metric | Previous3 samples | New2 samples |
| --- | ---: | ---: |
| Task I/O fresh connections |91 each|76 each (-16.48%)|
| Instrumented Cursor.execute calls |566 each|551 each (-2.65%)|
| Lease-fence epoch checks |32 each|32 each|
| Input recovery stage |271–306ms|224–229ms|
| Worker execution entry→actual HTTP |1227–1410ms|1134–1253ms|
| Task I/O connection elapsed |437ms (targeted baseline)|350–354ms|

This is a small fixed-startup improvement. The code deterministically removes15 connection paths and15 duplicate membership queries in these starts. Sample timing is exploratory and includes diagnostic overhead; no stable end-to-end/DOM improvement percentage is claimed. BFF terminal polls5.640s/4.411s are not first-body measurements; Provider thinking variability remains. These counts are scoped cursor calls, not complete Run/server SQL or the overall80% SQL acceptance gate.

Only packages/agent-storage/src/agent_storage/execution_inputs.py was layered over accepted Workerb3f64784. Active normal Worker236aef39ef8279759ba3b697c2ab0d1fc0389f0bc60cde97083485e0d2690176, API66603329 unchanged. Exact original normal six-file composition and entrypoints restored after tracing, both healthy;18 live source hashes match including all15 prior latency files and both quality/Provider fixes. defer_provision/v2 retained, no temporary trace service or browser batch global remains. Evidence: .artifacts/input-membership-20261015/{red.log,native-focused.log,local-focused.log,local-compatibility.log,native-final.log,check.log,summary.safe.json,canonical.safe.json,normal-active.safe.json,completed-page.png}. Initial compatibility failure remains in the evidence; no original Run replay, push or remote deployment.


## INPUT-BOUNDED-QUERIES-01: fixed startup SQL consolidation (2026-10-15)

Only `agent_storage/execution_inputs.py` changes production behavior. Checkpoint metadata
and body now share one query; database CASE returns NULL for an oversized/mismatched
body before client hydration. UTF-8 byte checks and canonical event identity remain.
The six terminal types retain separate covering-index LIMIT-1 seeks, combined with
UNION ALL/MAX in one round trip; admission anchor remains a separate bounded seek.
No authority cache, shared transaction/socket, pool or new dependency. Namespace,
captured highwater, index prerequisite, cumulative deadline and both write fences remain.

New PostgreSQL/SQLite tests first failed all eight cases, then passed size mismatch,
1.1-MiB corruption, multibyte state round trip and highwater/seek-count assertions.
The first green attempt exposed two assumptions in this new test only (compacted tool
output is absent from exact state; SQLite Row has no get); corrected without editing
old fixtures. Original native invocation:15 pass/1 failure in119.10s. The cold-history
case prepares over2,000 events after acquiring a60s scratch lease and was correctly
rejected at its first write fence. Diagnostic rerun of that unchanged test body with
only a5-minute scratch lease passed in100.26s. This is separate evidence, not a claim
that the unmodified full native invocation passed.104 local/core cases passed44.53s.
Final make check:3064 file sizes, Ruff, mypy1278 and eval30 passed.

Two new normal BFF requests, Flash/general/high, observed with the same bounded
API/Worker tracing as INPUT-MEMBERSHIP-01:

| Metric before actual Provider HTTP | Previous two samples | New two samples |
| --- | ---: | ---: |
| Cursor.execute calls |551 /551|525 /525|
| Task I/O fresh connections |76 /76|76 /76|
| Mutation fence epoch checks |32 /32|32 /32|
| Worker entry to HTTP |1253 /1134ms|1320 /1278ms|
| Native connection duration sum |354 /350ms|390 /398ms|

Runs e619186c-a80d-4837-83c2-fe4110cdc475 and48bc427b-74eb-4ee3-899b-e51b8d2fbe38
both canonically completed/transient_v2,1 model/0tools/0instances. Fixed query count
falls26/551=4.72%, cumulatively566→525=7.24% from pre-membership trace. These are
startup-scoped client cursor calls including SET/fences, not whole Run/server SQL
or the overall v1/v2≥80% gate. Samples do not prove lower startup latency; connection
variation exceeds the saved query time. BFF terminal polls are not first body.

After restoring normal entrypoints and original six-file composition, two actual-page
Flash/general/high requests both completed v2/1model/0tools/0instances:

| Actual page | First visible body | First visible draft | Provider first body / reasoning |
| --- | ---: | --- | ---: |
| Short b0286e47 |6.5986s|first observed in final state|797ms /44tokens|
| Story1ab820c4 |26.5966s|75chars, aria-busy=true,632.8ms before answer_committed|21871ms /4978tokens|

Story first SSE event195ms, model total22407ms; high thinking accounts for most of the
wait before public body. Story send→model event4075ms plus Provider first body21871ms
plus650ms mixed initialization/persistence/delivery/DOM remainder explains26.597s.
The650ms is not an isolated browser transport measurement because model event precedes
actual HTTP. The short answer does not independently prove provisional display; the
longer story does. First-nonbusy is not treated as canonical completion. Stable3s is
still unachieved, and no end-to-end speedup percentage is claimed. No quality revision
or Provider400 in these four new requests. No original Run/model replay.

Normal Worker a51c3a5969c71b47618822fa92b806204ae954cfa2ec8de9126128d4a4adf110;
API66603329 unchanged. Both healthy;18 live source hashes match accepted files and
prior latency/quality fixes. defer_provision and actual v2 retained. Browser diagnostic
globals/listeners removed; no trace launcher remains. Evidence under
.artifacts/input-bounded-queries-20261015/{red.log,native.log,native-final.log,
long-history-diagnostic.log,local.log,check.log,summary.safe.json,page-canonical.safe.json,
normal-active.safe.json,completed-page.png}.

Next priority: Cloud reasoning-budget policy preserving explicitly selected high effort,
and separately isolate the normal-page pre-model4.1–4.4s path. Do not keep iterating
millisecond-only SQL changes as a solution to21.9s Provider body wait. STOP, full SQL80%,
cold/hot/concurrent distributions and capacity/GC lifecycle acceptance remain open.


## PAGE-ADMISSION-TRACE-01: actual page path and bounded key warmup (2026-10-15)

Actual pages include client open/mount/run-binding, which empty-client-state BFF
samples omit. Trench source was read only; no Host product code/default changed.
Two baseline page requests and one empty-client control used existing accepted images.
The first trace omitted the /v1/extensions prefix; its1.258s before runtime-capabilities
is therefore before the first *recorded* API request, not all outside Cloud. The second
trace fixes this observation boundary. All requests are new, not original Run replay.

| Measured span, complete baseline page1f00dc76 | Duration |
| --- | ---: |
| Actual send→Skill HTTP entry |783ms|
| Skill HTTP authorization / metadata |291ms /13ms|
| Runtime capabilities HTTP total |20ms|
| Task creation HTTP total |253ms|
| Client open + mount + binding HTTP totals |43 +70 +99ms|
| AG-UI command HTTP total |219ms|
| Command HTTP response→Worker execution entry |208ms|
| Worker execution entry→Provider call entry |1384ms|
| Actual send→Provider call entry |3609.5ms|

HTTP durations exclude inter-request Host validation/grant exchange/network gaps;
host-binding renewal overlaps Worker preparation and must not be added as wholly
blocking time. Initial783ms includes browser conversation creation, Turn admission,
Host dispatch/preparation and grant/network; it is not a measured queue-only delay.
Skill metadata itself is13ms, not a hidden research/model step. A second page baseline
933cd2ee measured5107ms send→Provider,2092ms Worker; API/client/DB costs varied too.
Actual pages use531 startup cursorcalls vs525 for empty-client BFF, both76 Task I/O
connections. This does not establish that client integration caused the whole timing
variation. No state/authority read was removed to improve these numbers.

Minimal Cloud-only implementation: existing CachingJwksKeyResolver gains token-free
prefetch using its same lock, pinned HTTPS fetch, native kill/reap, size/capacity bound,
300s TTL and rotation behavior. API lifespan warms active registry URIs before readiness,
with one cumulative2s budget and maximum32 unique URIs. Custom/local authorizers are
unchanged. Failure logs only exception type and leaves ordinary fail-closed request
authorization. Every request still reads current registry, verifies signature/claims,
checks target and atomically consumes nonce. No authority/nonce cache, pool, dependency,
background refresh or reasoning policy change. Expired public keys still refresh normally;
this moves first-process work, not all future network misses.

Evidence is deliberately separated:

- Six new checks first failed, then46 focused security/API cases passed16.18s.
  Frozen-source new6 rerun passed3.58s; make check passed3065size/Ruff/mypy1278/eval30.
- Native signed-grant replay/origin/scope/audit matrix passed. Two additional native
  bounds checks initially skipped for missing scratch DSN, then failed setup because
  an existing dedicated container's volume password differs from its configured env.
  No fixture/credential was repaired. A disposable PostgreSQL ran those two unchanged
  checks:2passed0.73s; only its own container was removed.49 distinct focused checks pass.
- Three adjacent no-model PostgreSQL+native TLS pairs, alternating order: cold auth
  98.09/81.32/75.77ms, warm29.92/24.81/30.22ms. Medians81.32→29.92ms,51.41ms saved
  in this isolated boundary. Warm work63.68–76.96ms occurs before serving. Cold auth
  fetched once each; warm auth fetched zero times. This is not a page speedup claim.
- Candidate actual startup warm took391.38ms including362.93ms JWKS fetch. First real
  Skill request resolved the already-warmed key in0.172ms and performed no JWKS fetch.
  Its whole HTTP authorization nevertheless took496.49ms: first DB connection301.9ms
  (including163ms resolver), other DB/nonce work and scheduling remained. Baseline
  authorization291ms was faster overall. Thus no real-page/auth-total improvement
  percentage is established by the isolated component result.

| Actual page sample | First visible body | Provider total / successful-attempt first text | Gateway retries |
| --- | ---: | ---: | ---: |
| Baseline933cd2ee |6.6944s|537 /510ms|0|
| Baseline1f00dc76 |4.3622s|600 /581ms|0|
| Warm candidate, tracedcc44a0f8 |6.1645s|704 /692ms|0|
| Warm candidate, normal entrypoint30e491ae |12.3378s|7028 /917ms|1|

All four pages and control72eacaa4 canonically completed/transient_v2 with one logical
main-model round,zero tools/instances. The final normal request has two Provider HTTP
attempts due to one Gateway retry, not two research rounds. Its917ms field is relative
to the successful attempt while7028ms includes retries. Do not subtract917ms from page
latency and label the remaining time browser delay. The original failed-attempt type
was not retained; network/HTTP/provider reason is unknown. Thinking latency and Gateway
retry latency are separate remaining causes. No new Provider400/quality revision was
observed; this is not stable3s acceptance or proof that the whole first-body issue is fixed.

Normal APIc0b8e9dce87a9cdc2d4a10d202dc012bc72d3e081dcb8494bf1e55175bacf3ab;
Worker a51c3a59 unchanged. Both healthy under original six-file composition/entrypoints.
Three API source hashes plus18 accepted Worker hashes verified. defer_provision/v2/high
retained. Temporary launchers, browser observers/globals and Network instrumentation
removed; final screenshot retained. Private evidence .artifacts/page-admission-20261015
contains canonical.safe.json, native-pairs.safe.json, network/trace snapshots, red/focused/
native/static logs and normal-active.safe.json. Next narrow slice: retain safe per-attempt
retry reason/duration and distinguish total-call vs successful-attempt TTFT, then inspect
new real requests without replaying30e491ae. Worker connection overhead, adaptive Cloud
reasoning policy and the existing STOP/fullSQL80/distribution/lifecycle gates remain open.


## PROVIDER-ATTEMPT-TRACE-01: retained retry diagnostics (2026-10-15)

Normal Worker now emits one bounded JSON diagnostic per Gateway attempt, sharing a
random call_id only within that logical call. Both Chat Completions and DeepSeek Responses,
streaming and nonstreaming, use the same helper. Failed attempts retain exception class,
normalized category, optional HTTP status, attempt duration and cumulative elapsed time.
Successful completion retains attempt-relative first SSE/public text and reconstructed
call_to_successful_attempt_public_text_ms (attempt entry offset + stream TTFT). This
last value includes earlier failed attempts; it is not the earliest SSE across failed
attempts, an HTTP-only timer, or browser TTFT. Integer rounding and Gateway-to-reader
call entry contribute a small measurement boundary difference. Existing durable fields
remain successful-attempt-relative; their contract has not silently changed.

Failed attempts and recovered retries log at WARNING so the normal Worker default
retains them. Ordinary success logs at INFO, intentionally absent from default Worker
logs. No exception message/traceback, URL, header, request/response body, model text or
reasoning is logged. No per-delta records, SQL/event writes, new dependency, authority
cache or transport behavior change. Retry count/budget, no retry after semantic output,
private reasoning, deadline behavior and explicit high effort remain unchanged.

21 new deterministic checks first failed (20 missing diagnostics, then default-warning
visibility);141 focused cases pass including existing stream recovery/deadline, ordinary
Gateway and empty-reasoning regressions. make check passes3067 file sizes/Ruff/mypy1278/
eval30. This is a diagnostic correction, not an independently demonstrated speedup.

Three fresh normal-page requests use Flash/high and actual transient_v2, all canonically
completed with one logical main-model call, zero tools/OCI and zero Gateway retries:

| Run | Send→first visible body | Send→model-start event | Provider total / attempt first text | First observed busy |
| --- | ---: | ---: | ---: | --- |
|5ca5dab0-74a8-4387-87c8-2157671062c1|5651.8ms|4818.6ms|489 /470ms|true|
|64d88bb9-2a6c-48da-b047-712b80d3cd54|6084.8ms|4217.5ms|754 /715ms|false|
|8a47451e-7148-4222-9247-e480916d497e|5363.9ms|3561.1ms|532 /501ms|false|

Page median5651.8ms, observed range5363.9–6084.8ms, n3 only. First page provisional
body precedes canonical answer_committed by about500.5ms, confirming short drafts can
reach the page too. Later short answers were first observed final; this does not prove
withholding. Model-start events precede actual Provider HTTP, so these event spans do
not isolate a precise pre-network duration. No fresh Provider400, quality revision or
Gateway retry was observed. The old30e491ae first failed attempt is still unrecoverable:
its exact HTTP/transport/provider cause remains unknown, not fixed by speculation.
Do not compare12.3378s with these no-retry samples as a causal speedup percentage.

Normal Workere76adcdc54c51b5d8b3692b13f8af52e81dcb3d075d328d23223bb26e671e93a
active/healthy, APIc0b8e9dc unchanged. Original six-file composition/entrypoints/commands
and24 live source hashes verified. No temporary launcher, browser observer/global or
Network recording remains. Private evidence .artifacts/provider-attempt-20261015 contains
red/focused/static logs, canonical/page/attempts.safe.json, candidate and normal-active
hashes, and completed-page.png. No old Run replay, unrelated fixture edits or publication.

Next measured optimization target remains the normal page's3.56–4.82s to model-start
event. Earlier actual-HTTP traces separately identified Cloud admission and Worker
native Task I/O connections; existing composition pool explicitly excludes killable
bounded Task I/O. Reusing that pool blindly would change the deadline/isolation boundary.
Do not add a second generic pool or shorten Provider timeouts without evidence. Adaptive
reasoning policy, stable cold/hot/concurrent distributions, STOP, full-workload SQL80%
and capacity/GC lifecycle gates remain open.


## PRE-MODEL-CRITICAL-01: reuse the just-committed Context projections (2026-10-15)

Measured the actual page through Cloud HTTP entry, command response, Worker entry and
actual Provider HTTP, rather than treating model_request_started as the network start.
Same prompt throughout: `这是启动性能验收，只回复“接入完毕”，不要调用任何工具。`.
All samples request Flash/high; canonical metadata confirms thinking=enabled/high.
All are new requests, not replay of an old Run. Trench/SDK production source unchanged.

| Exclusive baseline interval | First sample | Second sample |
| --- | ---: | ---: |
| Send→first Cloud HTTP |473ms|1089ms|
| First Cloud HTTP→command response |1179ms|1166ms|
| Command response→Worker entry |255ms|382ms|
| Worker entry→actual Provider HTTP |1773ms|1528ms|

First interval includes browser/Host work and network, not an isolated queue timer.
The API/Host interval includes serial task/client open/mount/binding/command work;
Host-binding renewal overlaps Worker and is not added as fully blocking time.
Largest Cloud stage was Worker Context preparation827/592ms, inside Worker totals.
It contained two full Session recoveries after authority and memory-selection appends,
120 recovery cursor calls, despite the recorder's own fenced atomic commit already
updating both primary projections. Context authority433/340ms and input refresh273/194ms
are nested spans, not additive to the Context totals.

Minimal implementation changes two Worker files. Context reuses this recorder's exact
committed Session/Workspace only when a fresh primary control read still equals that
Session, and lease/fence/Session/Workspace revisions agree. Caller ownership check and
native cumulative2s deadline remain. Concurrent primary drift falls back to the original
bounded recovery within the same deadline; cancellation/foreign fence fails closed.
Fresh bounded execution-input refresh, authorization resolution and canonical appends
remain. Local/non-fenced recovery is unchanged. The existing cancellation callback
require_active_execution still returns None; read_active_session exposes its same one
fresh read for Context. No new pool/cache/dependency, Port change, reasoning downgrade,
Trench customization or per-frame SQL. Recovery checkpoints may catch up later through
the unchanged ordinary recovery path; no fact or canonical index check is synthesized.

Final frozen-code paired page results (not mixed with earlier intermediate images):

| Measurement | Before1 / Before2 | Final1 / Final2 | Two-sample median change |
| --- | ---: | ---: | ---: |
| Context preparation |827 /592ms|351 /501ms|709→426ms,40.0% lower|
| Worker→actual Provider HTTP |1773 /1528ms|1253 /1660ms|1650→1456ms,11.8% lower|
| Startup cursor.execute calls |531 /531|415 /415|116 fewer,21.85% lower|
| Fresh Task I/O connections |76 /76|66 /66|10 fewer,13.16% lower|
| Send→model-start event |3407 /3903ms|3090 /3947ms|3655→3518ms,3.7% lower|
| Send→actual Provider HTTP |3680 /4165ms|3338 /4295ms|3923→3817ms,2.7% lower|
| Send→visible first body |4743 /5379ms|4427 /6347ms|5061→5387ms,6.4% higher|
| Provider first public text |813 /913ms|708 /804ms|attempt-relative; no retry|

Before Runs190e0432-1cff-4292-85d9-12e97d928ac4/d59c3c87-9b92-4a93-a7ad-c95e9859059a;
final2d3f2b3d-62c3-45f1-8a6f-968880a9d10d/7f9dde7d-090f-49bb-bd8f-90ff63331b76.
Old-code return control7535253b-9f6d-4ac2-9aa1-e84586200a9e:
Context625ms,Worker1566ms,531cursor calls,76connections,body5316ms. It confirms the
old fixed work reappears on code switch. Intermediate candidates233250c3/6b3cca29,
before the fresh-primary drift fallback refinement, remain as exploratory evidence:
body6739/6086ms,Context304/492ms,415cursor calls; they are not final-cohort acceptance.
No outlier is deleted to claim a page speedup. Only two frozen matched samples per side;
no stable p50/p95, concurrency distribution or causal whole-page percentage is established.

Final1 first observed body was provisional; final2 was first observed final. Worker
Provider-first-text→draft publication took1.41/1.27ms, while publication→observed DOM
was378/1247ms. The latter mixes proof/read/persistence/relay/Host SSE/browser scheduling;
API first-draft instrumentation did not capture an independent boundary, so it is not
assigned to a specific hop. Thus this slice reduces fixed startup work but does not
prove faster page body. Stable3s remains unachieved. These startup cursor counts do not
represent server SQL or whole-Run workload, and do not satisfy the overall SQL80% gate.

Validation:12 new deterministic checks red→green, including coherent snapshot, explicit
ownership, fresh cancel/lease rejection, two-second scope, concurrent drift fallback,
local compatibility and unchanged cancellation return.46 related cases pass4.07s;
5 ordinary cancellation cases pass6.61s;10 native Context materialization cases pass;
6 native tail/fence/budget cases pass. make check passes file sizes/Ruff/mypy1278/eval30.
Failure boundaries retained without fixture repair: an existing Host identity wording
assertion fails identically on pre-change source (excluded from focused rerun); one
unchanged250ms native tail probe expected two sockets but its first operation exhausted
the budget (1failed/6passed). Two native cancellation cases fail fixture setup before
execution: existing guard pins127.0.0.1:32786/header_scratch, held by an existing scratch
container, while the generic test DSN is refused. No existing credentials/container/test
were changed; these two cases are not claimed as native cancellation acceptance.

Normal-service Run9220ce48-3055-42e1-90fd-fa28868270ad completed with transient_v2,
one main-model call,zero tools/OCI/retries,thinking enabled/high. Body4900.9ms,Provider
755ms total/753ms first text. This normal-entrypoint n1 is a sanity check, not a matched
speedup claim. Across all8new requests, canonical completions/profile/high/v2/one model/
zero tools/OCI are verified. Normal Worker376b20ddb9598f5f577c59493653b6ace8bfc67e0c64adb11d08ca8c12b37fc7,
APIc0b8e9dc unchanged;26live source hashes, healthy status and original six-file
composition/entrypoints/commands verified. All temporary launchers, Network recording
and browser observer/globals removed. Final screenshot retained.
All private evidence under .artifacts/pre-model-critical-20261015 includes every page,
sanitized network/trace/canonical summary, failure/red/focused/static logs, exact images,
and normal composition restoration. Preserve prior v2/lazy/input-SQL/key-warm/provider
fixes. STOP, full-workload SQL80%, capacity/GC lifecycle, adaptive reasoning policy and
controlled cold/hot/concurrent distributions remain separate open gates.

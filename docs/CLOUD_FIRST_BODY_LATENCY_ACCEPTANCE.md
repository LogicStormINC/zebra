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

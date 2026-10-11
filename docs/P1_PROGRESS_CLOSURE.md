# Progressive delivery P1 closure

Owner: Luke Ding. Zebra branch: `cloud-agent-trench`; Trench branch: `main`.
Started 2026-10-04 after the frozen P0 gates. This is implementation in progress,
not application activation or full-plan acceptance.

## Required evidence

- Durable semantic capsules beyond 2048 retained events / 1 MiB, with exact
  protected constraints, source coordinates, fenced writes and crash recovery.
- Bounded cloud MCP authority replay and background Memory source windows;
  no widening authority, guessed snapshots or silent evidence truncation.
- Handoff/control/command paths reuse bounded native facts where applicable.
- Reply completion does not wait for optional Memory/title work; native lease
  and gateway cleanup have independently verified terminal outcomes.
- Actual isolated joint cases: multi-source, tool-only, slow execution, partial
  failure, images, inline video, chart/Markdown/LaTeX, revisions, frame disconnect,
  navigation, worker takeover, authority and bounded concurrency, alongside the
  existing simple-answer case.
- At least 100 representative healthy timing samples, faults reported separately.
  Admission feedback <=1 s; meaningful first communication P95 <=8 s;
  persisted milestone to visible P95 <=1 s; relay to paint-ready P95 <=500 ms.
  Generic acceptance/heartbeat text is not meaningful communication. Browser
  paint-ready measures React commit plus two animation frames, not physical
  monitor output. Provider latency floors must be reported, not hidden.
- Fresh focused/native regressions, quality gates and latest-source build/hash
  evidence. User application services remain untouched.

## Execution ownership

Context lane: input reducer/storage/preparation and existing context compaction.
After input closure, the lane owns additive `joint_media_cases.py`, its tests
and scoped QA media fixtures for image/video/chart/revision live acceptance;
shared browser-runner edits require coordination with the QA lane.
Delivery lane: producer/public-output policy and paired Host admission/timing.
After publication freeze, the lane owns additive `joint_fault_cases.py` and
dedicated tests for slow execution and partial failure; shared runner wiring
requires coordination with the media and QA lanes.
Background lane: MCP and cloud Memory reads with dedicated native readers/tests;
follow-up owns native `command_wakeup_message.py`, `session_cancellation.py` and
`direct_control.py` bounded exact replay. Main stops editing those paths.
The same follow-up owns the recorder's native tail read and recorder factory
in `execution_events.py`/`worker_projection.py`; local behavior remains unchanged.
Exact command snapshots also own `task_turn_fields.py`, task read-summary
checkpoint adapters and Session-recovery integration. Migration 77 is reserved
for the exact native command snapshot; catalog registration stays with main.
QA lane: isolated topology and actual scenarios/timing samples.
Catalog DNS follow-up also owns API `http.py`, `extension_composition.py`,
`host_auth.py` and PostgreSQL `host_auth.py` explicit connector composition;
main relinquishes those paths until the focused/native proof freezes.
Main: Handoff/connection deadlines/cleanup, shared wiring/catalog and integration docs.

## Evidence and boundaries

Evidence root: `/tmp/zebra-p1-closure-20261004-9oGtCn`.
P0 baseline: `/tmp/zebra-p0-closure-20261004-uVMAj2`.
Existing user application images differ from the frozen P0 images; no restart,
migration, commit, push or publication is performed by this task.

Status: implementation and verification underway. Results will be recorded only
after commands finish; unit tests do not substitute for actual joint acceptance.

Completed targeted integration checks (not a frozen full gate):

- Main Handoff/gateway/finalization slice: 31 passed (`handoff-cleanup.log`).
- Native control deadline: 1 passed (`native-control-deadline.log`).
- Native Handoff/direct-control API: 37 passed (`native-control-v3.log`).
- MESSAGE/reader/composition: 27 passed, 13 native-only skips; those reader cases
  were rerun explicitly on scratch PG: 18 passed, zero skips
  (`native-worker-replay.log`).
- Input/context regressions: 93 passed (`context-focused.log`).
- Native compacted inputs: 6 passed, zero skips (`native-context-inputs.log`).
- Handoff/MESSAGE/progressive composition: 16 passed (`handoff-message-output.log`).
- Main cleanup/schema regressions: 14 passed (`main-regressions.log`).
- Expanded native MESSAGE/Handoff/control/legacy/deadline matrix: 82 passed,
  zero skips (`native-command-control-v4.log`); this proves the existing contract,
  not yet the new command-snapshot implementation.
- Trench frontend: 63 files / 374 tests passed; TypeScript check passed
  (`trench-frontend-tests.log`, `trench-typecheck.log`).
- Integration quality check passed: 2360 files in size gate, Ruff,
  1096 source files in mypy, 30 deterministic eval cases
  (`integration-check-v2.log`). Later lane edits require a fresh frozen gate.

Migration 75 admits indexed compaction evidence boundaries; migration 76 admits
indexed exact MCP/Memory replay. Registered in the catalog only; application DB
is not migrated. Memory recovery uses the composed cloud DSN, not a settings
fallback. Runtime semantic evidence is appended as data, never as authority.

Archived approval-reference rehydration is implemented in the context lane:
exact indexed source reads verify positions/IDs/checksums and restore only the
referenced exchange, under the original capacity and lease fence. Lane evidence:
106 focused pass, 1 checksum rollback pass, 7 native pass (zero skips); the
integration gate must still be rerun after the shared changes freeze.

One shared recorder factory now supplies bounded native tail reads to authority
initialization, execution and Memory recovery. Composition regression: 25 passed;
recorder/finalization regression: 15 passed. The cumulative tail deadline and
publication cleanup are still under implementation/review.

Native command/control snapshots and cumulative recorder/publication deadlines
are implemented and frozen. Still open: producer/Host timing acceptance, frozen
full gates, fourteen actual joint cases and at least 100 healthy timing samples.
Actual latest-source P1 joint evidence is 1/14 passed (simple answer) and
0/100 meaningful-communication cohort samples. Multi-source and tool-only runs
are blocked at answer rendering; this is not successful progressive delivery.
The old baseline topology is not latest-source P1; a catalog GET returned 503
before provider execution. Root cause and shared-connector fix are verified by
native cold HTTP tests; final-source joint replay is pending.
Synthetic business seed is two sources / 48 actual scratch Host rows;
neither those rows nor runner unit tests establish live case acceptance.

Latest integration check (`integration-check-v5.log`) passed file-size/Ruff,
1102-file mypy and 30 deterministic evals. Publication lane frozen with native
12 passed / zero skipped, including blocked INSERT/deferred COMMIT and actual
backend/timer cleanup. Later shared-store changes need another frozen gate.
Timing aggregation guards: 8 passed (`timing-aggregation.log`); duplicate runs,
mixed source identities, faults and missing meaningful markers cannot fill the
100 healthy sample quota. Cross-clock persisted-to-visible remains unmeasured.
Catalog 503 was traced to repeated cold DNS subprocess startup exhausting a
shared 2-second budget, not slow catalog SQL. QA lane completed the explicit
shared-connector fix. Main native cold signed grant/catalog HTTP regression:
11 passed / zero skips (`native-cold-catalog-main.log`); latest-source live replay
still pending.
Main independently reran publication's scratch-PG suite: 12 passed / zero skips
(`native-publication-main-v2.log`). Incremental collector plus aggregation guards:
10 passed (`timing-collector.log`), synthetic tests only. The collector cycles
multi-source/tool-only cases, preserves each live report and stops on the
first blocked case. Run only against a pinned latest-source isolated topology:

Simple answers remain a separate live matrix case: they deliberately emit no
redundant intermediate commentary and cannot fill the meaningful-communication
cohort with generic acceptance text.

```sh
uv run python tests/compose/trench_read_e2e/joint_timing_collector.py \
  /tmp/zebra-p1-live-timings --seed /path/to/scratch-business-seed.json
```

Runner environment must already come from the authorized isolated QA inputs;
no application credentials are inferred. A browser-timing pass cannot close the
unmeasured cross-clock metric or the remaining fault/media/concurrency matrix.

RabbitMQ control settlement now requeues `PREPARING`, matching the already
deferred Handoff preparation. Regression: 27 passed
(`command-preparing-settlement.log`), including zero ACK/one requeue for both
control preparation and Handoff preparation. Main media browser wiring added;
syntax check passed, actual playback/render acceptance still pending.

Frozen integration gate: `make test` completed with 6539 passed and 1328
environment-gated skips in 795.91 seconds (`frozen-full-tests.log`). Explicit
native suites above remain separate evidence for those skipped integrations.
`make check` passed size gate, Ruff, mypy 1103 source files and 30 deterministic
evals (`frozen-check-v2.log`). New QA-only probes require their focused checks.
API/Worker/migrate images built from the unchanged frozen source manifest;
scratch graph refreshed only. Actual replay exposed stream 503 / Worker recovery
preparation exhaustion, currently under diagnosis; this prevents P1 acceptance.
Latest simple-answer replay independently passed browser/SSE/canonical-final
and native Worker cleanup (`latest-first-three/simple_answer/`). Admission
feedback was 1316.8 ms and first public text 16012.7 ms, so this is functional
evidence, not a latency-target pass. Mutation-guard process overhead is included
in the browser clock; no unmeasured provider or commit latency is subtracted.

Live investigation separated three causes rather than weakening assertions:
- Native three-cold-connector recovery exhausted the shared 2-second budget;
  explicit same-DSN connector injection is being applied and invalidates the
  prior source freeze/build evidence for release use.
- Host tool failures were HTTP 500 from invalid QA business `source_type='feed'`.
  The seed now uses `custom_subscription` and validates every seeded row through
  the real read-tool serializer before commit. This is a fixture fix, not a
  claimed application defect repair.
- The browser runner incorrectly required two marker paragraphs although the
  user message is a div. It now checks the exact authoritative committed
  assistant message ID and visible marker, retaining same-Turn/Run/native-final
  checks. Dedicated selector guard passed; live replay remains required.

Final connector follow-up now shares the explicit same-DSN address resolver
through API Host authorization, tenant/binding checks, Task reads and recovery.
Native signed-grant-to-SSE proof: 6 passed, 0 skipped
(`api-binding-sse-native.xml`); the independent final `make check` passed sizes,
Ruff, mypy 1103 files and 30 evals (`api-binding-final-check.log`). No read budget
or authority fence was relaxed. Updated API/Worker/migrate images were built
and match `final-product-source-v3.sha256`; full regression and refreshed joint
replay are still running, so the earlier 6539 result is not the final gate.
The second full run exposed 8 failures (6623 passed, 1333 skipped, 799.88 s).
Two explicit-adapter composition failures were fixed in the shared HTTP entry;
the remaining fixture/connector arguments were aligned without removing DSN,
namespace or pre-I/O rejection assertions. All four affected modules reran with
65 passed (`final-regressions-fixed-main-v2.log`). A new full run remains pending.
Native SSE repeated after the HTTP guard: 6 passed, 0 skipped; full extension
composition: 32 passed (`api-binding-sse-native-guard.xml`,
`explicit-injection-guard.xml`). QA refresh confirms all three deployed roles
match all 1103 current Python source files (`v3-first-three/refresh-proof.json`).

QA commit-visibility RPC and browser calibration guards independently passed
26 native PostgreSQL checks without skips and 13 Node checks. The shared runner
now has opt-in `ZEBRA_E2E_COMMIT_VISIBILITY=1` wiring with 0600 temporary inputs,
exact admission identity and canonical Run floor. Left-censored observations
and missing milestones remain invalid; no historical timestamp is presented
as a commit instant. Real calibrated samples and the 100-run cohort remain open.

Latest v3 full regression finished with 6675 passed, 1334 environment skips and
3 failures (`final-full-tests-v3.log`), not a passing full gate. Two composition
fixtures subsequently passed in the 65-test focused run; the navigation guard
was aligned with the authority runner without removing normal-case checks.
The v4 full gate is running and remains unclaimed until it finishes.

Actual v3 multi-source replay returned canonical final events but paused for
mutation verification. Two independent shared causes were repaired:
- Host structured `public_facts` was discarded by scalar-only gateway metadata
  filtering. Only existing strict PublicReadFacts/PublicOperationFacts now cross
  that boundary; credentials, arbitrary nesting and invalid facts remain rejected.
- Object-separated prohibitions such as `不得把冲突记录删除` were classified as
  affirmative deletion. Bounded negated objects are removed before intent
  inference; punctuation/contrast and subsequent affirmative actions retain
  their verification requirements. Explicit Host contracts remain authoritative.

Combined intent/public-facts regression: 49 passed; public-output, recovery and
QA observer regressions: 130 passed. `final-check-v4.log` passed file sizes,
Ruff, mypy 1103 sources and 30 evals. Three isolated QA images rebuilt from
`final-product-source-v4.sha256`; user application images/services remain untouched.
All earlier joint passes refer to earlier images, not the new v4 freeze.
Latest-source joint replay and calibrated timing remain in progress; this is
not 100% P1 closure or application activation.

V4 first-three actual replay now passed all three functional cases (3/14):
simple 21.775 s, multi-source 37.021 s, tool-only 41.132 s. Each has one canonical
final and actual lease release/cleanup. Multi-source contract is `answer/complete`;
verified partial facts really appear before final receipt. First meaningful
communication was 11.930 s / 9.991 s for multi/tool, and feedback exceeded 1 s.
These are functional passes, not SLO passes.

One opt-in calibrated real sample functionally passed, but measurement completeness
is false: five measured targets and two invalid observations of the same legacy
`public_update` event (native `model_response_received`, tool-loop stage). That
event remains fail-closed, not excluded as metadata. Three conservative interval
upper bounds exceed 1 s; browser relay-to-paint itself was roughly 19–29 ms.
The sample does not count toward the 100 complete calibrated healthy-run quota.
Media live acceptance now owns the serial scratch window. No application restart,
commit, push or release publication has been performed.

Frozen v4 `make test` finished green: 6715 passed, 1334 environment-gated skips,
793.98 s (`final-full-tests-v4.log`). Explicit native suites remain separate proof;
the skipped count is not converted into successful integration acceptance.
Image live replay subsequently failed after `media.import_historical` started,
with no final commit; native failure/lease release/Worker cleanup were recorded.
Do not count that image case or run subsequent media cases until its cause is known.

Read-only latency diagnosis reproduced a Host Redis-timeout double wait (600 ms
timeout plus 500 ms fallback sleep, local elapsed 1.103 s). This is a shared-path
defect, not proof that the one measured Turn used Redis degradation. The owned
Trench wakeup fix is underway; global polling parameters remain unchanged.

Wakeup fix froze with 3 RED cases becoming 7 passed and an expanded 54 passed /
12 environment skips. A local blocking-read cancellation probe improved from
1.103 s to 0.505 s with both connections closed. Native Redis and new calibrated
live acceptance are still required; no new P95 success is inferred.

The image failure was reproduced by two read-only checks of the same object:
the QA bucket lacked versioning, so HEAD returned no VersionId and both put
verification and subsequent verification raised ArtifactObjectUnavailableError.
The resulting ExceptionGroup terminated the Turn; its actual lease was released
and all five observed Worker activity counts were zero. This is QA initialization,
not a frontend diagnosis. QA seed correction must enable/verify versioning only
in the proved isolated bucket; existing unversioned objects remain untouched.

Producer-backed public model commentary is now being implemented with exact text,
deterministic identity, bounded crash recovery and an independent quota. It is
not meaningful/verified evidence. New source markers must prevent duplicate Host
legacy updates while retaining old-record compatibility, actual deltas and usage.
This follow-up invalidates v4 product freeze for release and requires fresh gates,
images and joint replay; the green v4 full result remains historical evidence.

Canonical Host composition now passes 67 focused/related tests; AG-UI projection
passes 18. Exact Unicode/whitespace chunks share the original streamed message,
duplicate replay cannot truncate it or move the chunk frontier backwards, and
checksums/gaps/forged evidence fail closed. Raw assistant whitespace now survives
AG-UI rather than being stripped before producer checksum verification.
These checks do not close the live matrix or count as calibrated timing samples.
Native QA bucket versioning and real Redis wakeup/cancellation/fallback evidence
are separately recorded; application services remain untouched.

Final consumer-path review found missing hook integration despite green component
tests. The stream now receives restored commentary prefixes, retains newly applied
prefixes if a reconnect snapshot fails, and does not label validated commentary as
legacy/unproven in snapshot timing. A runnable hook regression proves the exact
disconnect-plus-snapshot-failure path; 84 related tests and that new test pass.
Host snapshots also retain the highest confirmed chunk output ID when an older
chunk replays. Frontend/Host composition is frozen again for fresh v5 gates/builds.

V5 full Python regression finished: 6750 passed, 1338 environment-gated skips,
819.64 s (`final-full-tests-v5.log`). Frontend full regression is 397 passed,
TypeScript/ESLint and final production build pass. SDK check/build also passes
under the bundled supported Node 24 runtime. The earlier shell Node 20 check was
engine-mismatched and is not the supported-runtime proof. No P95 or remaining
live case is inferred from these gates.

V5 latest-source activation is independently byte-verified, but its image replay
failed before any tool executed: Run `500df592-1a59-4f10-8e07-56bc85cc430d`
emitted two real assistant deltas (88 characters), then rejected the model
response with `invalid_response_shape / response_payload`. Repair count is zero
because text was already exposed; this is not the earlier bucket-versioning
failure. Only payload size/hash were retained, so the exact invalid field cannot
be recovered from this Run. Safe allowlisted field-level diagnostics are owned
separately; strict validation and retry guards are not relaxed to hide the failure.
Image is zero pass on v5, and the three later media cases remain unexecuted.
The suspended Run released its lease; observed Worker activity counts are zero.

Read-only timing diagnosis also found seven synchronous QA mutation guards,
each about 1.05–1.24 seconds, inside the browser clock. Their exact windows were
not recorded, so neither subtracting their total nor assigning the entire relay
delay to the product is valid. QA-only async preflight now has explicit ownership:
each mutation still awaits fresh native checks, with bounded queued deadlines,
fail-closed replies and joined child shutdown. Exact guard windows must accompany
the next sample. No calibrated sample yet counts toward the required 100.

Controlled rejection diagnostics are implemented: fixed parser rule codes survive
Worker error metadata and bounded repair wrapping; unknown exceptions use one
generic code. Provider bodies and arbitrary exception text are not exported.
Main reran diagnostic/Worker/stream-recovery/OpenAI/DeepSeek suites: 166 passed
(1.21 s). Strict rejection reason/phase and public-delta retry protection remain
unchanged. This is diagnostic coverage, not proof that v5's parser defect is fixed;
a fresh isolated diagnostic-image replay is required.

V6 diagnostic activation now matches all 1110 Zebra source files exactly
(`16c4be7dcc6b5d623834db76d3064593561f59ef4c6ebeff31f3e0db5bfad3db`).
Only QA API/Worker/Broker were replaced; the same protected database, Redis,
object store, Host and frontend remain. No migration or Turn was executed during
activation. Fixture adoption verifies the original 48 rows/digest without
reseed, and bucket versioning remains enabled. Exact image pins and activation
proof are under `v6-build/`; fixture/bucket read proofs are under `v6-media/`.
Image replay waits for the shared asynchronous QA runner regression freeze.

## 2026-10-07 continuation

Main independently reproduced the missing empty reasoning-field adapter defect:
stream assembly discarded provider-returned `reasoning_content=""`, despite
the nonstream parser deliberately accepting its presence for thinking tool calls.
The shared adapter now retains one empty presence marker, preserves exact
nonempty chunks, and does not treat empty presence as semantic output. Missing
or null fields still fail strict validation; transport repair remains bounded.
This is not attribution of the old v5 failure, whose exact field was not retained.
Focused diagnostic/stream/Worker/OpenAI/DeepSeek regressions: 174 passed (1.31 s).
Fresh `make check`: sizes 2360/no violations, Ruff, mypy 1110, eval 30 all pass.

The old async QA lane is preserved. Main reproduced three operator-hook fixture
failures: two extracted fragments omit the real child-close helper, and one
expects obsolete cleanup ordering. The explicitly owned fixture alignment must
retain actual child-close joins and fail-closed proof checks. Isolated v7 builds
are underway; product v6 byte proofs remain historical. Current live acceptance
and calibrated timing counts have not increased. No application restart,
migration, commit, push or publication has been performed.

The QA operator fixture is now aligned; main independently reran its related
matrix: 92 passed. Review found a real cleanup liveness bug beyond the fixture:
`Promise.allSettled` waited for unbounded `operatorExit` beside a bounded close
check. The shared runner now awaits only bounded native cleanup and closes the
browser last in `finally`, including failure. A no-close regression rejects in
900–2500 ms without a fabricated close event; successful cleanup must observe
actual close before browser shutdown. QA Node guard/observer/SSE matrix passes
57 tests. Python coverage/media/timing matrix passes 97, with three native-gated
skips explicitly not counted. Fresh full Python gate is running in
`final-full-tests-v7.log`; terminal results are pending.

Main explicitly reran native commentary/recovery/publication/commit visibility
against the separately owned scratch PostgreSQL: 65 passed, zero skips (20.38 s).
Paired frontend full regression: 397 passed; fresh TypeScript check passed.
V7 API/Worker/Migrate candidates are byte-verified, but activation is blocked by
expired scratch CA/leaf (2026-10-05) and the exited Worker. Host's original
424-file proof and 287 frontend output files still match. No image/fixture
activation is claimed. Read-only scratch checks found zero unreleased leases,
pending commands/effects, but ready/running projections exist. Exact discovery
must rule out old execution before the scoped QA-only trust renewal and service
recovery; missing-process counters are never synthesized as zero. This upkeep
does not authorize restarting the user's application or modifying its data.

Fresh full gate finished: 6800 passed, 1338 environment-gated skips, 881.22 s
(`final-full-tests-v7.log`). The skips remain separate from the 65 explicit
native passes. QA image IDs disappeared before activation, so candidates are
being rebuilt/reverified; no deletion cause is asserted. Exact discovery proves
empty execution/control/Memory candidates under the actual Worker configuration;
ready projections alone are not discoverable work. No TLS/runtime mutation,
fixture adoption or Turn is claimed until its completed proof is recorded.

V7 isolated maintenance/activation is now complete. Worker/API/Broker source
hash is `12b704b725d854ecc36eef8a0ffe6453c918d91eaa09f08afe69435a0f6999bc`;
the existing QA Host/proxy were restarted under the explicitly expanded trust
renewal boundary, with unchanged IDs. PostgreSQL/Redis/MinIO/frontend and user
services remain untouched. Broker signing identity is preserved and verified;
new CA/leaf signatures/SANs/SPKI/mounted bytes and actual zero Worker counters
pass. No migration, seed, object write or Turn occurred during activation.
V7 fixture adoption retains the original 48-row v6 digest and Enabled bucket,
without rewriting the old null-version object. Proofs: `v7-build/activation-proof.json`,
`tls-renewal-proof.json`, and `v7-media/fixture-adoption-proof.json`.
Three actual image attempts remain failures, not live passes. The observer now
uses the SDK assistant-message outer container: rich parts are siblings of the
inner text wrapper. Fault injection derives its exact relative preview target
from the actual import receipt, before the explicit presentation label mounts.
Node guard/observer/SSE regressions: 59 passed. Related runner/media Python:
48 passed. The corrected observer exposes good-image decode failure, not absence
of content parts. Latest Turn `e5e7b85b-d4ed-4c18-8c20-f33bac587c50` has actual
bad-image abort, final received, but good image HTTP 502; native preview is 503.

Read-only native diagnostics show finalized image metadata, pinned version and
18122 verified bytes readable. A detail request returns
`task_preflight_unavailable` at 1.978 seconds. Reproduction within the unchanged
2-second Task I/O budget measures separate resolver calls at 0.722, 0.726 and
0.475 seconds before timeout; a subsequent read still uses four independent
connectors. The three missing Artifact index/metadata/audit compositions now
reuse the existing explicit cloud TaskIoConnections. No global cache, timeout
increase, skipped object verification or fabricated version evidence is added.
Regression checks pass: 66 with 6 environment skips; exact separately owned
PostgreSQL follow-up passes 25 with 2 DNS-probe environment skips. An initial
assumed scratch credential failed setup (13 errors); discovering the actual
container configuration resolved that test-environment error without changing
database credentials. make check passes.
Native Artifact composition/PostgreSQL/download-deadline follow-up passes
39 with one explicit MinIO-bucket environment skip. Independent read-only review
finds no correctness/security regression in connector injection; it confirms
full preview still performs two bounded S3 HEADs plus one pinned GET, so neither
the 0.49-second single GET nor focused gates establish browser acceptance.
V8 isolated images are now byte-verified and activated, with source digest
`d8b80faf3137110981937179fb26d855cf185587566dcb144e7094d8dd010579`.
Only QA API/Worker/Broker changed; trust, signing, protected resources and user
services remained unchanged. Original 48-row fixture adopted without reseeding.
Actual v8 image replay passed: Turn `57b08037-6dbb-4009-8fde-4550aeb120ca`,
Run `439734d5-e29a-4825-8a21-84c00115b204`. Native receipts show six model calls,
seven tools, two presentations and one final. Actual browser verifies decoded
good image, aborted fault image, surviving sibling and presentation before both
terminal and final receipt. Main inspected the preterminal screenshot. Evidence:
`v8-media/image/media-result.json`, `image-preterminal.png`. This is a functional
slice, not full-goal or timing acceptance. Inline video also passes: Turn
`91262fe6-9085-4b94-8b4a-39cb1726d850`, Run
`5862dbc6-8280-4e18-b7f1-c473df0caf94`. The real external-direct player advances
0.213973 seconds and seven frames; zero file-download requests, visible before
terminal/final. Screenshot inspected; no object-store video import is claimed.
Evidence: `v8-media/inline_video/media-result.json`. Neither functional slice
establishes the first-communication SLO.
Measured single-turn (not cohort P95) image/video feedback is 648.4/620.4 ms;
first verified useful receipt is 12432.4/12383.3 ms, exceeding the 8-second
target. Their relay-to-paint-ready event P95 is 35.9/36.3 ms. These endpoints
are browser React plus double-RAF readiness, not physical display timing. No
successful-media shortcut reclassifies commentary as verified useful output.
Healthy calibrated cohort remains
0/100; remaining media/fault/navigation/takeover/authority/concurrency cases are
not complete. Evidence: `v7-media/image-selector-fixed/image-failure.json`.

V8 Chart/Markdown/LaTeX did not pass. Turn
`6e21048d-af9d-42e0-834a-214ae78ff795`, Run
`21fdda79-6328-4e7b-a5c6-59817f8ff4db`; browser fails at `answer_render`.
Bounded exact-Run reads show both files published and chart content parts in
native presentation receipts. One answer is committed with delivery assessment
`partial`, unmet `task_contract_verification`, task type `operate`; the Task is
then suspended and Host is `awaiting_input`. No assertion is weakened to count
that as a successful requested final or chart rendering. Exact cleanup proves
lease released and all five actual Worker execution/thread/timer counters zero.
Next: reconcile genuine task-contract verification with multimedia delivery and
inspect actual chart/Markdown/LaTeX DOM, then revision and the remaining matrix.
Evidence: `v8-media/chart_markdown_latex/chart-markdown-latex-failure.json`.

## 2026-10-07 progressive execution follow-up

The exact chart request says both files.publish and "发布以下两个 .vl.json 文件".
The second publication verb survived the existing Artifact exception and inferred
OPERATE, hence the unnecessary task-contract verification. Reproduced red with
Chinese/English file-publication tests. The shared classifier now excludes only
bounded extension-qualified Artifact file objects when files.publish is explicit;
ambiguous/external-destination publication and mixed deployment retain verification.
The exact original QA prompt now infers CREATE with answer/evidence/artifact required.
A deterministic full Harness check completes with a successful Artifact receipt;
without an Artifact it suspends at required_artifact. No completion gate is relaxed.

Reused the existing embedded Cloud identity rather than adding a second prompt:
public updates belong in assistant content alongside tool calls, not an extra
acknowledgement model request. Material received evidence/path changes should be
reported early; routine narration and generic waiting repetitions are discouraged.
Local identity/prompt behavior remains unchanged. This is a behavior directive,
not measured improvement or a guarantee of model compliance.

Read-only bounded exact-Run header checks for the existing image/video cases show
accepted-command to model-request Event creation intervals of 4990.1/4763.0 ms,
and model-request to first-text Event intervals of 863.8/1513.3 ms. This localizes
an important pre-model interval; it does not isolate context preparation from
durable writes/other setup. Some setup events reuse the attempt start timestamp,
so these are not commit timestamps, provider-only timing or cross-clock browser
calibration. Do not attribute the whole first-visible delay to provider thinking.

Fresh related core/AG-UI/stream/Worker regressions: 1295 passed, 3 explicit
environment skips (11.99 s). make check passes all size/Ruff/mypy/eval gates;
diff check passes. No new full workspace gate, isolated image rebuild/activation,
chart/revision browser acceptance or user service restart has occurred. Current
source differs from v8; old v8 live proofs remain historical, healthy cohort 0/100.
Next critical path: attribute pre-model preparation/write waits, rebuild the exact
source in owned QA, replay chart/revision and text-progress cases, then complete
remaining fault/recovery scenarios and the calibrated performance cohort.

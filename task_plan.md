# Planned Cloud stream/storage refactor — 2026-10-12

User-requested roadmap: `docs/CLOUD_STREAM_STORAGE_REFACTOR_SPEC.md` §15/§20.
Execution authorized 2026-10-12; baseline claimed on codex/cloud-stream-baseline-01.
Contracts, dependent implementation and rollout gates remain open.
Existing incident/search and COV-SQL-PHASE-01 work retains its scope and priority.

1. In Progress / user authorized execution: CLOUD-STREAM-BASELINE-01; measure three
   observation paths, delta transactions, authorization and real dependency costs.
   Instrumentation reviewed; frozen45/18short-window cells preserve4/6terminal
   gaps; seven profiler checks/static GO. Final3cell smoke retains1Task terminal gap.
   Next: current-harness60s/3repeat steady runs, then baseline review/integration.
2. Locked: CLOUD-STREAM-READ-01; remove fixed-frequency SQL data polling.
3. Locked: CLOUD-STREAM-CONTRACT-01; freeze v2/RPO/STOP/sequence/privacy semantics.
4. Locked: CLOUD-STREAM-WRITER-01; bounded Redis delta path after READ/CONTRACT.
5. Locked: CLOUD-STREAM-CLIENT-01; SDK/AG-UI replace/resync and old cursor/history.
6. Locked: CLOUD-STREAM-RELIABILITY-01; postcommit relay, crash/GC/byte quotas.
7. Locked: CLOUD-STREAM-ACCEPTANCE-01; native paired SQL gates, full checks,
   authorized signed Host/browser and separate rollout/rollback acceptance.

Planning SQL range for ordinary stream-heavy workload: 80%–95% total statement
reduction (remaining5%–20%); illustrative60s Run ~10,000 -> ~500–2,000.
These are assumptions/targets, not current production or measured v2 results.
Coverage's recorded6,411/15,653 costs are authority/proof/settlement dominated;
no blanket stream percentage or strict<=1000 success is inferred.
Replace the spec model with Native measured Cd/B/H/R/f before claiming budgets.
Historical planning-only boundary superseded by the user's start instruction.
Disposable native test dependencies are permitted; existing business services,
production migrations, paid-model calls, remote push and deploy remain untouched.


# Active Worker startup incident — 2026-10-12

## Follow-up WEB-SEARCH-READINESS-01

1. Done: live failure replay; current SearXNG0/CAPTCHA and Bing disabled default.
2. Done: bounded upstream controls, explicit enabled Bing-cn succeeds10/8results.
3. Done: sanitized engine codes, known execution, bounded retry rules/native hop.
4. Done: actual adapter-to-ledger operator probe; never qualify empty/error as ready.
5. Done: affected1617pass12environment-skips, static/image proof and real temporary
   v1/v2 search-to-evidence acceptance. Local integration/handoff follows.
6. Operator pending: replace search/API/Worker and run probe/new conversation.

## Follow-up WEB-EGRESS-DELIVERY-01

1. Done: reconstruct live child301ee0ef and exact citation false positive.
2. Done: exact Markdown link regression; Fake-IP-only public resolver and pinning.
3. Done: fixed operator private search endpoint, both registries/native child.
4. Done: independent SearXNG/TLS configuration, secret bootstrap and manual runbook.
5. Done: complete search URLs-to-ledger boundary and canonical fetch metadata.
6. Done: final affected1602pass12environment-skips, make check and rebuilt images.
   Source96a817bc fast-forwarded into cloud-agent-trench; primary46pass0skip.
7. Operator pending: start search, replace API/Worker, test a new signed-network
   conversation; original suspended Task is neither resubmitted nor rewritten.

1. Done: exact session/log reconstruction; readonly reuse and cold DNS reproduced.
2. Done: shared zero-SQL default reset; readonly/success/failure/reset-discard tests.
3. Done: bounded maintenance budget and discovery cooldown; cold native repair test.
4. Done: actual pooled Worker runtime binding and two durable failure finalizations.
5. Done: native boundary145pass10skip; complete native projector68pass0skip;
   critical/concurrency/tenant/Worker12pass0skip; full9041pass2685skip0fail;
   sizes/Ruff/mypy1243/eval30 GO. Late native fixture changes separately covered.
6. Images prepared: API/Worker/migrate arm64, offline imports/catalog99 and
   exact runtime hashes GO. Local code21825082 integrated into cloud-agent-trench;
   primary postmerge12pass0skip6.53s and make check GO, dirty/stash hashes unchanged.
   Operator owns restarts/replay; no flags or original task changed/resubmitted.
7. Separate open issue: strict SQL<=1000, activation/fleet/semantic acceptance.

# Active SQL root-cause repair — 2026-10-12

1. Done: reproduce exact serial long/short nine including final certification.
2. Done: trace nested authority, lifecycle, clock and connection call stacks.
3. Component implemented: bounded proof/projection/Task repair, readonly authority,
   unit/Harness replay distinction, full-record cache and physical I/O barriers.
4. Borrowed-owner publication rollback30 and static GO. Full9019pass2556skip7fail;
   corresponding paging/catalog repairs24pass, fresh full green remains OPEN.
   Private publication authority/sync no longer projects. Host exit revocation
   now refuses and is included in final measurement. No service activation.
5. Component implemented: source-qualified native pure preparation and semantic
   wrapper, per-object publication barriers and atomic receipt/finalization.
   Final-proof fresh bounded bytes/native MODEL acknowledgement9 pass. Fresh
   single-SQL readonly authority/native executor CPU hooks pass native30 and
   enhanced11; unknown/changed delegates retain full fallback. Scoped review GO.
   Superseded by step7: consolidated MODEL usage and unit settlement implemented;
   nested executor/publication/singleton-reader entries remain. Finals unchanged.
6. OPEN: strict <=1000 FAIL (6411 post-review long;15653 short), tenant fleet
   load/fairness, live E2E and independent business semantic accuracy.
7. Implemented, validation in progress (user-approved2026-10-12): bounded evidence owner
   spans fresh authority/metadata read preparation and post-upload checkpoint /
   receipt / usage / eligible unit Event settlement. Preserve durable precharge,
   external I/O guards, exact retry and independent final originals. Existing
   separate phases exceed the budget even without connection resets; do not
   spend another slice only changing SQL spelling or hiding server statements.
   Implementation lanes: storage-owned two-phase publisher with postupload
   locked usage/acceptance kernels; main-owned native invocation/executor hooks,
   Worker qualification and bounded fresh readonly metadata. Acceptance requires
   crash/replay/isolation/revocation/final-proof regressions and serial unchanged
   <=1000 SQL gates; no release approval inferred from focused tests. Subsequent
   user request authorizes local merge/manual-test image preparation only;
   restarts and business migrations remain operator actions.
   Post-review: Host I/O outside native settlement TX, typed pre-I/O fallback,
   exact staged-original crash approval/handoff and Worker recovery implemented.
   Actual Worker4 and recovery123pass10skip GO; full checkpoint9036pass2680skip
   0fail, final tiny timeout/PG-trigger fixes have separate19/12 focused GO.
   Performance still FAIL; operation entry fanout/normal wake facts not closed.
8. Next root boundary: qualified Host/outer consumer operation ownership and
   normal-wake authority facts must replace repeated guarded adapter entries.
   Retain per-I/O revocation and independent final proof; do not remove reset
   accounting, obscure server work, widen strict1000, or activate this candidate.
9. User-authorized manual-test preparation: code b40a38be locally fast-forwarded
   into cloud-agent-trench; pre-merge69/post-merge hermetic40 and primary static
   GO. Migrate/API/Worker arm64 images built and exact-source/offline-smoke checked.
   Preserve dirty SDK/AGENTS/stashes and runtime config. Strict-Pro test profile
   selection, operator migration/replacement/manual acceptance and SQL gate stay
   open; no runtime/remote activation. Commands in COV_SQL_MANUAL_TEST_20261012.md.

# Completed local integration — 2026-10-12

- User approved repairing regressions before local branch consolidation.
- Source checkpoints and complete private recovery bundles exist for both repos;
  existing stashes, ignored runtime files and independent SDK edits stay intact.
- Trench local main integration and redundant local branch cleanup are complete;
  full check/build and native70 passed. No remote action or business migration.
- Zebra integration candidate combines both histories; original65 failures fixed.
  Focused/native root-cause repairs pass; final full-source9011pass2511skip GO.
- Checkpoint routing/privacy compatibility and scalar-header cost gates pass;
  staged make check passes2920-size/1231-typed/eval30.
- Validated merge0c78c9b2 fast-forwarded into cloud-agent-trench; coverage and
  compatibility refs removed after same-HEAD detach and exact file-hash checks.
- Outcome committed and target fast-forwarded; integration checkout retained
  detached and its redundant ref removed. Final stash/backup checks are logged
  in the private recovery inventory; no runtime or remote activation occurred.
- Keep cloud-agent/main, receipts OFF and the10497 SQL performance failure open.

# Preserved progressive-delivery plan
# Active task — CLOUD-PROGRESS-OUTPUT-01 full progressive delivery (2026-10-02)

User-approved complete scope and checkbox/evidence ledger:
`docs/CLOUD_PROGRESSIVE_DELIVERY_PLAN.md`.

## Current continuation evidence (supersedes earlier snapshots below)

- Explicit full-goal continuation resumes implementation, with Luke Ding's
  existing task/branches and disjoint lanes preserved. No application restart,
  application migration, commit, push or publication is inferred.
- Latest full Zebra run: 5524 passed, 29 failed, 4 errors, 1129 skipped in
  582.31s. Native authorization errors lacked the explicit isolated scratch DSN;
  storage/API failures require focused root-cause reproduction, not weakened
  assertions. This is not a green full gate.
- Latest SDK `pnpm verify` completed successfully (package/consumer builds,
  Chromium/WebKit interactions and Next hydration). It does not prove runtime
  package identity or actual Host-to-Worker acceptance.
- Six UTC-expiry probes first failed, then the preflight success and typed-error
  exits were guarded with both monotonic and UTC expiry checks. The related
  preflight/principal/stream matrix passed 35 checks; per-frame wall-clock expiry
  is now being verified separately.
- Read-only resource authorization review found the target-resource check
  incomplete. Whole pre-Grant I/O, migration offline closure, the latest full
  gates/builds, running identity, 14 live cases and >=100 healthy timing samples
  remain required. No 100-percent claim.

## Earlier implementation snapshots

The latest plan-only audit is evidence progress: cloud GET still renews bindings,
live/optimistic state bypasses history budgets, and projection repair may roll
back a completed prefix on deadline. Goal continuation resumes the same owned
lanes; main separates authenticated renewal from observation without losing
queued authority. Native/full/build/activated gates remain required. No
application migration, restart, commit/push or publication is inferred.

Latest final-proposal continuation: resolve native PG Handoff causal allocation,
separate dependency waiting from failure budgets, propagate durable projection
problems, remove observation binding renewal without weakening queued execution
authority, and constrain real Task-store I/O. Then rerun latest full gates and
build exact artifacts; activated 14-case product/timing acceptance remains open.
Snapshot import now has 22 actual PG passes. Five disjoint lanes are resumed;
main owns shared storage/authorization/catalog and governance. No restart or
application database mutation is authorized by this continuation.

1. `in_review` — durable public output, Harness pacing and truthful fallback; full tests/check pass.
2. `verified_local` — ordered reusable React, stable mixed-content rendering, spec/quality and full verify.
3. `in_review` — paired Trench projection, facts, browser timing and intake; three navigation races fixed, fresh quality found same-key navigation recovery still broken.
4. `in_review` — timers/budgets/recovery and intra-Event cursor regressions; live faults still open.
5. `in_progress` — packages/frontend built before follow-up fixes; rebuild and user-operated activation/live gates open.
6. `pending` — requirement-by-requirement audit and baseline comparison.

2026-10-03 resumed full objective after the final system plan. Full Zebra suite:
5042 passed / 915 skipped; paired API: 794 passed; frontend: 254 passed.
Isolated real PostgreSQL Effect/consumer checks: 16 passed, scratch DB removed.
SSE spec approved (26 checks). Navigation-before-prop queue dispatch and stale
feedback/deletion now pass 51 focused checks; Effect cleanup passes 46 checks and
41 independent probes. Same-key return now passes 56 focused checks; re-review
is pending. Source/build/runtime identities differ. Tests, mock browsers, builds
and health checks do not prove live acceptance.
Now: the latest user-approved final plan resumes the complete objective. Both
production builders compose projection work; v67 is registered and its checksum
verified. Three consumer/CAS regressions now pass; joint checkpoint/Worker tests
report 77 pass and one CAS-message compatibility failure. API quality reports
60 pass; queue/native checks report 24 plus 2 pass, but v68 is not frozen or
registered and existing-Task discovery remains missing. Binding-ledger native
proof and typed pending handling remain open. Host focused API reports 188 pass;
full API still has a snapshot-completion-race test discrepancy. Main owns shared
read-only/CAS/composition/catalog/import fixes; five disjoint lanes resume.
All latest full gates, builds, activation and 14 live cases remain open.
No application migration/restart or publication; no live/100-percent claim.
Latest continuation: 26 Task/API checks pass after explicit fixture admission;
background bootstrap and typed binding continuation are wired. Five snapshot
column regressions pass; actual PG import reached 21 pass / one missing-source-
metadata RED, now repaired by explicit bounded rebuild after admission.
Independent consumer/API lanes validate wake/closure and true PG observation.
Next: fresh regressions, production composition, all full gates/builds and all
14 activated live/fault cases. No completion claim from a focused green subset.

The latest thirteen-section plan requires paged/checkpointed replay. Late
predecessor memory/title writes stay legal; freeze published Task positions.

Continue directly on user-selected `cloud-agent-trench` and Trench `main`.
Preserve dirty changes. Implementation does not authorize registry publication,
remote deployment or service restarts. Keep all unproved gates open.
# Preserved coverage-execution plan
# Active task — COV-EXEC-01 durable coverage closure (2026-10-10)

Latest MODEL settlement continuation (2026-10-11): atomic exact acknowledgement,
same-TX exit lifecycle/canonical Event revalidation and custom acknowledgement/
uncommitted-owner refusal component-implemented. Unsafe post-settlement reread
elision rejected; current original and independent final proof retained.
Native10/pure155/static1115/eval30 pass; full nine certifies16.1541s10497client/
15637server237GET/4callbacks/5batches, **SQL<=1000 FAIL**. No performance win;
bounded Worker-wide authority/adapter phase composition is still the required
root, followed by immutable retention, history/fleet/live acceptance. In Progress,
runtime receipts OFF. Details: docs/COVERAGE_MODEL_SETTLEMENT_EVIDENCE.md.

Shared read-phase continuation: common loader reuses existing optional Port;
native execution read prep/exit checks and original guarded owned-proof fallback
are distinct. Namespace equality and scoped corruption fault tests added. Exact
native clock single-guard optimization excludes injectable clocks. Final48 and
critical native85/local compatibility199 pass. Final serial strict nine certifies
17.5762s10485client15619server225GET/4callbacks/5batches, SQL<=1000 STILL FAIL.
1127lease pins/877lineage reads/1419resets remain; no latency/p95 improvement claim.
Do not merge/activate or declare whole plan finished from these component tests.

Latest exact-owner operation continuation (2026-10-11): existing work-unit owner
reentry composes MODEL budget, accepted-batch commit/certification and short Worker
local authority/tail transactions. Deadline, rollback, fresh permissions and
connection cleanup retained. Native smoke51/boundary60/corrected operation2 pass.
Nested deadline wrapper widening fixed through existing minimum ContextVar;
positive nested SQL timeout/native recovery/report/API51 pass. Expanded MODEL/
final/batch/core56 passed before that fix; failed measurements retained.
Final source nine23.4505s12180client18052server248GET/5callbacks/6batches,
certification passes, strict<=1000 SQL FAIL. No fixed-batch/p95 gain claimed.
Next root is bounded native execution-phase prepare/validation, not more socket
reuse: guarded adapter-entry fanout remains. Preserve public/post-I/O freshness,
STOP/lease/revocation and original final certification. Immutable-retention short
final proof, history/fleet load/fairness and live release gates remain OPEN.
Exact evidence: docs/COVERAGE_BATCH_TRANSACTION_EVIDENCE.md; activation OFF.

Latest execution-context continuation (2026-10-11): native batched canonical
materialization/finalization/audit, optional readonly metadata scope, paged exact
locked row/Event proof and URI index94 implemented. Native76/proof74/index-fleet37
pass, static1114/eval30/actual2610-size/diff GO. Complete final-source strict nine
16.0781s10806client16273server218GET/4callbacks/4batches, independent certification
passes but SQL<=1000 fails. This is still component delivery, not full root cure.
Next required root is Worker-wide phase authority/transaction composition:
991 lineage reads,1234 lease pins and1605 connection resets remain. Preserve
fresh post-lock snapshots, STOP/revocation, side-effect guards and tenant cleanup;
do not disable DISCARD ALL, use TTL permissions, or hide handoff/reset SQL.
Immutable-retention-backed final proof outside locks, history/fleet load/fairness,
live Trench and release acceptance remain open. No activation/business restart.

Latest governed Artifact continuation (2026-10-11): batch reserve/receipt,
physical I/O outside transactions and atomic exact finalization are implemented.
Core observations/results batch with immediate durable MODEL checkpoint/charge;
fault/replacement replay and concurrent reservation rollback verified. Native124,
MODEL23, buffered-replay2 pass; pure88 pass8 skips/static1110/eval30/actual2604 GO.
Final-source strict nine19.6260s11772client17472server225GET/4callbacks/5batches:
<=1000 SQL FAIL, no latency gain. Do not stop at these partial savings: next root
is bulk governed reads/current operation authority plus native batched canonical
Event/finalization/audit, then immutable-retention short final proof, history/
fleet quota/fairness/native load/live acceptance. Full task In Progress, runtime
receipts OFF. Evidence document retains all measurements and corrected failures.

Latest sealed membership follow-up (2026-10-11): migration93 exact ordered unit
and record metadata roots, unique Event-backed settlement, selected bounded record
reads, mutation/legacy fallback and fleet qualification component-implemented.
Current native44 and expanded19 passed, pure65 passed20 native skips, static1108/
eval30/actual2600 size GO. Final certification original corruption gate passed.
Serial nine18.2650s12916client19132server218GET/four wakes/four qualified/root4/4.
First current21.3039s14371client/five wakes retained. Strict <=1000 SQL gate FAIL.
Exclusive meters show read/publication5019 plus outer handoff/authority3545,
commit434. No whole-system improvement claim. Full plan NOT complete.
Next: bounded governed Artifact lifecycle reserve/settle batches with crash and
charge safety, then immutable-retention short final transactions and tenant/fleet
capacity/load/live acceptance. Executor initialization/final/recovery still full;
selected commit complexity is not whole-execution constant cost. No activation.

Latest batch follow-up (2026-10-11): bounded exact acceptance, operation-pinned
pure proof, owner-TX borrowing, verified reader, native volume91/delta indexes92,
fleet qualification and strict client/server SQL measurement component-verified.
Nine certified18.0889s12912client18823server218GET/four qualified batches;
**strict <=1000 SQL gate FAIL**. Native MODEL30/readiness55/root-boundaries10,
pure143 and static gates pass. Full plan remains In Progress, not optimized away.
Next required root mechanisms: sealed exact membership/delta state; batch evidence
lifecycle with reserve/settle/crash safety; immutable-retention-backed short final
certification; shared tenant quotas/backpressure/fairness; live load/Trench closure.
Exact results and strict reproduction: docs/COVERAGE_BATCH_TRANSACTION_EVIDENCE.md.
Runtime receipt activation OFF; no service restart/business migration/merge/push.

v90 authority follow-up is component-implemented, NOT whole-system complete.
Final serial nine30.5219s/20403execute/287GET;7 service binding reads but20 total
full native validations (7 service/7 dispatch/6 cold new-owner preparations).
No per-Artifact full Task lineage replay on the versioned normal path. See
docs/COVERAGE_EXECUTION_CONTEXT_EVIDENCE.md for exact guarantees and open work.

v89 native Task-origin follow-up claimed/implemented2026-10-11. Normal strict
Task descriptor/continuity reads are bounded while latest binding remains fresh;
legacy, recovery, initialization and independent certification use full proof.
Native MODEL54/Worker-fleet82/root8/renewal1 and serial nine passed. This Task
origin slice is component-verified, not system performance closure:56.0948s,
49137execute,100 fewer than v88 but no latency gain. Next shared root remains
per-Artifact fresh Task/Host lineage fanout; no TTL or cross-phase permission cache.
See docs/COVERAGE_TASK_ADMISSION_EVIDENCE.md. No runtime activation.

Branch: `codex/cov-exec-01`; owner Luke Ding/Codex; paths: `docs/AGENT_TASKS.md`.
Detailed acceptance contract: `docs/superpowers/plans/2026-10-08-coverage-closure.md`.

Root continuation work (2026-10-11): v87 mutation revisions and normal receipt
reads are component-verified. Revision-bound mint now removes the redundant
full-history fingerprint after exact native commit validation; legacy fallback
is retained. Native15 and serial nine certified50.4048s49375execute passed;
this mint slice is component-verified, not system performance closure.
Next: seal incremental MODEL budget facts
with atomic native mutation rules, not scalar revision arithmetic; then versioned
fresh authority, short transactions and tenant/fleet acceptance. Production
receipts remain OFF. This does not mark the full root plan complete.

v88 incremental facts follow-up: new runs have exact native transition-maintained
budget/source/witness summaries. Final-certification normal index has one scoped
proof read; eager, legacy, invalidated roots and full certification retain native
history proof. Legacy requalification and Task/Host version roots remain open.
Native5/pure105 and static gates passed; final combined MODEL48 and Worker/fleet82
passed with zero skips. Serial nine certified52.1281s/49237execute passed;
138 fewer executes than prior same-callback run, no latency gain. This slice is
component-verified, not whole-system performance or live acceptance. Next shared
root is versioned Task/Host authority and Artifact read fanout, not caller caches.

1. `component_verified` — durable snapshot adapter, resumable executor,
   exact Effect invocation and cross-process Artifact publication.
2. `component_verified` — immutable single-shot MODEL request, full original
   completion checkpoint, bounded semantic derivation and reserve/replay
   accounting. PostgreSQL callback composition has separate SPEC/QUALITY GO.
3. `component_verified` — verify each accepted MODEL unit against its original
   response and canonical observation on commit, retry, rebuild and certificate
   issue/read. Raw typed inputs must be checked before lossy normalization.
4. `component_verified` — bounded multipart same-Session Worker recovery,
   atomic admission and compatible process routing have separate SPEC/QUALITY
   GO. Final native matrix 106/zero skips includes resumed certification.
   Heavy recovery preparation is outside lifecycle locks; final exact checks
   are deadline-bounded. Original authority and unknown-call refusal remain.
5. `component_verified` — API safety preflight approved; durable absolute events and
   paired Trench counters/reconnect/terminal state passed SPEC and QUALITY.
   Report GET/HEAD checks fresh authority and original proof: independent
   SPEC/QUALITY GO, 41 native/42 pure checks. Trench: 37 backend/225 frontend
   checks and production build. Live joint acceptance remains.
6. `component_verified` — proof reads/history and acceptance tools; pure 33;
   default 6,688/1,523; native 10/0; real-service synthetic load report recorded.
   Active-lease preflight: nine144.69s; diagnostic60s99.53s (worse, unchanged SQL).
   See COVERAGE_WORK_SLICE_EVIDENCE.md; normal continuation/SLO/live remain open.

Evidence: component tests do not prove semantics or live scale; no activation,
merge or deployment. Preserve unrelated dirty work.

## Current authority/transaction root follow-up (2026-10-11)

1. Component-verified: native lineage revision plus fresh scoped Task/lease/binding
   checks, shared Worker guard and skipping unchanged projection tail reads.
   Normal same-wake continuation reuses its exact context; new-owner handoff and
   exceptional recovery prepare independent authority. Missing strict consumer
   exits before proof I/O, without replacing final native atomic admission.
2. Component-verified: callback-local exact immutable bytes (256 entries/32MiB),
   phase-pinned pure reads and short database read work units. Live Host/current
   authority and independent final physical certification remain; all existing
   final proof external I/O has NOT been moved out of lock windows.
3. Component validation: native mutation/lease-wait/revocation/isolation and
   workload structural gates. Remaining: overall execute/rows/lock budgets,
   per-Artifact fanout, MODEL membership/volume roots, native multi-tenant growth
   load and p95, fleet fairness, coordinated rollout/live progressive output.
   20403 executes for tiny nine data remains above the intended system goal.

# Previous task — HOST-MEDIA-IMPORT-01 governed historical media (2026-09-29)

Branch: `cloud-agent-trench`; working directly in the user's requested checkout.

1. `completed` — trace the response, Host Tool, Artifact, AG-UI and React
   rendering path and isolate the missing authority transition.
2. `completed` — add an entitled Trench historical image/video selector that
   returns a narrow import envelope rather than exposing presentation authority.
3. `completed` — validate, bounded-download and publish Host media through the
   existing Zebra Artifact coordinator; return a current-Session
   `artifact://` URI.
4. `completed` — retain existing `content.present` and ordered AG-UI content
   parts; add focused Host/Worker/Artifact regressions.
5. `completed` — run focused and full Zebra/Trench gates and prove one real
   historical image in the browser.

Key decision: rich rendering stays a native Zebra capability. Trench only
selects media within its authority scope; it does not bypass Artifact authority
or duplicate the renderer. Image browser acceptance is complete. Video shares
the same MIME-bounded path and deterministic coverage but has no separate real
source browser proof in this slice. No commit, push, merge or deployment was
performed.

# Previous task — REACT-PRESENT-01 governed rich presentation (2026-09-28)

Branch: `codex/rich-presentation-01`; isolated worktree:
`/Users/lukeding/.codex/worktrees/rich-presentation-01/zebra-agent`.

1. `completed` — add a bounded `content.present` typed tool that validates
   current-Session Artifact references and explicit image/video/chart/file
   presentation metadata.
2. `completed` — register the tool in eligible profiles without changing model or
   reasoning settings; keep it unavailable when Artifact reads are unavailable.
3. `completed` — project ordered V2 content parts over replayable AG-UI custom
   events while retaining legacy `files.publish` MIME inference.
4. `completed` — add deterministic tool, runtime and AG-UI regressions for
   authorization, schemas, ordering and graceful failures.
5. `completed_local` — run focused tests and repository gates; record provider-generation,
   package publication, paired Host and deployment boundaries separately.

Key decisions: the model chooses a typed presentation intent but never supplies
raw HTML or remote URLs; code validates every opaque Artifact reference against
the current Session; standard media stays on the native Content Part path while
interactive MCP Apps remain a separate capability.

Local closure: focused Python `77/77`; `make check` passes file size, Ruff,
strict Mypy over `985` source files and deterministic eval `30/30`; `make test`
passes `4711`, with `901` environment-gated skips. Existing React image/video/
file and optional chart renderers build and pass `10/10` focused tests on Node
24. The initial pytest collection failure was only an unsynchronized isolated
worktree and passed after `make sync`. The first pnpm install returned the
repository's ignored-build-script policy signal; the supported `--ignore-scripts`
install, package builds and tests pass. Merge, npm publication, paired Host
packaging, provider-specific generation and deployment remain separate gates.

# Prior task — CTX-OBS-02 six-category context observability (2026-09-27)

Branch: `codex/context-breakdown-v2`; isolated worktree:
`/Users/lukeding/.codex/worktrees/context-breakdown-v2/zebra-agent`.

1. `completed` — add typed message/tool provenance and a deterministic V2
   token-breakdown model without changing model payloads or limits.
2. `completed` — dual-write V1/V2 usage into durable model request/response
   events, API summaries and bounded AG-UI projections.
3. `completed` — make the shared React Composer render dynamic categories,
   measurement basis and historical fallback accessibly and responsively.
4. `completed` — update Trench's Host adapter, Chinese labels and packed package
   without disturbing its current full-content/media work.
5. `completed_local` — run focused, repository, SDK, Host build and browser/runtime
   acceptance; record merge, deployment and live-call boundaries separately.

Key decisions: the provider input total is authoritative; category values are
deterministically reconciled to that total; old events remain readable; no
historical categories or prompt contents are fabricated.

Errors encountered:

- The first isolated-worktree pytest collection could not import workspace
  packages because `make sync` had not yet run; synchronize the worktree before
  repeating the focused gate. Ruff also identified and then corrected one
  import-order issue in `task_model_usage.py`.
- The first SDK build used the host's global legacy TSDX because the isolated
  worktree had no Node modules; install the frozen SDK workspace first.
- The first complete SDK verification ran under unsupported Node 20 and failed
  an unrelated chart DOM test; the required Node 24 runtime passes all 42 SDK
  tests, package audit, React 18/19 Vite/Next consumers and browser matrices.
- Local implementation and paired Host acceptance are closed. Merge, package
  publication, deployment and one real-provider production Turn are explicitly
  not inferred from local tests.

# Prior task — REACT-MEDIA-01 durable rich-content surface (2026-09-27)

Branch: `codex/react-media-content-01`; isolated worktree:
`/Users/lukeding/.codex/worktrees/media-content-blocks/zebra-agent`.

1. `completed` — freeze the typed content-part, Artifact preview, AG-UI custom
   event and sandbox security contracts in ADR-CLIENT-02 while preserving legacy
   string messages.
2. `completed` — implement host-neutral image, video, file and fallback renderers,
   renderer registration, responsive styles, accessibility and deterministic
   React tests.
3. `completed` — add the optional Vega-Lite chart package with schema/version and
   resource guards, lazy loading, cleanup, data-table/static fallbacks and real
   package-consumer checks.
4. `completed` — project published media Artifacts over replayable AG-UI events and
   expose authorized inline preview/HEAD/Range responses without putting binary
   data in durable events.
5. `completed` — add the sandboxed MCP Apps host boundary with explicit capability
   negotiation, origin/CSP controls, postMessage validation and static fallback.
6. `completed` — consume packed packages in Trench, map existing file deliveries to
   typed parts, add BFF preview proxy and verify image/video/chart rendering in a
   production browser build.
7. `completed` — run focused, SDK package, React 18/19 Vite/Next, browser, Python
   repository and paired Trench gates; review the implementation against every
   acceptance item and record any external publication/deployment boundary.

Detailed decision:
`docs/ADR-CLIENT-02_Durable多媒体内容面.md`.

# Prior task — CLOUD-MEMORY-AUTONOMY-01 natural cross-session Memory (2026-09-27)

1. `completed` — classify source-bound natural self-statements with a deterministic,
   credential-safe policy.
2. `completed` — auto-confirm stable preferences while keeping background, goals,
   interests and volatile portfolio facts behind review.
3. `completed` — preserve PostgreSQL governed Memory as authority and identify
   dynamic positions by canonical subject without adding a parallel store.
4. `completed` — supersede only an older position for the same asset and prove
   cross-language relevant recall plus profile projection.
5. `completed` — finish repository gates and record final evidence. Commit,
   push, deployment and production acceptance remain separate actions.

# Prior task — REACT-CONVERSATION-02 ZCode-style complete conversation surface (2026-09-26)

1. `completed` — define host-neutral Turn/work-segment contracts and a stable
   compatibility projection without changing runtime authority.
2. `completed` — implement the conversation timeline, per-Turn work collapse,
   live-tail rendering and sticky Composer layout in `@zebra-agent/react`.
3. `completed` — migrate the Trench strategy Host from `Bubble.List` and embedded
   progress rendering to the packaged Zebra timeline through a Host adapter.
4. `completed` — add deterministic interaction, ordering, collapse, scroll and
   empty-to-active transition regressions.
5. `completed` — run SDK package/consumer gates and Trench frontend/browser gates,
   then record evidence and remaining release boundaries.
6. `in_progress` — align the surrounding conversation shell: responsive active
   widths, centered draft composition, long user-input folding, icon-only
   back-to-bottom control and Composer focus/hover treatment.

Evidence: SDK `verify` passes 26 deterministic tests, exact package audit,
React 18/19 Vite/Next consumers, Chromium/WebKit interaction checks and Next
hydration. Zebra `make check` passes file size, Ruff, strict Mypy over 978
sources and eval `30/30`. Trench `make check` passes API `139`, pipeline `74`,
ToC `109`, lint with three pre-existing image warnings, production builds,
migration dry-run and diff gate; its production Chromium Host acceptance also
passes. Zebra's unrelated full Python suite remains blocked at collection by
the base branch's missing committed `_quality_revision_feedback` implementation;
that source path is outside this task and modified only in the user's original
dirty checkout. Running the remaining suite explicitly passes `4616` tests with
`899` environment-gated skips.

Detailed plan:
`docs/Zebra_ZCode式聊天时间线实施方案_v1.0.md`.

# Prior task — CLOUD-PLAN-ACCEPTANCE-02 strict 100-point closure (2026-09-26)

1. `completed` — close SDK supply-chain gaps: pinned toolchain, package audit,
   tree-shaking proof and CI integration.
2. `completed` — add real-browser React and Trench acceptance for responsive,
   IME, attachment, session-transition, scroll, collapse and recovery flows.
3. `completed` — materialize executable fixtures, a real Zebra runner and
   independent verifiers; complete the current-version 180-attempt matrix.
4. `completed_local` — execute real-model Memory/result matrices and cache
   boundary reports; recovery/compaction cache percentages remain unmeasured.
5. `blocked_external` — local `runsc` is absent and the remote host rejects the
   available SSH credential, so one-digest gVisor/canary/rollback proof cannot run.
6. `completed_local` — rerun Zebra/Trench/SDK/browser/PostgreSQL gates and report
   implementation, strict acceptance, real-task and production evidence separately.

Detailed plan:
`docs/Zebra_Cloud_Agent_100分严格验收闭环计划_v1.0.md`.

Errors encountered:

- Ruby 2.6 `YAML.load_file(..., aliases: true)` rejected the unsupported keyword;
  use the compatible `YAML.load_file(path)` parser for workflow syntax checks.
- The first browser-matrix preparation used a repository-root path while the
  command already ran inside `sdks/typescript`; use SDK-relative paths there.
- The first Chromium focus assertion clicked an external lifecycle-control
  button, which correctly moved browser focus. Advance lifecycle state through
  a programmatic fixture action after attachment selection instead.
- Vite browser acceptance passed, but the first Next server command forwarded
  an extra `--` and never bound. Invoke `pnpm exec next start -H/-p` directly
  and retain child output for readiness diagnostics.
- The first Trench browser assertion assumed a fixed conversation id, but the
  product intentionally creates a random durable id. Assert the id captured
  from the real create-conversation request instead.
- The first live-eval reporting shell used `status`, which is a read-only zsh
  parameter. Use a task-specific exit variable for report commands.
- The 12-case real-model pilot exposed three truthful delivery-gate blocks:
  file and package deliverables retain publication requirements, while local
  memory-recovery fixtures now require an explicit write/read-back proof so
  they do not accidentally enter the artifact-publication path.
- The first browser scroll assertion sampled immediately after requesting
  smooth scrolling. Wait for the browser to settle at the bottom instead of
  changing production behavior to make an asynchronous animation synchronous.
- The first terminal-collapse and touch-target browser assertions sampled the
  React effect synchronously and included fixture-only navigation controls.
  Wait for the observable collapsed state and scope target sizing to the
  published `.zebra-agent-chat` surface.
- Failed commands originally exposed only `status=failed` to the model. Project
  bounded `stderr`, `exit_code`, timeout and failure reason so retries can correct
  the cause instead of repeating blind calls.
- Standard Git diff headers were validated after stripping `a/` and `b/` but the
  unnormalized patch was applied with `-p0`. Normalize once before both validation
  and execution, and reject hunk headers whose declared line counts do not match.
- The local policy rejected an absolute `command.run.cwd` even when it was the
  exact authorized workspace. Supply the workspace root to policy, allow only
  contained absolute cwd values, and retain the tool-level containment check.
- English `Create ... scheduled job` was classified as CREATE and invented an
  Artifact obligation. Scheduling is an OPERATE task and still requires fresh
  postcondition verification, not an unrelated file publication.

# Prior task — CLOUD-PLAN-CLOSURE-01 end-to-end plan closure (2026-09-26)

1. `completed` — Trench consumes the packaged React surface from reproducible vendored tarballs; the duplicate Composer implementation and source alias are gone.
2. `completed_implementation` — the fixed corpus contains 60 cases / 180 planned attempts and an independently verified runner/report path; the real campaign remains `0/180` until isolated fixtures, authority-backed verifiers and credentials are supplied.
3. `completed` — real package tarballs pass React 18 and 19 in Vite plus Next SSR/RSC consumers.
4. `partially_completed` — real PostgreSQL fault, Memory and application Compose gates pass; the no-gVisor composition tier passes fail-closed, while the seven gVisor execution scenarios and remote canary/rollback remain externally blocked.
5. `completed` — Zebra and Trench focused/full gates are reconciled, with implementation, local acceptance, real-task and production evidence reported separately.

# Prior task — CLOUD-RELIABILITY-02 reliability and release closure (2026-09-26)

1. `completed` — fail closed on missing/duplicate/out-of-order durable Task events and prove exact cursor recovery.
2. `completed` — replace an invalid persisted browser cursor with the authoritative Task tail, refresh pending effects, and stop reconnect loops when login/session authority expires.
3. `completed` — freeze exact source-matching React package versions with Zebra/Trench commits, image digests, migrations, protocols and configuration.
4. `completed` — bind the remaining reliability scenarios to candidate/rehearsal evidence without converting unavailable production evidence into PASS.
5. `completed` — run focused SDK/API/release suites and full repository gates, then report local, acceptance and production completion separately.

# Prior task — MEMORY-CONTEXT-02 memory, compaction and cache closure (2026-09-22)

1. `completed` — preserve completed actions, pending actions, rejected approaches and permission boundaries in durable Context Capsules and all recovery materialization paths.
2. `completed` — prove synonym recall, preference reversal, temporary-preference rejection, cross-project isolation, deletion suppression and irrelevant-memory bounds.
3. `completed` — segment cache evidence into cold start, warm loop, recovery, compaction and child wakeup without changing prompts, model or reasoning settings.
4. `completed` — run focused suites, full repository gates and record evidence-backed implementation coverage.

# Prior task — AGENT-QUALITY-04 result-level acceptance (2026-09-22)

1. `completed` — strengthen the typed acceptance contract with explicit response bounds and Host-verifiable goal terms without turning keyword classification into authority.
2. `completed` — make task-type outcomes require matching result evidence rather than treating any mutation or HTTP/tool success as completion.
3. `completed` — preserve recoverable parameter/read failures for correction while stopping evidence-free repeated actions and reconciling unknown writes.
4. `completed` — add deterministic result-level regressions for answer, research, change, create and operate tasks.
5. `completed` — rerun the failed real-model constraint smoke, focused suites and full repository gates, then record honest evidence.

# Prior task — AGENT-LIVE-EVAL-01 representative real-task evaluation (2026-09-22)

1. `completed` — define a live-eval case and attempt contract that cannot mix deterministic replay with real-model evidence.
2. `completed` — add 12 representative tasks across answer, research, code, file, operation and memory/recovery, split into development and holdout sets.
3. `completed` — aggregate first/final success, intervention, false-completion, recovery, citation, repeated-tool, latency and cost metrics only when 3 repetitions are complete.
4. `completed` — add a safe CLI report entry and deterministic contract tests.
5. `completed` — run the available real-model smoke, repository gates and record honest executed versus pending evidence.

# Prior task — REACT-UX-01 React task lifecycle experience (2026-09-22)

1. `completed` — define one typed public lifecycle contract for local submit, server acceptance, queue, execution, user wait, reconciliation, disconnect and distinct terminal outcomes.
2. `completed` — render lifecycle and recovery controls without exposing private reasoning or raw errors.
3. `completed` — prove reconnect, resume and retry remain distinct and unsafe unknown writes cannot be blindly replayed.
4. `completed` — prove new-session to active-chat rerenders retain the same controlled Composer node, input, attachments and focus boundary.
5. `completed` — run package, external-consumer and repository gates; document the S2 evidence and remaining Host-adapter boundary.

# Prior task — REACT-UI-01 React Agent composer foundation (2026-09-22)

1. `completed` — trace the Trench composer and identify its reusable behavior and Host-only dependencies.
2. `completed` — implement the finite public `AgentChat`, Composer, message, activity, approval, clarification, Artifact and Memory setting surfaces with explicit CSS variables.
3. `completed` — add interaction regressions for IME, submit/pause/continue, activity collapse, interrupts, resources, attachment removal and disabled state.
4. `completed` — build, pack and verify ESM/CJS/types/styles in isolated Vite and Next React consumers.
5. `completed` — review package API, run SDK and repository gates, and establish the stable Host-adapter boundary for later Trench migration.

# Prior task — REACT-PKG-01 TSDX package and consumer boundary (2026-09-21)

1. `completed` — save the complete Cloud Agent + React optimization plan under `docs/` and claim the task with explicit owned paths.
2. `completed` — validate TSDX 2.x against the existing pnpm workspace and correct the four SDK package boundaries.
3. `completed` — build and pack every SDK package; inspect exports, declarations and package contents.
4. `completed` — install the real tarballs into isolated Vite and Next.js React consumers and run production builds without source aliases.
5. `completed` — run SDK tests/type checks, document evidence and review the slice before component migration.

# Prior task — CLOUD-MEMORY-CLOSURE-01 PostgreSQL governed-Memory closure (2026-09-21)

Branch: `codex/cloud-memory-closure-01`, based on
`cloud-agent-trench@3fe23bbd`.

1. `completed` — bind Memory writes and reads to stable frozen Host principal
   and workspace scope without weakening Definition scope.
2. `completed` — add deterministic Chinese/English remember, update and forget
   directives with secret rejection and governed lifecycle mutations.
3. `completed` — add bounded Chinese-capable PostgreSQL recall and durable
   selected-Memory evidence.
4. `completed` — persist finalization outcomes for zero-candidate, created,
   updated, deleted and failed processing, and expose runtime status through the
   existing memory API surface.
5. `completed` — run focused, PostgreSQL, full repository and real composed
   cross-session acceptance; record evidence and implementation percentage.

Model and reasoning-effort settings remain unchanged. Redis Agent Memory stays
disabled while PostgreSQL remains the authoritative store.

Review follow-up closed five reproduced defects: Host visibility parity, safe
forget semantics, source-specific expiry, session metric scope parity, and older
relevant PostgreSQL recall. A real PostgreSQL acceptance now proves a confirmed
USER Memory written by one Session is automatically recalled by a later Session.
The second review closed four deeper boundary defects: every session Memory read
now freezes the complete Host workspace/principal/tenant/Definition scope and
fails closed without one principal; automatic expiry requires reconstructable
tool-event provenance; and PostgreSQL applies relevance before its bounded row
cutoff while retaining a stable preference/project-rule lane.

## Prior task — CLOUD-AGENT-PARITY-01 General capability and quality closure (2026-09-20)

Branch: `cloud-agent-trench`; Trench consumer:
`/Users/lukeding/Desktop/playground/2026/product/Trench`.

1. `completed` — remove Host-specific assistant identity/format constraints from generic modes and add typed task acceptance contracts.
2. `completed` — make completion, verification, retry and continuation state task-aware and durable.
3. `completed` — improve tool efficiency, evidence/claim quality and adaptive final-answer shaping.
4. `completed` — harden the reusable Agent UI boundary and process rendering for future npm extraction.
5. `completed` — add a representative multi-category quality suite and run focused/full/cross-repository acceptance.

Model and reasoning-effort settings remain unchanged. This task improves the
Cloud Agent runtime and reusable Host boundary; Trench is only the first Host.

Closure evidence: Zebra `make check` and `make test` pass (`4577 passed, 892
skipped`, deterministic eval `30/30`); TypeScript SDK check and `15/15` tests
pass. Trench complete gates pass (`136` API/model tests, `74` pipeline tests,
`91` ToC tests, lint, both production builds, migrations and diff check).
Logged-in browser conversation `conv_1789910351988_0397a0` completed with one
committed answer, one model call, no tools, no failed event and no irrelevant
Skill binding. Local Zebra API/Worker images were rebuilt and are healthy.

## Prior task — CLOUD-CAPABILITY-UI-01 Host-selectable agent modes (2026-09-20)

Branch: `cloud-agent-trench`; Trench consumer:
`/Users/lukeding/Desktop/playground/2026/product/Trench`.

1. `completed` — define a server-owned research/general/coding capability contract.
2. `completed` — bind capability changes to successor Zebra Tasks and durable Turns.
3. `completed` — expose the contract through the reusable composer boundary.
4. `completed` — verify API, runtime, frontend and cross-repository quality gates.

The host selects a product-level mode; clients never submit raw Tool, Policy,
network or budget profiles. Model and reasoning-effort behavior remains unchanged.

Follow-up closure: exploration, research and expert conversations again omit
model/tool call ceilings, as required by `CTX-SEG-03` and ADR-013. Explicit
administrative, scheduled and evaluation budgets remain strict, but Zebra now
validates them as positive integers without a magic maximum. Generation
`trench-native-v15` migrates existing conversations away from the regressed
snapshots. Focused Zebra API tests pass `22/22`; Trench runtime tests pass
`35/35`, and both complete repository gates pass. Existing browser conversation
`conv_1789911230325_53c036` migrated to v15 and completed; its successor Task
stores both model/tool call budgets as `null`.

## Prior task — AGENT-QUALITY-03 Real Answer Quality Closure (2026-09-20)

Branch: `cloud-agent-trench`; Trench consumer:
`/Users/lukeding/Desktop/playground/2026/product/Trench`.

1. `completed` — preserve structured failed Tool status through AG-UI and Trench.
2. `completed` — hide Host Tools that the current Grant cannot invoke.
3. `completed` — replace tool-count evidence with a durable, continuation-safe evidence ledger.
4. `completed` — require collected, matching citations for freshness-sensitive answers.
5. `completed` — reduce broad Trench retrieval churn and verify focused regressions.
6. `completed` — rebuild the local runtime and run real-model/API/browser acceptance.
7. `completed` — run complete Zebra and affected Trench quality gates and record evidence.

Model and reasoning-effort settings remain unchanged.

Closure evidence: Zebra `make test` passes `4573 passed, 892 skipped`; `make
check` passes the file-size gate, Ruff, strict Mypy over 968 source files and
deterministic Harness eval 10/10. Trench `make check` passes 129 Python tests,
74 cleaning tests, 89 ToC tests, lint, production builds, migration checks and
the diff gate. Real browser conversation `conv_1789903152657_6847d3` completed
with first public activity in 1.29 seconds, 6 model calls, 14 successful tools,
7 evidence-backed findings and 21 exact source links; reload restored the same
terminal timeline and committed answer.

## Prior task — AGENT-QUALITY-01 Evidence Closure And Skill-Guided Deliverables (2026-09-16)

## Current task — AGENT-QUALITY-02 Quality Loop Completion (2026-09-16)

Branch: `cloud-agent-trench`; Trench consumer: `/Users/lukeding/Desktop/playground/2026/product/Trench`.

1. `completed` — enforce selected Skill reads before final answers.
2. `completed` — bind freshness verification to resource evidence with opaque fallback.
3. `completed` — retain safe Host business-error diagnostics.
4. `completed` — add deterministic substantive-answer revision/warning gates.
5. `completed` — carry selected Skill components into bounded research children.
6. `completed` — validate and refresh Trench native source mutations.
7. `completed` — run static/focused/full checks and record remaining baseline failures.
8. `completed` — rebuild the live acceptance stack and verify service health; the
   source mutation path is covered by the focused Trench contract suite.

Branch: `cloud-agent-trench` (explicit user-requested in-place integration)
Trench consumer: `/Users/lukeding/Desktop/playground/2026/product/Trench`

1. `completed` — bind selected Skills to the coordinator prompt and tool profile.
2. `completed` — add declared mutation/fresh-read evidence tracking and bounded
   completion verification.
3. `completed` — increase the bounded Cloud conversation history budget.
4. `completed` — project user subscription truth in Trench source reads.
5. `completed` — separate tool-loop progress prose from the final assistant answer.
6. `completed` — run focused and affected validation, then close durable records.

## Prior task — CTX-SEG-03 Host Budget Defaults And Truthful Suspension (2026-09-16)

Branch: `cloud-agent-trench` (explicit user-requested in-place integration)
Trench consumer: `/Users/lukeding/Desktop/playground/2026/product/Trench`

1. `completed` — reproduce the incident from durable events and separate model-call
   exhaustion from tool-call exhaustion.
2. `completed` — remove Trench's implicit `6/16` limits from normal conversations.
3. `completed` — let the final permitted model request retain tool capability.
4. `completed` — project explicit budget suspension as a terminal AG-UI interrupt.
5. `completed` — run focused and affected repository validation, then close docs.

## Prior task — CLOUD-USER-SCHEDULE-DEPLOY-01 (2026-09-15)

Branch: `cloud-agent-trench` (explicit user-requested in-place integration)
Trench consumer: `/Users/lukeding/Desktop/playground/2026/product/Trench`

1. `completed` — compose the independent API, Worker and Scheduler processes.
2. `completed` — expose user-scoped schedule CRUD and controls in Trench ToC.
3. `completed` — bind host workspace references and enabled Skills at the BFF.
4. `completed` — dispatch schedules through the standard RUN-command path.
5. `completed` — freeze one Skill and one MCP in the scheduled Turn snapshot.
6. `completed` — reconcile terminal Task state into durable Firing history.
7. `completed` — prove logged-in browser run-now and visible completed history.
8. `completed` — pass focused, PostgreSQL, type/lint/eval and frontend build gates.
9. `completed` — update durable project records for review handoff.

Implementation plan: `docs/Cloud_Agent用户级定时任务技术方案_v1.0.md`
(accepted and present in this worktree).

## Current task — Durable interactive execution and reconnect recovery (2026-09-21)

1. `completed` — preserve truthful non-budget suspension reasons.
2. `completed` — prove an unbudgeted Harness run exceeds the retired 24/64 ceilings.
3. `completed` — reconnect Trench after AG-UI idle timeout from the durable cursor.
4. `completed` — run focused Zebra and Trench regressions.
5. `completed` — run both repository quality gates and record durable evidence.
6. `completed` — verify the local composed runtime and browser path without changing
   model or reasoning settings.

## Prior task — RabbitMQ reliability (2026-09-05)

Approved isolated worktrees: `rabbitmq-reliability/zebra-agent` and
`rabbitmq-reliability/Trench`; original services remain unchanged.

1. Completed: stages 0/1 local contracts and broker evidence.
2. Completed: Stage 2 Trench Turn, 10/10 isolated acceptance.
3. Completed: Stage 3 Zebra command, 6/6 isolated acceptance; actual product,
   browser/file, broker restart, fallback/restore and process-fault evidence in
   `docs/rabbitmq_stage3_composition.md`.
4. Review: `RABBIT-SOURCE-SCOPE-01`, explicit source bindings and operator
   CAS backfill. Private/credential execution remains fail-closed.
5. Review: `RABBIT-SOURCE-SCHEDULE-01`, source-wide scheduling/fencing and
   atomic FetchCommand/source-Outbox admission; slice 6/6 and Stage 4 group 2
   accepted.
6. Review: `RABBIT-SOURCE-DELIVERY-01`, dedicated source relay/Inbox,
   bounded consumer/recovery/quarantine and opt-in restricted topology; Stage 4
   group 3 accepted. Stage 4 is now 2/7.
7. Review: `RABBIT-SOURCE-CUTOVER-01`, every old business fetch entry point now
   uses one default-off authority without double scheduling; Stage 4 group 4
   accepted. Stage 4 is now 3/7.
8. Review: `RABBIT-SOURCE-RESULT-01`, durable fenced fetch-result
   classification, safe diagnostics and bounded retry/recovery; Stage 4 group 5
   accepted. Stage 4 is now 4/7.
9. Review: `RABBIT-SOURCE-E2E-01`, real fixture HTTP fetch through
   PostgreSQL/Redis/RabbitMQ into authenticated history/timeline, including
   duplicate, Redis-rejection and cross-user isolation evidence; Stage 4 group 6
   accepted. Stage 4 is now 5/7.
10. Review: `RABBIT-SOURCE-COMPOSE-01`, default-off process composition,
    explicit cutover, actual-process fallback/restore/rollback and terminal
    database evidence; Stage 4 group 7 accepted. Stage 4 is now 6/7.
11. Review: `RABBIT-SOURCE-CREDENTIAL-REF-01`, existing credential identity,
    enabled state and platform validation with principal association and
    fail-closed drift; Stage 4 group 1 accepted. Stage 4 is now 7/7.
12. Review: `RABBIT-ROLLOUT-CAPACITY-01`, atomic admission/backlog bounds and
    frozen active-scope fair pickup accepted; Stage 5 is 1/8 (12.5%).
13. Review: Stage 5 group 2, default-off scope allowlist, physically separate
    side-effect-free bounded shadow lane and exact message/digest reconciliation;
    Stage 5 is 2/8 (25%).

Use `docs/AGENT_TASKS.md` for ownership and `docs/rabbitmq_completion.md` for
fixed acceptance counts. Implementation, isolated acceptance, commit/merge and
production activation remain separate. No commit or activation requested here.

## Prior task record — TRN-LINK (2026-08-26)

1. `completed` - P0 契约核对：7 项契合 / 5 项差距冻结
   （`docs/Zebra_Trench对接差距清单.md`）。
2. `completed` - G1 Host Grant Broker（`apps/host_grant_broker`）：
   RS256 签发（claim 集与 `HostSessionGrant` 精确一致，thread/run 经
   resource_refs 绑定）、JWKS 端点、Trench 会话验证（Cookie 只转发到
   `/api/trench-ai/me`）；8 个测试含真实验证器闭环。
3. `completed` - G2 Host 注册脚本（`scripts/register_trench_host.py`），
   已对真实 PostgreSQL host authority schema 冒烟。
4. `completed` - G3/G4 验收 operator sidecar（业务快照 + Worker 重启
   hook，token 保护，10 个测试）。
5. `completed` - G5 验收编排：`docker/compose.trench-acceptance.yml`
   （broker/sidecar/caddy TLS）+ `docker/trench-acceptance/bootstrap.sh`
   （密钥与本地 CA 生成，已实际执行）；`docker/Dockerfile` 增加 broker
   target。
6. `in_progress` - 全量回归验证与提交。
7. `blocked` - 应用镜像构建 + 完整栈拉起 + Trench `.env` 填值 +
   `EMB-TRN-READ-E2E-01` 16 输入执行（需 Trench 侧清场提交与真实
   部署输入，非代码缺口）。

下一步：等 Trench 侧提交清场后，按 `docs/Zebra_Trench对接实施方案_v1.0.md`
P1→P3 顺序拉栈、填配置、跑 runner。

## Current task — CLOUD-MEMORY-PROFILE-01 (2026-09-21)

1. `completed` — derive an inspectable user profile only from confirmed governed Memory.
2. `completed` — capture explicit background/goal self-statements as review-only candidates.
3. `completed` — balance bounded recall across preferences and task-relevant Memory types.
4. `completed` — expose principal-bound profile reads and exact governed deletion.
5. `completed` — enforce typed CHANGE/CREATE/OPERATE outcomes before answer commit.
6. `completed` — prove focused, API, real PostgreSQL, file-size, lint, type and eval gates.
7. `completed` — run the full suite and classify the sole live-provider-only failure.
8. `completed` — complete the real Trench Host surface with edit, source,
   scope and actual-recall transparency while keeping PostgreSQL authoritative.
9. `completed` — prove direct replacement, deletion suppression, cross-session
   recall and browser-visible governance in the composed local stack.
10. `completed` — review and harden fail-closed Host authority, PostgreSQL lock
    ordering, bounded source enrichment, blank input and overlapping UI requests.
# ZCode AG-UI pixel-parity closure (2026-09-27)

- [x] Inspect ZCode's current Apache-2.0 conversation components and design tokens.
- [x] Match the AG-UI turn, user bubble, reasoning/tool summary, expanded work and composer geometry.
- [x] Add deterministic DOM/style and browser visual acceptance at desktop and mobile widths.
- [x] Repack the React artifact into Trench and repeat Host build/browser acceptance.
- [x] Record final evidence and return `REACT-CONVERSATION-02` to Review.

# ZCode SendBar bottom-dock regression (2026-09-27)

- [x] Re-open `REACT-CONVERSATION-02` and trace the viewport/stage height chain.
- [x] Make the active stage fill the scroll viewport without changing the centered draft state.
- [x] Add browser assertions for short, long, mobile and desktop conversations.
- [x] Repack into Trench and repeat production Host acceptance.
- [x] Record evidence and return the task to Review.

# React component theme-token API (2026-09-27)

- [x] Re-open `REACT-CONVERSATION-02` and inventory the existing CSS variable boundary.
- [x] Export typed color and geometry tokens for `AgentChat` and standalone `AgentComposer`.
- [x] Make all documented tokens affect computed styles without changing defaults.
- [x] Add deterministic and packaged-browser customization coverage.
- [x] Repack Trench, repeat Host acceptance and return the task to Review.

# CLIENT-TRENCH-LIVE-01 durable Client pilot (2026-09-27)

- [x] Recover Research Child wakeups and suppress superseded continuation markers.
- [x] Freeze and resume Client effects through durable Receipt authority.
- [x] Enforce Client policy, exact profile readiness and terminal cancellation.
- [x] Harden Worker setup diagnostics and Docker/model health probes.
- [x] Complete one real-model same-Turn Host read, Research Child, browser action,
  succeeded Receipt and resumed final answer.
- [x] Pass focused tests, full Zebra gates and full Trench gates.
- [ ] Execute Linux gVisor, one-digest production canary and rollback rehearsal
  on the authorized production host before release approval.
# WEB-SEARCH-CHINA-01 - 2026-10-12

- Claimed focused domestic config/selector follow-up; preserve primary dirty work.
- Actual native engine matrix: Bing/Sogou/360/WeChat usable; Baidu CAPTCHA.
- RED/GREEN config and shared v1/v2 tool query guidance implemented.
- Exact-settings HTTPS-to-evidence qualification and static/test gates complete.
- Final images built; local integration next. Operator/model tests pending;
  v2 mixed-HTTP result compatibility remains OPEN separately from engine config.

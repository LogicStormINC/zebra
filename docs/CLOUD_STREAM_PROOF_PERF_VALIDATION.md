# Cloud stream proof/read validation follow-up

Owner: Luke Ding; executor: Codex. Task CLOUD-STREAM-PROOF-PERF-01.
Branch codex/cloud-stream-proof-perf-01, integration target cloud-agent-trench.
Local integration only after serial review; no push or deployment.

The paired runtime SQL-reduction gate and full refactor remain open.
18 actual healthy 600-second HTTP cells passed at frozen runtime a4b2;
see CLOUD_STREAM_PROOF_PERF_EVIDENCE.md for inclusive SQL and proof boundaries.
Later changes need their own source provenance and review.

## Clean validation provenance

Managed verification checkout: cloud-stream-perf-validation/zebra-agent.
The initial 64 source/governance files matched freeze027f; all 1269 runtime
entries matched a4b2. Imports were asserted to originate in that checkout;
the existing environment was reused without editable-environment resync.
Private logs and XML are outside the verification checkout.
Literal make check exited0 in11.289s; it does not certify full make test.

Original make test collected12081. It stopped at an inherited unbounded
terminal-race oracle after one SIGINT to pytest only, exiting2. Partial XML:
9930pass/96fail/1fixtureerror/228skip. The fixture error is separate from the
interrupt. Safe log/XML hashes and failure identities are retained privately.
The stale Session hook targeted read_since although both f919 and current
readers use read_session_event_page. The repaired test retains scheduling,
commit/status/drain assertions and bounds collection15s; two native cases pass.

Remaining partition:10254 unique prefix cases +2 terminal cases +1825 suffix
cases =12081. Function-family collection counts match; import-time UUID case
IDs require file-level suffix execution. Without maxfail, the suffix naturally
exited1:1615pass/142fail/2error/66skip,1825 actual records,16113.157s. All1269
runtime entries remain e28cf before/after with0diff. Its verification files stayed
frozen while follow-ups were prepared separately. No partitioned pass or literal
make test GO is claimed; original prefix failures remain separately retained.

## Follow-up boundaries

Local SQLite regression: two database-identity reads now occur only cloud=True.
Nine current local cases pass; the cloud=True predicates are unchanged per a
limited review. Runtime changes to e28cf; a4b2 matrix remains historical.

Preflight hooks accept existing continuation keyword, retaining lock checks.
Coverage fixtures prepare canonical projections at three finite setup points,
retaining late/private rejection and cold-history prohibition. Static serial
SPEC then QUALITY pass; focused native results are recorded below.

Confirmed current AGUI early optional command_outcome lookup requires a narrow
compatibility fix. Scalar outcome test must check args-CTE exact anchor bindings,
not obsolete placeholder positions; no event body hydration is permitted.
Two further static stale-test roots are present identically at f919: wrong
recovery clock module and legacy-schema test's unrelated current bootstrap.
They are not runtime baseline confirmations. Narrow test-only fixes are owned;
original deadline/no-model and missing-migration/load-not-called oracles remain.

Final current-source static checks, focused native results, failure disposition,
frozen serial SPEC then QUALITY, commit and local integration remain pending.
Relay, capacity, control and actual paired Worker/browser acceptance follow.

Skip audit:87 original records explicitly mention header scratch configuration.
Source-level fixture audit adds35, yielding122 nodes across18 families requiring
owned32786 supplementation after the frozen suffix exits. Other106 records span
MinIO34/sharedDNS5/Rabbit15/Trench-joint29/provider6/runtime10/otherRedis2/Mem0 3/
Crawl4AI1/intentionalSQLite1. Do not alias sharedDNS to32786 or count the intentional
SQLite PG-only exclusion as an environment omission. Actual supplemental gates
remain pending; no whole skipped-capability certification is implied.

Prepared follow-ups in implementation checkout only: two stale test-boundary
repairs and optional-lookup/scalar-query guards passed static SPEC then QUALITY.
An extra shared native outcome-reader qualification gap is statically confirmed:
class-level __call__ override was bypassed by captured outcome metadata. Its
minimal original-method identity guard and actual callback regressions passed
serial static SPEC then QUALITY. Separate-process pure identity smoke passes
default/plain/wraps/restored cases; actual native callback checks remain pending.
The running suffix retains e28cf files; these new changes are not its provenance.

Suffix raw SHA4c90767dabc54e40ac04cff18f22526c376baac87f832d8d51860e497ff98e13;
XML SHA1c4a232ae7a5601ce519184631fca74ff02cde84c8e9fdc6d157f60bccf02838.
Work-load256 results152pass/104fail are contained in the142 suffix failures.
Class/family static triage is separate from the bounded representatives below;
Timeout classes alone do not prove infrastructure failure or inherited behavior.

Focused fixture repairs:preflight13pass/0skip17.232s; coverage5PG+5SQLite
10pass/0skip16.075s. Two test hashes match before/after; validation production
remains e28cf. Original TypeError/CheckpointNotReady failures remain preserved.
Four suffix fixture repairs are explicitly owned before preparation: routing
projection8/9 Events, actual StreamProofReader target, shaped checkpoint publisher,
and matching isolated PG memory-review configuration. Serial reviews/native
checks are pending. Work-load104 failures all use2000ms; three distinct root/class
f919 representatives are authorized sequentially with60s external bounds. An
external timeout is incomplete evidence, not a baseline failure reproduction.

Matched f919 work-load representatives retain original source/tests and owned
dependencies. The initial three attempts stopped at capability fixture setup;
a boolean-only diagnostic isolated a mismatched model setting. Primary's existing
local config alias overrode the explicit fixture model; no config value was exposed
or changed. Repeating from the clean validation cwd used identical tracked defaults,
absolute primary test paths and primary source imports. Test-module origin/blob
checks were supplemental after launch; the source-origin check preceded launch.
Only the first exact2000ms representative reproduced the same TimeoutError/root
in35.815s. The ValueError representative reached the50s external bound and exited
after51.077s cleanup: INCOMPLETE, regardless of partial XML. The previously unknown
class representative produced TimeoutError in33.532s; its original class remains
unknown. These observations do not confirm all95 Timeout or104 failure cases.
Initial setup errors, diagnostic records and every original failure remain retained.

Four suffix repairs focused GO:routing6(3PG+3SQLite)20.730s,transient2 1.102s,
worker storage1 1.070s,memory native1 2.412s; all0fail/error/skip, reviewed
test hashes unchanged. Production remains e28cf; new-source gates still pending.
Two stale exact native cases also pass/0skip16.196s; simulated clock scope is
not proof of real elapsed PostgreSQL deadline. Original failures stay preserved.
Suffix skip source audit adds50 header nodes/5families; total172/23families.
Additional2 publication proofs are separately authorized on existing owned32781
by publication DSN exact equality to stream DSN. Never use business32768 or alias
header32786 for those checks. Other suffix exclusions:2intentionalSQLite/12MinIO.
Fresh collection/cardinality reconciliation and actual supplemental results await.

Current-source follow-up native GO:27pass/0fail/error/skip,33.387s pytest;
1269 runtime entries match before/after, fingerprint64df3082303f46c425de4dcb29ff2b9dc508353da4999eea34ac8aa5e6a34092.
Root independently checked XML counts, exact runtime maps and raw SHA
fd639fb17f37b896155d367fefaf47870891eb6790352a09c9073007b7cbb4e1.
This covers native default and three custom callback cases, scalar outcome,
tail and heartbeat. Historical a4b2 long-matrix results retain their provenance.

Header fresh collection reconciles all172 exact nodes/23families;43 other
parameters were excluded. Supplemental attempt01 stopped at maxfail1:
1pass/1fail/0skip,2.020s, runtime64df unchanged. Consumer scratch composes
frozen queue schema v68 plus privacy v97; current source-head read reports
UndefinedTable for session_observation_headers. This is a current composition
fixture gap, not a confirmed baseline failure. Remaining170 were not executed.
Original failed attempt retained; minimal dedicated fixture migration scope
is under read-only review.

Independent publication supplement:2native pass/0fail/error/skip,3.825s pytest.
ZEBRA_PUBLICATION_SCRATCH_DSN exactly aliases the owned32781 baseline DSN;
the existing fixture creates/drops only its unique schema. Runtime1269
before/after maps match64df; Root independently checked counts/maps/raw SHA
79fb888f67b69a5b7831ee0ca7367c04c52d53c607c2ac18cbbd9f392fa0500e.
Safe records:publication-supplement-attempt01; no business32768/header alias.

Consumer fixture first SPEC NO-GO (invalid CREATED→RUNNING setup) is retained.
Reviewed correction appends real PG TASK_PREPARED, applies v69 only in consumer
scratch beside existing v97, then saves canonical per-Segment setup projections.
Frozen v68 queue fixture is unchanged. Focused24:12PG+12SQLite pass/0skip,
331.200s; reviewed test hashes and1269runtime64df maps unchanged. Root checked
XML/maps/raw7078c868bf5544c2f4ef4fa32105bb93bf4f26a5443d5527953602fde83508a4.

Exact header partition:focused12PG + remaining160 = original172, disjoint and
without omissions;12SQLite cases are separate compatibility evidence. Attempt02
stopped at first failure:56pass/1fail/0error/skip,27.449s;103 not executed.
Combined current header disposition:68pass/1fail/103unexecuted, not all-header GO.
Failure is HostGrantScopeError in resource-binding wrong-resource setup before
forged-resource injection; original fixture already adds a second Host thread.
Raw a4775cde50087a19817e6a23009486459282f8e4b0729b51f9474591f791e4d4,
runtime64df unchanged. Existing accepted249 baseline six-failure evidence remains
separate; current fixture/helper/policy/_host_scope bytes match f919 and249.
No new baseline native execution or security-policy change is claimed.

Resource fixture reviewed TEST-only correction preserves every assertion;7native
pass/0skip,9.569s. Root checked XML/runtime maps and raw
797844d8c77c7d135e9bd25e1e2ee48e27995ee7603bd9d630f2a7f0c1259ff1.
Exact172 partition12PG+56previous passes+7resource+97remaining is disjoint,
without omissions, independently checked from actual XML/node selections.

Attempt03 (97remaining) stopped at first case:0pass/1fail/0error/skip,0.833s;
96 unexecuted. Current172 disposition is75pass/1fail/96unexecuted. Failure
is UndefinedColumn privacy_frontier in projection-work bootstrap: shared
queue scratch installs v68 while the unchanged current bootstrap expects v98.
Queue helper/bootstrap/real v98 migration and production queue module match
f919 byte-for-byte; this is static equality, not a fresh native baseline claim.
Runtime64df unchanged; raw9238c87a1dbc25c82e00c90263a09b3dda64ed80a1476a66ca4365c916864a3b.
Original header failures remain immutable. Minimal queue fixture migration
completion is under read-only review; no production/frozen-v68 change.

Reviewed queue-only v68→v98 fixture composition:focused34 stopped after
3bootstrap passes/1failure/0skip,1.750s;30 affected+63 other nodes unexecuted.
Current header disposition78pass/1fail/93unexecuted. Failure is
InsufficientPrivilege on source-coordinate-only task_replay_coverage_privacy
in the huge-payload queue test's restricted role; its Event grants remain
scalar-only. Existing scalar-header role fixture already grants SELECT on
this real v97 view. Minimal equivalent role setup is under read-only review.
Runtime64df unchanged; raw6e4a15dbf3f496a05d0f13ff3f93db4e4b33e0adf2ecbe603d017b79c444c25a.
No production privacy bypass, payload/table grant, or automatic rerun.

Reviewed restricted-role setup focused PG1+SQLite1 pass/0skip,0.530s;
Event payload privileges and every assertion are unchanged. Root verified
XML/runtime maps/raw1d0b5c00c6a8fea5ce0a1d232739811c918fabb710a624128624e523b2e9a914.
Exact172 partition from actual XML:79pass+93unexecuted before attempt04.

Attempt04 stopped at first failure:11pass/1fail/0error/skip,13.003s;
current172 disposition90pass/1fail/81unexecuted. UndefinedTable
task_replay_coverage_privacy occurs in the existing native-bootstrap False
parameter. That exact current-bootstrap test uses frozen shared native_dsn
throughv68 without test-local realv97/v98 composition; both parameter cases
need setup before seed/Events/enable. Shared fixture and v68 catalog remain
unchanged; current test file matchesf919. No fresh native baseline claim.
Runtime64df unchanged; raw92b9165c17a1bf631917b7c893aab3fb8806551ed7c67b5faeea72c2812238cc.
Minimal test-local setup is under read-only review; no automatic rerun.

Reviewed test-local nativebootstrap setup2 pass/0skip,2.078s; shared fixture
function/v68 source unchanged. Root verified XML/runtime maps/raw
dbb0f9dd76878b56dca66721ecd705ce8a951f77085aa7719c332728f62e5ba8.
Exact172 partition became92pass+80unexecuted. Attempt05 stopped at scale1000:
0pass/1fail/0skip,1.627s; current92pass/1fail/79unexecuted. Cold subprocess
reports InsufficientPrivilege on the same metadata-only privacy view;
scale's independent restricted-role setup lacks the view SELECT grant.
Its file matchesf919; no fresh native baseline claim. Actual payload-denial
and unchanged physical-plan probe assertions remain required. Other queue
restricted-role setup is already repaired IO; observer/scalar roles grant
the real view. Runtime64df unchanged; raw
56e72c427e8a139b13e7d632200c4916cbcd53947cb1ea9ffaf8af1a6dfda07f.
No grant/code/rerun before exact fixture scope review.


## SQL observation phase boundary (2026-10-14)

The original whole-HTTP zero-Event-body preflight oracle is **NOT GO**.
Native snapshot diagnostics captured409 `stream_source_unavailable`; first
rejected SQL was the Run metadata CTE wrapper (`cd3d4051…`, zero payload
identifiers). After its fixed-shape correction, the rejected SQL was the
canonical accepted-command point Page (`3c9390a2…`, one complete payload).
The latter is a necessary protocol-admission read, not source/checkpoint
metadata hydration. Original diagnostics and failed gates remain immutable.

The test-only phase observer keeps the real loader and accepted-command
validator. Only inside that loader's original Page call may the fixed SQL
read exactly its typed Run anchor: namespace/Task, after=anchor-1,
through=anchor, limit1, bytes<=1MiB, actual TaskIO deadline, and returned
single Event identity/Segment coordinates must all match. Scope restores
in finally. Protocol reads/connections and actual validator calls are counted
separately; they remain part of HTTP SQL totals. No authority callback/native
reader identity, production query, privacy check, or450ms oracle is changed.

Source/checkpoint metadata continues to reject Event bodies, including the
same accepted-command SQL outside the protocol scope. Public replay still
uses its original bounded Page gate. Fixed metadata shapes require explicit
re-review after SQL changes. This proves metadata results do not hydrate a
complete Event body; scalar predicates may internally read JSON/TOAST.
It is not equivalent to the former whole-HTTP zero-body claim.

A new real canonical fixture changes only the accepted intent fingerprint;
its Event idempotency key otherwise matches the original typed command.
The actual validator must reject it, the existing HTTP mapping must fail
closed before any frame, and tables must remain unchanged. This phase
instrumentation and negative test are prepared for independent review;
no native acceptance or current full-suite GO is claimed here.


## 2026-10-14 user-directed convergence gate

Scope is frozen at the currently prepared owned changes. No further old fixture,
SQL observer or hook expansion belongs to this batch. Any newly discovered issue
is classified and recorded separately; only a demonstrated regression of this
batch or security/data-loss fault may reopen implementation scope.

Finish criteria: freeze exact source/test/doc hashes; run one concentrated
necessary regression batch plus current static checks; retain every failed result
and classify new regression / existing defect / stale test / unconfirmed. Perform
one final consolidated SPEC then QUALITY review. Commit coherent production and
supporting test slices and integrate locally into cloud-agent-trench while
preserving dirty work. No push/deploy; no full12k or18x600 repetition without a
new production change requiring it. The accepted72 new-source native checks and
historical18 long cells keep their original provenance, not renamed fresh proof.

Then implement RELAY, capacity/GC and STOP as focused tasks. Overall>=80% SQL
reduction remains the actual paired runtime/browser acceptance gate. Necessary
bounded protocol intent validation is included in its total; checkpoint metadata
body-free evidence does not assert whole-HTTP zero-body behavior.


## Frozen component convergence result — 2026-10-14

The single concentrated native batch collected exactly69 and completed59pass,
10fail,0error,0skip in839.064s; pytest exit1. Subsequent literal make check
in the clean exact-source validation checkout passed (exit0,4.401s).
All93 frozen review files and all1270 runtime files remained unchanged;
runtime fingerprint492d632fa2523507f20117a4ba2ca2e5a1f383d073c42250d28e9edeee22ca66.
The new invalid-fingerprint test passed through the original validator.

Original172 selection reconciliation has no overlap/omission or remaining node:
93 latest passes belong to current492d;79 belong to historical64df. This is
mixed-provenance evidence, not172 current-source passes or literal fulltest GO.
Current v10072 native checks remain GO; the18 long observations remain historical
a4b2 evidence and do not certify the current complete runtime.

Retained10 failures: one SQL observer rejects an audited metadata wrapper;
eight HTTP200 protocol-output differences remain unconfirmed; one pre-HTTP
fixture repair COMMIT exceeds TaskIO deadline with unconfirmed timing cause.
The two long GET cases naturally ended at their300s signed Host expiry.
Do not label unknown output differences obsolete fixtures or production regressions.
No oracle was weakened and no follow-up test rerun or automatic fix was performed.

One consolidated SPEC and one consolidated QUALITY review permit local acceptance
of this source component and progression to separate RELAY work. They found no
demonstrated unclosed production blocker, not proof of absence of regression.
These failures still block complete HTTP/fulltest closure. WholeHTTPzeroBody is
NOTGO; complete SQL80%, Worker/SDK/browser/runtime and fullPERF remain OPEN.

Private retained evidence: convergence-candidate-attempt01 under the owned
stream-proof-perf artifact directory contains candidate manifest, actual selection,
JUnit/raw hashes, classification.safe.json, original172.reconciled.safe.json and
spec-consolidated-review.md / quality-consolidated-review.md. Candidate manifest
SHA c134919bbf29171f1570aba0988bffad2bbfb50ffa5511d4daea6e293f793d7d;
JUnit SHA99ecd593774deeeade4e9beb66e25d6d72ed96c7cca04ba218b306a73729b8e4.
Raw evidence and all earlier failed attempts are retained privately.

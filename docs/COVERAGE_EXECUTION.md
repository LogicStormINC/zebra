# Coverage execution boundary

## Current implementation boundary

### Work slices / proof-read scaling (2026-10-10, bounded component only)

- Recovery now reuses the existing invocation-local model verifier, as rebuild
  and publication already do. No ledger/manifest rescan for each accepted batch;
  receipt, membership, derivation, sequence and logical byte checks still execute.
- Only RR read-only preparation reuses original bytes, at most 32 MiB; beyond
  capacity it falls back to physical I/O. Each hit compares the full native/fresh
  record, validates lifecycle/receipt/length/SHA and checks fresh authority/time.
  Version or lifecycle mismatch refuses; no eviction/refetch conceals a conflict.
- Finalization retains only original records/digests, never cached bodies, and
  independently rereads exact physical versions under fresh authority/deadlines.
  No cross-callback proof/authority cache, new dependency or product budget change.
- Work slices default32 units/8MiB/2s, per-unit commit and fresh authority retained.
  RR native SELECT reuse, single timeout wrapper; default nine180.50s/178760 SQL.
  See COVERAGE_WORK_SLICE_EVIDENCE.md. Normal continuation/incremental/SLO open.

### Callback connection reuse (2026-10-10, earlier bounded native matrix)

- Coverage execution/recovery/final scopes reuse up to eight idle sockets;
  deployment/DSN/thread isolation, independent transactions, session reset and
  callback cleanup mandatory. Reset errors discard sockets without masking
  committed success/business failure; deadline and final authority remain fresh.
- Earlier1/6/9:17.23/172.42/459.46s, opens53/343/517; native14+safety8/zero schemas;
  default6699/1533 prerequisites skipped, Mypy1082/Ruff/size/eval30. Retain old XML.
- Full-C1,048,576 per part/10,000,000-token ceiling admit at most nine parts;
  twelve is typed pre-model refusal, not load GO.
- Actual broker/process/browser/model and business semantic acceptance remain open.

### Worker/UI acceptance follow-up (2026-10-10, before socket reuse; scale RED)

- Added an actual Worker/PostgreSQL load matrix at 1/6/12 records, one part each. It uses
  existing native admission, continuation and certificate paths; Host, provider
  and S3 remain controlled transports, not broker/process/browser acceptance.
- The callback fixture has no capability heartbeat. Initial scale testing
  correctly refused an expired consumer lease. Replacement-consumer-per-wake
  testing now uses actual readiness/handoff rather than increasing its TTL.
- Measured boundary excludes fixture admission/setup and ends at certified
  completion. Object GET counts exclude fixture setup. The one-part diagnostic
  run uses cProfile; other sizes do not. No retrospective latency threshold.
- One-part diagnostic: 2 units, 1 model HTTP call, 52.77s to certification;
  4,610 PostgresDatabase.connect calls consumed 29.51s cumulative profile time.
  Controlled model transport is immediate. Fresh Artifact/authority proofs
  dominate this synthetic boundary; removing them or trusting cached authority
  is not an acceptable latency repair. Not production latency or throughput.
- The scale gate is red: the six-record case ended FAILED at its final callback,
  with a 604.29s test-case duration and a fixed 600s execution budget. Deadline
  exhaustion is consistent with this result; its exact refusal code was not
  retained before fixture teardown. `-x` prevented the 12-record case from
  running. One pass/one failure in 663.13s, zero new scratch schemas. Keep the
  failed JUnit evidence; do not increase the deadline or call this scale GO.
- Paired Trench now renders absolute coverage in the actual Workspace/SDK path.
  A 30-second idle observation deadline reconnects through the durable snapshot;
  only advancing cursors renew it. Queued/dispatching/running projections remain
  active. Snapshot failure preserves partial text/cursor; timers never cancel or
  declare backend completion. Frontend 100/backend 95 tests and build passed.
- Worker setup failures retain only typed coverage refusal reasons in terminal
  metadata. Expired grants are checked before admission with one entry timestamp;
  subsequent IO still checks fresh time. Runtime expiry is budget_exceeded,
  grant expiry authority_invalid. No deadline increase or raw-error disclosure.
- Default regression: 6,695 passed/1,528 prerequisite skips in 130.02s;
  focused 31, Ruff and Mypy 1,081 clean. Native smoke 3/zero skips (165.44s)
  before the final entry guard; final native runtime/grant/expiry-race regressions
  3/zero skips (17.04s), zero new schemas, separately cover that guard.
  These gates do not supersede the failed scale matrix.
  Final focused selection: 30 passed/4 deselected (2.57s); independent guard
  review found no remaining blocker. Earlier 31-case selection was different.
- Real signed-Host/JWT browser delivery, continuous process heartbeat/broker
  scale-out, independent business semantics and runtime activation remain
  separate acceptance boundaries; existing QA images are not this candidate.

### Proof bytes/history/acceptance follow-up (2026-10-10)

- Reuse immutable checkpoint bytes only inside one private locked proof phase,
  capped at 32 MiB. Each use still checks current metadata, native provenance,
  sequence, digest, receipt and retention; logical budgets do not receive a
  refund. Independent certificate/publication phases get fresh reads.
- Final lifecycle phases now reuse the existing locked reader's full metadata
  records only for the exact known pure semantic deriver. Budget replay and full
  source/aggregate proof remain separate complete proofs with no shared byte
  cache. Each lifecycle gets a fresh reader, invalidated before certificate append
  or retry. Entry/exit and physical-read pre/post authority, fresh expiry, native
  pins and bounded fallback remain; arbitrary derivers keep public guarded reads.
  Report-read/rebuild composition is unchanged. This is a source optimization,
  not authorization caching across phases or a deployed-runtime claim.
- Rebuild spools full native rows to a private automatically deleted temporary
  file. Lock-time comparison remains exact row equality, not a count/digest
  shortcut. Manifest and one batch request are decoded on demand; the complete
  Event bodies and all batch requests no longer stay resident together.
- Native model history, call indexes and original metadata use bounded pages.
  Original preflight aggregates count/bytes/missing metadata and duplicate join
  multiplicity before object reads, retains only reservation identities and the
  candidate retry receipt, then pages through recorded deadline-aware execute.
  RecoveryReadSnapshot still records and exactly revalidates those queries.
  A server-cursor attempt was rejected because it bypassed those adapters.
- `scripts/coverage_acceptance_load.py` measures disposable real PostgreSQL/MinIO
  components with synthetic contents. Results and reproduction instructions are
  under `evals/coverage_acceptance/`; no production load or live Worker claim.
- `scripts/coverage_acceptance_semantic.py` scores an exact labeled/predicted ID
  set, confusion, precision/recall, unresolved rate, missed findings and Unicode
  quote offsets. Incomplete/malformed inputs refuse; unresolved positives count
  as misses. Caller-declared labels/profile are not model provenance. The user
  has no independent business labels, so actual business accuracy is unverified.

Measured allocation bounds are not constant whole-process memory. Identity sets
and replay indexes remain O(N), original metadata joins repeat per page, recovery
read transcripts cap at 8,192 reads, and ordinary successive-call gates can still
have quadratic cumulative proof cost. Improving those ceilings requires measured
full-run evidence and a retained immutable proof-root design, not caching trusted
authority across phases. No merge, runtime replacement or deployment in this slice.

Latest gates: 33 focused; 6,688 passed/1,523 prerequisite skips (128.53s);
Mypy 1,081, Ruff, tracked size and all 2,031 Python-file limits passed; eval30.
Latest-source native matrix: 10 passed/zero skips (373.00s), zero new scratch
schemas. Includes multipart physical-read counts, rebuild/rollback, actual 32 MiB
candidate refusal, pre-object volume gates and missing reserved-source guards.
Independent read-only review found no remaining blocker after the adapter repair.

Refreshed isolated 10,003-row measurement: resident-list Python peak 21,234,714
bytes; paged disk spool 545,222 bytes; original metadata pages 434,182 bytes.
Times 1.312/1.326/0.870s respectively. Real MinIO 128 originals used three times:
384 -> 128 physical GETs, exact bytes equal; 2.661 -> 2.910s, peak Python allocation
507,057 -> 1,508,883 bytes. The bounded byte cache trades memory for bandwidth;
these two runs do not establish a latency improvement or production SLO. All fresh
test resources cleaned. See `evals/coverage_acceptance/component-load-20261010.json`.

### Report deadline and scale follow-up (2026-10-10, component checks verified)

Read-only operation-count review found a multiplicative proof replay: for B
accepted batches and N settled MODEL calls, each batch verifier replays the whole
ledger. The successful report path invokes that replay 2B+2 times, including the
final locked publication phase, with additional record-merge batch rescans.
The earlier O(n) description below is an incomplete cost bound, not scale GO.
Pure batch probes at 10/100/1,000 batches made 10/100/1,000 whole-run verifier
calls respectively. These counts are source/fixture evidence, not live latency.

Implemented first repair: one remaining monotonic budget across report preflight,
PostgreSQL connect/query/lock, original object reads, Host checks and final gate.
Do not only time out the awaiting coroutine while proof threads continue. Keep
ordinary callers unchanged and preserve every membership/lifecycle/authority
check. Request-local ContextVar scopes reset on success/failure and cannot extend
an outer budget; ordinary database callers stay unchanged. SQL cancellations
roll back and refuse transiently; object clients and bodies close on exhaustion.
The report budget is 20 seconds, not a promised wall-clock response ceiling:
libpq DNS/per-address connection setup, thread-pool queueing, synchronous CPU
parsing and blocking cleanup are not hard-preemptible. Expired results fail closed
once control resumes. Fresh JWT verification precedes this report-specific budget.

Paired Trench overrides its report-owned client's default 5-second timeout within
the remaining 25-second budget, including mapping/grant/stream; unrelated client
defaults stay unchanged. Frontend Unicode bounds use backend-equivalent code-point
counts. Safe transient 503/504 and deterministic 422 failures have distinct hints.
Trench verification: 37 backend / 225 frontend checks and production build passed.
Zebra author verification: 30 native-enabled checks / zero skips, including backend-idle
SQL cancellation, original certified GET/HEAD and mid-proof revocation. Independent
source/pure review passed 89 checks plus three probes. Independent native-enabled
selection passed 32 / zero skips and left zero new scratch schemas; actual report
GET/HEAD, revocation and reusable idle backend after cancellation passed. The
contended-lock probe cancelled with QueryCanceled, proving bounded waiting, not
independently which configured timeout fired first. Independent Trench checks:
37 backend and 29 focused frontend passed. Final default Zebra regression:
6,655 passed / 1,519 prerequisite skips; Mypy 1,079, Ruff, size 2,024/zero and
eval 30/30 passed. These are cooperative component gates, not production latency.

Next scale boundary: one verification-local transcript per proof phase can
eliminate repeated ledger/batch parsing only if source sequence, original receipt
linkage, exact membership, duplicate detection, retention and final locked pins
remain verified. No cross-request certificate cache or skipped final proof pass.
Transcript implementation passed independent scoped SPEC/QUALITY review. Public
commit verification still constructs its own proof; publication can share
only the manifest/ledger and canonical batch index inside one source-verification
invocation. Merge provenance must still be earlier than each target batch.
Native/browser scale acceptance remains pending; no latency claim follows from
reduced operation counts alone.

Publication source verification now performs one manifest/ledger replay per
invocation, independent of batch count. Canonical batches are loaded once into
a bounded index; duplicate sources and more than 200,000 source units/batches
refuse before unbounded accumulation. Record merges use exact indexed part
provenance rather than rescanning all batches. Request/part/observation proofs
still execute, and logical batch bytes are charged for each merge even when
physical reads are shared. This is not a cross-request trusted proof root.
Source tracing of strict MODEL report reads shows four whole-ledger replay calls
across independent gates, replacing the previous 2B+2 count. Locked rebuild now
shares one transcript across its batches; independent certificate proofs remain.
Do not describe all coverage proof work as linear.

Pure 1/10/100/1,000-batch operation probes confirm one manifest/ledger replay
and linear canonical-batch parsing per source-verification invocation. Native
one/two-record fixtures use respectively three/four accepted batches: one
manifest and ledger replay, two original ledger checkpoint validations, four
part checkpoint validations/derivations. Exact certificate bytes, earlier/equal
receipt/source refusal, expiry, exact cap boundaries and repeated logical merge
charging passed in two author cases, zero skips/leaks. This is isolated PG with
fixture object transports, not live MinIO/browser or production latency evidence.

Independent frozen validation completed: 53 native PostgreSQL cases/zero skips
in 1127.53 seconds, zero fixture schema leaks; pure S3/HTTP/transcript selections
15/11/8 passed separately. Provenance, chronology, repeated logical charging,
original certified bytes and final expiry/revocation passed.

Rebuild follow-up (2026-10-10, scoped SPEC/QUALITY GO): construct
one private transcript after the locked source comparison, before deleting
coverage projections. Rebuild mode repairs missing model projections inside the
same transaction. Each batch retains its own historical sequence, byte charging
and original evidence checks; merges query the progressively restored accepted
parts. Any later proof failure rolls back model repair and coverage projections
together. Final retention, attempt-budget reconstruction and certificate proofs
remain independent; snapshot expiry does not become fresh publication authority.
Author native: two new one/two-record cases (74.01s) and nine existing recovery
cases (214.73s), zero skips and zero fixture leaks. Batch reconstruction performs
one verification manifest/ledger replay; the outer manifest preflight is separate.
Canonical batch parsing remains proportional to accepted batches. Original part
proofs can still repeat and history stays in
memory. No live latency or native large-run throughput claim follows.
Independent frozen review: 11 native/zero skips (305.22s), zero fixture leaks.
Historical sequence constraints passed source review; expired-snapshot rebuild
was not separately exercised in this native selection. Default 6,663 passed/
1,523 prerequisite skips (122.55s), Mypy 1,080/Ruff/size 2,028/eval30 passed.

### Certified report HTTP delivery follow-up (2026-10-10, component verified)

GET and HEAD `/tasks/{task_id}/coverage/report` are private read-only delivery
routes, not ordinary Artifact aliases. Each request authenticates one fresh
signed grant with `history.read` and `artifact.read`; repeated authority checks
must not consume its JTI again. Current Task/principal/Host/connector/resource
binding and the frozen snapshot descriptor are revalidated independently of
historical progress. No manifest discovery or binding renewal is allowed on reads.

The existing canonical-byte gate verifies original membership, MODEL evidence,
certificate digest, publication lifecycle and retention. It additionally checks
the certificate source actor, canonical historical fence and lawful original
issuance time. The execution deadline governs original issuance, not a later
authorized read. The current grant deadline is checked at the final DB boundary.
HEAD performs the same gate; Range is refused and ETag never skips authorization.
Successful responses carry exact bytes, SHA-256/ETag, length and `private, no-store`.

Paired Trench delivery resolves the Task through the server-owned conversation
mapping, signs fresh authority and proxies this route only. Preview/download may
not fall back to raw Artifact or legacy answer output. The existing Drawer shows
50 observations per page; preview and download each fetch fresh authorized bytes.
Conversation changes abort requests and discard loaded report state. The proxy
checks exact length, SHA-256 and ETag under a 32 MiB response limit. The signing
broker adds the verified principal even when requested resources contain history
only; no owner check was relaxed.

Scoped independent SPEC/QUALITY GO: 41 native checks / zero skips, 42 pure checks,
zero new fixture schemas. Actual Worker certification reaches GET/HEAD; source
revocation during proof validation refuses delivery. Zebra default regression:
6,648 passed / 1,518 prerequisite skips; Mypy 1,079, Ruff, 2,022-file Python size
scan and eval 30/30 passed. Paired Trench: 32 focused backend checks, 216 frontend
checks and production build. Its full backend suite was not rerun in this slice.

Remaining boundaries: original proof reads are O(n) and final revalidation uses
the existing run lock. Host's 20-second/eight-call budget is not an end-to-end
database/object deadline; Trench proxy/UI budgets are 25/30 seconds. Large-run
latency, semantic precision/recall, live JWT/Host/browser acceptance and deployed
broker configuration remain unverified. No runtime replacement or integration.

### Atomic delivery and recovery-lock follow-up (2026-10-09)

Multipart7 native QUALITY is now complete: ten actual-PG controls, zero skips,
unchanged seven-file freeze. Normal six-record completion took 585.288 seconds;
the sampled maximum idle transaction was 257.975 seconds and maximum waiting
query age 178.909 seconds. This is bounded correctness evidence, not latency GO.

The current follow-up reuses native Task admission for bootstrap/binding/command/
outbox/idempotency in one transaction and records an exact deployment-configured
consumer requirement. A compatible process must prove its own current capability
at pickup; an unrelated healthy process cannot confer authority on an old Worker.
Expensive recovery preparation moves original object verification, authenticated
source checks and semantic replay before command locks. Finalization must pin and
compare every observed native read, not only a stream revision, and recheck the
DB clock/retention. Any changed evidence refuses reuse. Ordinary callbacks keep
their existing safe path. These changes are implemented in the isolated checkout,
with separate SPEC/QUALITY GO for both scoped follow-ups, not activated.
Final native PostgreSQL selection passed 106 / zero skips (168.33s), including
the actual NativeChecker continuation through report certification; no new
fixture schemas remain. Default regression passed 6,613 / 1,514 prerequisite
skips; Mypy 1,076, Ruff, 2,017-file source/test size check and eval 30/30 passed.
Preparation is bound to the actual database/server/schema and exact canonical
pending/receipt rows. Finalization compares complete native row multisets,
preserving duplicate multiplicity, and checks age plus proof/command expiry
after the last lease/capability check. Regression controls cover an unblocked
evidence writer during preparation, blocked lifecycle writes during finalization
and a cloned-schema refusal. This proves
the lock boundary, not an end-to-end latency target. Final native/object proof
reads remain O(n); the read-only preparation snapshot can still be long-lived.
Large-run vacuum pressure and provider/browser performance are not solved by
this split or by raising a lease TTL. Finalization uses a monotonic deadline,
per-statement lock/query timeouts, bounded HTTP body streaming and a private
deadline-configured S3 client. Transient proof-window exhaustion rolls back and
defers; it must not dead-letter, ACK or certify the command. OS DNS scheduling
and arbitrary-scale proof scans do not become hard real-time guarantees.

Strict admission now persists bootstrap, binding, initial RUN, pending command,
outbox and idempotency atomically, with a deferred commit-time capability gate.
Pickup proves the actual consuming process, not an observational health lease.
Skipped execution polls cannot renew readiness. Configuration includes the
composed S3 endpoint as well as namespace/bucket/prefix. After the Session lock,
pickup takes the existing Task authority shared lock and rereads binding/Host
authority after capability waits. The final clock bounds capability, Host,
context and Task runtime together. Natural process expiry is renewable under
the exact epoch/configuration; explicit revocation is not silently revived.

The public canonical reader no longer trusts an indexed prefix as source proof:
all original Segment Events are read and checked. This is O(n) per read and is
not the planned scale optimization. Full Task strict identity is pinned across
SSE slices/reconnects after an independent late-marker counterexample; ordinary
streams remain unchanged. Public20 source/pure SPEC and QUALITY approved this
identity repair. Descriptor-only reads now run
the existing final authority/budget check after wire parsing. Certified-byte
reads optionally accept the currently verified grant's expiry and compare it
with the final database clock under the publication lock; the caller must still
verify current authority/binding. Descriptor repaired2 passed separate SPEC and
QUALITY; reportdeadline3 also passed separate native QUALITY (nine actual-PG
cases plus four pure). None of these helpers
activates HTTP downloads.

Public14 raw-output isolation passed native SPEC, but QUALITY reproduced a
partial-root membership bypass. Public18 initial SPEC found a relabelled-root
bypass and an uncaught Task stream error; both superseded freezes are BLOCKED.
The shared identity repair now checks durable handoff root/parent/stage and
translates raw adapter refusal consistently; independent re-SPEC is active.
A follow-up summary whitelist is wired because
approval/plan/attachment metadata must not become a candidate-output bypass.
Bounded Cloud reads passed SPEC/QUALITY. The Session/deployment-bound read-only
Artifact adapter passed SPEC and QUALITY; actual HTTP composition remains open.
Descriptor-only Host revalidation avoids re-enumerating the immutable snapshot
but does not replace certificate, current grant, expiry or lifecycle gates.

The incremental SSE helper was extracted into ag_ui_task_frames.py after the
Public20 review. Strict tasks validate their complete canonical stream/cursor
once before skipping only hidden, already-started same-Segment prefixes. Public
progress, Segment starts and ordinary streams retain exact reference output.
Work is O(N*P) for P visible events/starts, still quadratic in the worst case;
this is not a stateful linear projector or a solution to native proof scans.
Performance3 SPEC approved its bounded controls, but QUALITY found that equal
Segment IDs can belong to different contiguous slices across an excluded
intervening Segment. The repaired slices4 compares contiguous slice identity;
replay/reconnect reference tests preserve returning starts/cursors. Separate
SPEC/QUALITY approved slices4: SPEC 98 tests plus 2,730 comparisons, QUALITY
98 tests plus 786 comparisons. Main repaired selection: 42 passed; API/AG-UI
selection: 911 passed/29 prerequisite skips. Final slices4 full Python passed
6,551/1,487 prerequisite skips; Mypy 1,070, Ruff, file-size gate and 30/30
deterministic eval pass. No live response-time acceptance.

Public strict-output isolation is implemented and under independent review:
persisted strict admission is recognized before progress exists, typed AG-UI
shows only absolute counts and sanitized terminal state, and ordinary raw
stream/Artifact routes refuse strict output. A SPEC-discovered child-Segment
bypass is being repaired at the shared parent Task identity boundary. Cursor
anchors stay canonical when private Events are hidden; historical certification
never releases arbitrary MODEL checkpoints, tools or attachments. The verified
report-byte reader is still awaiting HTTP composition and current authority.

Readiness cannot be a settings flag, ordinary health response, sandbox instance
or Session lease. A native process-capability lease now binds the deployment
epoch, storage/schema, configuration and actual consumer/recovery progress.
Its missing mandatory dispatch-dependency counterexample is repaired; separate
native SPEC and QUALITY approved readiness7. That earlier observational lookup
has now been extended by the atomic admission/routing follow-up above. HTTP
still fails closed when the actual compatible process, deployment/storage/config
identity or current authority is unavailable. No service activation is inferred.

Multipart's independent native SPEC observed long whole-proof transactions
blocking lease renewal while the lease row is SHARE-locked. Correctness controls
passed, but neither arbitrary-scale processing nor low latency is established.
Do not remove the fence/retention checks or raise limits to conceal this ceiling;
bounded proof roots and shorter atomic finalization need separate implementation
and native performance acceptance before general large-run admission.

COV-EXEC-01 implements the Host snapshot adapter, resumable core executor,
immutable Artifact publication, bounded physical readers, prepared membership
indexes and PostgreSQL exact-report certification. The Worker Artifact facade
and first strict dispatch are now wired in the isolated composition checkout;
recovery/handoff and admission readiness are still being implemented/reviewed. The existing
exploratory runtime remains unchanged. This is not full-chain runtime activation:
configured strict Task admission, Worker composition, publication bypass guards,
API/UI and coupled live acceptance remain unfinished. Migrations 79–82 are source-only; no live
migration, restart or business-data update has been performed.

API shared preflight passed SPEC/QUALITY, including rejection before idempotent
receipt replay and direct composition/queue bypasses before Host/bootstrap writes.
Strict HTTP requests still refuse while Worker acceptance is
unfinished. AG-UI absolute progress and paired Trench persistence/UI passed SPEC
and QUALITY, including certified-to-cancelled replay and uncertified terminal
labels. Historical `certified` state does not authorize a present-day
report download. The first Worker dispatch supports empty snapshots or one MODEL
part; same-Session continuation and crash recovery passed SPEC/QUALITY with real
PostgreSQL and fixture Host/provider/object seams. Larger snapshots, cross-segment
recovery, live semantic/browser acceptance and native scale remain unproven.

The adapter consumes an admission-frozen Host manifest, an authorized session,
the exact history resource and injected signed Host invocation. Snapshot creation
requires a separately injected admitted Effect invocation and preserves its
idempotency key. Merely having a Host gateway or write scope does not constitute
Effect admission. The composition root must supply capabilities only after its
existing Policy/Effect checks; the adapter cannot prove that admission itself.

## Published semantic rule

The user authorized the fixed `bounded_semantic/1` source-annotation rule on
2026-10-08. It reviews explicit operational/harm claims, contradictions within
one canonical part, and consequential assertions with missing supporting
context. It is not external fact verification or a guarantee of no real-world
risk. A negative observation means clear only under that frozen rule.

Structured responses bind the exact unit key and quote Unicode character
offsets from the immutable source. Unknown fields, including confidence scores
in directly constructed or copied typed objects, are rejected before conversion.
Unresolved outputs never become accepted negative results. The validator passed
66 focused deterministic tests and independent specification/quality review;
live model precision/recall, Worker dispatch and product activation are not
established by those tests.

The user reaffirmed autonomous semantic implementation on 2026-10-08. This is
the fixed v1 choice, not an outstanding product question. Runtime support stays
disabled until exact prepared-request reservations, immutable full-completion
checkpoints, usage acknowledgment and replacement replay are composed. A saved
usage receipt without recoverable original output cannot establish a completed
semantic unit. Current authority and the frozen source/rule remain mandatory
when consuming checkpointed responses.

The opt-in prepared Chat request prerequisite has passed specification/quality
review: exact canonical bytes and resolved metadata, raw-policy validation before
fallback, owned/configuration-checked single-shot sends, and rejection of Client
auth/hooks/query drift, unsupported retries and URL userinfo. Ordinary Chat is
unchanged. Existing HTTPTransport-pool reuse is currently unsupported; MockTransport
is a trusted fixture only. This does not certify a total-token bound or compose
durable MODEL reservations/checkpoints into the Worker.

The full-completion codec preserves supported typed metadata/usage, tools,
message metadata and provider-private reasoning in bounded canonical JSON.
Private fields are recovery evidence only, never chat/asset/download content.
Raw unknown fields, counter coercion, normalization-changing copies and scalar
internal-state mutation refuse before encoding; reads reject duplicate keys,
nonfinite JSON, unsupported schema and byte overflow without truncation.
Timezone support is fixed stdlib timezones and canonical cached ZoneInfo; arbitrary
uncached/file-backed timezone object identity is not persistable and refuses.
Independent specification re-review passed after original timezone/UUID/Enum
counterexamples were repaired. Fixed-offset/UTF-8 repairs also passed independent
specification and quality re-reviews. Main full Python: 5,956 passed / 1,201 skipped;
143 focused codec checks pass. This codec does not persist checkpoints or settle
reservations by itself.

## Transport to durable evidence

MODEL checkpoint/receipt lifecycle passed independent specification and quality
reviews after readerless-rebuild, sequential-retention and first-issuance deadline
repairs. Original bytes and canonical Event/lifecycle proofs gate refunds,
replacement replay, reconstructed headroom and certificates. Main final time
boundary matrix: 34 real PostgreSQL passed / zero skipped; full Python 5,985
passed / 1,345 skipped. This is component approval only: response-only evidence
cannot prove semantic source/unit derivation. Exact prepared requests, composed
MODEL invoke-or-replay and Worker dispatch remain pending. Proof object reads
still cost O(n) per gate / O(n²) cumulative new calls; scale acceptance is open.

Trench descriptors do not supply Zebra Artifact references. Pages carry transport
provenance and a digest of the entire response except `page_digest`. Body reads
carry bounded base64 byte chunks, not independently decodable text fragments.

The adapter must verify all pages, exact contiguous ordinals, unique identities,
scope and authority bindings before publishing a canonical manifest Artifact.
The Host manifest digest and stored Artifact digest represent different canonical
encodings and must be checked separately. A valid empty snapshot is supported.
Manifest and body identities are deterministic and session-bound so another
adapter instance can reuse durable evidence rather than process-local state.

Every body read must belong to the sealed manifest, revalidate current Host
authority, verify contiguous offsets, final byte length and SHA-256, then persist
the canonical bytes. An existing Artifact is not authorization: cached reads still
perform current-authority checks. Missing, expired, pruned, cross-session or
corrupt Artifacts must not be treated as successful evidence.

## Bounded operations

- Maximum snapshot size: 100,000 records.
- Maximum manifest or individual body: 32 MiB, additionally capped by the grant.
- Host page size: at most 100; shorter pages are valid.
- Body transport chunk: at most 32,768 bytes.
- Default public-operation budget: 2,048 Host calls and 60 seconds; configurable.
- No transparent unbounded retry and no new HTTP client or network-policy bypass.

These are v1 ceilings, not unlimited streaming or production capacity evidence.
An operation exceeding a ceiling must refuse rather than certify partial data.

The adapter requires optional immutable-publication and bounded-read Ports;
unsupported stores refuse instead of silently falling back. SQLite serializes
publication using BEGIN IMMEDIATE and exclusive/fsynced file creation, including
legacy writes. Exact retries preserve evidence, conflicting/partial orphans refuse,
and interrupted prune cleanup can retry. Legacy rows adopt a previously unrecorded
filename only after exact metadata/bytes verification. Physical SQLite/S3 readers
request at most the allowed size plus one and close S3 streams on failure.

Cloud publication uses PostgreSQL reservation metadata and immutable versioned S3
objects. Reservation keys bind the full frozen run, not only the Artifact ID.
Uploaded/STAGED data is not readable coverage evidence. The canonical materialized
Event and FINALIZED transition share a fenced transaction; interrupted uploads
resume under current authority. Retargeting an unfinalized reservation to the
current Event sequence is coverage-specific and records old/new hashes.
Two independent Python processes with synchronized upload barriers have been
tested against real PostgreSQL and versioned MinIO: both recover the same
canonical receipt, with one materialized Event and one immutable object version.

Prepared batches verify/index the manifest once. Each body/cache access still asks
the signed Host to validate the immutable descriptor and current authority. An
index caches membership, never permission. The unprepared read path remains O(N)
per body; production Worker composition must explicitly use the prepared reader.

The executor reserves immutable run-wide attempt/input-byte budgets in the Event
transaction using O(1) counters. Rebuild recovers counters from Events; restart
cannot enlarge the frozen budget. Durable MODEL storage now freezes original
Task deadlines, profiles, call counts and token bounds; actual request-bound
callbacks and durable runtime terminal stop outcomes remain unfinished. Literal checks are actual program
checks, not substitutes for semantic risk analysis; model checks require an
explicit configured callback and refuse unsupported body sizes without truncation.

Migration 80 reserves the supported full-request/output token bound before
transport and settles only exact integer usage tied to that request and unit.
Missing/malformed/conflicting usage stays charged and unresolved. Exact replay
does not authorize another model call. Call counts are never refunded. Strict
certification refuses uninitialized or unresolved MODEL ledgers, exhausted
quotas and late certification; valid historical certificates remain governed by
snapshot expiry and fresh authority rather than expiring at execution deadline.
The snapshot now freezes the verified history resource locally; strict MODEL
policy refuses absent or foreign provenance without fabricating legacy values.

Native MODEL integrity scans currently cost O(n) per mutation/O(n²) cumulatively.
They avoid Python allocation on the hot counter path, but source replay still
allocates Task descriptors/run history. No bounded whole-path memory or 10k-scale
performance claim is made. Main synthetic 250 reservation/receipt pairs took
34.33 seconds on scratch PostgreSQL; no provider call or actual usage was measured.

Each validated observation is immutable before acceptance. Missing units drive
restart, part checks precede record merges, and completed units are not rerun.
Record lookup uses keyset pages and check filtering; merge membership lookup is
indexed rather than quadratic. Multipart merges retain every part-result digest
while displaying at most 100 quotes; the exact report includes every part finding
and negative result. Report generation has a 200,000-unit / 32 MiB ceiling and
fails rather than silently omitting findings. Unit counts are checked before
expansion, not after allocating the records × checks × parts set. Multipart
body and prior-observation accumulation each has a 32 MiB serialized-byte
ceiling before decoding/parsing more data. Decoded Python objects have bounded
overhead beyond serialized size; this is not a 32 MiB process-RSS guarantee.

Certification rechecks canonical manifest/report bytes, the expected/accepted
exact sets, source batch Artifacts and every certificate binding field. Its Event
and projection watermark commit together. Source evidence loss, cancellation,
expiry or current authority failure denies both new certification and certificate
retrieval. Certified runs reject new attempts/acceptance, while exact old receipts
remain retryable. This store-level certificate is not yet a gate on all product
final/stream/replay/presentation/publication/download surfaces.
Cloud evidence lifecycle rows are locked in the same PostgreSQL transaction;
SQLite evidence lives in another database and only has observational rechecks,
not an atomic cross-database pruning boundary. Final Host/fence timing repairs
passed independent specification and quality reviews of the bounded component;
this does not authorize activation or establish all-surface product gates.

## Remaining COV-EXEC-01 work

1. Multipart continuation has completed separate native QUALITY (ten controls,
   zero skips). Repaired SSE
   contiguous-slice optimization and current grant's final report deadline have
   separate SPEC/QUALITY GO. The fixed semantic registry, prepared gateway,
   MODEL reservation/checkpoint/replay and empty/single same-Session Worker path
   are implemented and reviewed; they are not missing greenfield components.
   Multipart SPEC approved bounded many-record execution, not multi-part records,
   cross-Segment execution, live semantic accuracy or large-run performance.
2. Atomic strict admission and compatible-consumer routing are implemented with
   native Task admission and a hard handoff guard before lease/Inbox writes.
   Scoped SPEC/QUALITY and the final native matrix passed; production migration,
   rebuilt runtime and mixed-version rollout remain open.
3. Compose certified report GET/HEAD with the current signed Host grant and
   read-only frozen Task/run/manifest resolution. Bind issuer/Host/principal,
   namespace/origin/workspace, exact history resource and contract/source identity;
   verify both read scopes. Reuse the bounded read-only Cloud adapter and the
   exact bytes returned by certified_report, passing the verified expiry. Do not
   discover/renew bindings, copy private checkpoints or re-read an ordinary
   Artifact after the final gate. Refuse Range explicitly until supported.
   The existing resolve_frozen_manifest is an admission get-or-fetch writer,
   not a read-only report resolver. Authenticate/consume the fresh JWT once;
   repeated authority checks must not consume its JTI again. Frozen execution
   expiry or an unverified supplied deadline is not historical-read authority.
4. Wire paired Trench entry/report controls to those actual APIs. Absolute progress
   persistence and reload/cancel/reconnect UI passed component SPEC/QUALITY, but
   certified progress alone must never enable download. Current strict report
   failures must not trigger legacy download/share fallbacks.
5. Expensive semantic proof preparation is outside command lifecycle locks;
   final exact native/object checks are deadline-bounded and retryable. Retain
   original evidence, full-C reservations and final retention/fence checks.
   Repeated O(n) proof reads, long read-only snapshots/vacuum pressure, bounded
   proof-root optimization and measured live large-run latency remain open.
6. Verify signed Host + model + authenticated browser acceptance and fault
   recovery together with real PostgreSQL/MinIO. Component upload/crash/restart
   verification against real PostgreSQL/MinIO has passed; it does not establish
   a signed-Host/Worker/model/browser loop.
7. Integrate the reviewed slices into the requested target without overwriting
   unrelated dirty primary-checkout work. Current isolated tests do not establish
   that the primary checkout or running images contain these changes.

New admission/control-plane paths must be added to task ownership before editing;
Trench needs its paired task card. Whole-chain completion, merge/push, local image
replacement and deployment are separate proof/authority boundaries. Unit tests,
a build or `/health` do not establish whole-chain acceptance.

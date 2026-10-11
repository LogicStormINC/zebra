# Coverage full-chain closure implementation plan

> **For agentic workers:** Use subagent-driven-development and independent
> specification then quality reviews. Steps use checkboxes.

**Goal:** Complete durable canonical-body execution, guarded publication and the
Trench API/UI loop without changing exploratory task behavior.

**Architecture:** Reuse session Events, fenced PostgreSQL coverage indexes,
existing signed Host tools/Effect ledger and governed Artifacts. No new queue,
DAG or unrestricted HTTP channel. Explicit exhaustive admission freezes scope
and published check definitions. Unsupported checks never silently downgrade.

**Tech Stack:** Existing Python 3.12/Pydantic/PostgreSQL/S3 and React/Next.js.

## Chunk 1: Safe Artifact publication and bounded reads

Review clarifications: immutable writes and legacy writes share the same SQLite
transaction and exclusive-file path. Exact retries compare all immutable metadata;
orphan files are verified and adopted only for the same bytes, partial/conflicting
orphans fail closed. Every physical reader requests at most the allowed size + 1,
including storage preflight and S3 full/range paths, and closes streams on failure.
Prepared indexes bind the complete immutable snapshot and session and expire with
the grant; each cached body still calls the signed Host descriptor tool to check
current authorization without re-reading the Artifact manifest.

Cloud lifecycle mapping: stage immutable bytes through the existing coordinator,
append a dedicated artifact-materialized Event with metadata.artifact_uri under
the current mutation authority, then finalize its reservation against that Event.
Manifest binding and batch acceptance occur only after finalization. Recovery
reuses deterministic IDs and verifies the prior binding Event; uploaded but
unbound bytes never count as accepted coverage. The batch transaction remains the
single authority for result indexes, watermark and continuation intent.

Files: core ports/artifact_payload_store.py; storage artifact_payload*.py;
storage artifact_objects.py; integrations coverage_snapshot*.py; focused tests.

- [x] Add optional runtime-checkable immutable publication/bounded-read capability
  beside the legacy Port: existing callers remain unchanged. No write-first
  overwrite of deterministic IDs. Physical reads request at most limit+1 bytes.
- [x] SQLite implementation serializes same-ID metadata/file publication across
  processes using existing database transactions and exclusive file creation;
  exact retry returns existing evidence; conflicts/corruption fail without writes.
  A crash must not make conflicting bytes available as successful evidence.
- [ ] Cloud composition reuses PostgreSQL reservation/Event lifecycle and S3
  put_if_absent, rather than treating SQLite locks as multi-worker safety.
- [x] Adapter uses these capabilities for safe publication/bounded reads. Verify
  the manifest once per bounded prepared batch, build indexed exact membership,
  still verify Host authority for every body/cache read. No process cache can
  create authority or survive digest changes unchecked.
- [x] Tests: separate processes same/different payload, corrupt existing object,
  dishonest length, chunk limit, fresh instance recovery and manifest read count.

## Chunk 2: Durable executor and Worker composition

Files: core application/coverage*.py and ports/coverage*.py; storage postgres/
coverage*.py; Worker coverage*.py/execution.py/cloud_composition.py; tests.

- [x] Add frozen versioned check-runner contract and validate exact result keys,
  schema, source digest and evidence before any accepted unit. No model-written
  certification; program/model checks are explicit published definitions.
- [x] Read indexed missing units in fixed bounded batches. Part checks precede
  record merge; persist result Artifact before fenced idempotent commit. Restart
  begins at durable missing units, not a chat summary or in-memory cursor.
- [ ] Record run-wide usage, attempts and stopping reasons durably; cancelled,
  expired, revoked, budget-exhausted and stale-fence work never certifies.
- [ ] Worker handles admitted exhaustive tasks before exploratory Harness; live
  configured Host grant, frozen manifest, Effect receipt and mutation fence are
  required. Strict tasks cannot fall through on unconfigured capabilities.
  Compose the existing SemanticCoverageModel, CoverageModelInvocation and
  PublishedCoverageRunner with native Cloud artifacts and the pure derivation
  verifier. Fresh official metadata uses bounded TLS-only reads; recovery pins
  the original governed policy rather than silently replacing its capacity.
  Reuse native command wakeups, lease heartbeat and external authority checks.
  Split the existing 500-line execution composition before adding dispatch.
- [ ] Tests include crash-after-Artifact/commit-before-response, replacement lease,
  invalid model output, negative findings, empty set and 10,003 records.

## Chunk 3: Publication gates and API/UI

Prequeue wiring boundary (read-only trace, 2026-10-09): `CreateSessionPayload`
and `create_queued_session` currently omit coverage admission. Carry the typed
request through parsing, canonical idempotency hash, bootstrap and native atomic
Task admission; advertise support only when the real Worker factory is available.
Before model transport, compare the sealed manifest's required part-call count
against admitted call/runtime/token limits. Neither a fresh lease nor a queue
wakeup may renew the original deadline. Return durable refusal reasons rather
than letting unsupported strict work enter the exploratory Harness. The current
MODEL proof gate rereads the settled set under a 32 MiB settled-original volume
ceiling, not a cumulative physical-I/O ceiling. Large-run activation requires
bounded sharded proof verification or an explicit
early unsupported response, not accepting partial data or raising limits blindly.

Files: coverage application/storage/API adapters; final_completion.py;
execution_completion.py; paired Trench Host/BFF/ToC files claimed before coding.

- [x] Deterministic exact-set verification produces a durable certificate bound
  to report digest and Event watermark. Fixed report includes all findings.
- [ ] Enforce final/stream/replay/present/publish/download/business-write gates
  server-side with current authority. Uncertified strict tasks expose system
  progress or explicit stop reasons only; no free-text success inference.
- [ ] API returns absolute phase counters, scope/as-of/expiry, reason codes,
  keyset-paginated details and governed report download. Namespace/session checks
  apply on every request; no unscoped artifact URLs.
- [ ] Trench BFF forwards signed requests; ToC consumes backend facts, supports
  reload/cancel/reconnect and displays null ratios for legitimate empty scopes.
- [ ] UI tests cover running/stopped/certified/revoked/download states; strict
  entry controls only offer published supported scope/check capabilities.

## Chunk 4: Integration and acceptance

- [x] Repair inherited runtime-capabilities assertion without removing schema
  metadata or weakening production checks.
- [ ] Run focused tests, full suites and checks in both isolated repositories;
  review each chunk before successors, then perform whole-chain review.
- [ ] Test real isolated PostgreSQL/object-store/Host fault paths. A live model
  and logged-in browser are separate proof levels; never claim them from fixtures.
- [ ] Commit explicit paths, preserve dirty primaries and running services.
  Merge/push/restart/deployment require their own explicit instructions.

Commands (Zebra worktree, reuse installed primary environment):
```sh
PYTHONPATH="$(find apps packages -type d -name src | paste -sd: -):." \
 /Users/lukeding/Desktop/playground/2026/product/zebra-agent/.venv/bin/python \
 -m pytest -q
/Users/lukeding/Desktop/playground/2026/product/zebra-agent/.venv/bin/ruff check .
MYPYPATH="$(find apps packages -type d -name src | paste -sd: -)" \
 /Users/lukeding/Desktop/playground/2026/product/zebra-agent/.venv/bin/mypy packages apps
```
Expected: applicable checks pass; environmental skips and real E2E gaps are
recorded separately. No production activation with fixture-only check runners.

## Semantic rule decision (user authorized 2026-10-08)

The user selected semantic checks and delegated the first published rule. Version
1 performs evidence-grounded risk/uncertainty annotation of every canonical text
part: explicit harmful/operational-risk claims, conflicting assertions inside the
part, and consequential claims with missing qualifying context. These are source
annotations, not investment advice, external fact verification or a claim that
all real-world risk has been detected. Quotes must match immutable character
offsets exactly. Unsupported or inconclusive results remain unresolved and cannot
certify; model confidence never grants acceptance. Negative results mean no
finding under this fixed rule, not no risk in the real world. A frozen admitted
model profile is required; no test model or literal checker may replace it.

Semantic quality is separate from coverage completeness. Production rollout
requires labeled representative cases, finding precision/recall each at least
0.90 and zero acceptance of unresolved outputs; thresholds cannot be relaxed
after observing results. Representative live-model evaluation is still pending.
No additional human policy decision blocks implementation of the infrastructure.

### Immediate continuation checks

- [x] Implement `application/coverage_semantic.py` with frozen published rule,
  typed finding/clear/unresolved output and exact-source validation; deterministic
  regressions under `tests/agent_core/test_coverage_semantic.py`.
- [x] Bind configured `ModelGatewayPort` in
  `agent-integrations/coverage_model.py`; bounded strict JSON response, duplicate
  key rejection, no tool execution or model-originated certificate, before/after
  authority checks and model usage receipt callback. Validate with
  `tests/agent_integrations/test_coverage_model.py`.
  Component SPEC/QUALITY approved. Shared provider parser now rejects non-assistant
  wire roles before normalization. Callbacks still need durable Worker composition;
  production gateway must explicitly disable internal retries.
- [x] Add `domain/coverage_task_admission.py`, carry explicit request through
  `SessionBootstrapCommand`, `TaskPreparedPayload` and `RecoveredTask`. Extract
  the existing Task contract into `contracts/task_prepared.py` before extending
  the 499-line registry. Unknown check digest/profile, missing Host/history grant,
  or missing runtime capability must refuse rather than become exploratory.
  Tests must include legacy omission, fresh recovery and tampered definitions.
  SPEC/QUALITY approved after repairing bootstrap's backdated-event expiry check.
  Temporary shared Worker recovery refuses strict tasks before ordinary execution;
  API capability admission, configured dispatch and cross-session handoff remain
  unimplemented. Structural validation is not JWT verification or activation.
- [ ] Connect main Worker dispatch before sandbox/Harness provisioning; only a
  certified report may produce a successful strict task. Continue with Cloud
  factory/Effect reconciliation, continuation wakeup and all-surface gates.

Run focused pytest with the primary installed Python and worktree `apps/packages`
PYTHONPATH, then Ruff and Mypy. Each chunk needs independent SPEC then QUALITY
approval before the following implementation chunk. No activation or merge is
implied by a component-level green test.

## Current verification boundary

### Conservative MODEL token-bound candidate (2026-10-08)

For direct official DeepSeek Chat only, an explicit frozen proof contract may
reserve the provider's full input-plus-output context capacity per invocation.
This is an inference from the official [model metadata definition](https://api-docs.deepseek.com/api/list-models/)
and [Chat limit/usage contract](https://api-docs.deepseek.com/api/create-chat-completion/),
not a local context-window configuration or tokenizer estimate. Read-only
authenticated discovery on 2026-10-08 returned deepseek-v4-pro with a 1,048,576
input-plus-output context window and 393,216 maximum output tokens. This proves
discovery only: frozen metadata proof, transport composition and activation
still require implementation and acceptance.

Pin verified endpoint/model/profile/metadata digest, thinking/output settings and
proof-policy version to the actual prepared request. Disallow arbitrary proxies,
redirects, fallback profiles and silent metadata expansion. Changed metadata or
remaining authorized budget below the full reservation refuses before transport.
Require exact integer usage with total equal to prompt plus completion; reasoning
is included in completion, cache-hit input is not free token usage. Finalize and
verify the complete immutable response before usage settlement releases headroom.
Missing output/usage remains fully charged and unresolved. This relies on the
provider honoring its public contract, is not a monetary-price guarantee, and
does not resolve semantic quality or authorize deployment.
The existing ordinary Worker authority defaults to 200,000 model tokens, below
this conservative per-call reservation. Do not silently enlarge grants or use
an input estimate to bypass that mismatch. Strict admission must explain the
insufficient authorized budget before queuing model work; the Host must grant
an adequate explicit budget, or a separately verified tighter bound is required.

### Next Worker bootstrap dependency

Before Cloud publication, prepare the signed descriptor and complete bounded
canonical manifest without an Artifact store. Reuse the adapter's descriptor,
page, membership, authority and allocation checks; do not introduce a second
enumerator or a fake/unbound Artifact facade. The prepared value contains the
descriptor, exact records, canonical bytes and deterministic manifest identifier.
An `artifact://` intent is not readable evidence or a completed snapshot.

Cloud composition can then construct the full `CoverageRunBinding`, verify its
manifest digest, publish through the existing fenced immutable publisher and
only afterwards bind the run. Legacy adapter creation/get keep their current
publication and read-back behavior. Preparation is a dependency, not activation.
Tests must prove no Artifact I/O during preparation, exact identity/bytes, fresh
authority and budget refusal, plus unchanged legacy corruption/recovery behavior.
This dependency is implemented in `coverage_snapshot_source.py` and approved by
SPEC/QUALITY. It adds 58 preparation regressions; all 159 snapshot tests pass.
Current full Python suite: 5,472 passed / 1,018 skipped. Actual Cloud bootstrap
composition is still the next step, not proven by these source tests.

Cloud bootstrap is implemented next in `apps/worker/coverage_bootstrap.py` with
focused `tests/worker/test_coverage_bootstrap.py`: explicit configured source,
frozen admission and current Host identity; deterministic run/snapshot request;
full binding before constructing CloudCoverageArtifacts; immutable publication,
verified finalized read-back, then PostgresCoverageStore.bind. Fresh-instance
retry must reuse the same manifest Event/object and must not bind a staged or
revoked manifest. Real PostgreSQL tests use only fixture-owned schemas; fake S3
is not a real object-store acceptance claim. This component precedes main-loop
activation and does not replace durable model/time budget or Effect composition.

Bootstrap component SPEC and QUALITY re-reviews approved. Final bind pins the
verified stream revision and Task-binding digest in the same locked transaction;
changed admission Events and binding renewals refuse before manifest/run writes.
Main scratch PostgreSQL bootstrap selection: 79 passed, zero skipped. This does
not approve main-loop activation; Effect replay and durable usage remain next.

Strict dispatch must branch after fresh Task recovery and bound Host validation,
but before ordinary model construction, sandbox provisioning or tool execution.
The temporary recovery refusal stays until one configured Cloud composition
supplies snapshot preparation, fenced Effect reconciliation, governed Artifacts,
the frozen model profile and durable usage callbacks. A receipt alone is not a
snapshot descriptor: recover the original durable Effect output or query the
Host's operation status before accepting create. Never create again with a new
idempotency key to hide an uncertain write.
The shared Effect guard keys writes by canonical arguments and may return the
original ToolResult on replay. CoverageInvocation now derives a stable create
ToolCall ID from the exact key and bound request; read-only calls remain unique.
The admitted snapshot callback must preserve this stable
call identity (or remap only a verified exact-identity durable result), not reject
an otherwise valid replay or mint another Effect. Reconciled generic receipts
contain no descriptor; successful reconciliation still requires authoritative
snapshot discovery/read-back before manifest enumeration.

Next focused Effect prerequisite: snapshot create requests must use a stable
ToolCall identity derived from the exact admitted opaque idempotency key and complete
business request/Host binding, independently of timestamps or process. Keep
read-only calls unique. The shared CoverageInvocation callback must receive the
same identity on an exact retry, so the existing fenced ledger's authoritative
ToolResult passes its ID check. Different namespace, key, manifest or arguments
must not alias. Test a fresh invocation instance returning the original stored
result, wrong-result IDs, missing keys and uncertain content-free receipts.
This is not permission to retry an uncertain write or bypass admitted Effects.
Existing adapters explicitly preserve nonblank opaque keys, including surrounding
whitespace. Therefore hash and forward the same original validated key; do not
trim only one side or change legacy Host key behavior. Distinct raw keys must
have distinct call identities, while exact raw-key retries reuse the same ID.

Before strict dispatch, model calls/tokens/time need durable reservations under
the same run/Task/fence transaction. A restart cannot reset limits, a malformed
or absent usage receipt cannot refund an uncertain request, and concurrent
Workers cannot independently spend the same budget. Persist reservation and
receipt identities, pin the original deadline, disable provider retries and
check current authority before reservation, invocation and certification.
Attempts/input-byte migration 79 alone does not enforce these model/time limits.
The durable model reservation must bind the exact unit/source/request digest and
admission digest, consume one call before transport, and reserve the admitted
token ceiling before invocation. A valid matching usage receipt may reconcile
that reservation; missing/malformed/conflicting usage leaves it charged and
unresolved. Reservations and receipts must be authoritative Events with indexed
rebuild/replay, not only mutable counters. The deadline is frozen from the
original persisted strict admission boundary, never a replacement lease's clock.
Provider input-token estimation is not exact coverage or a hard provider quota:
if a profile cannot establish a supported request/output bound, refuse that
profile rather than claiming an estimate guarantees the admitted spend ceiling.

Next model-budget storage slice must be cohesive, not an in-memory callback:

- Frozen policy comes from validated persisted Task admission, with the original
  start/deadline and profile; caller-supplied quota changes are refused.
- Additive coverage migration stores reservation/receipt indexes under the run.
  Existing Session/lease/Task/run/stream lock order guards all mutations.
- Reserve call and caller-proven token bound before transport; exact retry of an
  unresolved reservation returns state, never permission to invoke again.
  Changed unit/source/request identity under the same reservation key conflicts.
- Receipt requires exact integer input/output/total counters, matching profile,
  reservation and request identity. Total must cover input plus output and not
  exceed its reservation. Unknown usage remains charged; malformed receipts do
  not delete or refund reservations. Duplicate exact receipt is idempotent.
- Authoritative reservation/receipt Events and their projection update together.
  Recovery/rebuild checks exact Event identity and frozen policy; edited or
  missing source Events cannot manufacture remaining quota.
- Strict certification checks frozen deadline, charged quota and zero unresolved
  reservations. Legacy program-only component tests remain compatible.
- Real isolated PostgreSQL tests cover concurrent spend, replacement lease,
  restart/no deadline reset, invalid/conflicting/missing usage, exact receipt
  replay, unknown request charges and rebuild/certification refusal.

This storage slice alone cannot advertise runtime support. The configured model
adapter still needs request-bound callbacks, a supported token bound and
max_retries=0 before strict Worker admission becomes available.

MODEL callback recovery must also cover the response-to-unit crash window:

- Bind the actual text-only request and invocation policy to the reservation,
  excluding transient message IDs/timestamps from business replay identity.
- Persist the bounded original completion/usage as governed immutable evidence
  before acknowledging settled usage or accepting the derived unit.
- A replacement Worker with an existing reservation may consume only the exact
  verified original output; `invoke=False` never becomes a second provider call.
- Missing output/usage after uncertain transport stays explicitly unresolved and
  charged. Do not invent a receipt or reuse a successful unrelated response.
- Replayed output still passes current authority, profile, rule, source identity
  and semantic validation; checkpoint existence is not accepted-unit coverage.

Prepared-request prerequisite (before durable MODEL callback composition): reuse
`OpenAICompatibleModelGateway._request_body` and `parse_completion`. The opt-in
coverage path freezes canonical wire bytes, resolved profile and request metadata
once, and its single-shot send consumes exactly those bytes without resolving
again. Refuse tool-bearing, streaming, redirected or alternate-provider paths;
disable internal retries. Freeze gateway endpoint/provider ownership so another
gateway or changed configuration cannot send a previously prepared request.
Mutation/forgery and transport failures need deterministic regression checks.
Ordinary complete/stream callers keep existing behavior. This capability alone
does not establish a supported total-token bound or runtime admission: those
require the separately verified official endpoint/model metadata policy, durable
reservation, completion checkpoint and usage receipt linkage described below.

Crash acceptance matrix for the durable MODEL callback (not yet implemented):

| Durable state | Replacement behavior |
| --- | --- |
| Reservation only, no verified completion | Charged/unresolved; no second call |
| Finalized completion, usage unacknowledged | Verify exact request/unit/output, then idempotently acknowledge usage |
| Usage acknowledged, unit missing | Read original completion and validate under current authority; never invoke again |
| Missing/corrupt/foreign completion after acknowledgment | Deny acceptance/certification; do not synthesize or refund |
| STOP, revoked authority, expired grant or stale fence | Deny new invocation, acknowledgment and acceptance |

Completion serialization must explicitly preserve provider reasoning fields that
SessionMessage excludes from its ordinary public dump. Reuse typed completion and
metadata contracts, reject malformed raw values before normalization, and bound
checkpoint bytes without truncation. Deterministic checkpoint identity binds the
full run/admission/reservation/request, excluding replacement fence and transient
message identifiers. A checksum or receipt without a verified finalized payload
is insufficient proof. Certification must lock/check checkpoint lifecycle through
the existing Cloud Artifact transaction boundary, not rely on callback-only
validation or on `unresolved == 0` after a response has been lost.

Durable callback integration boundary (code trace, 2026-10-08):

- Keep `ModelCompletion` serialization in integrations; storage must not import
  provider adapters. The stored envelope additionally binds schema, the full
  run/admission identity, exact reservation and prepared request digest. Its
  deterministic Artifact ID is derived from those identities, not response
  content, Worker fence, wall clock or message IDs.
- Use the existing `CloudCoverageArtifacts.store_payload_immutable` and bounded
  read-back; no new object store or queue. A reserved call can publish only its
  original response. Publication conflicts never select a later response.
- The full completion is internal recovery evidence, not a user presentation
  Artifact. Provider reasoning remains excluded from public chat, AG-UI, asset
  listing/preview and download paths. API ownership alone must not turn internal
  checkpoint bytes into a downloadable report; add negative surface tests when
  enabling checkpoint composition. Publish only the validated semantic report.
- The current `CoverageModelUsageReceipt` contains only reservation/counters.
  Before runtime activation extend its strict evidence contract to carry a
  canonical checkpoint reference/digest. Verify the finalized checkpoint under
  the existing co-located lifecycle lock before receipt mutation and exact
  replay. Do not settle/refund a call solely because a callback returns usage.
- `certify_model_budget` currently replays budget Events but checks only
  unresolved count/deadline. All certificate issuance/replay/read gates must
  verify the original settled checkpoint linkage and pinned lifecycle too.
  Storage can validate the neutral envelope/usage fields without decoding the
  provider response; integrations must independently decode and verify the full
  completion before semantic acceptance. Neither replaces the other check.
- Existing reservation-only component tests remain useful, but strict admitted
  tasks must not accept legacy receipts without evidence. An unsupported legacy
  or malformed checkpoint fails closed; never silently upgrade its identity.
- Clock/lease/STOP/revocation checks still apply to response persistence,
  acknowledgment and replay. A response returning after the original deadline
  does not reset the budget or authorize publication.
- `bootstrap_cloud_coverage` currently constructs its store with an empty
  supported-model profile set. Compose supported profiles only from the verified
  configured gateway/proof policy, not from user admission text, and do so before
  initializing the ledger. This is another reason the approved bootstrap/codec
  components do not yet make MODEL execution available in the running product.

Snapshot-create callback integration likewise preserves the exact opaque Host
key through the existing fenced Effect dispatch and replays the original Tool
result. A reconciled generic business receipt is not a snapshot descriptor.

Next callback and Worker acceptance boundary (2026-10-08):

- The semantic adapter currently reserves through a zero-argument callback and
  then calls ordinary `complete`. Replace that strict path with one composed
  invoke-or-replay callback receiving the actual messages and invocation policy.
  Prepare the transport bytes first; reserve their exact digest before I/O.
  Fresh message IDs/timestamps do not participate in the provider wire digest.
  Keep legacy adapter callers unchanged; an unconfigured strict path must refuse.
- The semantic callback must verify the full completion codec independently of
  storage's neutral envelope checks. Persist and read back the original complete
  response before settling usage. A reserved, unacknowledged call is not permission
  to invoke a second time; an existing finalized checkpoint is the only recovery
  source. Apply the original deadline and fresh authority at every boundary.
- Every accepted MODEL part must bind its exact unit key and observation digest
  to a verified settled response. All-call settlement alone does not establish
  unit coverage: one settled call cannot certify two unrelated model parts.
  Record merges remain deterministic and must bind every prior part result.
- Persist the exact prepared request bytes alongside the original response on
  the strict composed path. The current response envelope proves a matching
  request hash, not what that request contained. Before unit acceptance, verify
  those bytes hash to the reservation, include the frozen rule and exact unit,
  and carry source text matching the immutable manifest's part digest/length.
  Otherwise one response hash could be attached to an unrelated source body.
  Additive codec compatibility may retain old envelopes for legacy budget reads,
  but a response-only envelope must not certify MODEL unit derivation. Keep raw
  request/private response bytes internal and inside the existing byte ceiling.
  For v1 semantic derivation, require exactly the generated system/user message
  pair, exact published instructions, a strictly parsed user object with only
  key/bodies, and the one admitted part. Re-encode its source string as UTF-8
  and verify manifest part digest/byte length before validating response quotes.
  Arbitrary historical messages, duplicate embedded JSON keys or a different
  rule must not pass merely because the outer request digest matches. This proves
  provenance under the trusted transport/Worker boundary, not external factual
  truth or cryptographic attestation that a remote model reasoned correctly.
- The integration derivation helper alone cannot authorize storage acceptance.
  The same proof must guard first batch commit, exact commit retry, projection
  rebuild, first certification and certificate replay/read. Validate raw typed
  commit inputs before `model_dump` can erase extra attributes. Bind the result
  digest to the derived observation and deterministic merge inputs; reject an
  otherwise complete accepted-unit set without that per-unit evidence. Do not
  import provider adapters into storage: compose the existing integration proof
  callback at the application boundary and keep authority/lifecycle under the
  storage transaction. No configured verifier means no strict MODEL acceptance.
- Uncertified projection rebuild must verify original settled-response bytes,
  header and current lifecycle before restoring ledger/call projections. A
  linkage-only fallback cannot recreate refunded transport authority. New calls
  must likewise refuse when the settled evidence supporting available headroom
  has become unavailable; test different reservation keys, not just exact replay.
  Existing projections do not make a failed rebuild's next invocation safe.
- Retention is a time boundary as well as a locked lifecycle boundary. Preserve
  the earliest verified settled-checkpoint retention deadline across sequential
  object reads; use a fresh clock before returning authority or committing
  reservation/refund/rebuild/certificate mutations. A run deadline check alone
  does not preserve already verified evidence. Acceptance must expire the first
  checkpoint during a delayed second read and prove complete rollback.
- Private checkpoint IDs must not resolve through user Artifact lists, detail,
  content, inline/range preview or download, even with `artifact.read` and an
  otherwise authorized Session. The existing public reader resolves the Session
  Artifact projection, not payload metadata; checkpoint publication must not
  create that projection. Prove this with negative surface tests before activation.
- Main Worker dispatch currently constructs the ordinary model gateway before
  preparing bound Host context. Strict dispatch must precede that construction
  and sandbox provisioning, after fresh Task and bound Host verification. Retain
  the recovery refusal until the configured composition covers these dependencies.
- Provider model-list authentication can prove identity/availability, not a
  context-token ceiling if the response omits that field. A supported admission
  must pin the independently published capacity policy as well as the verified
  endpoint/model/profile; model IDs alone or local defaults do not prove capacity.
  Explicit live capacity fields need their published meaning and frozen metadata
  evidence, as established by the read-only discovery below.

Current provider evidence (2026-10-08, non-activation): read-only authenticated
`https://api.deepseek.com/models` returned HTTP 200 and exactly one reviewer model
`deepseek-v4-pro`, `owned_by=deepseek`, `context_window=1048576`,
`max_output_tokens=393216`, text-only modalities and HIGH effort support. The
[official list-models contract](https://api-docs.deepseek.com/api/list-models/)
defines context capacity as input plus output. Future composition must freeze
and strictly validate these actual values and the pinned endpoint/profile before
using the full-capacity reservation bound; a documentation example, environment
key or a successful discovery request alone does not activate transport. The
local profile's 1,000,000-token default is not that discovery result. No generation
or semantic quality acceptance was performed by this read-only request.

Paired Trench read-only tracing confirmed the current mapper and progress UI
only consume generic narration/tool metadata; they do not carry authoritative
coverage phase counters. Future paired task must cover runtime request types,
signed Zebra task submission, `trench_ai_zebra_event_map.py`, durable Turn metadata
and the typed frontend chat API/progress component together. Do not infer
coverage from tool counts or a generated summary. Propagate dedicated absolute
scope/unit counters, stage and stop reason through stream plus snapshot replay,
and keep the published report download behind current user/Host authority.
No edits have been made to Trench or its running frontend during this tracing.

Next transaction acceptance slice must compare every MODEL part's accepted
digest/outcome with the observation derived from its exact settled v2 original
request/response and frozen manifest part. Accounting alone is insufficient.
Use an explicitly composed pure derivation callback rather than importing a
provider package into storage. Missing composition must refuse strict MODEL.
Apply the same proof to first commit, exact retry, rebuild, first certificate
and current certificate reads; compare deterministic record merges with all
canonical matching part observations. Preserve raw typed inputs before
model_dump can erase illegal attributes. Carry earliest retention through final
locked time checks, and add real PostgreSQL corruption/retry/rebuild cases.

Measured component debt (independent QUALITY, 2026-10-08): a fresh invocation
performs 26 bounded Artifact reads; settled replay performs 15. These are fixture
read counts, not S3/PG/user latency. Baseline native whole-run reads/bytes and
memory before optimization; keep all current lifecycle/authority checks. A
cached digest does not prove an original object still exists. The existing
settled-checkpoint gate also remains O(n) per new call / O(n²) cumulative. Do not
activate large-run support on the basis of keyset paging or mocked timing alone.

Native admission currently caps signed Host model tokens at 10,000,000. With
the observed combined capacity C=1,048,576, even the maximum grant permits at
most nine simultaneous full-C reservations before settled refunds; the common
200,000 grant permits none. Future concurrency must derive its bound from the
remaining admitted tokens and configured C, never silently raise grants or
weaken uncertain-call charges. Original Task runtime remains a deadline, not
renewed by batch wakeups or lease replacement. Measure provider plus native
storage latency before promising a 10,000-unit run inside that window. If the
scope cannot fit, admission must explicitly refuse rather than stall or publish
a partial report labelled complete. Batching needs a separately frozen exact
multi-unit wire/checkpoint rule, not reuse of the single-unit rule with hidden
extra bodies.

The paired progress contract must distinguish preparation, processing,
validation and certified completion. Preparation is not complete until the
signed snapshot and immutable manifest are published and read back. Processing
counters come from accepted exact units, not model narration, started calls or
tool counts. Validation may show remaining missing/unresolved units; only the
canonical certificate Event plus a fresh publication gate may mark completion.
Expose absolute counters and run identity/source watermark in both stream and
snapshot so reconnect replaces state rather than adding replayed deltas twice.
Task STOP, expiry and failure must terminate the spinner while preserving the
incomplete counters and concrete refusal reason. A generated final-looking
paragraph must not imply certified completion or keep a terminal Task Working.

Continuation intent already exists in `coverage_continuations`; it is currently
dormant. Claim/recovery must reuse Task/Session lease boundaries rather than a
new queue. Resume only from durable missing-unit indexes with current authority;
STOP/expiry/revocation must prevent scheduling and certification. Cross-session
handoff must preserve the complete typed strict identity or explicitly refuse,
never synthesize an exploratory child Task.

The native command consumer ACKs scheduling, not completion. Its generic
recovery refuses post-floor Events or a started execution as uncertain. Strict
coverage therefore needs an explicitly proven continuation/reconciliation path
under the same native boundaries; merely calling execute_batch cannot guarantee
crash recovery. Do not relax uncertain-program recovery for ordinary tasks.

Strict handoff v1: explicitly refuse at the SQLite/PostgreSQL commit boundary
when persisted source Task Events carry non-null coverage admission. Inspect
source Events inside the already locked transaction, not request/workspace
projections. A later Task Event omitting admission cannot erase this boundary.
Refusal must leave parent/child Events, lineage, envelope and dispatch unchanged;
legacy sources retain their existing commit/replay behavior. Full strict child
binding/re-certification is not supported by the current handoff contract.


- Storage/prepared-reader specification and quality reviews approved. Executor/
  publication specification review repairs include missing/pruned batch or
  manifest evidence, full certificate binding, large multipart records and
  Artifact retention. Specification approved the component scope. Quality review
  found lifecycle/cancellation races and allocation-before-bound defects. Repairs
  passed final independent specification and quality re-reviews for this bounded
  component. Quality independently reran 15 focused real-PostgreSQL regressions.
  This approval excludes Worker/admission/API/UI activation and whole-chain acceptance.
- Full Python suite after final timing repairs: 5,188 passed / 1,018 skips.
  Final independent real PostgreSQL selection: 116 passed, including the added
  boundary regressions and Worker facade tests. Three tests passed against
  isolated real PostgreSQL/MinIO, including upload/crash/restart recovery and two
  independent processes producing exactly one materialized Event/object version.
  Only a unique owned test bucket was created/removed.
  Core allocation-bound regression selection after repairs: 47 passed.
- The first semantic rule was authorized above. Its bounded validator passed
  independent specification and quality review, including raw/typed response
  parity and injected unknown fields before serialization. The focused semantic
  file has 66 passing tests. Configured gateway activation and live semantic
  quality evaluation are still pending; literal checks cannot substitute.
- Ruff and Mypy (1,032 source files), tracked-and-new file-size gate (2,404 files) and deterministic
  eval (30/30) pass. These do not establish real Worker/model/Host/browser closure.
- Typed strict Task admission and fail-closed recovery are implemented; the API
  has not exposed configured admission and the production SessionExecutionService
  coverage route is still absent. Strict recovery explicitly refuses unsupported
  composition rather than falling through to exploratory execution. The Cloud
  facade and certificate store remain components, not product integration.
  Trench remains unmodified; the main user request is not complete.

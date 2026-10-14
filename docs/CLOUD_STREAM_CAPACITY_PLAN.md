# Cloud stream CAPACITY and GC implementation plan
Claimed2026-10-14 from Ready after RELAY component local integration6bea341d.
Human owner Luke Ding; executor Codex; branch codex/cloud-stream-capacity-01.
Exact source/test paths below plus this plan and AGENT_TASKS/PROGRESS/task_plan/
WORKLOG governance are owned. Accepted WRITER/ADMISSION/RELAY transfer only these
serial capacity/expiry/accounting boundaries; canonical appender/Recorder/coverage
proof writes and reliable STOP remain owned elsewhere. No migration is reserved:
current catalog tail101 remains unchanged unless a demonstrated need is declared.
No push/deploy/business DB/paid-model/service restart is authorized.
Full inclusive80% and complete Worker/SDK/browser/fleet acceptance remain later gates.
Original PERF10 failures and RELAY TLS/full-runtime limits retain their evidence.

## One coherent first slice
Transient Redis retained-capacity admission/accounting/expiry only. Reuse existing
Lua CAS/full fence/digest/offset/Redis TIME checks and immutable RunStreamAdmission.
No new dependency, generic quota service, per-delta PG table, canonical write change,
reliable STOP/display ACK or canonical-hint GC. Canonical-hint capacity remains its
own explicitly scoped follow-up; this quota is not a claim about all Redis RSS.
## Frozen policy and compatibility
Add optional typed capacity policy to server-owned RunStreamAdmission and writer
authorization. Freeze policy version, canonical digest, aggregate epoch, generation/
Run/tenant/deployment byte+row+retained-generation ceilings, metadata charge bounds,
active hard lifetime and ended retention. Positive strict finite values; no bool/
float coercion/unbounded defaults; Lua-accounted integers<=2^53-1. Mode/capabilities unchanged.
Server admission selects policy; clients cannot supply it. Canonical policy digest
is validated separately from existing client intent fingerprint. Duplicate command
idempotency returns original accepted policy even after config change, never current
settings; same-generation retry/renewal must match its original policy fingerprint.
Initial named defaults are review starting values, not measured production optima:
generation frame JSON<=8MiB/8192 rows; Run charged<=32MiB/32768 rows/32 retained slots;
tenant<=128MiB/131072 rows/128 slots; deployment<=512MiB/524288 rows/512 slots.
Retained slot includes a reservation or active/retired generation, never only current.
Fixtures lower limits to prove exact boundaries; finite configured Run ceiling may
be up to256 for the explicit256/257 test. New generations never reset aggregate caps.
Old absent stream admission stays legacy. Old V2 admission missing capacity policy
keeps V2 mode but refuses provisional activation conservatively. It must NOT take
ordinary_v2=False/legacy delta persistence fallback: register the actual V2 call as
transient-only before policy rejection, reset drafts and continue durable response/
final facts. Malformed policy/accounting also fails only provisional publication.
No authority expansion; fresh Host/Lease/Turn/source/ordinary-public checks unchanged.
## Aggregate identity and epoch
Run key hashes deployment + signed issuer + opaque namespace + TaskId + RunId,
excluding Segment/Turn/Attempt/call/generation and allowed-session sets. Tenant key
hashes deployment + OpaqueAuthorityScope.scope_key(issuer,namespace); deployment
key covers all tenants. Derive only from verified gate/admission, never frame claims.
First slice pins one aggregate quota-policy epoch until ALL retained slots drain.
A mismatched epoch/digest cannot open a parallel full-cap ledger or weaken an older
cap; deny new provisional admission, canonical execution continues. Policy changes
requiring simultaneous epochs need a separate explicit aggregate-cap rule, not here.
One bounded initialization/cutover seals the owned epoch before enabling publication;
activation does not auto-recreate missing ledgers. Empty first-use Run/tenant records
may be created only in the sealed epoch by verified admission; surviving-key accounting
loss is never an empty-record reset and fails closed pending bounded recovery.
Standalone Redis only: lane tags and cross-lane aggregate keys occupy different
Cluster slots. Reject unsupported Cluster composition; never replace atomic Lua with
separate cross-slot check/increment commands. No cross-deployment counter aliases.
## Atomic admission and retained accounting
Extend specific SNAPSHOT/ACTIVATE/PUBLISH/INVALIDATE paths, not a query/compiler layer.
Before FIRST quota/key mutation, call existing _resolve(authorization): exact actual
gate, frozen admission/policy, scope and trusted Grant must validate; constructed
authorization or cached bool is insufficient. Then SNAPSHOT reserves metadata/slot
with TTL<=30s clipped by verified Grant. After SNAPSHOT keep the existing fresh full
source/Host/Turn/Lease/privacy _resolve and ACTIVATE CAS; reservation grants no authority.
Measure/report both activation SQL proofs, including rejected calls; never hide added
SQL as SQL0/frame. ACTIVATE converts reservation once with absent-state ABA protection.
Initialize first generation count to1; replacement increments exactly once, including
multiple processes/restarts. Process-local4096 handles/256 calls are not quotas.
One per-generation accounting record retains exact frame bytes/rows, frozen policy,
aggregate identities and expiry while body/offset keys remain. Reserve a bounded
metadata allowance per slot (initial64KiB) covering bounded key/descriptor/control/
ledger/index fields; separately charge a validated per-offset serialized bound
(initial512B, fixed digest/cursor/offset fields) per appended frame. Validate those
bounds BEFORE writes; reject field growth above them. Global charged bytes include
frame UTF-8 JSON + metadata reservation + offset charges, not frame bodies alone.
Redis physical encoding/allocator overhead is measured separately, not claimed exact.
Atomic script checks all three aggregate byte/row/slot caps before new mutation.
Duplicate offset+digest returns original cursor without new charges, even at cap;
mismatch/gap rejects. Same-generation activation/renewal/uncertain-reply retry never
charges again. Replacement retires old scope but NEVER subtracts its retained charge
or resets old counters until keys are deleted/expired. Prevalidate key types/ranges/
policy first; Lua errors do not roll back earlier commands. Each mutation first seals
a bounded per-record dirty operation intent and GC index, then retains all required
charges BEFORE body/offset/control creation. Clear dirty only after related mutations
finish. Dirty/uncertain operations block continued reads/activation/renewal/publication;
never return success or refund uncertain partial writes. Keep conservative overcharge
until bounded indexed recovery, with exact operation ID/phases; no blind additive retry.
## Expiry, bounded cleanup and old keys
Freeze each generation's active hard maximum at first activation, clipped by original
Grant and finite execution/recovery lifetime (default active retention ceiling3600s).
Renewal/read/discovery never extend that maximum. Ended expiry is min(close-time+
configured<=600s, original hard maximum, Grant expiry); close cannot lengthen it.
Both frames and offsets use the SAME effective deadline. Accounting/index records
must survive until those keys are removed; first laneend cannot erase records for
later generations whose body keys still live. Closed readers continue to resync.
Redis TIME due index tracks every reservation and retained generation, not only the
active pointer. Index/accounting cardinality is bounded by deployment slot cap;
Run/tenant ledger records are charged/bounded and removed when no retained slots.
GC seals dirty, deletes exact body/offset/control keys BEFORE subtraction, then uses
release-once per-aggregate operation seals with counter+seal in ONE hash mutation,
so failure between aggregates/replies cannot double-release. Keep index until fully
settled; dirty recovery is bounded by the same batch/slot ceiling, preserves charges
when uncertain, and never enables another operation on an incomplete record.
No keyspace-notification dependency, full SCAN/body reconstruction in admission,
per-reader maintenance or sliding read TTL. If cleanup batch cannot make enough
space, reject provisional admission conservatively rather than looping unboundedly.
Reuse accepted RELAY cadence/deadline/lifecycle pattern for one Worker-owned capacity
maintenance client: <=32 due records per tick, one total<=2s IO budget, non-overlap,
local expected-failure backoff and owned close. Opportunistic admission cleanup uses
the SAME bounded work rule; no unbounded script loop/global lock scan. Record delete/
UNLINK logical release versus asynchronous physical memory reclamation explicitly.
Existing unaccounted keys cannot be ignored via a new prefix/epoch. First cutover
requires old provisional writers quiescent (disabling new Run admission alone does
not stop frozen old V2 Runs), then documented max old TTL drain and bounded scoped
inventory/recovery, or an explicitly owned bounded migration. Until that completes,
new global-cap certification/admission remains off. Never delete canonical/coverage/
Artifact keys or silently bulk-clean another prefix. Redis restart/eviction/deleted
accounting with surviving bodies is an explicit failclosed/recovery test, not zero.

## Claimed minimum source paths (12)

Core: packages/agent-core/src/agent_core/domain/stream_admission.py;
packages/agent-core/src/agent_core/ports/transient_output.py;
packages/agent-core/src/agent_core/contracts/session_commands.py.
Integrations: packages/agent-integrations/src/agent_integrations/redis_transient_scripts.py,
redis_transient_output.py, redis_transient_discovery.py (aggregate key derivation).
API/config: apps/api/src/zebra_agent_api/command_submission.py;
apps/config/src/zebra_agent_config/stream_settings.py.
Worker: apps/worker/src/zebra_agent_worker/transient_output_composition.py,
transient_output_runtime.py, worker_loop_service.py, loop.py (maintenance lifetime).
No migrations/Recorder/appender/receipt/coverage/RELAY implementation edits implied.
If file limits require a focused Lua quota module, add its exact path BEFORE coding;
do not pre-authorize a generic ledger framework or broaden owned source folders.

## Claimed tests and required native evidence

NEW tests/agent_integrations/test_redis_transient_capacity.py; existing
 tests/agent_integrations/test_redis_transient_output.py, test_run_stream_admission.py;
 tests/agent_core/test_transient_output_contract.py;
 tests/api/test_stream_command_admission_api.py;
 tests/worker/test_transient_output_runtime.py, test_transient_output_native.py,
 test_transient_output_composition_native.py;
 tests/config/test_stream_settings.py; NEW tests/worker/test_transient_capacity_maintenance.py.
Real two-Worker/two-lane races prove exact Run-across-Segment, issuer/tenant/deployment
caps. Test first slot, exact cap/+1 including256/257, empty reservation, duplicate at
cap, mismatch/gap, replacement with retained old keys and lost activate/append reply.
Test forged gate/scope/issuer/tenant/deployment/Grant and forbidden private/coverage:
ZERO reservation/quota mutation. Inject failure after early writes in SNAPSHOT,
ACTIVATE/PUBLISH/INVALIDATE/GC; verify dirty blocks reads/writes, bounded recovery,
no uncharged/unindexed body, early refund/double release/negative count. Test wrong
key types before writes, TIME TTL/reads-not-renewing/restart/concurrent GC/corruption.
Test config/idempotency/epoch conflicts and old missing-policy/old-key cutover; cap
exhaustion still produces real durable response/final commit and never V1 delta writes.
Retain full Lease/Host/privacy/cursor fencing; reject Cluster; bounded GC plan/steps,
index cardinality, SQL0/frame, inclusive renewal/maintenance SQL, Redis commands/script
CPU/latency/socket/RSS/offset/control overhead and physical memory lag are reported.
Focused checks precede independent SPEC→QUALITY; later full Worker/SDK/browser and
matched-work SQL/capacity/fault acceptance remain OPEN until actually run.

## Execution convergence

Audit all affected callers/old-V2/idempotency/fixture families before choosing
implementation. Reuse installed Lua/CAS/deadline/lifecycle patterns, with no generic
quota framework. Any new focused Lua/helper module or extra test module must have
its exact ownership declared before editing. Respect500/700-line limits; the
Worker loop is already482 lines and should delegate to existing composition.
Do not stop at unit-only quota arithmetic: the native minimum above is part of
component acceptance, especially real races, uncertain-write accounting, dirty
recovery, GC release-once, private/coverage denial and no V1 SQL fallback.
Use one coherent concentrated native/static batch and consolidated SPEC/QUALITY;
classify same-family failures together, keep raw evidence, do not replay previous
PERF/RELAY matrices blindly. Use clean exact-source validation with proper Git index,
resolved import paths and existing dependency environment; archive copies stay
immutable outside source gates. All additions count in later inclusive SQL/latency.

### Focused source ownership extension before editing — 2026-10-14

Add packages/agent-integrations/src/agent_integrations/redis_transient_capacity.py
for the specific atomic retained-quota/GC Lua and explicit epoch sealing; not a
generic ledger service. Add
apps/worker/src/zebra_agent_worker/transient_capacity_maintenance.py for bounded
capacity maintenance using accepted RELAY deadline/non-overlap/owned-close behavior.
The existing482-line loop composes the small maintenance object only. Initial
cutover configuration stays OFF; global-cap certification requires old writers
quiescent plus bounded inventory/TTL-drain proof, not merely a new key prefix.
Other source ownership remains the original12 paths and catalog tail101 unchanged.

### Consolidated review closure — 2026-10-14

The final review identified a GC corruption boundary: mutable record keys alone
cannot prove which bodies belong to a charged record. Reopen only the already
owned redis_transient_capacity.py and redis_transient_output.py to bind original
keys/generation/aggregate identities/policy in the independent ledger, atomically
with its charge. Charge/read/cleanup validate that binding before body operations;
its bounded overhead remains inside the metadata reservation. Add one same-prefix
wrong-body regression to the already owned capacity test module. This is the
existing corruption/delete-before-release requirement, not a new quota framework.
If the ledger/binding is lost, mutable records cannot authorize deleting bodies
or certify an empty cutover. Keep admission and recovery failclosed until explicit
owned inventory/TTL-drain certification; natural body expiry is not automatic
ledger reconstruction or proof that all historical keys have drained.

Before caller edit2026-10-14 add
apps/api/src/zebra_agent_api/api_command_mixin.py only to forward server-selected
settings.stream.capacity_policy into submit_session_command. Existing duplicate
commands still return their accepted Event before new policy selection; client
intent fingerprint stays unchanged. This is composition forwarding, not a new
canonical appender/transaction mutation path. Source ownership total15.

## Component acceptance evidence — 2026-10-14

Concentrated SPEC and QUALITY GO, independently verified1330 hashes and private
proof modes. Final affected45unique native passes comprise44 from attempt06 and
one test-only corrected assertion from attempt07; final runtime1273 files has SHA
1e5070fbf1a81ff382a7149380756cf50b9942d550a4411bb538cfc06eb51178.
Clean exact-source literal make check passed. Earlier137/52/13 runs retain their
different source provenance; original failures were not discarded. Explicit
minimum races/caps/partial operations/GC binding/oldV2/no-delta/epoch/private-source
checks passed. This is component acceptance for local integration, not production
cutover or complete runtime certification. Whole-lifecycle421clientSQL/66sockets
has no independent rate denominator;37 client EVAL attempts and36 server commands
use different sampling windows. CPU6289us and memory/RSS are owned-instance global
samples. Physical isolated capacity, TLS, STOP, full80/browser/fleet remain OPEN.

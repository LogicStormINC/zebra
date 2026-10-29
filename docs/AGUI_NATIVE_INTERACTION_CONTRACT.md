# Native AG-UI interaction contract (G5A revision 2)

Status: selected before native runtime implementation (2026-10-29).
This contract does not assert implementation or acceptance.
The existing durable native contracts remain authoritative. No real provider,
production deployment, original business Run replay, or package release is involved.

## Version and isolation

The existing profile IDs stay `agui-standard-1.0` and
`zebra-reliable-v2-agui-1.0`. Revision 1 remains the default and is immutable.
An optional `X-Zebra-AGUI-Revision` selects a strict decimal revision (`1` or `2`);
selection is by `(profile ID, revision)` at preparation and both stream paths.
Unknown, disabled, malformed, or profile-less revision selection fails closed.
The existing enable flag gates all standard profiles. A separate default-off
`ZEBRA_AGUI_NATIVE_INTERACTION_ENABLED` additionally gates revision 2 in both API
and Worker. Both flags must be enabled; neither flag silently selects revision 2.
Discovery lists available revisions additively; legacy discovery lists default-1
availability only. No default migration/backfill. The bounded registration cap is
ten: two legacy versions plus four standard/reliable revision/privacy pairs.
Default composition remains two legacy or six legacy/r1 versions.

Revision 2 uses its own restorable bounded state and existing `standard_v1`
cell kind in its isolated revision-2 profile scope (no storage kind or migration). Scope, profile revision, exact native anchor and namespace already enter
the existing checkpoint/cursor binding digest. Revision 1 state bytes, keys,
legacy projector, cursor bytes and HMAC domain remain unchanged.

## Native writes and immutable operations

The BFF captures one operation UUID and one immutable request before dispatch.
POST `/agui/threads/<Task>/runs/<nativeRun>/interaction` accepts
`{expectedRevision, input}` with official RunAgentInput. GET on the same route
reconciles the original operation using Idempotency-Key and Segment header;
it never writes, retries, repairs, renews Controller, or invents a new UUID.
Revision 2 and a published native Client Session binding are required.
Private input remains visible only to its original Client Session. Other
currently authorized observers may read the public stream.

Before any write, authenticate native Host/Task/Run/Client Session/Profile and
validate the entire latest interrupted public run response set: original public
run ID, exact interrupt IDs, no duplicate/missing/unknown IDs, canonical JSON,
strict payload shape and current pending native context. The native singleton
approval/clarification context is the complete supported set. Multiple native
aggregates are unsupported and rejected before mutation. Schema does not grant
edit, execution or multi-effect orchestration permission.

The existing 64 KiB total SessionCommand payload validator runs before any write,
including preparation metadata; this is the inherited native admission ceiling,
not a new history-size limit. Long read-only history is independent of valid
current-intent admission. Exact original-event reads use the existing one-event,
1 MiB Task page bound; the legacy approval 8 KiB receipt route stays unchanged.

The same checks run again within the existing native atomic stream boundary;
current Controller fence, active Segment/latest native Run, UI revision and
pending identity must still match. Accepted operations store bounded immutable
request metadata on the original native event, alongside the original owner and
hash. Conflict never silently changes the captured request. Read-only original
receipt observation requires current read authority, not a fresh fence, current
Controller or UI revision.

## Interrupt semantics and real anchors

Approval `resolved` payload is `{decision: approve|reject, operator, reason}`.
The native ApprovalDecisionService decides the actual domain transition.
Approve enqueues exactly the existing native HARNESS resume. Its exact source
Event UUID anchors the successor public run. Command UUID is never treated as
Event UUID. Reject is terminal native FAILED, queues no resume, and gets an
explicit revision-2 protocol acknowledgement anchored to the original rejection
Event UUID: RUN_STARTED, failed execution state, RUN_ERROR. It never resurrects
or invokes the Worker/model.

A cancelled approval response maps to native rejection with the operation's
explicit bounded operator/reason; it has the same terminal FAILED semantics.
No artificial approval expiration is inferred: native approval contexts have no
expiry field. If a native expiry is present in an actually supported pending
contract, expired responses only permit cancellation; otherwise expiry is not
advertised.

Clarification `resolved` payload is `{content: string}`. The BFF must explicitly
provide and authorize a fresh native Run target and its existing native binding
and Controller authority; it must also authorize the old pending native Run.
Clarification preserves Task, Segment, and actual continuation, but MESSAGE
creates a new native Run. Approval/effect continuations retain their native Run.
The public previous-run link comes from the exact validated old interrupted run. Free text is accepted
under the existing native clarification semantics; choices are suggestions,
case-insensitive matching is native. Its original accepted MESSAGE carries
`clarification_id`, then the existing Worker emits CLARIFICATION_RESPONDED and
continues. No extra RESUME. The actual USER CLARIFICATION_RESPONDED fact, matched
with the original server-owned MESSAGE operation, provides the canonical native
clarification tool result. No new tool proposal is fabricated. The previous-run
link is pinned to the selected profile and privacy variant, including `:coverage`.
Foreign profile metadata does not provide a link. Existing strict coverage text
privacy remains authoritative.

The new Run's Host Grant authorizes only the new target. Clarification POST also
requires `X-Zebra-Previous-Host-Grant: Bearer <JWT>` for the exact pending old
native Run named by `previousNativeRunId`. Both tokens independently undergo the
existing RS256/target/expiry/nonce checks, use distinct grant IDs, and have the
same issuer, principal, Host, namespace, workspace and origin. Browser JSON
cannot populate verified authority fields. Original-operation GET uses the new
read authority alone; it does not require a prior grant or current Controller.

Cancelled clarification uses actual native direct cancellation, with the same
native lease/stream lock order and child/lease cleanup. After acquiring the
native cancellation locks, the adapter revalidates current complete pending
context, Controller and profile before any semantic write. Its original
SESSION_CANCELLED Event UUID anchors a pure cancelled protocol acknowledgement;
zero Worker/model/extra command. A typed schema is published only where the
native consumer enforces it; structured clarification schemas remain unsupported.

## Frontend tool receipt roundtrip

Only an actual native CLIENT_EFFECT_SCHEDULED request authorizes a browser
handler. Its native proposal already emits TOOL_CALL_START/ARGS/END; revision 2
must not emit a second triad. Scheduling closes the public protocol run with
success and leaves the authorized frontend call unanswered, with truthful
`waiting_client_effect` execution state and bounded public effect metadata.
Private frozen conversation/assistant state is never projected.

The application performs or deliberately declines that exact effect through the
revision-two adapter into the existing native receipt acceptance. Its FIRST
receipt atomically captures the immutable original official input, original
operation and owner on the already-created HARNESS command. Reconciliation
reads that single exact event. An already accepted legacy receipt cannot be
mutated to attach a new input; that combination fails without a new command.
Optional preparation context is absent by default, preserving legacy behavior. The original accepted receipt is the sole
source for ToolMessage(s) in the next admitted protocol input: exact effect ID,
request digest, toolCallID, terminal status and sanitized result must match.
A browser ToolMessage on its own grants no execution authority. Its canonical
message ID must be `tool-result:<toolCallID>` so the official consumer merges it
with the actual public result rather than duplicating it. Succeeded receipt
results must satisfy the current published matching action's restricted
`result_schema` and `max_result_bytes`; failure/decline payloads retain their
native shape and bounded finite JSON. Claimed digest mismatches fail before write.

The exact native TOOL receipt fact followed by its adjacent trusted HARNESS
`client-effect-resume:<effectID>` command provides the actual public application
result. Native Worker provider continuation consumes the same durable result;
there need not be a second TOOL_EXECUTION_COMPLETED event. The producer emits one
canonical ToolCallResult and completed/failed Activity with the exact native
`client_effect_status`. It clears pending-effect state before the successor
snapshot, and clears the unanswered proposal only on the real result. No browser
execution or verification is inferred from arbitrary ToolMessage text.

Receipt acceptance already atomically queues one HARNESS resume; use that exact
source Event UUID for the public successor. Never enqueue another. GET receipt
reconciliation reads the immutable stored original result using the existing
ClientEffectReceiptReadPort; process rebuild and lost ACK preserve one handler,
one receipt and at most one legitimate continuation. Expiry is server-owned;
clients cannot forge expired/cancelled receipt statuses.

Existing ClientEffectRecovery may instead queue exact trusted HARNESS source
`client-effect-resume:recovery:<effectID>` after the actual descriptor deadline.
That native command carries status `expired` and reason
`browser_action_deadline_exceeded`; no browser receipt exists. Revision 2 checks
its canonical command envelope, effect/call/action binding and source timestamp,
then emits one truthful failed Activity and canonical expired ToolCallResult.
Execution remains unconfirmed. The Worker owns the one continuation. BFF recovery
can resolve the actual source header to its public slice and observe authorized
reliable GET with empty local input/history. It cannot fabricate a prepared
private input or rewrite an original receipt. Observation creates zero effects.

Native execution is sequential and defers at the first frontend effect. Do not
advertise parallel frontend results or build another orchestrator. Unsupported
mixed combinations fail before mutation; controlled mixed-tool checks must
establish provider-safe actual history rather than infer from private snapshots.
Cold history observation causes zero native effects.

## Source trust and classification

Shared public command admission rejects the server-owned `client_preparation`,
`client_preparation_source`, `agui_native_preparation` markers and nested
`client.client_state_admission_contract_version` proof. Legitimate native adapters
inject typed validated metadata through explicit server-only arguments after raw
parsing. Other legacy client fields remain compatible. A marker is not browser
execution authority.

Revision 2 publishes only validated PublicOutputPayload classification fields
`kind`, `meaningful`, `evidence_basis`, `evidence_refs`, under version-2 message
metadata. Private candidates and model deltas remain excluded. Partial close of
an actual ModelCommentaryChunk repeats its proven commentary/nonmeaningful
classification on TextMessageEnd because the official consumer merges metadata
shallowly. Revision 1 output bytes remain unchanged.

## Validation boundary

Required evidence: frozen legacy/revision-1 goldens; revision routing and restore;
three sequential real native approval/effect cycles; duplicate/lost ACK and
fresh-process observation; complete-set and stale authority negatives before
writes; official HTTP consumer against native producer and controlled fake
provider; no extra model calls or native commands. Schema-only or recorded-JSON
checks do not establish native interoperability. G5B owns registered React
handlers and scope safety; G6/T1/G7 retain packaging, Trench and full gates.

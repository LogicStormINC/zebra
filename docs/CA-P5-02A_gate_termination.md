# CA-P5-02A original gate termination

Implemented / Review; full gates passed. [Evidence](evidence/ca-p5-02a/README.md).

DDD fixed before implementation. A separate RuntimeGateTermination root owns one explicit termination
UUID, exact original gate bytes/hash, current expected namespace revision and immutable outcome.
Native gate originals and Tasks remain external facts, never rewritten. Missing original is not a proof:
only the atomic persisted fence, under the same namespace row used by v1 commit, proves no gate commit.
A tuple write (no semantic revision change) invalidates older repeatable-read snapshots; a future original
must encounter the durable tombstone. Already-committed returns its original receipt, never cancellation.
Separate mounted credential/config + current read/terminate approval, auth recheck before commit and GET;
128 immutable records, short bounded transactions, no retry. Termination itself may be unknown: original
termination GET only. No HTTP error proves noncommit. Future Go disposition must validate that proof
against its exact frozen raw request before allowing a different explicit intent; no automatic resend.
This is not Task cancellation, Worker/process/fleet drain, external-effect settlement or executor authority.
Baseline digests/local behavior/v1 contract remain unchanged; additive schema116, no history migration.
Full tests/checks and public contract handoff precede delivery; no deployment/production migration.

## Public interface and developer flow

`GET/POST /management/v1/runtime-gate-terminations`; separate `rtgstop_` bearer, exact scope headers
from gate v1, `X-Runtime-Gate-Termination-Contract` matching [digest](contracts/runtime-gate-termination-v1/digest.txt).
POST forbids X-Runtime-Operation and accepts termination_id, original_request (EXACT frozen gate bytes
encoded as a JSON string, <=16KiB UTF-8), expected_gate_revision. Envelope <=64KiB accommodates escaping.
GET requires X-Runtime-Operation = original termination UUID; query/body forbidden. Gate revision is a
CAS on current admission, not an increment performed by termination. No repeated POST, scheduler or retry.

1. Persist a distinct termination UUID and exact request bytes/hash before POST; one original gate command
   may have only one termination. Parent gate UUID and termination UUID must differ.
2. POST once with explicit current revision and current termination authority. A failed/unknown termination
   recovers only its original GET. Repeat IDs or another termination UUID for the same gate conflict409.
3. `no_gate_commit` proves that UUID did not commit a Native gate operation and later submission is fenced.
   A tombstone blocks ALL late bodies for that original UUID, not just the supplied hash. Original gate GET
   may still return404; only the termination receipt supplies the missing authoritative exclusion fact.
4. `already_committed` includes the immutable original gate receipt; it does not reverse admission or imply
   process/task cancellation. Mismatched original bytes are409; stale namespace revision409; capacity429.
5. Future Go consumption must separately preserve parent unknown, verify exact source/hash/scope/current
   authority, and audit a proof-based disposition. This slice supplies/pins the contract only. No automatic
   resend/new business intent, automatic open or Controller reclaim, even after a noncommit proof.

Response envelope rechecks current scope/trust; nested original receipt keeps historical actor/revision.
Proof includes terminationId, operationId, inputDigest (exact termination request), originalInputDigest,
outcome, gateRevision, actor, trustRevision, lateSubmissionFenced=true, proofScope=original_gate_command_only,
and original receipt or null. No fleet/process safe-stop/activation field can be promoted from this proof.

## Configuration and rollout

`ZEBRA_RUNTIME_GATE_TERMINATION_CONFIG` is a distinct private0400/0600 mounted JSON path, default off.
Schema `cloud-agent.runtime-gate-termination-approval/1`: exact BundleScope, namespace_exclusive=true,
new contract_digest, audience, actor, trust_revision, credential_sha256, expires_at and actions read/terminate.
Read is required with terminate. Authority becomes `gate-stop-<actor>`; gate v1 `gate-<actor>` and business
credentials grant no termination rights. Raw bearer remains in the trusted server/BFF Secret reference.
Only current explicit Native HostManagement approval can use it; current config and DB approval are
rechecked. Existing gate approval remains unchanged; no silent upgrade of old grants or baseline digests.

Explicit operator CLI `python -m zebra_agent_api.runtime_gates_admin --termination
--deployment-namespace NAME --expected-revision N` approves this separate configured authority, never
DDL/drain/open/deploy. Namespace must already be bound through the gate bootstrap. No startup migration
or startup approval. Partial CLI/config failure is inspected, not blindly retried. All proof records remain
immutable and are not evicted;128 per namespace. Bound API4 calls, DB2s/handler6s and body read0.5s.

Schema116 adds one proof/fence table and immutable trigger. Roll out/drain old writers before enabling
termination; old binaries' strict schema gate rejects116. Physical namespace tuple touch prevents an old
repeatable-read transaction from seeing absence after a newly committed fence. It does not change the
logical gate revision or open closed admission. A database operator bypassing Native gates/triggers is
outside the proof; no general adversarial database or fleet ownership certificate is claimed.

Proof assumes the authoritative database lineage retains its immutable fence rows. Backup rollback or
restoring a database without those rows is not certified. Recovery must preserve fences and rotate current
Target/machine approvals before admitting writers; an archived proof alone cannot certify a restored fleet.
This requirement belongs to separate recovery/HA acceptance, not a new stop or deployment permission.

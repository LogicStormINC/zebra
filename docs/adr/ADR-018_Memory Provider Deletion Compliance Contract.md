# ADR-018: Memory Provider Deletion Compliance Contract

- Status: `Accepted for provider admission review`
- Date: 2026-08-02
- Scope: Zebra Cloud Memory providers
- Task: `MEM-PROVIDER-DEL-COMPLIANCE-01`

## Decision

Zebra admits a Memory provider to the Runtime mainline only when the provider
proves deterministic recovery, deterministic physical deletion and complete
coverage for every Zebra scope and generation. Logical fencing is necessary but
is not physical deletion evidence. A provider that cannot close an ambiguous
write outcome is not admitted, even when its normal publish and delete calls
work.

The PostgreSQL Memory Delivery Ledger remains the Zebra lifecycle authority.
Provider indexes are derived and replaceable. Unknown provider outcomes are
quarantined and are never automatically retried or treated as a successful
delete. `MEM-GW-DEL-RUN-01`, its parent ledger task and Runtime composition stay
`Locked` until an admitted provider exists.

## Contract

### 1. Deterministic recovery

For a request whose response is lost after the provider may have committed, the
provider must expose a deterministic recovery operation. Given Zebra's opaque
scope, generation and idempotency key, recovery must return exactly one of:

1. the committed provider object and its stable provider reference;
2. a provider proof that no object was committed; or
3. an explicit, bounded uncertainty result that is itself sufficient to block
   admission and trigger operator reconciliation.

"Try the request again", a time-based guess, or a best-effort search is not
deterministic recovery. Zebra must never infer a provider reference from a
content digest or from a non-unique search result.

### 2. Deterministic physical deletion

Deletion must address an exact provider object or an atomic provider namespace.
The provider must return an outcome that proves the target is absent after the
operation. A successful request with no postcondition, a partial batch, or a
best-effort purge is insufficient. An exact not-found response may converge only
when the exact target identity was already proven.

The proof must cover objects created before a client response was lost. A
logical generation switch may prevent future reads, but it cannot be recorded as
physical deletion until this requirement is satisfied.

### 3. Complete scoped coverage

For a scope/generation reset, the provider must prove complete coverage through
at least one of these mechanisms:

- **Complete enumeration:** a documented, bounded, repeatable listing with a
  reliable end condition and no hidden result cap;
- **Deterministic lookup:** a unique lookup by Zebra's scope/generation and
  idempotency identity that recovers every possible committed object; or
- **Atomic namespace drop:** a provider-guaranteed operation that removes the
  entire exact namespace and returns a durable completion proof.

`top_k`, an undocumented page convention, a single partial search, or a global
reset does not satisfy complete scoped coverage. If none of the three proofs is
available, deletion compliance is `FAIL/UNPROVEN` and admission fails closed.

### 4. Unknown outcome handling

The following sequence is always an unknown outcome:

```text
request sent -> provider may commit -> client loses the response
```

The ledger records the operation as uncertain, quarantines its scope/generation
and retains no provider body or guessed reference. No automatic retry, search
admission, or physical-delete claim may use the uncertain operation as proof.

### 5. Admission policy

| Verdict | Meaning | Runtime use |
| --- | --- | --- |
| `PASS` | All mandatory capabilities and evidence are proven for the pinned provider version. | Eligible for Runtime mainline review. |
| `FAIL` | A mandatory capability is contradicted by the provider contract or a fault test. | Denied; do not start Runtime work. |
| `UNPROVEN` | Evidence is incomplete or the provider contract is ambiguous. | Fail closed; classify as Experimental/Research. |
| `BLOCKED` | A prerequisite or evidence gate is unavailable. | Keep the consuming task locked. |

`PASS` is necessary but does not by itself select a production backend. Runtime
selection still requires the separate cloud-composition and migration gates.

## Current Mem0 capability matrix

This matrix records only evidence already present on `zebra-cloud-trench`; it
does not infer undocumented Mem0 behavior.

| Capability | Required | Current evidence | Admission result |
| --- | --- | --- | --- |
| Scope/generation logical fencing | Yes | PostgreSQL v11 and reset-alternative tests pass | `PASS` |
| Known provider-mapping deletion path | Yes | Ledger mapping path passes; provider physical proof is not implied | `PASS` (ledger-only) |
| Ambiguous-create recovery | Yes | Unknown publish leaves a provider orphan without a recoverable ledger reference | `FAIL/UNPROVEN` |
| Complete scoped physical deletion | Yes | The pinned list contract has no proven bounded complete enumeration; mapping-only reset cannot cover an unknown orphan | `FAIL/UNPROVEN` |
| Runtime Memory admission | Yes | Deletion Compliance Contract is not satisfied | `BLOCKED` |

Therefore Mem0 is **not admitted to the Runtime mainline**. It may remain an
Experimental/Research provider behind explicit gates. This is a current
admission decision, not a permanent claim that Mem0 can never qualify.

## Re-admission evidence

A future provider version may request re-admission only with all of the
following, for the exact pinned version and deployment profile:

1. a documented deterministic recovery contract;
2. a documented deterministic physical-delete postcondition;
3. one complete scoped-coverage proof from Section 3;
4. a response-loss fault test showing recovery or a proven no-commit result;
5. a reset/delete test showing no cross-scope residue and no provider orphan;
6. an operator-readable evidence record and updated capability matrix.

The new evidence must be reviewed as a separate task. It must not unlock
`MEM-GW-DEL-RUN-01` by changing a status line alone.

## Non-goals and boundaries

- No Provider HTTP client, Mem0 adapter, Worker/Consumer, Desktop, Runtime
  composition or local SQLite change is authorized by this ADR.
- No PostgreSQL migration or delivery-ledger schema change is required.
- The original Mem0 enumeration Spike remains `Blocked`; its `top_k` finding is
  not reinterpreted as pagination.
- Logical reset remains useful for search isolation, but it is not a substitute
  for deletion compliance.

## Evidence and regression matrix

The specification test for this ADR is test-only and must remain independent of
provider HTTP. Existing evidence remains the regression floor:

- focused delivery Compose matrix: `24 passed`;
- full `tests/agent_storage` matrix: `295 passed, 1 skipped`;
- scoped reset alternative: `2 passed`, verdict `B/PARTIAL`.

No application container, Worker, Provider HTTP service or local SQLite
composition is started by the contract validation.

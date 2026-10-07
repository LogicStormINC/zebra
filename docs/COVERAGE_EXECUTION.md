# Coverage execution boundary

## Current implementation boundary

COV-EXEC-01 starts with a Host snapshot adapter in `agent-integrations`.
It implements the existing CoverageSnapshotPort without changing core models.
This slice is not a running exhaustive executor and is not publication authority.
The existing exploratory runtime remains unchanged; no Worker composition,
migration, service restart or business-data update is included.

The adapter consumes an admission-frozen Host manifest, an authorized session,
the exact history resource and injected signed Host invocation. Snapshot creation
requires a separately injected admitted Effect invocation and preserves its
idempotency key. Merely having a Host gateway or write scope does not constitute
Effect admission. The composition root must supply capabilities only after its
existing Policy/Effect checks; the adapter cannot prove that admission itself.

## Transport to durable evidence

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

The composition root must inject a publication lock shared by all publishers of
the same store. This guards cooperating publishers in one process only. Current
Artifact stores do not expose atomic create-if-absent; multiple Worker processes
must not activate this adapter without a single-writer or atomic store boundary.
Existing corrupt or conflicting deterministic IDs are refused, not overwritten.

ArtifactPayloadStorePort returns whole bytes. Metadata limits are checked before
reading and physical bytes/digests plus unchanged metadata afterward. A store
that understates physical size can still allocate too much before refusal;
strict allocation bounds require a bounded-read Port/storage implementation.
Each body read reloads and verifies the complete stored manifest (O(N) records),
although it does not re-enumerate Host pages. Repeated reads across all records
therefore have an O(N²) manifest-validation ceiling. The executor must compose
run-scoped verified indexed evidence or a bounded membership-proof read before
claiming high-volume throughput; no such throughput claim is made here.
Per-operation call/time budgets do not bound the aggregate cost of reading an
entire dataset; a run-wide budget is still an executor requirement.

## Remaining COV-EXEC-01 work

1. Compose approved, versioned check definitions and validate check outputs.
2. Execute persisted missing units with deterministic batches and durable receipts.
3. Resume under replacement lease fences without reaccepting completed units.
4. Enforce cancellation, expiry, call/token/time budgets and terminal outcomes.
5. Wire the adapter and executor into admitted Worker operations, including
   uncertain snapshot-creation Effect reconciliation.
6. Verify the real signed Trench-to-Zebra/PostgreSQL path and fault recovery.
7. Resolve the Artifact atomic-publication, bounded-read and repeated-manifest
   validation ceilings above before multi-worker/high-volume activation.

Worker paths must be explicitly added to task ownership before composition work.
Publication guards (COV-GATE-01), API/UI (COV-UI-01), migration reconciliation,
retention and deployed coupled acceptance (COV-ACCEPT-01) remain separate gates.
Unit tests, a build or `/health` do not establish those gates.

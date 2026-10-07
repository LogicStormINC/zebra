# COV-CON-01: exhaustive coverage v1 contract baseline

Date: 2026-10-07. Status: implementation review; not runtime-enabled.

Validation: focused regressions 50 passed, core 931 passed, full suite 4,925
passed / 911 environment skips. make check passed: size, Ruff, Mypy (1,010
source files) and deterministic eval (30/30). These are local source gates,
not real PostgreSQL/object-store/Host/model/browser coverage acceptance.

Source design: user-approved implementation start for
Cloud Agent 全量数据处理与覆盖验收技术方案, section 12.
The supplied design is in the primary checkout's
docs/CLOUD_DATA_COVERAGE_DESIGN.md. This isolated worktree starts from the
committed cloud-agent-trench@6b624ac4 baseline, not its uncommitted changes.

## Implemented contract

- CoverageContract is separate from exploratory TaskAcceptanceContract.
  No parser, inference heuristic or existing Task behavior changes in this slice.
- v1 admits only trench.subscribed_events, exhaustive mode, visible_at,
  an aware finite [from, to) range and all_entitled_periods.
- IANA timezone remains explicit; instants normalize to UTC before hashing.
- Exactly canonical_body is required. Attachments and cross-record checks
  are explicitly unsupported rather than silently omitted.
- Check IDs are unique and versioned. definition_digest must identify a
  published definition binding input/output schemas, prompt, model/extractor
  configuration and review rules. The Host registry adapter must validate that
  definition before admission; providing an arbitrary hash is not sufficient.
- block / certified_report_only cannot be weakened by input.
- Unknown fields and protocol versions are rejected; bool is not an integer
  count/revision/schema version. Metadata is frozen with immutable tuples.

## Snapshot, parts and units

Only sealed snapshots have this representation. The reference binds namespace,
Host, authority revision, snapshot ID, contract/scope/manifest digests, exact
record count, immutable manifest Artifact, as_of and expiry.

Record identity is (record_id, content_digest). Unique part IDs carry SHA-256
and byte length. verify_bytes rejects missing, truncated or changed bytes;
chunk boundaries must be established by the Host without losing UTF-8 bytes.
Input adapters still need to validate record-level frozen content against
the manifest; metadata alone cannot establish that a body was read.

For every record/check, expected units include all body parts and a mandatory
record_merge unit. Unit identities bind check ID/version/definition digest and
record/part content versions. clear and finding are both accepted outcomes.
Unknown/failed/review-required/waived model outputs are not accepted outcomes.
An accepted shape is not permission for the model to mark itself accepted.

Pages bind namespace, snapshot and scope, enforce requested size and reject
immediately repeated cursors. The enumerator must also track previously seen
cursors, enforce deadlines and compare the final enumerated identities to the
sealed manifest. next_cursor=null alone is not completion evidence.

## Canonical digests and exact validation

Protocol JSON uses sorted keys, compact separators, ensure_ascii=False, UTF-8
and allow_nan=False. Nulls remain explicit. Manifest hashing includes schema,
scope digest, exact count and ordinal-sorted record metadata digests.
Result hashing includes the complete canonical accepted results sorted by digest.

validate_coverage is a deterministic reference validator:

- exact record-version set equality, no duplicates, continuous ordinal range;
- exact read-part set and expected-unit set equality, not just equal counts;
- snapshot contract/scope/hash/count/time match;
- live namespace/Host/snapshot/authority-bound adapter evidence;
- readable mandatory Artifacts, ready upstream, zero unresolved failures/reviews;
- aggregate input result-set digest matches the accepted set.

Its O(N) reference implementation is for bounded in-memory checks and testing.
Production storage must use indexed exact-set joins; no unbounded in-memory
scan is authorized by this contract. An empty authorized sealed set can pass,
but processed_ratio is null. This is not a claim that reality has no risks.

Aggregate input digest binding does not prove the report omitted no findings.
Deterministic aggregation, report schema/count checks and report Artifact digest
verification remain executor/gate responsibilities. Semantic accuracy remains
a separate evaluation boundary.

## Persistence and trust boundaries

CoverageSnapshotPort reuses HostContextEnvelope. Create must use the existing
Effect idempotency path; each get/page/read must enforce live authority,
snapshot expiry, signed scope-bound cursor and immutable content.
No HTTP or database implementation is included.

CoverageCommitPort requires a bounded accepted batch, canonical result Artifact
digest, session/task/run/snapshot/contract/manifest bindings, commit key and
existing LeaseFence. Implementation must check current authority and Artifact
readability, then atomically append the Event, update projections and schedule
intent. Same key/digest returns the original receipt; changed meaning and stale
fences fail. No projection-only implementation is conformant.

CoverageCertificate is an immutable receipt schema binding report, aggregate,
results, contract/snapshot, count, validator version, watermark and expiry.
Only the future internal validator transaction may mint and store it.
Constructing this Pydantic object or receiving it from a model is not authority
to publish. No certificate minting/publication adapter exists in this slice.

Protocol envelope bounds: page/batch 1,000 entries, checks 32, body parts 4,096
per record. These are parser ceilings, not measured safe throughput defaults.
Runtime limits need capacity validation and configuration in dependent slices.

## Remaining implementation and activation boundaries

| Task | Not implemented here |
|---|---|
| TRN-COV-SNAPSHOT-01 | PG consistent snapshot, immutable body copies, live permissions |
| COV-STO-01 | Event/Artifact atomic commits, projections, claims, fencing, replay |
| COV-EXEC-01 | Deterministic traversal, model schema/quote validation, bounded recovery |
| COV-GATE-01 | All final/stream/replay/present/publish/download/write gates |
| COV-UI-01 | Coverage API, progress, details, review and report UI |
| COV-ACCEPT-01 | Real PG/object-store/model/browser E2E, crash faults, capacity |

Dependencies retain the source design's merge order. No exhaustive product
entry point, database migration, service restart, merge, push or deployment was
performed. The primary checkout remains unchanged.

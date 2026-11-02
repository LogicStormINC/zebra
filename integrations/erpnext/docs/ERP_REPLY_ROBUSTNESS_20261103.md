# ERP reply robustness and latency — 2026-11-03

## Scope and observed causes

- `57r9penubd`: the original Task POST was refused with HTTP403 before execution.
  The wrapper classified only400/413/415/422, leaving a pre-Task dispatching row;
  snapshot and stop previously returned idle. This was not a failed model call.
- Ambiguous transport/commit outcomes must remain unknown; a missing receipt is not
  noncommit proof. A later rejection cannot erase an earlier uncertain acceptance.
- Full-mode read arguments were opaque despite an existing native validator.
  Among56 saved calls,14 failed with missing aggregate metric. These were repeated
  invalid shapes across DocTypes, not identical-call duplication.
- Discovery replies reached145,942 characters; repeated large tool text expanded
  context from roughly9–10K to53.7K tokens. Metadata access does not prove document access.
- Cold fresh-proof imports eagerly loaded Worker/storage/provider exports. The
  existing lazy-export pattern avoids this dependency loading; authorization is unchanged.

## Implementation

- Persist immutable Task-create intent and exact payload before dispatch. Definite
  first-attempt rejections become rejected; unknown ACKs retain identity and payload.
- Current-authority GET `/task-admissions/receipt`, scoped by the existing create key,
  returns only an original positive receipt after Task binding checks. No POST/replay.
- Reload/CAS request, Run and Task coordinates after grant commits/network calls.
  Pre-Task stop acknowledges only a proven local refusal; never claims resource release.
- No-Task snapshot retains user text and truthful rejected/reconciling status.
  Pinned unknown commands cannot become rejection/cancellation acknowledgements.
- Reuse `business_arguments_schema` for full read tools, including count/numeric metric
  fields. Full operations and native validation remain; schema cannot eliminate all model errors.
- Discovery has a bounded metadata index and honest pagination. The complete original
  JSON remains verbatim after the index and is retained by the generic Cloud Artifact projector.
  Read-only exact-prefix previews cannot replace evidence or change mutation results.
- Lazy exports preserve public symbol identity. Frozen117 deployment transforms the
  original117 exports, not later mainline APIs. Success timing exposes filesystem,
  fresh-proof and verified-receipt stages without credentials, arguments or response bodies.

## Verification and deployment

- Source checks: submit/lost ACK/stop/coordinate safety, full read schema, bounded
  discovery, authentication/JWKS, real fragmented HTTP history and presentation passed.
- Linux fixed-image acceptance:52 Worker/process/real PostgreSQL force-stop/lease/
  resource/evidence tests,10 API receipt tests including real PostgreSQL persistence.
  API tests run on the API candidate; Worker tests run on the Worker candidate.
- Original QA packaging missed pytest's pure-Python `py.py` shim; corrected offline.
  No production dependency was installed. An initial mixed-image API test invocation
  used the unpatched Worker API copy; final split-image acceptance passed.
- Fixed117 API/Worker/cleanup, root operator/helper and ERP application services deployed
  under saved admission flags, no-active-Run/lease/queue guards and production backup.
  Original images/config and per-conversation backup are retained for rollback.
- Original migration117 ledger, model-call count189, sessions53, original Native event
  checksum, workspace filesystem manifest, service environment hashes and unrelated
  containers preserved. Search/MCP not restarted; no model/search request or original replay.
- Real signed GET finds the existing `5vdk10lcmu` Task; missing57 receipt remains unknown.
 57 recovery additionally verifies the historical refusal audit's exact resource digest
  against original thread/principal/company/Run, then updates only the rejected intent.
  Expired historical ERP grant rows had already been GC'd; their absence is not evidence.
- Final cold process pair (AB/BA/AB,1CPU/256MiB): old3.384/3.455/3.823s,
  new1.547/1.280/1.379s. Median3.455→1.379s, about60% less proof-import time.
  This is not whole-Run or browser first-body speedup. No fresh model was called.

## Evidence and limits

The published JS hook version is bumped for normal refresh/cache invalidation.
Saved inventory replay:79,060 original bytes→7,964 model-visible prefix bytes (~90% less),
with complete original unchanged. Final live snapshot/served JS checksum and admission restore passed.
Owned QA containers/network/images were removed; production/rollback images retained.

Private remote receipts: `/home/ubuntu/releases/20261103-erp-reply/`.
Only sanitized measurements belong in Git. Preserve originals/rollback images;
no automatic retry, absent-receipt cancellation, quota bypass or stale authorization.
Model round-count/first-body improvements require later authorized natural or paired
model traffic. Upstream provider failures cannot be promised impossible.

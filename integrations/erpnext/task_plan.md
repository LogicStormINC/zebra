# ERP capability integration

## Goal
Wire ERP business operations, private input files/images, historical outputs/usage,
controlled web/analysis, Skill/MCP, knowledge/memory and durable schedules through
existing Native contracts; enforce current ERP user/company authorization.

## Phases
1. [complete] Exact deployed source/authority inventory and isolated105→114 migration; original tables preserved.
2. [complete] Generic Native input/fresh-Host/Skill/Memory/history/schedule/volume composition, committed and locally integrated into cloud-agent89e4afed; includes concurrent AG-UI fixes/v115.
3. [complete] ERP fixed runtime/profile BFF, private uploads, Skill/MCP, knowledge/Memory, historical artifacts and native schedules with UI.
4. [complete] Fixed source-only images built, QA115 applied; signed cloned management, private inputs, actual Skill bytes, physical quota/analysis, scheduler boundaries, legacy history and browser persistence accepted without model/search requests.
5. [pending approval] Production blue/green activation after review of the concrete accepted candidate. Keep original runtime/data/ready work and Search/MCP intact.

## Constraints
No credential output, original Run replay, permission expansion, quota bypass,
new model/search request or fabricated readiness. No restarts while active work exists.

## Errors
- Initial SSH root login refused; identified existing authorized ubuntu login from prior deployment command metadata.

- Isolated PostgreSQL first readiness probe observed the temporary Unix-only init server before the target DB existed; restore refused before connecting. Fix probe to TCP127.0.0.1. Keep failed attempt and resume restore only after confirming empty clone/finished initialization; no production operation.

- Migrator could not open the protected evidence path: root with all capabilities dropped cannot traverse an ubuntu-owned0700 directory. It never opened Python/DB. Use the evidence directory owner's numeric UID/GID, retaining cap-drop/read-only; retain first log separately.

- First migration completed and was idempotent. Only changed table was zebra_schema_migrations:104→113 expected rows. Correct original-data invariant to compare ledger versions≤105 and independently require exact114 catalog; do not treat the required nine ledger append rows as lost data. Retain full first migrated clone under a separate QA database name, plus its original result/log.

- HTTP setup correctly refused an unspecified runtime image. Preserve failure log; compose candidate settings from the actual cached, digest-pinned runtime image, not a fabricated image. No HTTP request had started.

- Actual configured runtime digest33735... is absent, not merely an alias mismatch. Keep production unchanged. Cached Python3.12 base has a real RepoDigest; use it only for the isolated metadata/API candidate and separately prove gVisor startup. Quota/files/sandbox workflow still pending.

- Actual signed HTTP accepted own header and refused unsigned/foreign requests. Expired JWT was refused403 by Native decode policy; the check had incorrectly required401. Accept either authentication denial401/403; keep exact actual response statuses and the failed assertion log, no Native error suppression.

- Bounded summary maintenance actually completed all22 Tasks; only task_read_summary_heads/frontiers changed. The script's derived-table allowlist used an incorrect table name. Preserve its result and failure; correct names from the existing Native INSERT/UPDATE statements. Close against the recorded before/after changed-table set without rerunning maintenance; then repeat only HTTP reads after the real409 prerequisite is repaired.

## Current verification receipts
- Native3111097f is committed but not integrated into cloud-agent or deployed. make check passes;1435 typed source modules, file-size and all progress gates pass.75 focused API/model/authority tests and90 sibling Worker execution tests passed; no real provider/search requests.
- ERP deterministic runtime/chat/resource scripts pass. Frontend build and existing npm tests pass after correcting use of the existing attachmentInfo helper. New BFF/UI functionality still needs isolated actual-data acceptance; do not claim flags/bundles prove readiness.
- Original untracked cloud-patches/fresh-slice-sha256.json remains untouched.
- Production container read-only inventory on2026-10-28: original API6e4b2cdfa32b, chat Worker812202f8891b and Search/MCP unchanged; no service was stopped or reconfigured.

## 2026-10-29 actual capability receipts
Dedicated QA root /opt/erpnext/zebra-agent/full-capability-qa-20261028-2.
Actual input admission/S3 rollback/isolation; signed Host identity; root-only256MiB
ext4 allocator; non-root gVisor CSV/ENOSPC; normal AG-UI frozen Skill bytes;
MCP encrypted credentials (invalid example endpoint deliberately not called);
private knowledge and scoped Memory; signed schedule idempotency/revocation and
one idle native scheduler cycle; UI selection/reload persistence all checked.
Cloned-only native ToDo/file and Material Request lifecycle/approval/replay
acceptance passed and disposed its own fixtures; no original business mutation.
Existing search leaf expired Oct26: original service untouched; new isolated TLS
listener reuses exact GET/path policy and127.0.0.1:18446 backend. TLS verifies;
HTTP/search probes0. Yahoo/default/Exa controls unchanged.
Native full suite11415 passed/3094 skipped/9 failures, all affected failures closed
by32 focused checks; merged-source48 passed/4 skipped and make check pass.
No full-suite repeat loop, no model/search request.

## Final checkpoint
Immutable Native9a09d2d50d5a (source89e4afed), ERP2d16a18f2af4 (application
source91f1b19). QA schema115, same original production process inventory unchanged.
Actual legacy f1p4qpa1me restores2 messages/4 tables. Actual new73okscoa80 Memory
creation and reload persistence pass. Initial417 was canonical_task_incomplete:
QA had no Worker loop, hence no Session observation recovery. Used the existing
projection service plus one actual fenced recovery/release of that QA Session;
no Run execution, no privacy bypass. SQL confirms0 model/tool execution events.
Current production snapshots/backups prepared separately under
/opt/erpnext/zebra-agent/full-capability-release-ready-20261029-1. Never promote
QA databases/buckets or test records. Production activation still requires the
final approval beyond the user's isolated-migration/compatibility authorization.

## Approved production activation2026-10-29
User explicitly approved switching online. New dedicated activation branch/card;
legacy runtime and original work remain. Inspect active state, build fresh durable
production namespace from current backup (never QA), compose authority/quota/S3/
Redis/TLS/Worker/scheduler, update Host, verify without models/search, enable new
conversations last, retain rollback.

### Activation result
- Complete: fresh backups, separate production115 runtime, persistent storage/quota,
  accepted Host image and original port/env, existing public signing authority.
- Complete: actual no-model S3/BFF/Native/Worker sandbox/lease/Host/metadata gates;
  canary cancelled before Worker start; cleanup excludes all original data.
- Complete: ordinary new conversations select full/high; v2 enabled, old105 retained;
  Search/MCP unchanged and no model/search probes. Current new service restarts0.
- Pending acceptance boundary: logged-in production browser unavailable; external
  model/search/MCP and production HA/SLO not demonstrated by no-model checks.

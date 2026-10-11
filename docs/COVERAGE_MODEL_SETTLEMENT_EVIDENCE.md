# MODEL settlement proof boundary — 2026-10-11

Task COV-EXEC-01, Luke Ding/Codex, isolated branch `codex/cov-exec-01`.
This is component work, not closure of the Worker SQL root cure. Runtime
execution-receipt activation remains OFF. No business migration, restart,
integration, commit, merge or push was performed.

## Implemented contract

- The optional settlement Port returns the exact checkpoint bytes verified by
  the native usage transaction and its positive Event sequence. First strict
  incremental settlement checks that acknowledgement against the prepared
  checkpoint. Eager and legacy adapters retain the original integer Port.
- The verified-result API refuses a borrowed, still-uncommitted work unit. The
  old integer API continues to compose inside an existing transaction.
- Existing `record_model_usage` overrides still execute. Lost acknowledgements
  remain failures; `None`, `bool`, zero and conflicting sequences cannot inherit
  a verified native acknowledgement. Retry does not authorize provider transport.
- Already-settled invocation replay does not open another optional settlement
  phase: the existing reservation and current original read remain responsible
  for replay proof. Calling the optional store API explicitly still verifies
  the current original and identical receipt.
- Settlement captures the complete lifecycle record and canonical SessionEvent.
  After the extensible proof-scope exit, it freshly lock-reads both without the
  scoped reader cache, compares exact identities/content and refuses mutations.
  First settlement and replay changes roll back. Lease, Task, Host, STOP and
  retention deadlines retain their current checks.

## Rejected unsafe shortcut

The initial attempt used the transaction's returned bytes to skip the later
integration checkpoint reread. Review demonstrated two distinct hazards:

1. An exit callback can change lifecycle metadata or a canonical Event inside
   the same transaction. Row locks do not protect against that transaction's
   own writes. A captured retention deadline is not a current-row proof.
2. A callback after commit can prune or physically corrupt the original. A
   prior transaction's bytes do not establish availability after that effect.

The shortcut was withdrawn. Integration **always retains its post-boundary
original reread**, and independent final certification rereads originals too.
This work therefore cannot be described as having eliminated all repeated
checkpoint reads or having demonstrated a SQL reduction. No permission TTL,
reset suppression, object immutability assumption or disabled gate was added.

## Evidence and retained failures

- Final pure MODEL/incremental/recovery/settlement: **155 passed, 2.86s**;
  `/tmp/cov-settlement-pure-final2.xml`.
- Final-source real PostgreSQL settlement/fault/rollback: **10 passed, 70.35s**;
  `/tmp/cov-settlement-native-boundary-current.xml`. Includes first/replay scope
  exit mutation, direct corruption/retention/lease loss, exact retry, old hooks
  and uncommitted-owner rejection. S3/Host/model transports are controlled.
- Earlier broad run: **72 passed, 3 failed, 335.82s**;
  `/tmp/cov-settlement-native-final.xml`. Its retention fixtures used a nonexistent
  `created_at` column and were corrected to `request_created_at`; only the final
  focused rerun is final-source passing evidence, not a claimed 75-test full GO.
- Earlier boundary run: **14 passed, 4 failed, 71.11s**;
  `/tmp/cov-settlement-boundary-final.xml`. Corrected retention DDL constraints,
  the production exception wrapper/cause, and expected earlier canonical proof
  refusal. The original two-module invocation also failed collection because
  basenames collided; the native test now has a distinct filename.
- Initial older-source expanded smoke: **118 passed, 1 failed, 223.34s**;
  `/tmp/cov-settlement-native-smoke.xml`. Corrupt objects raise the actual typed
  integrity exception; the test was corrected. Not final-source/full evidence.
- `make check`: Ruff, Mypy **1115 files**, deterministic eval **30/30** pass.
  Final tracked/untracked source-size gate **2615 files** and diff check pass.
  Full `make test` and live E2E were not run.
- Read-only second/final reviews found no further concrete source finding after
  the fixes. Review itself is not test or performance evidence.
- This turn's disposable `zebra-cov-settlement-20261011` container and its exact
  anonymous PostgreSQL volume were removed after all native measurements;
  both are verified absent. Only temporary fixture data was deleted; XML
  evidence remains. Existing business containers, volumes and services untouched.

## Whole-chain SQL gate

Final-source serial nine-record measurement:
`/tmp/cov-settlement-nine-strict.xml`, **16.1541s / 10497 application calls /
15637 server calls / 237 object GETs / four Worker callbacks / five accepted
batches**. Nine MODEL requests, 18 accepted units and independent final
certification completed; one initialization replay and zero exceptional full
recoveries. All five continuation receipts are qualified. **<=1000 SQL FAIL**.
The complete boundary includes handoffs, clocks, resets and final certification;
no other native workload ran concurrently with server observation.

Previous shared-read run:17.5762s /10485client /15619server /225GET /4callbacks /
5batches. Current calls increased12 and object GETs12. Do not claim a SQL or
latency improvement: elapsed observations are single controlled runs, not SLOs.
The fresh settlement exit adds nine uncached metadata and nine canonical Event
queries; other measured fingerprints also vary. Exact totals, not truncated
top-fingerprint sums, determine the gate. Post-callback original reads remain.

Current SQL categories:business6616 /clock1948 /reset1419 /timeout514, sum10497.
Exclusive phases:outer3834 /initial6 /publication1698 /metadata562 /executor1387 /
MODEL1740 /commit413 /continuation243 /revalidation240 /final374, sum10497.
Server13582 top-level+2055 nested=15637;674.42ms inclusive execution time is
non-additive. Lease/epoch1127 and fresh lineage877 remain unchanged. Thus the
dominant root is repeated bounded guard/adapter phase entry, not exceptional
full recovery. Returning a verified settlement acknowledgement does not cure it.

## Still required

1. Worker-wide bounded native phase preparation/authority composition. Reusing
   a socket or returning a proof does not by itself remove layered guard entry.
2. An actual immutable-retention proof before removing final external original
   reads from lifecycle locks. No such proof is fabricated here.
3. Manifest/history growth, cross-process tenant quotas/fairness/fleet load,
   real provider/MinIO/Trench acceptance and independently labeled semantics.
4. The complete <=1000 SQL gate. Passing component checks is not root-cure GO.

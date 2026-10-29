# Early ERP fresh-authority refusal: review boundary

This isolated slice implements the approved bounded refusal design. It is not an activation approval. No service, production data, model, business tool, migration source, or public repository was changed by the implementation agent. Root alone operated disposable runtime checks.

## Source and packaging

The base is the approved 146-file fresh-authority snapshot `df8d45aa6de1dd3ed62e631c644d0d544a70929fa2d069e8fd2fc1cf0ea69b76` from `work/takeover-20261024/fresh-2477`. New native baselines are byte-identical to captured Worker105 (`33b93abc4b257d0639730f2e2c388d765f092d7979a03b117f6387b0049c0e18`) and API105 (`2156443eea6ad9330853d16ece204dfa0995a41e5b5b677063386216797daaef`). BFF baselines are the supplied current ERP source, separate from the unchanged approved Host authority/gateway overrides. The provenance manifest identifies each comparison source and hash.

API and Worker Dockerfiles copy the shared disposition/idempotency/recovery modules and their own new callers. The Host Dockerfile copies Python and compiled `public/zebra.js`/`zebra.css` through its existing package-directory COPY. Frontend assets were built from the complete existing frontend plus the two overlay files, using already-installed esbuild/dependencies and the existing production build options. No dependency was added. UI build inputs outside the two changed frontend files are byte-identical copies; scratch build directories are excluded from the review manifest.

The cumulative image still includes the previously approved HTTP-input migration106. This slice changes no migration. Ordinary refusal tests run on105. Native strict capability checks demand every migration version/name/checksum match the loaded catalog; an overlay106 process correctly rejects a105 ledger. Root therefore initialized a separate disposable QA106 from the existing approved catalog, leaving QA105 intact.

## Implemented behavior

The typed early gate runs before private input/progress recovery. Permanent refusal and the narrowly classified unavailable decision reach an optional callback inside the native LeaseHeartbeat, before lease release. They never become WorkerExecutionError and do not invent prior authority, AttemptStarted, command-handled, Turn failure, model, business effect, or publication events. Disabled fresh and non-ERP paths retain native behavior.

The shared SQL transaction checks exact accepted command identity, binding/scope, modern capability/fence/Inbox and contiguous recovery generation history, plus the whole Turn's never-executed metadata. It seals metadata only in the existing idempotency table. Classic additionally writes its exact existing rejection receipt; the paired receipt anchors the full proof digest, including a validated historical LeaseFence. Modern permanent refusal becomes a dead pending outcome. Known temporary unavailability retains the native released-lease recovery budget: generation0 plus at most5 recovery approvals, original expiry/backoff and24-hour ceiling. Exhaustion exposes a fixed outcome. No new table, event, queue, budget, or recovery framework exists.

Historical proof validation ends at the first canonical successor admission, so later legitimate execution/new Turns cannot resurrect an old refusal as unresolved. Current explicit retry eligibility is separate: no post-floor evidence or live lease, whole Turn never executed, complete durable proof, and native current strict Host/runtime authority when applicable. The native validator permits an observation-only registry read through a private default-true lock option; all three original admission/pin calls retain the share lock, and the header stays repeatable-read read-only. Started, clarification, uncertain, or strict-authority-expired work cannot obtain this seal or retry action; native control/reconciliation paths remain authoritative.

The authorized exact-Run header and AG-UI observation metadata expose fixed outcomes without changing canonical Task status. BFF retry creates one new Run/Grant and an empty-message native RUN on the same Turn. Durable preparing intent precedes grant/client mutations; the native420-second unknown client-opening fence is preserved. The exact command body, key, revision and Run are committed before AG-UI POST. Unknown outcomes retain them. Only the first send's enumerated exact native pre-accept reason may restore the predecessor. Any invocation resuming an already durable dispatching phase conservatively retains the pin across403/422, including interruption before POST; a later response cannot disprove earlier acceptance. Existing native retry UI is reused; no automatic business replay or original-message append is introduced.

## Fixed policy refinements

Root narrowed retryable HTTP statuses to `{408,425,429,500,502,503,504}`;501/505 and protocol/malformed/internal failures remain unclassified fail closed. Only typed timeout/network failures qualify. Missing/inactive local connector binding or verified profile digest drift yields the existing fixed authority-drift refusal before HTTP. Native strict pin/expiry semantics are unchanged: an expired strict Host grant cannot be bypassed to manufacture a seal.

The initial approved design hash remains recorded separately. `EARLY_FRESH_REFUSAL_DESIGN.md` now reflects the later root HTTP refinement; this does not silently redefine the original approved hash.

## Checks and evidence boundaries

Root's pinned native network-none checks passed the original8 fresh groups, continuation startup checks, legacy containment, and the early typed-heartbeat boundary (snapshot C). The boundary checks verify zero private/fake-finalization calls, correct callback-before-release, fixed HTTP classification and unclassified errors remaining unsealed. Root's compiled candidate network-none checks also passed the local-registry revocation zero-HTTP regression.

Root's real PostgreSQL checks passed classic immutable exact rejection, modern real handoff/Inbox/concurrent writers, late fence rollback, native generations0..5 and exhaustion (D and repeated F/G). Real classic missing/malformed/valid-but-changed fence negatives passed. These scripts retain uniquely named owned QA fixtures and never reset existing data or epochs.

Root's G exact API105 checks passed the actual AG-UI handler, new Host binding renewal, empty-message same-Turn RUN, immutable idempotent replay, authorized header/wrong-scope rejection, started refusal negative, and a third ordinary MESSAGE after successor completion for classic/permanent/exhausted paths. Worker lifecycle events in this check are explicit deterministic native event commits, not actual model execution. VerifiedHostGrant is supplied to the handler; HTTP JWT authentication is not certified by this test.

Configured native CloudExtensionTurnAdmission and native PostgreSQL same-Turn snapshot reuse/new-Turn snapshot admission: root I passed on QA105. Real strict process registration/admission/attestation, valid seal and missing-capability negative, natural final-capability expiry with whole-transaction rollback, and expired Host no-seal checks: root J passed on QA106. No weakened guard or fake process capability is used.

Local actual BFF/client code checks passed9 new groups (including accepted-lostACK then403/422 and interruption beforePOST), inherited chat/history/client checks, the fixed protocol reduction check, and build identity checks. These use Frappe/Redis/Cloud IO doubles; they do not claim actual Redis lease duration, deployed RPC, HTTP JWT, or browser acceptance. Root independently passed the BFF groups and frontend build/existing checks. The compiled UI preserves original messages/canonical status and only offers retry from an authorized snapshot.

## Remaining gates

Final independent SPEC/QUALITY review and final native checks are required. Root owns image builds and any subsequent HTTP JWT/Host/BFF/client cross-service acceptance, actual browser cold refresh/retry/Stop UX, deployment and activation. This source slice alone does not certify those gates. Strict ERP's synthetic test context includes native history scopes solely to exercise its capability contract; this does not make strict ERP generally supported or activate it.

Runnable checks: `tests/check_fresh_refusal_boundary.py` (pinned Worker, network-none); `tests/check_fresh_refusal_postgres.py` (explicit QA105/106 DSN); `tests/check_fresh_refusal_successor.py` (pinned API and QA105/106); `tests/check_fresh_refusal_strict.py` (pinned Worker and QA106 only); `tests/check_fresh_refusal_bff.py`; `node tests/check_fresh_refusal_protocol.mjs`. Existing checks remain available unchanged except inherited history's explicit isolated-source path.


## Final SPEC correction pass

The prior204-file freeze was NOT APPROVED because it cleared a previously unknown accepted POST after a later pre-idempotency rejection and exposed strict retry after a current deadline expired. This revision fixes those exact two findings. Native shared `_identity` gained only the authorized registry lock option needed for the existing read-only observation transaction; structural/deadline validation and all original execution pins are unchanged. The public successor regression now supplies a newly issued same-Run Grant on duplicate delivery. Root K independently passed all9 BFF groups, all6 exact API105/QA105 successor groups with a newly issued same-Run Grant on duplicate delivery, and all8 exact Worker105/QA106 strict groups. The new actual read-only header check proves current Host and runtime expiry each remove retry eligibility while the immutable historical proof survives. Native strict valid/missing-capability/final-expiry rollback cases remain green. Host frontend assets were rebuilt with unchanged build inputs/options and retain the same hashes. Incremental SPEC/QUALITY review and live integration remain required; earlier204-file review was not an approval.


## QUALITY ownership correction

The206-file freeze passed source SPEC but failed QUALITY: fixed Redis lease expiry allowed an old first sender to clear a successor's accepted-but-unacknowledged request. Freeze3 repairs the shared mutation boundary across chat, client, Cloud grant initialization, and presentation, using current native FOR UPDATE loading followed by actual Redis token ownership under the row lock. Every intended write uses the fresh Document and commits before releasing admission. No TTL extension or replacement coordination framework is used.

`tests/check_fresh_refusal_ownership.py` passes7 deterministic groups using actual shared functions and distinct stale Document copies: overlap A403 after B accepted+lostACK; delayed client open/release; ordinary submit/cancel/manage; token lost while waiting for row lock; presentation; grant initialization/expired-token denial; successful first/follow-up submit/client/Stop/settings/rename. Existing9 BFF groups and inherited chat/client/history checks still pass. These IO doubles validate full caller composition; native Frappe/Redis/MariaDB primitive acceptance is a separately reported Root gate.

The cloud baseline refresh is intentional provenance correction, not a production source change: original stale baseline is superseded by current HRMS `d9651d...`, confirmed image/live/public equal by Root. Required Host base is `sha256:1a56e963dae6f9cb86399dfa8c3a05fd281bc0cc755b0016b1c10886e542c07d`; Dockerfile records this requirement. New Cloud/Worker runtime code is unchanged in this correction. Final incremental SPEC/QUALITY and HTTP JWT/browser acceptance remain pending.

Root later re-inspected the Host base: exact image1a56e963... is currently tagged `erpnext:hrms-16.52.0-20261024`, preserving a separately human-authorized HRMS installation. The older r3 tag resolves a different image and is not an acceptable substitute. This slice pins the exact current image identity; it does not roll back HRMS.

Root built the ownership candidate from exact current HRMS image1a56e963... and installed it on the disposable QA Host only. The real Redis/MariaDB expired-A/accepted-successor-B case passed the ownership refusal boundary. In the initial real row-wait run, MariaDB1020 rejected the stale read before FOR UPDATE returned; no stale mutation occurred, but that branch does not prove the later Redis check executed. Root is recording this native concurrency boundary separately. No SQL deadlock is caught to clear a pin or replay business. The implementation agent performed no server or QA deployment action.

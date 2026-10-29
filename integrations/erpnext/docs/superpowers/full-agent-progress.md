## 2026-10-29 当前生产激活状态

经用户明确批准，七类通用能力已切入新的持久cloud114运行时（实际schema115）。
新普通会话默认使用该运行时；原native105会话、API/chat Worker和Search/MCP不迁移。
Native API9a09d2d50d5a，Worker仅补现成Docker CLI依赖层a8f0e494c3aa，ERP2d16a18f2af4。
实际无模型BFF、S3输入、记忆恢复、目录、暂停计划、v2准入、Worker内真实租约/
Host proof/gVisor/独立硬配额及旧历史兼容通过。canary已取消并隐藏，自有测试资料/
记忆/计划已清理，原Run不变；八项新服务运行且重启0。原搜索/MCP进程完全未重启。
生产登录后页面点击验收仍待用户登录；未调用模型/搜索或声称外部MCP/SLA已验收。
ERP通用生命周期已接入，模块专用流程按原覆盖清单保留partial边界。
最新证据与回滚规则见[生产接入记录](../ERP_CAPABILITY_RELEASE_20261028.md)。

以下为保留的历史阶段记录，以本节为当前状态。

## 2026-10-28 — 通用运行时升级隔离前置

用户批准先做Native105→cloud-agent114隔离迁移与兼容验收，尚未授权直接切换。
已备份原库，138原表/旧列一致、迁移幂等；22Task/3791事件/132拒绝、真实签名
HTTP11项与gVisor冷启动通过。历史用量409通过隔离库显式有界投影修复闭合。
线上仍105，原服务未重启，零模型/搜索；七项能力未宣称交付。
详见[接入与验收边界](../ERP_CAPABILITY_RELEASE_20261028.md)。

# Full Agent implementation progress

The approved full design remains open. This file separates code, deployment and acceptance.

## Current recovery checkpoint — 2026-10-28

Maintenance is off. The dedicated native105 Agent now completes real model chat,
permission-scoped ERP queries and Production Plan approval workflows. Chinese,
CNY, Asia/Shanghai and HRMS were checked on the deployed Host. The consolidated
deployed sources and public verification record are in
`cloud-patches/chat-recovery/`; its 27 production files match the running images.

Actual authenticated acceptance queried the company/currency, 28 Sales Orders,
10 original Production Plans, 46 Work Orders, 168 Job Cards and four Workstations.
The scheduling response was rechecked against actual data: 36 submitted unfinished
orders total742 units, four draft orders total74, and the draft orders have no
Job Cards. Corrected advice uses separate workstation loads and explicitly avoids
a guaranteed daily output from variable demo Job Card timings. A finite-capacity
optimization engine is outside this bounded recovery.

One independent acceptance Production Plan, `MFG-PP-2026-00011`, was created as a
draft with quantity1, updated to2 and submitted (`docstatus=1`, `status=Submitted`).
Each exact proposal left business data unchanged before confirmation. Independent
authenticated cookie/CSRF confirmations performed native transactions, and repeat
confirmations returned the same receipts without duplicate writes. Final Task
`d30b250d-8108-4354-9df1-f3462a49d13b` completed three real turns: update proposal,
submit proposal and post-submit ERP verification; canonical events show two
successful `erpnext.propose` and four successful `erpnext.read`, no failed or
suspended turn. Fresh HTTP history reload also passed.

The original8 Tasks,10 segments,591 events and22 binding rows retain their full-row
fingerprints. Original rows in20 manufacturing/inventory/ledger tables are unchanged;
only the acceptance Plan and its single child row were added. Work Orders/Job Cards,
stock and GL entries did not increase. All17 XGO services remain stopped. The original
general Worker stays stopped; the dedicated Agent/API/backend/frontend run with zero
restarts. Schema remains105 (104 ledger records, native gap71), with no migration.

Actual root causes fixed: hardcoded unbound API connector snapshots; missing native
empty extension authority; an unnecessary Effect payload requirement for frozen
read-only tools; logical workspaces treated as filesystem directories; full-history
projection backfill competing with live event writes; missing published aggregate
argument schemas; and file-Artifact delivery inference on business approval preparation.
The last fix uses the existing native Host contract and requires actual successful
tool evidence. Pending approval is never reported as completed business execution.

Five standalone stdlib source regressions and native builder/context/evidence checks
passed. Independently reviewed source freezes and failed live attempts remain retained
in the private server recovery directory. The initial fixture's read-only stock_uom
and description fields were correctly rejected and removed from that fixture; no ERP
field validation was relaxed. The first creation proposal's delivery suspension is
retained, and final update/submit acceptance passed after the contract repair.

This recovery enables bounded chat/read and Production Plan create/update/submit
proposals, each requiring independent confirmation. Attachments, Artifact/S3, commands,
arbitrary business writes, MCP/skills, knowledge/memory and scheduled jobs remain held.
No new browser visual acceptance was performed; the verified live path is authenticated
same-origin HTTP, actual ERP records and native canonical events. The existing frontend
and its fullscreen/session/Markdown behavior were preserved.

Older checkpoints below retain their historical deployment and acceptance boundaries.

## Prepared, reviewed and deployed

Commit `4af3922`: owner/company/site workspace references, owned resource APIs and safe UI, public task status/clarification, bounded ERP pagination/CSV/aggregate/report descriptors/comment and five additional reviewed controller conversions. Existing conversations and original native Runs remain intact. Backend image after containment: `sha256:7483b9f376d35f896b624d8667988c393c44d997d26c9be9df982e25c41fe620`; browser asset version `20261023-7`.

Local Python/Node checks pass. Authenticated low-role HTTP checks deny other users' resources/metadata and business approvals. Mocked browser acceptance passes at desktop1440x806 and mobile390x844 with reduced motion. These mocks make zero model calls and do not prove native file storage.

Static installed-source inventory now records1,403 whitelisted functions/controller methods (599 Frappe,804 ERPNext), with zero parse errors. Every entry remains pending method review; this is not arbitrary RPC exposure or proof of permissions.

Read-only native business checks validated194 report descriptors through the public adapter and the signatures/whitelist status of19 conversions. This is not module-chain certification.

## Native acceptance blockers found and contained

- Real TXT upload in QA conversation `mngo4262kr` failed before the Host received a Task ID. Cloud input still invokes legacy `store_payload`, whereas deployed PostgreSQL authority exposes only Worker-fenced output methods. A typed HTTP-input lane and atomic Task/message/rollover admission is required; a fake lease or shim is rejected.
- Cloud Worker root volume layout currently shares storage. Before private uploads/scripts, new workspaces require a sibling private root, actual quota mounts and a trusted allocator with native Task proof. Existing READY/SEALED legacy paths must remain unchanged.
- ERP and Trench Cloud currently share the same PostgreSQL database/role, despite different deployment namespaces. Global schema105 cannot be upgraded in place for ERP. A dedicated ERP database/role and verified namespace-only transfer must precede106.
- Server-only `attachments_enabled` defaults false; the deployed catalog disables uploads and explains the native repair. It must remain false until real initial/follow-up/refresh, isolation and resource acceptance pass.

Native ingress architecture and the no-dispatch database transfer plan passed independent review. Commit `eb36695` prepares independently approved initial/followup/clarification/atomic rollover input admission against captured deployed105 sources. Real disposable PostgreSQL106 checks pass for four-file admission, exact replay, rollback before dispatch, stable handoff retry, lost ACK, concurrent terminal inputs, original event preservation and exact committed root receipt coordinates. Actual pinned Worker tests capture provider requests after native clarification serialization/recovery, including original/prior current-turn images once and no durable data URLs. Final API SQLite compatibility checks preserve400 with zero writes outside verified Cloud opt-in. Thirteen native Worker artifact-fence checks passed on the earlier unchanged transition/schema models; they were not rerun against the final image. Real S3, private quota storage, fresh authority and user/browser file acceptance remain open. No production schema106 migration or native activation has run; shared Trench configuration and original database105 remain unchanged.

## Prepared and reviewed, not activated

Commit `b73529c`: server-only maintenance admission guard blocks submit/cancel, surface creation and all non-GET Cloud proxy calls before new grants/HTTP. Workspace/chat/client checks and independent spec/quality review pass. The flag remains inactive; inflight requests must still drain and ERP consumers must stop before any database transfer. This gate alone does not establish quiescence.

Commits `26edb88` and `30d7f47` prepare the independently reviewed native105 database transfer operator. Two disposable PostgreSQL17.5 servers passed the complete held-snapshot/pre-data/COPY/post-data/hash/catalog/scope/sequence flow:138 base tables,164 selected rows,3 Task IDs,9 event IDs, typed binding and idempotency receipts preserved, excluded namespace absent, nonsuperuser destination role and denied source authentication verified. The small native fixture separately passed cyclic deferred FKs, identity/generated values, escaped data and injected COPY rollback. Temporary maintenance containers and credential copies were removed. This is disposable QA acceptance, not production migration or API/browser continuity. Production105 and consumers remain unchanged. Consumer release must wait for legacy execution containment, private quota and fresh-authority acceptance; the105 Worker loop is consuming work even with Rabbit disabled and cannot be used as readiness.

Commit `270bbc5`: independently reviewed ERP-only legacy execution containment source. The final pinned105-base Worker image passed the runnable check under UID65532. Real disposable105 SQL validates typed Task/active-segment/workspace/binding classification including native NULL owner and folded URI; concurrent broker RUN, fallback MESSAGE and legacy RUN are exact typed metadata refusals with no new execution events, input materialization or active lease. Injected final capability-clock failure rolls back the actual PostgreSQL tentative dead update; this uses an explicit capability double and does not certify the complete strict-capability lifecycle. Enabled containment still refuses every private generation until real quota/mount/fresh-authority hooks. It is not activated in production. A separate ERP business QA site has its own MariaDB/Redis/app, Chinese/CNY/Shanghai company and no public port. Real native session/Desk-CSRF HTTP checks passed create/read/approval/replay, update/revision, ERP-document private upload/authorized download/removal, and a non-stock Material Request submit/cancel/amend cycle; fixtures were deleted. Cloud is disabled there. Inventory movements, financial postings, remaining module chains, browser page actions and Cloud Agent input files are not covered.

P2 canonical revision2 frontend profile: seven typed actions; native fixed-key/depth4/16KiB constraints, total100 child edit cells and mandatory complete-receipt byte preflight. Revision1 digest is preserved. Explicit CAS activation is required. Handlers, native publication and browser page acceptance remain open.

## Still required

- Complete native attachment repair, dedicated ERP DB transfer and per-workspace physical isolation; verify real files/artifact download and preserved histories.
- Implement the reviewed indexed admission receipt and explicit prepared-input recovery; browser refresh must not reconstruct absent bytes or replay a model automatically.
- Wire native input attachment history into the UI (the metadata RPC exists); define bounded owned input-content retrieval if the native contract lacks it. Extracted documents must not masquerade as downloadable original binaries. Keep indexed model/tool internals out of the user file gallery.
- Add fresh ERP user/company authority checks at native generic tool/model/context/publication boundaries before P3; current frozen grants/Cloud lease checks alone do not certify revocation.
- Contain new execution on legacy shared-root bindings while preserving owned history/stop; `research/read_only` and upload rejection alone do not isolate file reads. Enable execution through explicit new private Tasks.
- P2 fresh Host page authority and typed browser handlers, full operation ledger, isolated module-chain QA.
- P3 protected web/analysis and scoped skill/MCP selection/Policy/HITL acceptance.
- P4 scoped memory management/injection and honest full-text knowledge retrieval; no semantic index is currently demonstrated.
- P5 scheduler renewal/fire-to-Task mapping, per-session settings, notification/budget controls and firing/restart acceptance.

Detailed plans are in `plans/`; sibling evidence file `zebra-erpnext-evidence/full-agent-p0-p1.json` records exact tested/unaccepted boundaries. No package-status label substitutes for these remaining gates.

## Private-workspace preflight

Read-only actual-host inspection confirms Worker UID/GID65532 with identity mappings, no added capabilities, and native OCI command isolation configuration (one leaf bind, read-only root, network none, runsc). The old workspace host mount is shared but its Worker bind is rprivate; a new sibling root and rslave propagation are still required. Existing quota validation checks mount/capacity only, so per-leaf filesystem identity must be enforced before provisioning and on every resolution. The configured fixed sandbox image `zebra/runtime@sha256:33735bd63cf84d7e388d9f6d297d348c523c044410f553bd878c6d7829612735` is absent both by repository reference and image ID on the server. Physical quota, OCI execution and restart persistence acceptance remain open; static OCI source does not prove them.

A separate fixed Python candidate was successfully pulled and executed directly under runsc, network none, read-only root, cap-drop ALL, no-new-privileges and UID65532: `swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/python@sha256:52331dac368d5bcf1c00d30a782753d28bb7286a12b7bb629f388cec4cfd6fb2` (Python3.12.12, stdlib CSV/JSON/SQLite/ZIP/hash checks). No workspace was mounted; this proves basic candidate execution only, not native Task/OCI, physical quota or cross-user isolation. Production configuration and original Tasks retain their previous image binding.

## 2026-10-24 coordinated takeover and API-only continuity

This chat is the sole deployment owner following the user's explicit decision; the other chat confirmed all related source/server work stopped. Its inherited private-quota changes are preserved but remain unapproved and inactive.

The dedicated ERP PostgreSQL105 transfer was independently reverified against its sealed manifest: all138 tables and11,279 selected rows matched full row hashes, with original8 Tasks/10 segments/591 events/22 bindings preserved. The runtime role is nonsuperuser with no role memberships or source-database access. Only the pinned original105 API has now switched to the dedicated database; Worker remains stopped with restart disabled and an execution-held Compose profile. API startup preserved every selected row hash. No106 migration ran. Host admission remains paused and attachments disabled.

Real Frappe Administrator CLI context plus Cloud API reads loaded all5 owned historical conversations and17 public messages, preserving2 completed/1 cancelled/2 failed statuses. No new Task, command or model call was submitted. This proves server-side owned-history continuity, not browser authentication; GET grants can legitimately update authorization audit metadata. Earlier paragraphs describing unchanged production consumers are historical checkpoints superseded by this API-only switch.

The isolated fresh-authority source freeze `df8d45aa6de1dd3ed62e631c644d0d544a70929fa2d069e8fd2fc1cf0ea69b76` passed independent spec and quality review, including continuation revision refresh. The public cumulative tree also includes inherited unreviewed quota changes and is not covered by that approval.

Actual disposable Frappe DB plus Caddy HTTPS tests passed mapped-user/company authorization, Shanghai expiry clamping, disabled-user/company-permission revocation, Task/thread/Run/workspace/status drift, invalid HMAC and expired Grant refusal. Fixtures were removed and the QA site's Cloud configuration disabled again. Production Host source was not changed. Complete native Worker refusal disposition, real PostgreSQL lifecycle tests and physical quota/OCI isolation remain activation blockers. Early-refusal design is under independent review and includes explicit same-Turn/new-Run recovery without re-appending user input or automatic business replay.

Evidence: sibling `database-api-only-preservation.json`, `database-api-only-history.json`, `database-transfer-production-reverification.json` and `fresh-host-https-acceptance.json`.

## Early fresh refusal source reviewed; execution still held

Freeze `bbd5f438f490bf1b1156b1fc4ba801c1ec6a32acc3dbd408621fe918bd2f282d` (210 files) passed independent SPEC and QUALITY review. The bounded slice adds native metadata-only early refusal receipts, original recovery budgets, exact historical proof gating, authorized public outcomes, and explicit same-Turn/new-Run recovery without re-appending user input. Unknown acknowledgements retain the exact command, Run, revision and key. Shared Host persistence reacquires the current MariaDB row and verifies the actual Redis token after grant commits/network boundaries; ordinary submit, retry, client surface, stop, settings, management and presentation share the guard. No new dependency or coordination framework was added.

Actual compiled API/Worker checks verified44/52 copied files and ran with the source overlay loader disabled. Disposable PostgreSQL105/106 checks cover canonical classic/modern receipts, concurrent writers, injected final-fence rollback, native generation0..5 exhaustion, native AG-UI handler/grant renewal/configured extension snapshot reuse, duplicate admission, later ordinary MESSAGE, real strict process attestation and natural final-capability-expiry rollback. Current strict expiry disables the read-only retry action while historical proof remains valid. These are native handler/store acceptance with synthetic lifecycle fixtures, not HTTP JWT ingress or business/model execution.

Independent deterministic Host checks pass7 ownership groups and9 BFF recovery groups. A QA-only Host candidate inherited the current HRMS16.52.0 image `sha256:1a56e963dae6f9cb86399dfa8c3a05fd281bc0cc755b0016b1c10886e542c07d`; its11 frozen Host files match the reviewed source. Actual Frappe/Redis/MariaDB checks reject an expired Redis owner and preserve a successor's Run/command. During the row-wait case, native RR/InnoDB error1020 refused the changed row before the Redis check; this proves fail-closed preservation, not execution of the later token check. Fixtures were removed; QA Cloud remains disabled and no model/Cloud Task was created. The stopped prior QA app is retained for rollback.

The current production ERP Host includes HRMS from a separate explicit user request; subsequent Agent images must preserve that current base, rather than restore the earlier r3 image. Production Agent remains pinned105 API-only on its dedicated database, with Worker stopped/restart disabled, admission paused and attachments disabled. Native physical quota/operator completion and real HTTP JWT/browser/file/model acceptance remain required. Unreviewed inherited private-quota changes remain separate dirty work and are not covered by this source approval. Detailed evidence is in sibling `early-fresh-refusal-checks.json`.

## Physical workspace primitives verified; allocator review pending

Live read-only preflight reconfirmed the current HRMS Host, original105 API and stopped/no-restart Worker. Two disposable256MiB ext4 leaves then passed real host/kernel and direct OCI checks: new child mounts propagated to an already-running rslave native Worker-style container with matching device/FSID; UID65532 runsc writes exhausted one leaf with ENOSPC while preserving both canaries; unmount/remount retained UUID, FSID, UID65532/mode0700 and files. Each filesystem exposed234,594,304 bytes capacity after ext4 overhead. The temporary observer, mounts, backing files and QA directories were removed.

These checks use synthetic canary identities and direct Docker commands. They do not certify the allocator protocol, native Task authority, native OCI adapter, HTTP/JWT ingress or model execution. A runsc observer virtualizes filesystem identity; equality is checked in the native Worker-style runc container while command isolation uses runsc. Direct runsc checks required512MiB/pids128 after the initial128MiB/pids32 sandbox failed startup. Evidence and runnable check: sibling `private-workspace-physical-primitives.json` and `check_physical_workspace_primitives.py`. The implementation and independent review of the privileged allocator remain in progress; production execution is still held.

## Actual allocator protocol accepted with synthetic authority; integration findings open

The inactive Worker candidate `sha256:2e730f259a8eccd96dfcf41d47c7b09657304057997d5250efaad493866a8eeb` matches all56 Docker COPY hashes. Its native identity/resolver dependency checks passed with the overlay loader disabled. Compiled helper malformed/oversized/invalid-UUID inputs returned bounded refusal without traceback or credential markers. These helper checks used network none and do not prove successful DB/HTTPS authority.

Actual UID65532 Unix-socket requests to operator source `278720b9c10c39e9929fdf30531a2aa8c45a080a5e858f4f829eb1c64be9199f` passed peer-credential/MAC/nonce/owner rejection, lost-ACK reuse of the identical ready allocation, compiled Worker receipt/UUID/kernel identity validation and root metadata tamper denial. Native mount reset/tree digest handled ext4 lost+found. Restart restored unmounted images and retained canaries/UUID/permissions. A real slow proof was interrupted after20.0019seconds and the next request succeeded. All disposable allocator processes, mounts, images, key, socket and state were removed. Evidence: sibling `private-workspace-allocator-uds.json` and runnable `check_private_allocator_uds.py`.

That test redirected the Worker ROOT and operator state to explicit QA siblings and supplied synthetic native identity/expiry. It does not prove native Task/Host authorization or production wiring. It also exposed that actual `/opt` ancestors are Ubuntu-owned; new root-exclusive state/config/key/socket/source must instead live under a root-controlled `/var/lib/zebra` sibling, preserving existing deployment ownership.

Independent quality review found an additional inherited private-activation blocker: the command handoff still unconditionally refuses a successful private policy check and skips native command preparation. The repair must gate private checkpoint reads with current native/Host/physical authority before entering the unchanged two-second native handoff budget. It must preserve canonical broker/fallback, recovery and control semantics; the existing unactivated coverage capability remains unavailable. Source fixes and repeated independent review are in progress. Production Worker, admission and uploads remain held.


## Private workspace source integrated; compiled and native DB boundaries checked

Cumulative freeze `f81bdbad9f5727588c56075b8e77df2ef724875d2b52c229e47a8d21dc471765` passed independent SPEC and QUALITY reviews and was integrated as local commit `a483c12`. The root-controlled state now defaults under `/var/lib/zebra`. Modern private admission verifies canonical active Task/workspace/binding, current Host authority and physical identity outside the unchanged native two-second handoff budget, then rechecks its exact request-local proof before preparation and lease. Classic body readers/direct claims defer private work before reading input or acquiring a lease. Native metadata-only historical settlement preserves handled/accepted/retired/stale no-execution outcomes without fresh Host or physical work. The private maintenance sweep retains existing verified FreshUnavailable recovery and generation limits while unsupported coverage remains guarded. Original exact accepted-command fingerprints are preserved; no business replay is introduced.

New inactive Worker `sha256:c3a545fa0fca2e4174065ed629cf15b0e7f871fc6cafb161809d5dd8607127fa` and API `sha256:b01f00afff3a027b5ce61f0747ff684ac2735ba67e5201fc321e804c896f3024` match all61/48 COPY hashes. With the source overlay loader disabled, compiled native private preparation/handoff, historical settlement, sweep configuration, classic/direct defenses and legacy/control checks pass. The AST wiring check reads the identical frozen source but imported product modules come from the compiled image. Neither image is activated.

Disposable PostgreSQL105 checks passed broker/fallback RUN/RESUME/MESSAGE handoff, native checkpoint/lease/receipt/message idempotency and missing/expired/revoked preparation denial. Six historical handled re-deliveries used native fenced synthetic AttemptStarted/TurnCompleted fixtures and returned DUPLICATE without Host/physical preparation or extra messages. This actual-DB milestone uses synthetic fresh/physical seams, not real HTTPS helper or model execution. A subsequent compiled test extension reached recovery proof validation and correctly rejected a fixture whose empty RUN payload lacked canonical Run attribution; its separate QA database is retained while the test fixture is corrected. Core/product validation was not weakened.

Production remains the original105 API-only deployment, Worker stopped with restart disabled, Host admission paused and attachments disabled. The real confined helper with a read-only native DB role and restricted DB/HTTPS network, native Task/Host lifecycle, authenticated HTTP/browser and minimal real file/model/artifact round trip remain activation gates. Evidence: sibling `private-workspace-source-review.json`, `private-workspace-compiled-f.json`, `private-workspace-compiled-f.log` and `private-command-postgres-flow-f.json`.


The corrected extension subsequently passed using the compiled Worker with the overlay loader disabled on a new empty own PostgreSQL105 QA database. In addition to the12 basic cases and6 handled-history checks, the actual native FreshDisposition/recovery paths preserved exact original-command fingerprints, approved known-unavailable generations0..5, exhausted at the original ceiling, and acknowledged approved stale-generation deliveries without Host/physical calls. There were no AttemptStarted events or replayed business inputs in that recovery fixture. Only this disposable fixture's recovery clocks were advanced. The earlier failed fixtures are retained. Runnable guarded test and test-only SHA manifest are included; compiled raw log and bounded evidence are sibling `private-command-postgres-compiled-f.log/json`. Restricted real helper DB/HTTPS and joint deployed acceptance remain open.


## Confined helper native hostname wiring reviewed; final real QA waiting for connectivity

The first full helper QA reached actual read-only role auditing, native Task admission, real Frappe fixture mapping and the positive helper boundary. Role attributes, memberships, object/column write privileges, sequences and artifact denial all passed; only8 metadata tables and6 event columns (including the complete synthetic-QA payload JSON) were readable. The positive helper remained unaccepted. Configuration bytes/mode/owner were restored, all owned Frappe fixtures were independently proven absent and the temporary proof network was removed. Nine apparent container differences were only nondeterministic Mounts array order: independent canonical comparison proved every mount/config object unchanged. QA file-opening and Frappe cwd/sites_path defects were corrected with runnable regressions; failed QA databases remain retained.

Compiled native read-only diagnostics separately passed private facts, typed binding, credentials, registry profile pin, FreshERPAuthority construction and gateway resolution without making an HTTP request. This exposed a required deployment configuration gap: the independently launched proof container does not inherit the main Worker's native SSRF hostname allowlist. Source commit `8cc62d0` now requires one trusted-root `helper_hostname`, validates canonical DNS syntax and uses native AI_NUMERICHOST parsing to reject decimal/hex/octal/abbreviated IP variants without DNS, then explicitly passes exactly that hostname through the existing native environment seam. Existing restricted network, TLS/CA, profile pin, credentials stdin, nonce, deadline and cleanup remain unchanged. Independent SPEC and QUALITY reviews and both offline runnable checks passed. The missing configuration is established; it is not claimed to be the only cause of the earlier failed positive probe.

The corresponding QA source package mirrors this exact launch configuration with a fixed QA hostname and verifies the actual container environment. Its fresh empty105 database is `zebra_private_workspace_qa_52347c1a62f8`; prior failed fixtures are not reset or reused. QA driver/source hashes passed independent SPEC and QUALITY reviews. Worker/API image code is unchanged, so no image rebuild is needed for this host-only correction.

Before uploading/retesting that package, SSH to192.168.110.42 failed with No route to host. Local en0 remains192.168.110.81, while target ARP is incomplete. No latest QA driver was executed and no production activation occurred. Production status after connectivity loss is unverified; the last confirmed state was original105 API, stopped/no-restart Worker, current HRMS Host and paused admission/attachments. After connectivity returns, run the frozen real-helper positive/deny/restored-control matrix, then continue the remaining operator/HTTP/browser/file/model acceptance gates. Sources, exact hashes and execution status are saved in sibling `private-helper-native-qa/`; actual prior QA evidence is `private-helper-native-qa-e3f.json`.


## Connectivity restored; compiled native helper real HTTPS matrix passed

After the operator requested retry, SSH to192.168.110.42 returned. Uptime showed a server reboot; the original105 API, HRMS ERP, Caddy and Authelia images remained unchanged. Production ERP Worker remains stopped with restart=no. Only the five preexisting disposable QA target DB/app/Redis/TLS services required for this check were started; their restart policies were not changed. The bootstrap now uses the fixed QA Docker DNS name instead of a stale container IP.

The first real HTTPS retry passed allow, disabled-user refusal and restored allow, then failed the company case without enough diagnostic detail. Actual read-only Frappe source/catalog checks did not establish a missing cache eviction or a product company-boundary defect. The next reviewed QA-only delta uses native User Permission insert/delete hooks with exact owned identifiers and preserves bounded failure categories. Both independent reviews passed, and the unchanged deny/restoration matrix subsequently passed all17 checks on a new empty105 database, zebra_private_workspace_qa_0534931fc627. This proves actual compiled helper DB + TLS authority behavior for user/company revocation, stale Run, wrong workspace, unknown session, bad CA/HMAC and connector-pin drift, each followed by restored allow. The original failed fixtures remain retained; the unique prior failure cause is not asserted.

Actual role/catalog audits, no helper DB writes, exact config byte/mode/owner restore, owned Host fixture cleanup, proof network deletion and original container configuration preservation passed. Root independently rechecked evidence, QA config absence/mode/owner, proof network absence and exact production image/restart state. No model, allocator, business dispatch, production migration or Worker activation occurred. The synthetic QA event-payload column privilege exception remains explicitly limited to this QA database. Evidence and runnable sources are in sibling private-helper-native-https-passed.json and private-helper-native-qa/. This closes the real DB/HTTPS helper gate only; the combined actual operator/UDS/ext4/native Task and later authenticated HTTP/browser/file/model gates remain open.

Read-only post-reboot inventory also found unrelated Trench Redis repeatedly exiting with a bad format in appendonly.aof.1680.incr.aof; multiple Trench services are consequently unhealthy. No Redis file was modified or truncated. This is a distinct availability issue and blocks a claim of healthy Trench joint acceptance.


## Combined native allocator attempt held before allocation

A new single-identity composition QA runner passed independent SPEC and QUALITY review after embedded-script syntax, nonblocking packet validation and pre-create container cleanup tracking fixes. Its copied driver preserves the complete17-case helper lifecycle, adding one explicit joint step before the existing finally. Root staged hash-pinned sources under a new root0700 control directory; no ordinary-user source was executed as root.

On fresh database zebra_private_workspace_qa_546f0c0172a8, the initial native HTTPS allow passed in3.242s. The next disabled-user case failed with checker phase cleanup and no retained primary outcome. This does not establish an unexpected authorization allow or uniquely prove a launch timeout: the existing finally lost the primary exception/timing. The joint packet was never published, so the native allocator, socket and ext4 portion did not start. Root stopped the pending root waiter. Driver cleanup passed; independent checks found no proof helper/network, no joint QA/state directories, and restored site config. The root-owned staged source control directory and failed native DB are retained for diagnosis.

The earlier17-case real HTTPS pass remains a bounded functional result, not a claim of stable joint acceptance. The next step is diagnostic-only timing/exception classification with unchanged helper7s and cleanup1s limits and no product authorization changes. Evidence: sibling private-joint-one-attempt-546.json and reviewed sources under private-joint-one-qa/. Production Worker/admission/attachments remain held.


Diagnostic attempt498e894a6960 retained the unchanged7s launch/1s cleanup limits and again passed all17 real HTTPS cases. Actual root NativeProof/UDS composition then reached its first ensure request, but cleanup failed closed before allocation. A concurrent sanitized Docker observer recorded the actual operator helper at create0/start0.149/die5.608/destroy9.405 seconds: process exit to deletion took3.797s, exceeding its1s cleanup budget. The helper exit code was not retained, so no unique primary authorization/output failure is inferred. Independent root inspection found zero volume records/ext4 images and zero server log bytes. Own allocator/helper/command processes are gone; root-only state and sources remain retained. Site/Host/network/container cleanup passed.

This establishes a cleanup-budget shortfall on the actual composition path. A host-only candidate will reserve5s for cleanup within the unchanged20s total request budget; the launch budget remains capped at7s and failure remains sticky/fail closed. Independent review and new live acceptance are required. Evidence: sibling private-joint-one-attempt-498.json and private-proof-events-498.jsonl.


The host-only cleanup-budget candidate passed independent SPEC and QUALITY review and offline checks. Operator9571f02e7eaff026a1f6022d6ce4865fb78ba110e0b107405d400751b7bdca2b now reserves up to5s for exact owned-helper cleanup while preserving the original20s absolute request bound and7s maximum helper launch. Available<=5s refuses before launch; near-deadline launches reserve the cleanup budget; failed cleanup remains sticky. No Worker/API image changes. A deterministic replay covers the observed3.797s interval, near-deadline boundaries, no post-deadline spawn and timeout refusal. QA instrumentation and root-runner source pin updates passed byte-exact provenance checks. Fresh real composition acceptance remains pending. Review/provenance are in cloud-patches/PRIVATE_HELPER_CLEANUP_REVIEW.md and private-helper-cleanup-budget-sha256.json.


## Single-identity real native allocator composition passed

Host-only cleanup budget repair is integrated locally as5a6759f after independent SPEC/QUALITY and the runnable hardening check. With the unchanged compiled Worker image, fresh QA database zebra_private_workspace_qa_c4e33f1235fa passed all17 real HTTPS checks and the actual root NativeProof→UDS→Allocator→ext4→compiled PrivateWorkspaceClient composition. UID/MAC/nonce refusals, unknown-session/wrong-workspace denial without extra images, lost ACK/new nonce receipt stability, canary/UUID persistence across own allocator restart and read-only root identity metadata checks passed. A c3/default-runc single-leaf container proved mount/credential scope only; it is not native commandgateway/runsc acceptance. The compiled client completed in3.573s; measured direct calls were under20s (maximum6.003s). Native DB snapshots remained unchanged by the helper/allocator.

Root joined both processes at exit0. Independent follow-up confirmed owned User/Employee/Company/Grant/Conversation absence, removed QA root/state/control trees, absent helper/command containers, restored site/Host/network/container invariants and the original production Worker still stopped with restart=no. A sanitized observer recorded25 helpers, each destroyed, with bounded die-event exit codes for this run. Failed earlier fixtures remain retained; no original Run/model/business replay or production activation occurred. The earlier helper primary outcome is still unknown; this success validates the repair without retroactively assigning an exit code.

Evidence and frozen runnable preparation sources: sibling private-joint-native-passed.json, private-proof-events-c4.jsonl and private-joint-native-passed/. Next gates remain two actual principals/companies in one native DB with cross-binding/file scope checks, then authenticated HTTP/browser/file/model/artifact and native commandgateway acceptance, reviewed production role/migration/activation, and remaining P2–P5 capabilities. Full Agent remains open.


## Proof-only locator read narrowed; production ACL work remains open

Read-only production/native-source audit confirmed that the QA reader's whole event JSON grant is not a production confidentiality boundary. The shared full workspace getter also loads definition_snapshot unnecessarily for the root allocation proof. The independently SPEC/QUALITY-approved source now adds private_facts(metadata_only=False): default containment/preparation callers retain the full native projection and recovery equality; only native_workspace_proof opts into an exact namespace/session workspace_root query and returns no fabricated projection. All active Task, typed binding/digest/lineage, source/owner/quota, identity and fresh Host checks remain shared.

The extended native regression passed on exact c3 dependencies with just the new module in memory, network none, read-only root, UID65532 and mocked DB/Host/physical seams. This is source-overlay acceptance, not compiled new-image or PostgreSQL view/ACL acceptance. A rebuilt Worker and API (both COPY the module) are required. Source SHA71a798ba5e649be51793ecd99bc6f9643d548d1de93036d3e601db7f34a5c216 and packet761b883943ae9bfce04fcfe3246ea7fcd876510baa0c49664aac7a7fde081f7c are recorded in cloud-patches/private-proof-locator-sha256.json.

The next database slice will use protected PostgreSQL control views and a nonowner role, with no direct base-table/body/definition grants. Namespace-wide trusted native-produced control metadata is the accepted root-helper boundary; raw user messages and definition bodies are excluded. No production DDL/role/grants or migration has occurred, and no old c3 result is claimed as executable acceptance of this changed source.


The proof-only locator candidate is now built into inactive Worker fbdfb5d3cbbabc360342b86841d4c0a83fc52098bacc47ed189fdf2a6f5fe3b9 and API 3e09053260f2deb447d47e9d5f7c8a5423f09aff1ac862e79c96f0939f0db2b6. Root verified all61/48 COPY file hashes inside the actual images. The extended native regression then passed on the actual new Worker module with no product source overlay; its test-only overlay_imports stub reads preparation_source from the actual image. DB/Host/physical seams remain mocked, so this closes compiled-code regression only, not protected-view/ACL or new-helper live acceptance. Build used the frozen f3e7268 context with no network and no base pull; neither image was activated. Evidence: sibling private-proof-locator-compiled.json and private-proof-locator-compiled/.


## Disposable native ERP Host site created; dual-identity acceptance still open

The fixed own QA site erpnext-dual-qa-c9e5b43a.local / database-user zebra_dual_qa_c9e5b43a is now created through the actual native Frappe→ERPNext→Zebra installation flow in the existing QA bench. Root driver d31854586d3618edd57ca77650ea5c6d400ea8eca7424b28d4122b24c1bd6aac exited0 under fresh root-only state c9e5b43a-native-init. Independent read-only Frappe SQL verified the exact database, exactly those three installed apps, zero Company/Task/Zebra Conversation/Zebra Grant rows, maintenance/pause/mute flags, disabled scheduler, disabled Zebra admission and own config0600. Original main-QA config/app-list/default-site/asset bytes, ownership and mode equal the frozen before-state. Site remains private and retained; no new TLS route, user/company fixtures, Cloud grant/Task, model call or production activation was performed.

Two failed own attempts remain retained. The first lost its original exception in the wrapper; a separate actual dummy constructor reproducer showed native Database initialization opens a nonexistent site log before directory creation. Native bench context resolves both pre-create admin queries and post-drop verification; bounded value-free error class/frame logging now preserves diagnostics. The next actual run passed admin checks but exposed the native CLI prerequisite: commands/site.py initializes the target with new_site=True before _new_site. A one-line matching initialization after bench destruction resolved IncorrectSitePath. Both fixes passed independent SPEC/QUALITY review, actual no-SQL constructor/context probes and focused runnable checks; no historical missing exception was invented. Native empty teardown has not been executed.

Source/probe manifests and retained-attempt evidence are sibling disposable-dual-host-site-attempt.json, disposable-host-logger-fix-attempt.json and disposable-host-native-init-passed.json; the final frozen runnable package is disposable-host-native-init/. This closes isolated Host bootstrap only. Protected proof views/role/HBA, two native principals/companies, actual commandgateway/browser/file/model/artifact and production migration/activation gates remain open. Original production API215644 is still running and Worker33b93 is stopped/restart=no after reconnection.


## Actual PostgreSQL17 protected reader and HBA matrix passed in new QA database

A newly created empty native105 database zebra_private_workspace_qa_c280841175cf now has the independently SPEC/QUALITY-approved nine protected control views, trusted NOLOGIN view owner and nonowner proof login. Actual PostgreSQL17 setup committed only after the full effective privilege audit passed. The catalog-guided eight-statement prerequisite transaction preserved all six existing runtime privileges while removing PUBLIC TEMP and three LO creator EXECUTE privileges; denied LO import privileges were not widened. Thirty-two native invoker trigger functions and three non-trigger definitions were reviewed; no blanket function revoke or RLS change was used.

The separately SPEC/QUALITY-approved fixed QA HBA operator then performed the actual Alpine uid70 atomic replacement, native rule parsing and reload. Five proof-login-only rules precede the unchanged original rules, enforcing target-only SCRAM over IPv4/IPv6 and rejecting other databases and Unix sockets. No restart or root/bootstrap-password retrieval was needed. Conditional restore is implemented but not executed: it requires the reader absent/NOLOGIN and zero sessions, plus exact owned after/backup hashes. The active QA reader remains restricted for later native fixture work.

Actual bounded verification passed75 checker cases plus Unix socket rejection, followed by independent SPEC/QUALITY review of executed source and evidence. Correct-password target connections worked over IPv4, IPv6 and internal IP; wrong passwords returned28P01, other existing databases returned28000. With readonly explicitly OFF, base message/definition/unrelated reads, DML/DDL/TEMP/LO creators/role escalation and invoker DML still refused42501; missing projected definition returned42703. All32 direct trigger calls refused0A000. The runtime successfully exercised owned TEMP and three LO constructors inside forced rollback. All138 public-table and LO metadata fingerprints, runtime ACL facts and HBA bytes remained unchanged; the client exited0 and its owned container was removed.

This closes SQL/HBA/ACL acceptance only. There are zero native Task fixtures in that QA database: actual native root/child/Fresh, body sentinels, malformed lineage, dual principals/companies, commandgateway/browser/model/artifact and production activation remain open. New Company/User/permission fixture preparation targets only the successfully bootstrapped private MariaDB site; no Company records have been created there yet. Production data, API/Worker images and admission state were not changed by this slice. Evidence: sibling private-proof-control-views-qa-passed.json, private-proof-acl-matrix/, private-proof-hba-qa/, private-proof-control-views-execution/ and the dependency-preserving private-proof-control-views-v2-bundle.tar.gz.


## Two native ERP principals/companies verified; private HTTPS transport passed

The private Host now retains two real Companies, two native Users and two UUID Company User Permissions. Native creation initially exposed the missing pre-company Warehouse Type Transit; actual source/data identified the canonical stage_fixtures step, which was then used without bypassing controllers or links. Creation committed, but verification correctly refused empty stored roles: ERPNext User.validate removes Employee when no Employee.user_id mapping exists. No cache bug or successful Company.read was claimed for that failed state. A separately SPEC/QUALITY-approved one-shot role-only correction used native User.add_roles('Projects User') on the two existing owned Users; no Employee was fabricated, no Company/User creation was replayed and no hook was disabled.

Actual correction and independent read-only follow-up passed: both stored roles are Projects User, both principals read/list only their own Company and refuse the other Company under native user contexts, including warm/cold cache paths. Company2/User4/UserPermission2 remain; Task/Grant/Conversation0. Business/reference snapshots and main-QA file fingerprints were preserved. The own site remains Cloud disabled/paused, maintenance/scheduler paused/mail muted; native HTTP login/Agent Task/Fresh/allocator acceptance is not implied. All prior failed source/state and bounded diagnostic metadata remain archived.

A new private Caddy transport also passed actual startup/native validation, exact CA+SAN/hostname verification, forbidden-route404 and maintenance/control refusal503. The first isolated service failed exec because the native Caddy binary carries cap_net_bind_service=ep; metadata-only platform probes established the cause. The reviewed fix adds only service NET_BIND_SERVICE while retaining nonroot1000, read-only root, no-new-privileges, no host ports and exact control route. The original stopped failure is retained. New TLS container bfccfc880c3a25e555a22ff88e55c084097d7a9f72bfeaa27441604e7241612c serves authority-dual-qa-c280841175cf.local on the QA app network; public CA hash de3bf58d12c754351ba5a725c1081d8c81335967b280f642961f39d8f62924c9. Private keys were not exported and no old CA was reused. Fresh authority allow is still NOT_TESTED.

Next is source preparation/review for the combined two-principal native admission→restricted-reader→real HTTPS→root UDS/allocator/ext4/compiled-client gate, using existing retained Host identities and the same c280 native105 QA database. Its five-minute Grants have not started; no new Agent Tasks/model/production activation occurred. Trusted compiled clients necessarily receive their client socket/key; untrusted command containers must receive only their own leaf. Native commandgateway/browser/model/artifact and P2–P5 remain open. Evidence: sibling private-dual-host-permissions-passed.json, private-dual-host-permissions-bundle.tar.gz, private-dual-https-passed.json and private-dual-https-bindcap-bundle.tar.gz.


## Dual native composition attempted; restricted-reader parity refused

Frozen manifest3a97c16bd52f374fd3020077eeb5155dc53c34f4b5f7e19296688f17cb6631ee passed SPEC/QUALITY and25 offline rejection checks, including mount-order normalization preserving full fields. Actual one-shot execution admitted exactly two native Task fixtures, then refused during reader-binding-parity before any temporary network, Host config, Grant, root packet or workspace allocation. Native Task history is retained; do not replay/reset admission. Driver reports original container boundaries and HBA unchanged, cleanup_errors empty. Parent joined the root packet-wait process at exit1 with Ctrl-C, before any packet/root leaf work. Independent check confirmed exact original site config, Cloud disabled/paused, no packet and no private network.

The parity wrapper suppressed primary exception details. Offline tracing found that the projected task_binding_snapshots columns omit binding_digest even though the native getter selects and validates it; this remains a hypothesis until the actual compiled-image read-only diagnostic confirms the failing frame/SQLSTATE. A separate read-only bounded diagnostic is being prepared against the retained fixtures and exact compiled image; it will emit only exception class/frame metadata, no credentials/SQL/native messages. No Fresh/physical/compiled-client acceptance is claimed. Production images/Worker state and business data were not activated or replayed. Evidence: sibling private-dual-native-composition-attempt.json and private-dual-native-composition-attempt-bundle.tar.gz.


Actual separately SPEC/QUALITY-approved read-only diagnostic f5e8d1c69d5e80da03f61244b037020f226922b7b0025fdaa4d0c57c2c5a372a confirmed the parity cause in the unchanged compiled Worker image: reader UndefinedColumn42703 at task_admission._read_session_root_binding line377; writer exact getter PASS on the same retained root Task. Actual task_admission source hash2f91854d4921edd41d00d4544a730db575327022a456efd1c246fb28daaa517f, expected reader role/database/search_path/READONLY all passed, actual view has exactly the four previously recorded columns and omits binding_digest. The diagnostic container was removed and pinned PG/network/HBA were unchanged. No Fresh/TTL renewal, model, admissions or data/policy changes occurred. This confirms the missing-column defect; it does not establish native Fresh/allocator acceptance. Minimal owned-view correction is being prepared separately, without weakening native stored-digest checks. Evidence: sibling private-dual-parity-diagnostic.json and matching bundle.


## Required native binding digest projected; actual retained-fixture parity passed

Separately SPEC/QUALITY-approved correction25357ae612de3c48c3a9d7c85087ea5608d4026d282aedb904edb9633e8098dd committed exactly three QA-only SQL statements: owner base-column SELECT(binding_digest), CREATE OR REPLACE the existing protected target view with that column appended last, and reader view-column SELECT(binding_digest). The unchanged full auditor ran before mutation; its shared column allowlist then appended only that native-required digest and the full effective auditor passed again. Existing column positions/metadata/ACLs, view identity/owner/security barrier/namespace, the other eight views, all138 base-table fingerprints, roles/memberships/schema+database+relation+other-column ACLs, runtime six ACL facts, LO metadata and HBA were preserved. No production DDL or activation occurred.

Actual post-commit compiled-image read-only validation passed full typed binding parity and metadata-only-reader root identity vs native writer full projection for BOTH retained Tasks. A separate invocation of the original approved read-only diagnostic independently confirmed digest exposed=true, reader/writer getter PASS, unchanged compiled module hash and binding equality. Both confined helpers were removed, PG boundary/HBA stayed unchanged, model/new-fixture counts were0. Existing Task history remains intact; no Host config, Grants, expiry extension, Fresh/allocator/root workspace work was part of this correction.

Evidence: sibling private-proof-binding-digest-correction.json, private-dual-parity-after-correction.json and private-proof-binding-digest-correction-bundle.tar.gz. This closes the actual missing-column repair and retained native read path; the combined two-principal Fresh/physical gate remains open. A new reviewed continuation must preserve the failed attempt/history and never rerun its one-shot admission. Any expired immutable binding is not renewed or treated as current authority.


## Two-principal actual native proof/HTTPS/physical composition passed

Continuation manifestad5638f7b3188538fdd48120b8564223fb7d8a362607d87acb17b44a68643390 passed SPEC/QUALITY,29 offline rejection checks and actual text/binary stdin-bootstrap regression. Before any new fixture, actual corrected full ACL plus both old native bindings/root metadata passed again. The continuation preserved full-row hash multisets across all138 tables, read the existing connector profile/binding without publishing/rebinding, and admitted exactly two distinct fresh synthetic Tasks. The original two bindings/history and original failed source/execution files remain unchanged; no old expiry was renewed. QA now retains4 Task/segment/binding/control rows.

Actual two-principal restricted-reader→real HTTPS→root UDS/Allocator/ext4→unchanged compiled Worker clients passed. Both actual native Fresh allows produced different ext4 UUIDs/filesystem IDs; cross-paired session/workspace requests refused without extra images or canary changes. UID/MAC/nonce replay refusals, lost ACK/new nonce receipt stability, both own UUIDs/canaries across allocator restart, trusted client own-leaf/read-only-own-metadata/sibling absence, and two untrusted default-runc own-leaf-only command containers passed. Native Company permission A→B immediately made existing A refuse while B allowed; native restoration made A allow again. Measured Grant window60.539s; maximum direct call5.953s, original20s request/7s launch/5s cleanup reserve unchanged. Both parent processes exited0.

Driver verified no proof/allocator writes against the full138-table post-admission baseline and completed exact config/native identity/permission/workflow/source/network/container/HBA restoration. Independent follow-up repeated native Host preflight including warm/cold own/foreign permission checks and zero Grants/Conversations, exact original site bytes/mode/owner, frozen sources, full original container boundaries/HBA, absent owned root/control/state trees and proof network, unchanged original fixture file, and original production Worker33b93 stopped/restart=no. No remaining owned clients/helpers or allocator process were reported. Failed earlier root/control evidence remains preserved separately.

This passes the declared two-principal QA leaf/compiled-client composition only. Native commandgateway/runsc, child/sentinel/malformed-lineage cases, authenticated HTTP/browser/file/model/artifact, production106/role/HBA/migration/activation and P2–P5 remain open. Full Agent is not complete. Evidence: sibling private-dual-native-continuation-passed.json, private-dual-native-independent-restoration.json, private-dual-native-new-fixtures.json and private-dual-native-continuation-passed-bundle.tar.gz; the archive was extracted and its offline check rerun successfully. No credential, private config or TLS key is included.


## Native child/body gate attempted; malformed-probe payload refused before append

Frozen sourcec9e8eae62be06429372f1180bc123da8a4a7710d549627bf7270e56a5df0d3bf passed SPEC/QUALITY,19 offline checks and native typed-model/bootstrap/handoff contract checks before the actual immutable-image run. Actual baseline full ACL/old4 parity passed. A new native root was admitted, natively cancelled and handed off through reserve/build/domain-validate/transactional commit; the actual root/child UUIDs are retained in the bounded progress evidence. Independent counts now5 Tasks/6 segments/5 binding/control rows. No original Task/Run was replayed or deleted.

The suite failed at the FIRST malformed probe's SessionEvent.create with EventPayloadValidationError, before append. Native exception frames are retained; driver confirms original containers, private configs and HBA unchanged, owned helper removed. The original one-shot execution/freeze and committed new Task/child are retained; no retry/reset. Source execution traversed positive binding/definition/sentinel/ACL checks before this failure, but the whole gate remains UNVERIFIED and its final result is not claimed as PASS.

Root cause in the probe: SessionHandoffReceivedPayload forbids extra fields and has no reason field, while the constructed probe added reason. Its synthetic committed payload also omitted required source range/hash/idempotency fields. Native validation correctly refused the malformed test payload. A separate minimal continuation will derive full templates internally from this owned native handoff and mutate only targeted lineage fields, retain rollback-only fault probes and repeat read-only positives without new admissions/cancellation/handoff. Original native validators, immutable bindings, role/HBA and all prior evidence remain unchanged. A domain/storage refusal is not relabelled as reader-layer acceptance.

Evidence: sibling private-native-lineage-execution-output.json, private-native-lineage-attempt-progress.json and private-native-lineage-attempt-bundle.tar.gz. The archive's offline check passed after extraction. Pending new-owned native cleanup/child dispatch are metadata, not runtime delivery acceptance; full Agent and production activation remain open.


The separately SPEC/QUALITY-approved resume3aadb1aacf32ef830356ca5b24f8a400fb9d200b65ad0a97730d32b6788fc599 passed native payload regressions and reused the existing fifth Task/child, without admission/cancel/handoff replay. Actual payload construction passed, but the first append was refused55000/ObjectNotInPrerequisiteState at native append_event_in_transaction. Driver again confirms container/config/HBA restoration. No malformed event committed; the whole reader-level negative gate remains UNVERIFIED.

Sanitized read-only PostgreSQL log metadata identifies compute_projection_source_metadata line33 atRAISE. Native source shows the probe made parent_session_id equal its own event session_id (and the intended committed probe similarly self-targeted); the database correctly rejects self-peer handoff metadata. This is another fault-fixture error, not a product failure. Neither native triggers nor immutable metadata will be disabled. Next preparation must use a legitimate temporary native session/projection inside the same forced-rollback transaction with a distinct parent/target, or report any unreachable reader case as unverified rather than forcing it through. Both failed source freezes and the actual fifth Task/child remain preserved. Evidence: sibling private-native-lineage-resume-output.json and private-native-lineage-resume-attempt-bundle.tar.gz. No production changes.


A third separately reviewed fixture150ff935217d8178e06c196f720f994ac30e1f5ea687a27ae7ea59e54a2a6461 used native admit_in_transaction for temporary distinct probe Sessions/Tasks inside forced rollback, correcting self-peer metadata. Actual run reached a native append22P02/InvalidTextRepresentation; sanitized PG context identified advance_coverage_lineage_versions line23. Source confirms the coverage-authority AFTER INSERT trigger casts root_session_id::uuid, so the malformed-root case is correctly rejected at the native write boundary before any reader call. Native storage was not weakened. Driver again reports containers/config/HBA restored; no temporary probe or malformed record committed.

The next minimal source slice will explicitly distinguish three valid-UUID reader lineage refusals from one native-write invalid-UUID refusal, emit bounded per-case progress, verify all138 rows after each rollback, and mark malformed-root getter acceptance UNVERIFIED/unreachable under native write guards. It will not relabel a write rejection as a reader rejection. Existing fifth root/child and all prior failure provenance remain intact. Evidence: sibling private-native-lineage-probe-output.json and private-native-lineage-probe-session-attempt-bundle.tar.gz. Full gate remains UNVERIFIED until that scoped run completes.


## Native child/body and declared lineage boundary scope passed; fresh read-only closure passed

Actual c2a54c6558495a3db82a20feae835f06d87ef66fbd0b14188fa71286906e8ce2 native suite passed all declared checks: independent SCRAM root/child full typed binding parity, active child private identity matching the root, inactive-root refusal, native definition copy, actual raw/definition sentinel presence with absence from all nine proof views, and body/definition base/view denials42501/42703 with read-only off. Three structurally valid malformed lineages were rejected by both native writer-equivalent and effective proof-reader getters; invalid root UUID was rejected22P02 by native advance_coverage_lineage_versions during append. Its defensive getter remains UNVERIFIED/unreachable under native write guards. Every temporary native probe Task/session/event rolled back, all138 table row multisets matched after every probe, counts remained5 Tasks/6 segments, and sequence metadata did not change. Thirteen bounded case/progress records retain the exact outcomes.

The c2 wrapper itself exited1: the pre/post helper used the same exclusive progress filename and the second save raised FileExistsError. This happened before inspecting that final audit subprocess returncode, so its old outcome remains UNVERIFIED. The native PASS and wrapper FAIL are both preserved. A separate SPEC/QUALITY-approved read-only closure905bff04afbbccd6dbf97de0dba806d2a129c2968a814a47129ef91f5de75362 fixes the shared tracking path with a unique invocation UUID; its regression extracts the actual path expression and saves twice without collision. No old evidence or exit code was overwritten.

The new actual closure exited0 and independently passed fresh pre/post full ACL/old4 parity audits plus fifth root/child binding, independently derived private identity, definition copy, inactive-root refusal, all138-table equality, expected5/6 counts and pending/undelivered native cleanup/child dispatch checks. All container boundaries/private configs/HBA remained unchanged. It performed only reads; no fault/admission/cancellation/handoff/model/Host/runtime replay occurred. This closes the declared storage/body/boundary scope while retaining the unverified malformed-root getter caveat. No production activation or native commandgateway/runsc/browser/model/artifact acceptance is implied.

Evidence: sibling private-native-lineage-boundaries-output.json and private-native-lineage-boundaries-progress.json (native PASS plus original wrapper failure), private-native-lineage-closure-output.json (fresh closure PASS), and private-native-lineage-closed-bundle.tar.gz containing all frozen attempts/provenance. The bundle was extracted and both stdlib preparation checks rerun successfully. Next is native commandgateway/runsc acceptance using actual fixed private root and resolver wiring, followed by HTTP/browser/file/model/artifact and production migration/activation/P2-P5.
## 2026-10-28 — bounded closeout requested

User requested a fast closeout with working functionality. Further feature expansion and the unexecuted isolated S3 component are held. No new service, migration, image activation or Worker restart was performed in this closeout.

Live checks: ERP HTTPS and HTTP login returned200; browser reached the login form; native production reads verified language zh, Asia/Shanghai, the existing company's CNY currency, installed HRMS and successful Agent bootstrap with one accessible company. Local npm frontend checks and business/chat/client/history Python checks passed. These do not constitute authenticated browser or real model-turn acceptance.

Agent chat remains unavailable: production admission_paused=true, attachments_enabled=false and Worker stopped. Existing research/read_only profiles still expose file capabilities; Host manifest also exposes ERP proposals. Restarting the old Worker would resume database scanning/recovery, so no restart was used to claim readiness. A narrowly enforced chat/ERP-read runtime plus an actual authenticated model round trip is still required before reopening admission. Full Agent delivery remains incomplete.

All17 XGO containers were already stopped; data retained. Trench and Authelia were running during the live inventory. Existing business data, original Runs and production images were preserved.

## 2026-10-28 — maintenance state presentation repaired

User screenshot showed the real paused-admission refusal plus a misleading generic network error. The bootstrap omitted maintenance status and the composer allowed doomed sends. Added strict boolean admission_paused, a maintenance banner, disabled sending, shared send guards and fresh bootstrap on open/reconnect/pre-submit. Original server admission guard and error handling remain. Source and production-only candidates passed SPEC/QUALITY plus runnable maintenance regression.

Published only this change using the current HRMS image as base, image ba23a96a08671aba0766f111876f1b60e72a8e4a17f9dc5d1c5e5d30ef2070b4, recreating backend/frontend only and clearing native cache. Production candidates preserve the older deployed retry/protocol behavior; local unreleased retry work was not activated. Login HTTP200, actual served JS hash, native bootstrap paused=true, HRMS, zh/Shanghai/CNY and unchanged site-config hash verified. Actual served bundle passed a synthetic browser RPC fixture: banner, disabled composer, no submit/network error, open-refresh false/true transitions. This is not authenticated browser/model/chat acceptance. No schema migration, Worker restart or maintenance removal; Agent chat remains unavailable. Public evidence: sibling maintenance-ux-20261028.json.


## 2026-10-28 — approved workbench A deployed

Implemented the approved left searchable session sidebar, compact chat header, sticky Trench composer and on-demand approval/resources drawer. Session CRUD uses existing native APIs; model/reasoning remain server-persisted per conversation. Unsaved drafts stay in memory. Shared guards prevent late approval success/failure from entering a different conversation, preserve newly typed drafts during reconnect/create, treat native ready/created/dispatching as busy and retain the exact uncertain-request identity. RPC uses existing same-origin cookies/CSRF with a bounded inline error. Approval review shows permission-scoped current values, removed/reordered child rows, unknown unreadable fields and exact parameters; native confirmation payload stays unchanged. No dependency was added.

SPEC and QUALITY review passed after the concrete stale-reader/draft fixes. `npm test`, `npm run build` and `git diff --check` passed. The actual built bundle passed isolated browser checks for delayed confirmations and failures across session switches, IME/Shift+Enter, ready/Stop double-click, reconnect/drafts, unknown-response explicit idempotent retry, Markdown/code/safe HTML and reduced-motion mobile layout. These mocked approval/mutation tests are not new live business-write acceptance.

Static-only image `sha256:1f77094c2396921ef1f6f124b94695bfc85e88b9d11e7cea16e45c2bb3487bd7` extends the verified live Host334476 image with only JS/CSS and two asset-version hook strings. Recreated backend/frontend only; clear-cache, no migration. Agent API/chat worker and compose.json remain unchanged; general worker remains stopped. Rollback metadata is private at `/opt/erpnext/zebra-agent/ui-a-20261028-1/backup`. Browser-served version `20261028-workbench-a1` hashes match JS949cc5355d34b9604158876ab2abec295360b83a87129d516d666042d0451e73 and CSSab894177679000ef7dfbe313d77015bf060eb936f753e49a3be9963d67c7f0b5.

Authenticated real-browser acceptance used new conversation `f1p4qpa1me`, titled `[UI A验收] 排产查询`, Run `9172fa90-a6f8-4907-a768-f2e6d97bcbd9`: real model/discover/read completed to awaiting_turn, queried11 production plans/46 work orders/4 workstations, and rendered4 native Markdown tables. Reload restored history and Flash/low; a separate disposable session retained Pro/max independently, then was explicitly deleted through the UI. Native create/switch/rename/delete, desktop1440x900 and mobile390x844 passed; no page horizontal overflow, mobile composer bottom831.844 within844, sidebar258 and drawer390, reduced-motion enabled.

Capacity remains bounded: Production Capacity report and Workstation Working Hour reads returned403, so the reply disclosed unavailable detailed capacity and gave qualified suggestions. This UI release does not claim complete capacity scheduling. No business writes were made. Full-row checks preserved20 business tables (including prior approved plan00011), plus original8 Tasks/10 segments/591 events/22 bindings. Full Agent capabilities beyond the recovered runtime remain incomplete. Public evidence: sibling `zebra-erpnext-evidence/workbench-a-20261028.json`.


## 2026-10-28 — recurring-failure stability repair

Worker812202... removes unnecessary healthy projection-route repair and replaces oldest-only ready polling with bounded scalar/Fresh-checked fairness. Source, independent review, failed image attempts retained, activation and evidence boundaries: cloud-patches/projection-stability/REVIEW.md. Isolated native105 PostgreSQL reproduced forced repair/50ms COMMIT contention;100 sequential and100 candidate-loop-concurrent native appends passed. Five real sequential same-conversation ERP query Turns and one new read-only original-owner verification completed. No new native failures/PG lock timeouts during final Worker11:26–11:33Z acceptance. Original20 business tables and8 Tasks/10 segments/591 events/22 bindings preserved; no business write or migration. Site config bytes restored, general Worker stopped, Host/API/frontend unchanged. Historical invalid-provider-response cause and production long-soak/SLA remain unverified. Sibling public evidence: zebra-erpnext-evidence/agent-stability-20261028.json.

## 2026-10-29 full capabilities candidate
Seven capability adapters and resources UI implemented in the dedicated ERP
branch. Native generic fixes integrated locally at cloud-agent89e4afed, including
current AG-UI115. Actual isolated PG/S3/Host/Skill/quota/gVisor/scheduler and
cloned-business gates passed; UI Skill/knowledge/schedule selections survive
reload. External MCP/query/model behavior and production activation are separate
acceptance boundaries. Exact receipts and remaining gates:
docs/ERP_CAPABILITY_RELEASE_20261028.md and task_plan.md.

Final isolated acceptance: Native9a09d2d50d5a and ERP2d16a18f2af4 pinned, QA115;
legacy history and real Memory save/reload accepted. Seven-category wiring is
complete; production activation is pending final approval. Current native105/ERP
transactional backups and rollback manifest exist separately; original service
records and Runs unchanged, SQL new-namespace model/tool execution events0.

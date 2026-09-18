# Zebra Agent Project Status

2026-09-16 AGENT-QUALITY-02: the Cloud Agent quality-loop repair is implemented
in-place on `cloud-agent-trench`. Finalization now enforces selected Skill reads,
revises shallow substantive deliverables once, and records a bounded warning if
the second answer remains weak. Mutation freshness is resource-scoped when a
tool exposes an id/url/path and keeps a global fallback for opaque mutations;
Host business errors retain bounded detail/code metadata. Research children
inherit the selected Skill components. Trench native source mutations now
reject ambiguous `sources.add` arguments and schedule an immediate RSS refresh
after add/resume, with periodic fallback truthfully reported. Zebra `make check`
passes (file-size, Ruff, strict Mypy over 945 sources, Eval 10/10); focused
quality/runtime tests pass 49, and the full suite reached 4446 passed, 887
skipped; the two timing-sensitive baseline failures passed in isolation. Trench
targeted tests pass 25/25; the stale custom-website fixture now uses a true
website URL while X URL normalization remains covered by native-history tests.
Acceptance images were rebuilt
from the current source; API, Worker, Scheduler, and Trench live/readiness
health checks are green.

2026-09-16 AGENT-QUALITY-01: the in-place Cloud Agent quality repair is ready
for review on `cloud-agent-trench`. Frozen selected Skills are now available to
the Trench coordinator and must be resolved/read before substantial output.
Declared business mutations enter an unverified state, allow a fresh repeated
read, and receive one bounded verification turn; tests and generic commands are
not misclassified as business writes. Cloud conversation history grows from
8192 to 32768 bounded tokens. Trench source reads project current user
subscription truth, while AG-UI marks `tool_loop/final` responses so live
progress remains visible but only the final response becomes the durable body.
Zebra affected suites passed 800 plus a 40-test classification regression;
the deterministic full suite excluding the live-provider smoke passed 4441
with 887 skips. Ruff, strict Mypy over 943 sources, file-size, Eval 10/10 and
diff gates pass. The live DeepSeek smoke's tool call returned reasoning_tokens=0
and fails only its external reasoning-presence assertion. Trench's affected
group passed 42 with target Ruff/diff green. Existing dirty work is preserved;
no commit, push, deployment, restart, or browser acceptance is claimed.

2026-09-16 CTX-SEG-03: budget-governance repair is ready for review on
`cloud-agent-trench`. Trench interactive tasks no longer inject implicit `6/16`
model/tool limits. The harness no longer reserves the final permitted model call
as a tool-disabled synthesis turn: that call retains tools, and only a required
subsequent model request causes structured `model_call_budget_exhausted`
suspension. AG-UI now closes explicit budget suspensions with a recoverable
interrupt while leaving internal `waiting_children` suspension untouched.
Core/AG-UI suites pass `948` with `1` skip; the focused regression passes `24`.
File-size, Ruff, strict Mypy over `942` source files and Eval `10/10` pass. The
full suite passed `4439` with `887` skips; its only failure was a pre-existing
module-level 30-second clock-window test that passed alone. Trench's affected
group passes `35`; its Python gate remains at the recorded baseline of `121`
passes plus 5 unrelated `_IncludedRouter` failures. No commit, push, deployment,
or browser acceptance is claimed.

2026-09-15 CLOUD-USER-SCHEDULE-DEPLOY-01: The independent Scheduler is now
composed beside the API and Worker in the real Trench acceptance stack. Trench
ToC provides logged-in user schedule CRUD, controls and durable run history;
the BFF binds opaque host workspaces and enabled Skills with separate one-use
Host grants. Scheduled execution now submits the standard RUN command, so its
Turn freezes normal Skill/MCP admission and uses the RabbitMQ wakeup path.
Terminal Task state is reconciled into durable Firing state. The logged-in
browser shows the latest manual run as `9/15 16:02 已完成`; its PostgreSQL Turn
snapshot contains Skill `1` and MCP `1`. Runtime/broker `24`, actual PostgreSQL
`13`, Trench API `6`, and ToC `78` tests pass, together with Zebra file-size,
Ruff, strict Mypy over `942` sources, Eval `10/10`, frontend ESLint and build.
This local slice is in Review; remote deployment remains separate.

2026-09-15 CLOUD-USER-SCHEDULE-API-01: The user schedule management surface is
implemented on `codex/cloud-user-schedule-api`. Verified Host grants now expose
owner-scoped create/list/get/update/delete, pause/resume, idempotent run-now and
run history with Task deep links. Schedule template changes pass through the
normal Task/Skill/MCP/Definition admission rules and atomically rotate the
immutable authority binding; optimistic versions protect every lifecycle write.
The focused API/Core/Storage group passes `824` with `37` dependency skips,
actual PostgreSQL schedule tests pass `9`, and file-size, Ruff, strict Mypy over
`941` sources plus Eval `10/10` are green. The full repository suite passes
`4429` with `887` dependency skips. Frontend, Trench UI, deployment and browser
E2E remain future slices.

2026-09-15 CLOUD-USER-SCHEDULE-STORAGE-01: User-level Task schedules now have
forward-only PostgreSQL v58 authority. Schedule and authority reads require all
owner coordinates; lifecycle and revocation writes use optimistic concurrency;
due pickup uses database time plus `FOR UPDATE SKIP LOCKED`; deterministic
Firings survive duplicate pickup and expired claims; misfire and overlap skips
remain durable evidence. Actual PostgreSQL tests pass 7, full Storage passes 361
with 799 externally gated skips, and full Core passes 763. API, Scheduler process,
Task materialization, RabbitMQ wakeup, UI and deployment remain future slices.

2026-09-15 CLOUD-USER-SCHEDULE-CORE-01: The first user-level scheduling slice
is implemented on `codex/cloud-user-schedule-core`. Core now owns immutable
Schedule, Trigger, Firing, secret-free authority and storage Port contracts,
plus deterministic IANA-timezone next-fire calculation. Once/interval/daily/
weekly rules, DST gap/fold behavior, monotonic lifecycle evidence and stable
Firing identity are pinned by 19 focused tests; the complete agent-core suite
passes 763, with Ruff, strict Mypy and diff checks green. PostgreSQL, API,
Scheduler process, RabbitMQ materialization, UI and deployment remain separate
unstarted slices.

2026-09-14 TRN-DEEPSEEK-V41-MM-01: DeepSeek V4.1 Flash replaces the historical
dual-channel Vision design. The stable Zebra Flash profile now calls the official
`deepseek-flash` alias and accepts validated JPEG/PNG/GIF/WebP attachments through
the existing durable Artifact path. Worker recovery verifies session ownership,
size and digest before attaching transient image content to the current USER
message; Chat Completions and Responses serializers emit their native image
parts. Trench exposes image selection on the existing plus button and switches
image requests from Pro to V4.1 Flash. A real Responses API request with an inline
PNG reached `deepseek-flash` successfully; V4.1 tool calls that omit an optional
reasoning item are also accepted without exposing or fabricating reasoning.
Focused tests, `make check`, and the full suite (`4401 passed`, `875 skipped`)
pass. No deployment or logged-in Trench browser image submission is claimed.
Follow-up browser acceptance exposed a stale PostgreSQL check constraint that
admitted `research` but not the current `research_coordinator` ToolProfile.
Forward migration v57 now accepts all domain ToolProfile values without
rewriting migration v29; a focused regression pins that enum/schema parity.
The existing acceptance database upgraded to v57, Extensions remained enabled
with the original read-only key mount, and a real logged-in Trench conversation
completed through API/Worker with `POST /tasks` 201. Focused checks passed 11;
`make check` passed file-size, Ruff, strict Mypy over 924 sources and Eval 10/10.

2026-09-14 DESKTOP-COMPOSER-UX-01: Desktop Cloud Agent composer is now a
compact command bar with attachment, truthful current permission, task config,
actual model/reasoning labels, and an SVG context-capacity ring. The popover is
derived exclusively from durable model request/response usage and reports the
latest input-window utilization plus weighted session prompt-cache hit rate; it
does not estimate tokens or expose private reasoning. One primary action now
switches between send, pause, and continue. While a Turn is running, typed
supplements remain visible in a bounded eight-item browser queue and are
submitted sequentially at safe Turn boundaries; the local optimistic message is
reconciled by the durable event stream without a blank-frame flicker. Existing
session control and authority contracts are unchanged. Build, all Desktop checks,
diff check, and browser layout/popover inspection passed; local API connectivity
was not available for a live execution/pause acceptance. No commit or push.

2026-09-14 TRN-SUBAGENT-UX-02: Trench Tasks now use a least-privilege
`research_coordinator` profile: the existing research read/publish surface plus
durable `agent.research`, without command, patch, Git or test tools. The
capability generation advances to v13 so the next Turn replaces existing
admission-frozen research Tasks instead of silently retaining the old profile.
Zebra projects safe child lifecycle metadata over AG-UI and exposes an
authoritative read-only parent-child Task query; child summaries and reasoning
remain private. Trench persists lifecycle events in the durable Turn stream and
renders one merged row per child in an opt-in detail panel that stays collapsed
after completion. Focused Zebra 17 tests, Ruff, file-size gate and Mypy over 915
sources passed; Trench 44 backend and 14 frontend tests plus focused ESLint
passed. The local acceptance Zebra API/Worker were rebuilt and are healthy; the
running images import the new profile/query and Worker tool set. A direct live
Task probe without a valid Host grant was correctly rejected with 401 and created
no Task, so logged-in Trench browser/model delegation remains unclaimed. No
commit or push.

2026-09-09 EXT-SKILL-UX-01: installed Skill reads enrich exact scoped/versioned
ready publication names, descriptions and version labels; no migration or object
downloads. Trench settings now provides a searchable readable list, details and
Radix enable switches, missing-metadata/empty/error feedback. Actual user's
better-writing name/description, purpose search and details verified in Chrome.
56 backend tests, 7 frontend tests, make check and focused ESLint pass. Full
frontend tsc remains blocked by three pre-existing dashboard-data-settings test
fixture type errors. API rebuilt with preserved environment; no Git operations.

2026-09-09 GitHub import follow-up: real user retry resumed a pre-deployment
clarification with 5/6 model calls consumed, so only tool-less final synthesis
ran. Trench capability generation now advances v11 -> v12, reusing existing
scoped CAS successor binding and bounded history without resetting Turn budgets.
37 focused tests passed. Real pending-clarification upgrade/import/reference
read passed (8.19 / 6.11 seconds) in an isolated account. User's existing
conversation is not edited; its next message selects the current generation.

2026-09-09 EXT-GITHUB-SKILL-01: Agent now accepts public GitHub Skill links via
extensions.import_skill: bounded HTTPS download, immutable commit verification,
package validation, scoped publication, idempotent install/enable and next-Turn
automatic binding. No script execution, arbitrary fetch or secret model inputs.
Real forjd/better-writing import and subsequent reference read passed through
Trench/Broker/Cloud Worker/model; reimport retained one installation. Worker
rebuilt locally with credentials/environment preserved. 83 initial focused tests
passed plus a subsequent concurrent-version regression; broad suite 4371 passed,
875 skipped with DeepSeek live smoke module explicitly excluded (known network
issue). No full-live-suite/browser/merge/push claim. See management doc and log.

2026-09-09 EXT-SKILL-AUTO-01: scoped enabled Skill IDs now bind automatically
on each new Trench Turn. Changed ID sets create a CAS-protected successor Task
under the same frontend conversation; upgrades select the new version next
Turn without unnecessary Task replacement. Replay/cancel keep their original
binding. Research exposes only the scoped Cloud Skill read tools. Canonical
publication UUIDs, bounded four-page selection and successor context seeding
are covered. Trench separates five-second control requests from a configurable
60-second stream idle budget (1–300 seconds), preventing premature interruption
between Skill tool calls. No schema migration or new consent UI.

Live HTTP-to-Worker/model acceptance passed in
conv_skill_acceptance_d5b35f4efb8e4a9d: initial reply, new Skill read using a
marker present only inside SKILL.md, Agent-native version upgrade, next-Turn
v2 read, disable/successor and other-user installation/Turn 404; all five Turns
completed in 4–8 seconds. API/Worker/Broker source deployed locally. Worker
currently has an acceptance-only api.deepseek.com public-IP mapping because
the host proxy fake-IP path fails TLS; see management doc before recreating it.
Latest Zebra make check passed; full make test: 4335 passed, 875 skipped, three
DeepSeek live transport failures (not passed). Trench focused 35 passed; prior
broader API baseline retains four unrelated failures. No new browser acceptance,
commit, merge or push claim. Other Skill upload/credential UI and full cross-Task
history authorization are separate work, not delivered by this slice.

2026-09-09 EXT-NATIVE-MANAGE-01 Host delegation source: confirmed login-once
policy now shares Trench viewer/chat scopes, including extensions.read/manage.
Broker checks explicit viewer/signed-workload ceilings and operator allowlist;
legacy Hosts cannot gain extension scopes implicitly. Trench rechecks workload
account/workspace before signing and advances Task/idempotency generations.
No perpetual grant, extra consent database or per-Turn consent UI. Accepted
durable work retains existing logout-independent semantics; not immediate global
revocation of issued grants. Zebra make test 4321 passed / 875 skipped; make check
passed. Trench targeted 37 passed; API suite 582 passed / 4 failed in untouched
startup/capsule/harness expectations. Deployment, real management E2E and new
Skill successor ceilings remain open. No commit/push or container recreation.

2026-09-09 EXT-NATIVE-MANAGE-01: seven typed extension management tools now
reuse scoped create/update/installation/catalog services. Cloud Worker registers
them only for explicit frozen Host management/read scopes and revalidates live
Task/Turn identity and lease, including before writes after intermediate reads.
No secret-bearing tool arguments, no synthetic HTTP grants, no active snapshot
rewrite; network-disabled Tasks cannot refresh MCP. Focused tests 119 passed;
full suite 4295 passed / 875 skipped; make check passed. This is runtime source
delivery, not Trench activation: signed Host delegation, new-Skill Task ceilings,
credential UI and real management E2E remain open. See
docs/cloud-extension-agent-management.md. No deployment or Git push this slice.

2026-09-09 EXT-AGUI-01: real Trench MCP fetch execution now verified. Fixed
AG-UI admission forwarding, existing-Turn RUN/RESUME selection/recovery,
PostgreSQL MESSAGE-only atomic admission, and the live publisher decorator
dropping the atomic method. Cloud aliases now fit the provider's 64-character
limit. Trench requests mcp-proxy-only (not unrestricted egress) and advances
its task generation/idempotency namespace to avoid old frozen none profiles.
Browser conv_1788883798514_259bde fetched public example.com via configured SSE:
policy allow, tool_execution_completed=executed with actual remote text,
model deltas, turn_completed and semantic title persisted; about 19 seconds.
API/Worker rebuilt and healthy. Focused Zebra 64 + 12 + 21 passed (one optional
live transport test skipped); Trench runtime 23 passed. Mypy 907 sources passes.
No full-suite, merge or commit claim. Skill upload/credential/deletion UI and
full multi-user live/revocation acceptance remain outstanding. Historical
rollout failures below are retained as evidence, not current MCP status.

2026-09-08 live rollout: schema v56 applied; 250 existing session streams retained.
API/Worker extension overlay active and healthy; Broker extension scopes enabled
with existing credentials retained. Trench API restored; real browser MCP list,
create and enable pass. Fixed production authorizer's unconditional agent.run
requirement (8 real PostgreSQL signed-authority tests pass), BFF history refs,
and refresh body contract (4 UI tests pass). Catalog refresh succeeded after a
transient 503; one catalog persisted. Real AG-UI Turn did not receive MCP:
no snapshot created. AG-UI RUN/RESUME bypasses MESSAGE-only admission. Worker
MCP E2E failed; normal reply/title persisted. See
docs/cloud-extensions-rollout.md for env preservation and remaining UI gaps.

Historical source-delivery entry below predates this activation:

2026-09-08: EXT-TRENCH-BFF-01 implemented in Trench's existing current branch.
Authenticated extension BFF reuses grant exchange with operation-only
extensions.read/manage; no management workload fallback or upstream Cookie.
Explicit bounded collection/create/enable/catalog/refresh paths only. Trench
settings now have Skill/MCP sections: public MCP create, toggle, refresh and
installed Skill toggle. Upload/credentials/deletion are not yet delivered.
Backend focused regression 30 passed. Runtime broker scopes, migration and
API/Worker activation remain pending; no browser/live Worker closure claim.
Extension UI tests 3 passed; focused ESLint and backend Ruff passed.
Frontend tsc is blocked by three pre-existing incomplete source fixtures in
dashboard-data-settings.test.tsx, not the added extension component.

2026-09-08: EXT-ROLLOUT-01 opt-in deployment overlay prepared in
docker/compose.extensions.yml. Actual Compose rendering tests: 3 passed;
paired API/Worker switches, private read-only required key mounts and unchanged
base defaults verified. Running stack NOT changed. Broker scope/Host ceiling,
Trench management BFF/UI, operator key and migrations remain activation gates.
See docs/cloud-extensions-rollout.md for exact sequencing and rollback boundary.

2026-09-08: EXT-MCP-SSE-01 remote legacy SSE compatibility implemented after
user approval. Cloud connections accept explicit sse alongside default
streamable_http; cloud stdio remains rejected. Discovery and execution reuse
bounded framing, schema checks and per-frame live authority/credentials.
Same-origin derived endpoints and public-IP-pinned sockets remain mandatory.
SSE focused 13 passed; make check passed (907 sources, Eval 10/10).
Full regression: 4238 passed / 866 skipped in 133.40s; two subsequently added
SSE checks passed with the complete focused suite (13 passed).
Repository live probe unblocked: a single-host Mihomo fake-IP exclusion restored
public DNS (39.96.127.68). Default discovery completed in 1.71s; CloudMcpTransport
fetch returned real example.com content, isError=false, total 7.47s. One initial
five-second discovery timeout was observed; no timeout/security bypass applied.
Probe used fixture scope/authority, not durable Worker or Trench authentication.
No runtime rollout or Trench E2E claim.

2026-09-08 live acceptance preflight: running zebra-trench-acceptance API/Worker
containers are healthy, but neither contains extension/MCP enable flags or an
MCP master-key mount. Verified runtime PostgreSQL database zebra remains v50;
extension_configurations and mcp_catalog_versions are absent. Active frontend is
Trench/toc-frontend on port 3000; settings sources contain no Skill/MCP management
entry. Live extension acceptance has NOT started. Requires runtime migration/
image/config rollout, Trench management delivery and a configured HTTP MCP target.
No database migration, container restart or operator secret changes were made.

2026-09-08: EXT-MCP-WORKER-01 lifecycle wiring implemented behind
ZEBRA_CLOUD_MCP_WORKER_ENABLED (default off). API composes stored catalog selection;
Worker composes catalog/credential stores from its existing cloud bundle and
replays current-Turn durable authority before HTTP frames. Execution gateway
receives the transport; empty cloud selection cannot fall back to process MCP.
Shared mounted-key startup validation preserves API behavior. Focused 102 passed /
1 skipped, isolated PostgreSQL-related subset 56 passed; make check passed
(906 sources, Eval 10/10). Runtime activation and real remote/Trench E2E pending.
Full regression: 4226 passed / 866 skipped in 151.01s; the subsequently added
empty-selection case passed in the focused gateway suite (3 passed).

2026-09-08: EXT-MCP-WORKER-01 authority adapter implemented. MCP accepts existing
bound Worker execution evidence without an HTTP Grant callback; release compares
it with current Task identity/digests/capability/expiry. Shared scope derivation
preserves user/workspace isolation. Focused 49 passed / 4 DB skipped; make check
passed (905 sources, Eval 10/10). Default lifecycle wiring and real MCP/Trench
acceptance remain pending; this is not a production activation. Expanded focused
regression: 70 passed / 4 skipped; isolated PostgreSQL subset: 33 passed.
Full regression: 4213 passed / 866 skipped in 139.67s; diff check passed.

2026-09-08: EXT-MCP-WORKER-01 remains In Progress. Explicit catalog/transport
composition passes 3 captured-network checks; full 4202 passed / 866 skipped
in 142.81s; make check passed (904 sources, Eval 10/10). Found startup mismatch:
Worker uses bound execution-authority snapshots/revalidation, not fresh verified
HTTP grants. MCP release must adapt to that existing authority boundary before
default lifecycle wiring. No fabricated Grant, activation, commit or deployment.

2026-09-08: EXT-MCP-AUTH-02 is in Review. Anonymous MCP now has a shared
snapshot/grant authorization hook with exact live config and lease/fence checks;
no credential access on that path. Existing Bearer release remains unchanged.
Focused 35 passed / 4 DB skipped; real isolated PG/runtime 39 passed; full
4199 passed / 866 skipped in 144.35s; make check passed (903 sources, Eval 10/10).
Worker transport callback and startup/recovery composition remain incomplete;
no live remote MCP/Trench E2E, production activation, commit or deployment.

2026-09-08: EXT-MCP-ADMISSION-01 is in Review. Optional catalog-store composition
automatically selects current-user enabled usable MCP catalogs for new Turns;
no remote discovery or client allowlist required. Unrefreshed connections are
skipped; exact scope/revision and bounded paging/tool counts enforced. Focused
28 passed; actual isolated PostgreSQL/admission 29 passed; full 4192 passed /
866 skipped in 139.92s; make check passed (903 sources, Eval 10/10).
Default startup remains unchanged pending production Worker recovery/live
authority composition. No deployment, activation or real Agent/browser E2E.

2026-09-08: EXT-MCP-EXEC-01 is in Review. Added pinned cloud HTTP transport
and explicit existing Harness injection, without per-turn remote discovery.
Exact catalog/digest and alias mapping, argument checks, per-frame authority,
none/Bearer auth, protocol drift rejection and bounded untrusted results reuse
existing runtime components. Focused 32 passed; full 4184 passed / 865 skipped
in 143.89s; fixture enum warning subsequently corrected with focused 5 passing.
make check passed (902 sources, Eval 10/10). Automatic scoped admission and
production Worker authorization/startup wiring are still incomplete; captured
HTTP is not real remote MCP or Trench E2E. No activation, commit or deployment.

2026-09-08: EXT-MCP-NAMES-01 is in Review. Fixed cloud discovery incorrectly
rejecting remote names through local alias restrictions. Preserve exact bounded
remote names, use collision-checked internal aliases with shared schema parsing,
keep local HTTP/stdio behavior unchanged. Focused 35 passed / 2 DB skipped;
full 4179 passed / 865 skipped in 141.91s; make check passed (901 sources,
Eval 10/10). Cloud Worker execution and Settings E2E remain incomplete; no
service activation, commit or deployment.

2026-09-08: EXT-MCP-CATALOG-01E is in Review. Scoped catalog GET now exposes
current-revision tool metadata without discovery or credential release. Product
decision clarified: configure/enable once, AI chooses tools; Task/Turn bookkeeping
is internal, never a new manual binding workflow. Focused 16 passed / 5 DB
skipped; real isolated PG/captured HTTP 21 passed; full rerun 4165 passed /
865 skipped in 132.16s. Initial unrelated process kill PermissionError passed
isolated retry and full rerun. make check passed (901 sources, Eval 10/10).
Cloud admission/Worker still need persisted user catalogs instead of process
MCP settings; execution and Settings/browser acceptance remain incomplete.

2026-09-08: EXT-MCP-CATALOG-01D is in Review. Separately opt-in automatic
management refresh startup shares credential storage/protector and resolved
cloud database/namespace. Defaults remain disabled; invalid prerequisites fail
startup and boot performs no discovery. Focused 50 passed / 3 DB skipped;
actual isolated PostgreSQL and captured HTTP matrix 14 passed; full 4159 passed /
864 skipped in 134.53s; make check passed (901 sources, Eval 10/10).
Distributed refresh coordination/limits, Task MCP ceiling/Turn admission,
Worker dispatch and Trench Settings E2E remain pending. No live schema changes,
service activation, remote MCP acceptance, commit or deployment.

2026-09-08: EXT-MCP-CATALOG-01C is in Review. Explicitly injected management
refresh service and protected POST route now connect scoped configuration,
per-frame grant expiry/configuration checks, Bearer ciphertext release, discovery
and revision-checked catalog publication. Input cannot supply URL, scope or token.
Focused 38 passed / 3 DB skipped; captured-network plus real PostgreSQL matrix
21 passed; full 4154 passed / 862 skipped in 132.64s; make check passed
(900 sources, Eval 10/10). Startup activation, distributed refresh scheduling,
Task MCP ceiling/Turn selection, Worker execution and Trench E2E remain pending.
No live schema change, activation, commit or deployment.

2026-09-08: EXT-MCP-CATALOG-01B is in Review. HTTP-only discovery now returns
complete connection-bound immutable catalogs through existing pagination/schema
and HTTPS framing. Per-frame Bearer resolver required; missing/unsupported auth
fails before send. Shared HTTP discovery rejects duplicate remote names early.
Focused 45 passed / 1 DB skipped; captured-network plus real PostgreSQL matrix
23 passed; full 4139 passed / 860 skipped in 130.33s; make check passed
(897 sources, Eval 10/10). Public authorized refresh route, Task MCP ceiling,
Worker dispatch and Trench Settings E2E remain pending. No live network/server
acceptance, schema changes, service activation, commit or deployment.

2026-09-08: EXT-MCP-CATALOG-01A is in Review. Bounded immutable tool catalog
contracts and PostgreSQL v56 persistence bind exact scoped connection/revision.
Parent-lock publication rejects configuration drift; validated digest readback
rejects corruption. Identical A-after-B refresh advances latest publication
without changing historical definition payloads. Deterministic 11 passed;
isolated PostgreSQL catalog/credential matrix 37 passed; full 4124 passed /
859 skipped in 133.57s; make check passed (896 sources, Eval 10/10).
Migration was tested only in disposable schemas. Remote discovery, Task MCP
ceiling/Turn admission, Worker execution and Trench Settings E2E remain pending.
No live service migration, activation, commit or deployment.

2026-09-08: EXT-AUTH-01I is in Review. Opt-in API credential startup now reuses
the admitted cloud DSN/namespace and existing SecretStore/AES-GCM components.
Operator supplies read-only mounted master key with exact handle/version;
missing, malformed or insecure key files stop startup. No user plaintext token
store or default permissions expansion. Focused 98 passed / 2 DB skipped;
real PostgreSQL startup/HTTP/management matrix 54 passed; full 4113 passed /
852 skipped in 122.86s; make check passed (892 sources, Eval 10/10).
Worker dispatch/catalog admission, OAuth and Trench Settings/deployed E2E remain
pending. No service activation, live schema migration, commit or deployment.

2026-09-08: EXT-AUTH-01H is in Review. Protected opt-in HTTP credential
provision/revoke routes reuse verified management grants and atomic revision CAS.
No credential readback, client identity override or default permission expansion.
Focused 23 passed / 1 DB skipped; isolated real PostgreSQL HTTP/service matrix
36 passed; full 4096 passed / 851 skipped in 131.21s. make check passed
(890 sources, Eval 10/10). Service injection is explicit: automatic SecretStore
composition, Worker dispatch and Trench settings/deployed E2E remain pending.
No live schema changes, commit or deployment.

2026-09-08: EXT-AUTH-01G is in Review. Internal MCP execution resolver binds
fresh grant, current lease fence, recovered snapshot and exact operation/params.
Lease is rechecked after credential I/O; shared release now explicitly verifies
target endpoint. Shared fenced Effect gateway rechecks ownership after payload
read and before tool invocation, preserving existing uncertain/recovery handling.
Focused 52 passed / 4 DB skipped; isolated real-DB matrix 44 passed including
existing terminal-result replay. Final full 4073 passed / 850 skipped in 128.59s;
make check passed (889 sources, Eval 10/10). Broker routes, trusted Worker
composition, MCP catalog admission and deployed E2E remain pending. No live
schema changes, Worker activation, commit or deployment.

2026-09-08: EXT-AUTH-01F is in Review. Existing MCP HTTP sessions support
per-frame endpoint-bound Bearer resolution without environment mutation or shared
credential caching. Mixed environment/scoped auth fails closed; initialize,
notification and tool frames reauthorize independently. Failure sends no denied
frame and adds no retry. Secret-bearing exception chains are suppressed.
Validation: 52 transport tests passed (15 new), full 4059 passed / 850 skipped
in 129.37s; make check passed (888 sources, Eval 10/10). Test composition connects
internal release to a captured HTTP opener, not a deployed remote MCP server.
Worker lease/digest/dispatch-ledger composition, API-key templates, OAuth, routes
and Settings E2E remain pending. No service activation, commit or deployment.

2026-09-08: EXT-AUTH-01E is in Review. Internal MCP credential release validates
live Task grant, frozen snapshot scope/coordinates/digest and operation permission,
then reads ciphertext under current-connection lock. Revoked/rotated/disabled or
changed connections reject old snapshots; secret material stays Broker-internal.
Expanded real-DB/crypto matrix 122 passed; final full 4044 passed / 850 skipped
in 125.73s; make check passed (887 sources, Eval 10/10). Initial real DeepSeek
smoke failed for missing reasoning output; isolated and full retries passed
without parser changes (see WORKLOG.md). No Worker/API/transport activation;
trusted lease/digest composition, OAuth and Settings/browser E2E still pending.

2026-09-08: EXT-AUTH-01D is in Review. Verified extensions.manage authority now
provisions bearer/API-key ciphertext and publishes its connection reference/state
atomically with configuration CAS; revoke disables and revisions the connection.
Fixed stale joined-lock reads by locking the parent before reading current payload.
Real PostgreSQL matrix 73 passed; crypto 30 passed; default full suite 4029 passed /
846 skipped in 129.50s; make check passed (886 sources, Eval 10/10). Five new DB
cases passed separately. Management slice complete; runtime credential release and
revocation enforcement, OAuth, public API and Trench Settings remain pending.
No live schema migration, runtime enablement, commit or deployment.

2026-09-08: EXT-AUTH-01C is in Review. Core encrypted credential DTO/Port and
PostgreSQL v55 ciphertext history implemented. Parent locking validates exact
connection/scope/endpoint and serializes append-only revision CAS. Storage never
decrypts or changes authentication state. Real PostgreSQL matrix 61 passed;
crypto 30 passed; full default suite 4022 passed / 841 skipped in 130.38s;
make check passed. Eleven new DB cases were exercised in the dedicated real
run. No service schema migrated; Broker authorization/revocation, OAuth, Worker
and Trench UI remain pending. See docs/cloud-mcp-credential-storage.md.

2026-09-08: EXT-AUTH-01B is in Review. Broker-internal MCP token protection
uses existing SecretStore and installed AES-GCM implementation with exact
deployment/scope/connection/endpoint/credential identity binding. Ciphertext
substitution, tamper and key-version mismatch fail closed; rotation retains
old readback only while old key handles remain available. Validation: 30 focused,
263 security tests; full 4021 passed / 830 skipped in 126.26s; make check passed.
This is cryptographic protection only, not persistence, authority, expiry,
revocation, OAuth, cloud Worker or Trench browser delivery.

2026-09-08: EXT-AUTH-01A is in Review. MCP HTTPS sockets now revalidate DNS
and connect directly to a validated numeric IP, retain original-host TLS checks,
disable environment proxies and reject tunnels. Failed sockets close; no request
replay is added. Validation: 16 egress / 135 MCP tests; full 3991 passed / 830
skipped in 134.86s; make check passed. User credential Broker/OAuth, cloud MCP
Worker activation and Settings/browser acceptance remain outstanding.

2026-09-08: EXT-MCP-HTTP-01B is in Review. HTTP resource and explicit prompt
discovery/read now reuse existing bounded content validation rather than being
silently skipped. Empty resource selection has zero I/O; duplicate server names
fail before network access. Validation: 15 focused / 119 MCP tests; full suite
3975 passed / 830 skipped in 132.12s; make check passed. This is shared transport
support, not user credential Broker, cloud MCP Worker activation or Settings E2E.

2026-09-08: EXT-MCP-HTTP-01A is in Review. HTTP SSE response framing now
returns the correlated result before EOF and carries negotiated protocol and
per-instance session headers. Failed initialization delivery stops the handshake.
Validation: 104 MCP tests; full suite 3960 passed / 830 skipped; make check
passed. Cloud MCP credential/egress composition, Worker activation, GET replay
and Trench settings/browser acceptance remain outstanding.

> This is the current project snapshot, not an append-only session log. Detailed
> history lives in task cards, acceptance records, merge commits, and Git history.

## Active Review

- `EXT-STORE-01B`: immutable exact-scope per-turn ExtensionSnapshot storage
  and migration v54 implemented. Trusted expected digest, full seven-coordinate
  lookup, typed payload/identity checks, idempotent replay, concurrent conflict,
  tamper and tenant isolation covered. Real PG/MinIO and related matrix:
  94 passed in 63.19 seconds, including persisted two-user private Skill
  readback after adapter restart and live disable rejection. make check passed
  (873 typed files, eval 10/10); independent spec/quality PASS.
  Final full regression: 3851 passed / 805 skipped in 145.98 seconds; final
  lint, type, eval, diff and size gates passed. This is persistence only: no
  admission, API, Worker activation, business migration, deployment or commit.

- `EXT-API-03B`: normal cloud HTTP startup now supports default-off Skill
  publication composition using one resolved control-plane bundle (DSN,
  deployment namespace and the same artifact object store). Mixed explicit
  store injection is rejected for automatic publication; explicit publication
  services and local/default-off paths retain their prior behavior.
  Real PostgreSQL/MinIO and related matrix: 77 passed in 55.41 seconds,
  including normal environment and explicit-bundle startup, upload, restart
  read/replay, installation and foreign-user denial. make check passed.
  Independent spec/quality PASS; 129 focused checks passed. First full run:
  3836 passed / 785 skipped / one live DeepSeek Responses payload rejection;
  isolated retry passed (3.22s). Final full rerun: 3837 passed / 785 skipped
  in 128.23s. No actual flags,
  business schema, running services, Worker or Trench Settings were changed.

- `EXT-API-03A`: explicitly composed raw ZIP upload and scoped publication
  metadata GET implemented. Migration 53 atomically binds hashed request keys
  and immutable publication reservations; interrupted uploads resume without
  creating another version. 125 focused tests, real PostgreSQL/MinIO and
  related matrix 75 passed, independent spec/quality PASS; make check passed
  (870 typed files). Real HTTP recovery/install/enable/tool-read path verified.
  Final full suite: 3809 passed / 783 skipped in 137.50 seconds.
  Default service injection remains absent; production object-store wiring,
  Worker authorization/admission and Trench Settings are still pending.
  No business migration, deployment, commit or branch change.

- `EXT-SKILL-02A`: private cloud Skill read adapter now consumes an explicitly
  bound frozen snapshot and verifies current installations, ready publication,
  archive bytes and complete package manifest. Existing skills.list/read reused
  with cloud provenance; no host extraction or script execution. 135 focused
  tests and real PG/MinIO matrix 67 passed, including two users' actual private
  bytes through shared tools. make check passed (868 typed files).
  Independent spec/quality PASS; full suite 3787 passed / 775 skipped.
  Not activated: admitted snapshot persistence, per-call live authorization,
  Worker composition, public upload, MCP execution and Trench Settings remain.
  Preloads bounded selected packages; first-text latency must be verified at
  Worker integration rather than inferred from this off-thread adapter.

- `EXT-API-02C`: Skill installation POST pins an own ready published version
  server-side at disabled revision 1. Scoped idempotency replays current state
  without overriding later toggles; existing store composition and migration
  reused. 114 focused tests, independent spec/quality PASS, real PostgreSQL/
  MinIO and related regressions 66 passed; make check passed (867 typed files).
  Final full suite: 3752 passed / 774 skipped in 137.93 seconds.
  Public upload, Worker consumption and Trench Settings remain unconnected;
  no business migration, environment activation, commit or deployment.

- `EXT-SKILL-01B`: internal durable package publication implemented and
  independently reviewed. Existing ZIP validation and ArtifactObjectStore are
  reused; migration 52 records exact-scope immutable named versions before
  object upload. Verified expectation and object version gate readiness;
  interrupted publication is resumable, with no false Session or raw bytes in PG.
  Final PostgreSQL/MinIO and related regression matrix: 59 passed, including
  recovery/readback and private user objects; make check passed (866 typed files).
  Full suite: 3695 passed / 767 skipped in 144.08 seconds.
  No public upload/install/Worker/Settings
  activation, business migration, commit or deployment.

- `EXT-API-02B`: MCP configuration creation is implemented behind the existing
  default-off management flag. Immutable revision 1 binds a scoped idempotency
  key; replay returns the current revision without overwriting later edits.
  New connections stay disabled and have no credentials or runtime admission.
  Real PostgreSQL matrix: 47 passed (including HTTP create/read/toggle/replay
  and concurrent duplicates); make check passed (861 typed files). Independent
  spec/quality re-reviews passed; 83 focused tests and final full suite
  3671 passed / 756 skipped (135.73 seconds). Storage validation failures now
  return sanitized 503 instead of blaming valid request input with 422.
  No deployment, business schema change or Trench Settings activation.

- `EXT-API-02A`: enabled-only PATCH with separate default-off management flag,
  strong If-Match/ETag, scoped CAS and bounded strict JSON implemented/reviewed.
  114 focused tests and 40 actual PostgreSQL tests passed; full suite 3614 passed
  / 749 skipped in 132.25 seconds, make check passed (858 typed files).
  No deployment or live Worker revocation. Creation/upload/delete/credentials,
  Worker composition and Trench Settings remain pending.

- `EXT-API-01B`: default-off PostgreSQL read composition implemented and
  independently reviewed. `ZEBRA_CLOUD_EXTENSIONS_READ_ENABLED` defaults false;
  cloud-only, matching namespace, read-only schema admission before construction.
  Local lazy SQLite startup preserved by factory-level regression tests;
  119 focused tests passed; final full suite 3574 passed / 747 skipped in
  129.58 seconds, make check passed (856 typed files). No actual environment
  change or migration applied.

- `EXT-API-01A`: opt-in read-only HTTP installation/MCP configuration adapter
  implemented and independently reviewed. Strict verified identity, bounded
  query/IDs, no-store, sanitized responses and cross-scope rejection. 53 focused
  tests after final method correction; preceding full suite 3544 passed / 747
  skipped. Write APIs, Broker scopes, Worker and
  Trench Settings remain pending; no running service activation.

- `EXT-CON-01` and configuration-only `EXT-STORE-01A`: implemented on the
  current branch by explicit user request. Immutable HTTP-only Skill/MCP
  configuration contracts and scoped PostgreSQL CAS/pagination/revision history
  pass independent spec and quality reviews. Evidence: 33 contract tests, 670
  core tests, 38 actual PostgreSQL tests in temporary schemas; make check passes.
  No live schema or Worker activation. Package/catalog/Outbox/Turn snapshot
  persistence, credential authorization, write management API, Trench Settings Skills
  and MCP sections, and actual Agent/browser acceptance remain unimplemented.
  Full-suite baseline repaired in EXT-BASELINE-01; Skill/identity checkpoint:
  changes: 3500 passed / 747 skipped (132.46 seconds).
  Unit tests now isolate their synthetic checkout and schema validation;
  production schema and original-worktree safeguards remain unchanged.
  EXT-SKILL-01A ZIP validation passed 57 tests and independent spec/quality
  reviews, including forged sizes and bounded deflate draining. No extraction,
  upload or script execution enabled. EXT-AUTH-01A passed 41 focused tests and
  independent reviews: verified issuer/subject retained, management permissions
  explicit. Read HTTP routes use this identity; Broker scopes are not enabled.

- `CLOUD-EXT-HTTP-DESIGN-01`: Skill and HTTP-only MCP cloud design drafted in
  `docs/cloud-skills-http-mcp-design.md`. User confirmed no cloud stdio support.
  The design is approved; initial contracts/configuration storage are in review,
  not implemented cloud extension management. Existing
  local compatibility remains unchanged; implementation requires separate task claims.

- `TRN-NATIVE-WORKER-01`: local Apple Silicon latency investigation identified
  amd64 CLI emulation overhead (150 ms versus 18 ms median native info query).
  Worker-only opt-in native image inputs preserve deployment defaults and all
  runtime checks; see `docs/native-worker-local.md`. Local native Worker is
  healthy: continuation first text 2.021s, preparation 0.860s, real sources.list
  executed. This is local cross-service acceptance, not browser paint or p95.

- `RABBIT-SOURCE-CREDENTIAL-REF-01` passes isolated acceptance and is in
  Review. Source bindings now validate an existing credential identity's enabled
  state and source platform without loading its payload. Missing, inactive,
  mismatched and post-bind drifted references fail closed; principal user,
  workspace and active-subscription association remains mandatory. Even a valid
  reference stays `credential_execution_unavailable`, so this closes identity
  integrity without enabling secret resolution or X fetching. Final source
  regression is 100 passed/21 explicit-integration skipped; focused actual
  PostgreSQL is 5/5 including a controlled credential-writer lock race;
  independent SPEC/QUALITY pass. Stage 4 is **7/7 = 100%** at the isolated
  acceptance boundary. No credential payload, live source/schema or production
  process was activated.

- `RABBIT-SOURCE-COMPOSE-01` passes isolated acceptance and is in Review. An
  opt-in minimal-credential process composes the accepted source relay,
  consumer, recovery and quarantine with one shared fail-closed cutover
  selector and a 45-second drain window. Separate real Python processes passed
  broker execution, database fallback, broker restore and default-off rollback;
  fallback generations remain auditable as `superseded` and are not published
  on restore. Actual subprocess E2E is 2/2, cleanup leaves Redis DB 14 empty,
  and independent SPEC/QUALITY pass. Stage 4 group 7 is accepted and Stage 4 is
  **6/7 = 85.7%**. Credential-reference scope closure remains open; no live
  business schema/feed, credentialed source or production process was activated.

- `RABBIT-SOURCE-E2E-01` passes isolated acceptance and is in Review. A real
  fixture HTTP feed traverses durable PostgreSQL admission/Outbox, RabbitMQ,
  fenced execution, Redis raw handoff, normalize and archive into the
  authenticated product timeline and signed Host history Tool. Duplicate
  delivery proves two ACKs, zero requeues and one canonical raw item. A
  deterministic Redis-rejection fault injection leaves source success, raw
  length and normalize cursor unchanged, while two users see only entitled
  source content. Combined source acceptance is 106/106 on actual
  PostgreSQL/Redis/RabbitMQ where applicable; SPEC/QUALITY pass. Stage 4 group 6
  is accepted and Stage 4 is **5/7 = 71.4%**. No credentialed source, live
  business schema/feed or production process was activated.

- `RABBIT-SOURCE-RESULT-01` passes isolated acceptance and is in Review. Six
  sanitized result classes now finalize only the exact command/fence and reuse
  durable FetchAttempt/parse evidence plus a callback-minted Redis checkpoint.
  Retry-After/exponential delay, generation and age are bounded; fallback uses
  the latest due Outbox and completes claim/Inbox/receipt in one transaction,
  while prior generations become auditable `superseded` rows. Migrated URL and
  exception logs are safe, malformed scraper shapes are typed, and downgrade is
  conservative. Combined result/delivery/schedule/cutover/adapter acceptance is
  63/63 including actual generated-schema PostgreSQL; SPEC/QUALITY pass. Stage 4
  group 5 is accepted and Stage 4 is **4/7 = 57.1%**. No live schema/feed,
  credential or production process was activated.

- `RABBIT-SOURCE-CUTOVER-01` passes isolated acceptance and is in Review.
  Managed/default RSS, scraper ARQ and legacy fallback entry points now share a
  default-off selector; broker and DB fallback modes are exclusive and migrated
  mode has one admission trigger. Exact locked validation freezes a non-secret
  execution snapshot before IO; config races fail closed and legacy result state
  is suppressed. Focused 75 passed/12 explicit-PG skipped; parent combined 21/21
  including actual PostgreSQL 9; SPEC/QUALITY pass. Stage 4 group 4 is accepted
  and Stage 4 is **3/7 = 42.9%**. No live process/schema/feed activation.

- `RABBIT-SOURCE-DELIVERY-01` passes isolated acceptance and is in Review.
  Dedicated source Outbox/Inbox/receipt, bounded relay/consumer/recovery,
  exact Redis-checkpoint ACK and opt-in least-privilege RabbitMQ topology are
  implemented independently from the Turn lane. Trench local 15 passed/5
  explicit-PG skipped; parent actual PostgreSQL delivery+schedule 9/9; Zebra
  topology 9/9; isolated live Rabbit source route/ACL 1/1; post-fix SPEC/QUALITY
  pass. Stage 4 group 3 is accepted and Stage 4 is **2/7 = 28.6%**. No old fetch
  entry point, live business schema, feed or production process was activated.

- `RABBIT-SOURCE-SCHEDULE-01` passes isolated acceptance and is in Review.
  Source-wide immutable schedule ownership, atomic FetchCommand plus dedicated
  source Outbox, DB-clock due coalescing, stable manual idempotency and exact
  lease/fence/Redis-handoff finalization are implemented without network or
  process activation. Local 116 passed/4 explicit-PG skipped; parent random-schema
  PostgreSQL 4/4 passed; SPEC/QUALITY pass. Slice **6/6 = 100%**; Stage 4 group 2
  is accepted. Private, credential-reference and
  ambient-auth execution remain blocked; original services are unchanged.

- `RABBIT-ZEBRA-COMPOSE-01` now passes isolated acceptance and is in Review.
  Stage 3 **6/6 = 100%**: broker-only real model, stream replay/user isolation,
  semantic titles/stable routes/draft-only creation, actual answer and asset-page
  file downloads; real broker restart, duplicate drain, fallback/restore and
  canonical cancellation/cleanup. Process fault harness uses real subprocess/PG
  with explicitly injected transport/executor/OCI: final 15 passed. Parent local
  regression 3223 passed/692 skipped, PG 279, live relay/quarantine 7, check 842;
  independent SPEC/QUALITY pass. See `docs/rabbitmq_stage3_composition.md` for
  exact versions, terminal counts, timings and evidence boundaries. Stages 4/5
  remain open; original services and checkouts are unchanged. No commit/merge or
  production-HA acceptance is implied.

- `RABBIT-ZEBRA-RECEIPTS-01` passes SPEC/QUALITY: precise full-fence and canonical
  execution-floor attribution, atomic start/handled receipt with primary worker
  Event/projection commit; no arbitrary model-output completion heuristic.
  Slice 5/5; 61 actual PG cases and 54 shared callers pass; make check (803).
  `RABBIT-ZEBRA-CLAIMED-EXECUTION-01` passes 42 PG/worker cases plus both reviews:
  existing handed-off leases enter the real worker with a scripted model, and
  the completed-tool continuation raw-start gap closes when recorder is supplied.
  `RABBIT-ZEBRA-RECOVERY-01` now handles bounded, proven-unstarted recovery and
  uncertainty isolation; it will not blindly replay prior model/tool execution.
  Recovery accepted 5/5: 129 combined PG/Rabbit cases, final 44 recovery cases,
  make check (806) and SPEC/QUALITY. Poison rows cannot starve healthy candidates.
  Stage 3 is 5/6 (83.3%). MESSAGE atomic input/handoff is accepted: 12 actual PG
  cases, expanded 145 cases, make check (808), SPEC/QUALITY. Canonical CANCEL/STOP
  storage is accepted: 18 actual PG cases, combined 121 cases, make check (810),
  SPEC/QUALITY. Historical cutover accepted after stream-head guard fix: final
  81 PG cases, make check (812), SPEC/QUALITY. Shared fenced Task attach lock-order
  correction passed 7 PG/24 shared tests and both reviews. Consumer accepted:
  final 40 PG/runtime/migration cases, make check (815), SPEC/QUALITY, durable
  reconciliation ACK and bounded requeue fixes included. Quarantine, instance-safe
  cleanup and client-visible outcomes still require composition. Quarantine now
  passes 60 actual PG/Rabbit/runtime cases, check (819), SPEC/QUALITY; slice 5/5.
  Runtime instance identity is accepted 5/5: final 20 actual PG cases, check
  (827), SPEC/QUALITY, including row-lock waits across lease/authority expiry.
  Exact post-commit cleanup accepted 5/5: 92 PG/runtime + 5 live Docker cases,
  check (831), SPEC/QUALITY; plaintext Docker routing fixed from live evidence.
  Public cancel compatibility accepted 5/5: 91 actual PG + 6 live Docker cases,
  check (834), SPEC/QUALITY. Cross-rollover Task-target/CAS and canonical child
  Host identity are now accepted 5/5: 65 + 18 actual PG cases, check (835),
  SPEC/QUALITY. Client-visible outcomes accepted 5/5: actual PG 101 cases,
  final API/projection 52 cases, check (838), SPEC/QUALITY. Shared frame gating
  fixes expiry during DB waits or consumer pauses. Process composition is now
  claimed; Stage 3 group 6 remains open until actual fault/client acceptance.
  Original runtime unchanged.

- `RABBIT-ZEBRA-HANDOFF-01` storage slice passes SPEC/QUALITY: atomic Inbox plus the existing
  Session Lease/Fence and explicit canonical command association. Read-only audit
  confirms old RUN/RESUME execution has no generic command completion receipt;
  ambiguous backfill must not automatically rerun or be marked completed.
  Storage slice 5/5: initial 118 actual PG cases; review found terminal-state
  change during lease wait, fixed with post-lock recheck/savepoint rollback.
  Final race/clock 40 and shared-callers 54 pass. Later receipts, claimed execution,
  control and cutover slices now close group 4; process activation remains off.

- `RABBIT-ZEBRA-RELAY-01` passes SPEC/QUALITY: fenced Broker Outbox relay, confirmed
  transport, bounded physical retry and no network inside DB transactions.
  Actual PG/Rabbit combined suite 111 passed in 49.94 s; make check passes
  (799 typed files). Slice 5/5; later slices now close groups 1–5. Runtime
  activation remains off pending the remaining composition acceptance.

- `RABBIT-ZEBRA-LEASE-CLOCK-01` passes SPEC/QUALITY after a real-PG blocked-heartbeat
  expiry defect was reproduced. Fix the shared current Lease/Fence boundary before
  handoff activation; no new lease authority or original service changes. Slice
  5/5; 81 targeted/real-PG cases and full make check pass, including DST handling.

- `RABBIT-ZEBRA-DISCOVERY-01` passes independent SPEC/QUALITY: bounded canonical-history backfill
  and scoped pending discovery. Explicit admission cutover only; consumers remain
  off. Cursor and derived rows commit together, including old sessions and
  concurrent live admission. Slice 5/5; 60 focused/real-PG tests and make check
  (796 typed files) pass. Group 2 is not accepted until recovery also passes.

- `RABBIT-ZEBRA-ADMISSION-01` passes independent SPEC and QUALITY. Common
  PostgreSQL command admission gains opt-in derived pending/Outbox records; no
  publisher/consumer activation or SQLite changes. Real-PG plus focused tests pass
  36 cases across all four producers; existing PG regression 14 and make check pass.
  Slice 5/5; stage 3 is 1/6 (16.7%). Bounded historical backfill and recovery are
  next, with no activation. See `docs/rabbitmq_stage3_commands.md`.

- `RABBIT-TURN-E2E-01` passes isolated real-model/browser acceptance and independent
  reviews. Fixed shared mapper buffering, takeover reconstruction, separate model
  idle timeout, terminal replay and Next SSE gzip buffering. Browser first text
  4.795s with continuous increments; real files.publish/native asset download
  verified by bytes/hash. Slice 7/7; stage 2 10/10. Original activation remains off;
  stages 3–5 are not complete. Evidence: `docs/rabbitmq_stage2_product_e2e.md`.
  Full frontend typecheck retains three documented baseline fixture errors.

- `RABBIT-TURN-COMPOSE-01` passes spec and quality reviews after fixing real
  signed cancellation replay past earlier approval terminals. Default-off managed
  lifecycle, independent recovery, bounded drain, cancellation control capacity
  and fallback rollback are implemented. Actual PG/Rabbit acceptance: 10 passed,
  including three abrupt subprocess exits; 1000 Turns/route reduce local pickup
  p95 from 250.067ms to 53.939ms. Slice 6/6; stage 2 now 9/10 (90%). Real-model/
  browser verification awaits isolated authority confirmation; stages 3–5 remain
  pending. Original services/data untouched; no production activation or HA claim.

- `RABBIT-TURN-QUARANTINE-01` passes both independent reviews. Sanitized
  receipt/diagnostic Outbox, strict matching DTOs, mandatory confirmed transport,
  separate diagnostic quorum topology/ACL and additive migration are implemented.
  Parent actual PG/Rabbit suite passes 4 cases including 8-way receipt dedupe,
  fencing/migration parity and malformed-secret-safe delivery. Zebra `make check`
  passes (792 Mypy files, eval 10/10). Slice 5/5; stage 2 now 7/10 (70%).
  Default-off composition and dead-owner cancellation gap G20 are in progress.

- `RABBIT-TURN-CONSUMER-01` passes both independent reviews (28 tests each),
  and the combined consumer/dispatcher/handoff/recovery suite passes 65 tests.
  Actual PG/Rabbit capacity-1/prefetch-2 execution persists both answers without
  over-claiming after ACK. Shared reservations keep polling and broker execution
  within one bound. Slice 5/5; stage 2 is 6/10 (60%). Sanitized rejection and
  diagnostic delivery are next; original application startup remains unchanged.

- `RABBIT-TURN-RELAY-01` passes independent spec and quality reviews. Fenced
  relay preserves physical retry identity; durable recovery and scheduling
  deferral create atomic successor generations. Combined tests 60 passed;
  actual isolated PG/Rabbit lost-confirm/duplicate/owner-death acceptance passed.
  Slice 6/6; stage 2 now 5/10 (50%). Bounded consumer implementation continues;
  no original runtime activation. See `docs/rabbitmq_stage2_delivery_evidence.md`.

- `RABBIT-TURN-HANDOFF-01` adds dormant, explicit migration-mode atomic broker
  admission and scoped Inbox+execution-lease handoff in isolated Trench. Shared
  claim logic preserves fencing and fallback; separate broker tables do not
  replace execution Outbox. Independent spec/quality reviews pass, 174 targeted
  tests pass including 37 new cases; final 12 real PG cases pass three extra runs.
  Fixed publishing-state vocabulary and Unicode scope-key overflow. Current slice
  8/8 (100%); Trench Turn stage 3/10 (30%) under the fixed acceptance ledger in
  `docs/rabbitmq_completion.md`. No relay/consumer/sweeper or live activation yet.
  Evidence: `docs/rabbitmq_stage2_handoff_evidence.md`.

- `RABBIT-TURN-FENCE-01` completes the stage-2 prerequisite in isolated Trench:
  monotonic lease fences, owner/active/DB-expiry validation after Turn→Outbox
  locks, local cancellation on heartbeat loss, authoritative execution identity
  and individual shutdown release. Repeated PG tests exposed and fixed mixed
  admission/claim clocks. Independent spec/quality reviews pass; 53 targeted
  tests pass, including 9 real PG scenarios repeated three extra times. Additive
  migration tested on synthetic existing rows only. No business Rabbit activation,
  atomic broker Outbox/Inbox, original-service migration, merge or E2E claim.
  Evidence and next gates: `docs/rabbitmq_stage2_fencing_evidence.md`.

- `RABBIT-INFRA-01` adds optional RabbitMQ transports to both approved isolated
  repositories and a pinned 4.3.5 local broker fixture with least-privilege vhosts,
  quorum queues, mandatory confirmed publishing and explicit manual settlement.
  Both actual adapters pass the same 8 real broker scenarios (disconnect/restart,
  redelivery, routing/role isolation, prefetch, capacity and quarantine), with
  30 unit tests each and 3 provisioning tests. Zebra make check passes (791 Mypy
  files, eval 10/10). Independent spec and quality reviews pass after closing
  initial-connect cancellation and default-dev-install defects. No business activation,
  PG handoff, browser E2E or production HA is claimed. See
  `docs/rabbitmq_stage1_evidence.md` and `docker/rabbitmq/README.md`.
  Final full Zebra suite: 2984 passed, 381 skipped; disposable acceptance broker
  and test volume removed after zero-connection/zero-message checks.

- `RABBIT-FOUNDATION-01` implements the stage-0 envelope contract in both isolated
  repositories, with identical generated schema/fixtures and 84 envelope tests per
  repository. Real disposable PostgreSQL baselines measured Trench pickup p95 at
  242–257ms for 100-Turn runs and proved Zebra's recent-session scan misses an older
  pending command (9 SQL/9 connections per scan). No runtime integration or service
  activation. Core tests pass 637; Trench focused tests pass 97; Zebra make check
  passes (790 Mypy files, eval 10/10). See `docs/rabbitmq_stage0_evidence.md` for
  reproduction, identity/command producer inventory and remaining integration gates.

- `RABBIT-RELIABILITY-REVIEW-01`: RabbitMQ plan revised to content v1.1 after
  checking existing Trench/Zebra code and RabbitMQ delivery semantics. The
  audit distinguishes deterministic contradictions from implementation risks;
  it specifies scoped operation/generation deduplication, fenced handoff,
  mandatory returns, isolated shadow traffic, source scope and Redis limits.
  Work is isolated on `codex/rabbitmq-foundation-01`; no runtime activation or
  migration. The foundation continuation above supplies Schema/local baseline;
  real PG/Rabbit failure tests and runtime integration remain open. See
  `docs/RabbitMQ可靠投递缺口核验与验收.md` for evidence and gates.

- Trench user-file profile follow-up (`CLOUD-USER-FILES-TRN-PROFILE-02`) is in
  review on `codex/zebra-durable-turn-grants`. The research parent profile
  now exposes the existing governed `files.publish` Tool while keeping shell,
  patch, Git and nested delegation unavailable. Focused validation passes
  `27 passed`, Ruff and Mypy are clean, and real Trench browser acceptance
  published and downloaded a governed Markdown file.

- Trench long-turn recovery fixes (`TRN-MODEL-TOOL-REPAIR-02` and
  `CLOUD-CONT-FALLBACK-02`) are in review on
  `codex/zebra-durable-turn-grants`. OpenAI-compatible response rejection now
  preserves the provider tool name for bounded repair/audit. Cloud Provider
  Continuation only intercepts `provider_native`; `capsule_fallback` follows
  the ordinary durable Event path instead of failing for a missing artifact.
  Focused tests are `18 passed` with Ruff clean. A real Trench Task crossed
  three context compactions, persisted the fallback selections and completed
  with 360 Zebra Events; the repository-wide `make check` remains blocked only
  by the pre-existing 742-line handoff test against the 700-line size gate.

- Trench Durable Turn workload grants (`TRN-DURABLE-GRANT-01`) are in review on
  `codex/zebra-durable-turn-grants`. The Host Grant Broker now accepts either
  the existing verified browser Cookie or an allowlisted HMAC-authenticated
  Trench server workload. Workload signatures bind timestamp, nonce and the
  canonical principal/workspace/source request; repeated nonces derive the
  same JTI for Zebra replay rejection. The default grant TTL is 1900 seconds
  against the current 1800-second execution ceiling. Broker focused tests are
  `13 passed`; full Ruff, mypy (`789` source files), and the 10-case release eval
  pass. The full suite reached `2850 passed, 370 skipped`; its only failure is
  the pre-existing, out-of-scope 742-line
  `tests/agent_storage/test_postgres_session_handoffs.py` file-size violation.
  Local real Trench/Zebra cross-service execution and browser switch/refresh
  acceptance pass; production deployment remains a separate gate.

- Manifest-declared Host write approval (`HOST-WRITE-POLICY-01`) is in review on
  `codex/fix-agui-live-tail` after integrating `codex/host-write-policy-01`.
  The slice maps Host manifest write risk into
  Zebra's existing durable approval flow while keeping read-only Tasks closed;
  approval now enqueues one idempotent resume command, and cloud recovery repairs
  a one-sided Session/Workspace projection write from canonical Events before
  continuing. Real Trench acceptance subscribed an X profile through
  `sources.add`, resumed after explicit approval, and kept one subscription on
  an idempotent repeat. `make check` and the full suite (`2830 passed, 372
  skipped`) are green. The local Trench Cloud stack now has an explicit
  `ZEBRA_DEVELOPMENT_UNRESTRICTED` operator switch; it auto-allows approval-bound
  tools only in the `cloud` development profile and is rejected by production.
  The switch changes policy decisions only: the cloud gVisor/network profile,
  Host Grant, principal/resource binding, SSRF and path checks remain enforced.
  A logged-in browser acceptance directly subscribed the public ITJuzi feed and
  persisted exactly one user/workspace-scoped row. Trench remains responsible
  for business authorization and idempotent writes.

- Trench/Zebra response-latency and availability closeout (`TRN-PERF-01`) is
  implemented on `codex/fix-agui-live-tail`. Host-bound Tasks skip disposable
  workspace scanning; the first provider delta is committed immediately even
  when Host tools are advertised, and a streamed partial response disables
  semantic replay so visible text cannot be duplicated; later tiny chunks are
  bounded; PostgreSQL commits publish Redis live hints
  only after commit; the Worker fallback poll is 100ms; Memory/title side
  effects recover off the reply path. Conversation recovery now supplies the
  bounded completed-turn history, and AG-UI suppresses the internal tool-only
  assistant sentinel. DeepSeek Chat and Responses adapters preserve a present
  but empty provider reasoning field exactly, so a valid thinking-mode tool
  call no longer becomes a generic unavailable error while a genuinely missing
  continuation still fails closed. Current Compose images were rebuilt from
  this worktree. Real Trench TLS/Broker/Worker acceptance after rebuild passes
  three consecutive Turns: first visible events `36ms / 8ms / 7ms`, ordinary
  first text `4.04s / 4.15s`, exact recall of `灯塔`, and `sources.list` callback
  plus clean final answer in `6.65s`. The Trench development BFF now uses an
  explicit same-origin streaming Route Handler instead of the generic Next.js
  rewrite for chat SSE. A logged-in Chrome turn produced 27 increasing body
  snapshots (`47 -> 1625` characters) before terminal state. `make check` is green;
  the final repository-wide suite is `2826 passed, 369 skipped`.

- Cloud user file delivery (`CLOUD-USER-FILES-01`) is implemented on
  `codex/cloud-user-files-01`. A Grant-gated `files.publish` Tool accepts
  generated UTF-8 content or a safe workspace file, commits `kind=user_file`
  through the existing PostgreSQL Event/Artifact authority and private
  versioned MinIO store, and exposes raw private downloads behind
  `artifact.read`. The broker binds an opaque authenticated `principal`; Task
  binding renewal and task reads reject principal drift, so users sharing a
  namespace/workspace cannot cross-read files. Trench owns the stable BFF URL;
  neither MinIO credentials nor presigned URLs reach the browser. Real
  PostgreSQL + MinIO publication and HTTP download pass `2/2`; focused
  regression is green. Full-gate inherited failures remain separately recorded
  on the task card.
  The AG-UI adapter now preserves only the downloadable file fields in a
  versioned Tool-result envelope, allowing Hosts to build authenticated links
  without exposing MinIO keys, credentials, or presigned URLs. The production
  AG-UI stream tenant guard now authorizes the path's thread id (not its run id),
  restoring secure Host streaming without weakening principal isolation.

- Trench cloud governed Memory closeout (`TRN-MEM-E2E-01`) now routes API
  confirm/expire through the PostgreSQL aggregate CAS instead of the SQLite-only
  `upsert` path. Worker recovery persists a receipt for each closed Turn and
  selects oldest unreceipted closes, removing the moving recent-Session blind
  spot. Real PostgreSQL acceptance proves Lease-safe candidate review, atomic
  Memory/Event/Session/Workspace advancement, next-task confirmed recall and
  durable recovery selection (`6 passed`); the focused Memory matrix is
  `85 passed`. Local SQLite behavior is unchanged. Mem0 delivery/runtime remains
  separately locked and is not implied by this closeout.

- Orchestration package boundary is integrated into `cloud-agent`
  (`AL-BOUNDARY-ORCH-01`, source PR #260 / `codex/al-boundary-orch-01`,
  ADR-021): the
  deterministic orchestration domain — plan/budget contracts, DAG validation
  and scheduling, five-layer
  completion gate, worktree merge fix loop, Agent Team contracts and the
  ordinary `system/orchestrator@1` definition — moved from `agent-core`
  into the new `agent-orchestration` workspace package as pure renames +
  import rewrites, with the nine focused test modules moved to
  `tests/agent_orchestration/`. The undeclared `agent-core → agent-tools`
  reverse dependency is closed and now guarded by a new core architecture
  gate. Review closeout pins the internal wheel requirements to the Zebra
  `0.1.0` distributions; a clean trusted-wheelhouse install no longer
  resolves the unrelated public `agent-tools==1.0.1`. Core, control-plane
  and orchestration boundaries now use AST import allowlists plus exact
  TOML dependency sets, including adversarial future-agent/bare-apps/
  security/HTTP imports. The control-plane gate forbids
  `agent_orchestration` (allowed direction: orchestration → control plane,
  never the reverse).
  `subagents.py` stays in `agent-core` (Focused Subagent is the
  parent-agent mode); the PostgreSQL orchestration adapter stays in
  `agent-storage` and the AG-UI projection in `agent-integrations`, both
  now declaring the workspace dependency. No microservice split and no
  behavior change. Validation: `make sync`/`make check` green (file-size
  1446, Ruff, Mypy 716, Eval 10/10); focused boundary/orchestration matrix
  `133 passed / 4 skipped`; full suite `2614 passed / 0 failed / 342 skipped`
  (real-PG/MinIO suites skip locally as before).

## Current Mainline Snapshot

- Mainline branch is `cloud-agent` (it carries the cloud product line and
  sits ahead of `origin/main`; PRs land on `cloud-agent` and main syncs
  on cut points).

- Client Integration Plane architecture is proposed and under review
  (`CLIENT-ADR-01` on unmerged `codex/client-adr-01`, ADR-CLIENT-01): V1
  browser integration is designed as a durable client plane —
  published Frontend Capability Profiles as the configuration source of
  truth, Client Sessions with one-controller fencing (Observers are
  read-only), and PostgreSQL-durable Client Effects with receipts,
  idempotency and expected-UI-revision checks — while formal business
  writes stay on Host Backend Tools and the agent keeps no arbitrary
  JavaScript/DOM authority. Browser access goes through the Host BFF
  (Direct Browser-to-Zebra stays off). The dependency-ordered 22-card
  CLIENT board (contract → PostgreSQL → admission/API → client context →
  durable client action → suspend/resume → TS/React SDK → conformance →
  Trench pilot → production gate) is registered in `docs/AGENT_TASKS.md`;
  the original docs-only card was expanded by explicit maintainer batch
  activation, so the implementation and governance delta now require review
  together before this ADR can be accepted.

- Client Integration Plane V1 backend and browser-runtime candidate is
  partially implemented on the unmerged review branch (reviewed 2026-08-26): the
  backend chain — capability/session/effect contracts (append-only migrations
  v31-v34; real-PostgreSQL capability/session/effect suites PASS 7/6/6), platform bundle
  composition behind the default-off `ZEBRA_CLIENT_INTEGRATION_ENABLED`
  flag, the Runtime Client API, the schedule-only Worker client
  channel with `waiting_client_effect` suspension and atomic
  receipt-driven resume restoring the original tool call — plus the
  typed TypeScript client-core and initial React hook surface. Review fixes
  separate session credentials from controller fences, renew/release the
  controller lease, require every lease to reference the exact persisted Run
  Binding, bind Worker lookup through Task-to-active-Segment,
  harden legacy migration and exact digest/UI-revision checks, and add the
  dedicated Client Effect AG-UI SSE projection. Cloud HTTP uses independent
  HostGrant and Client Session headers and binds all runtime requests to the
  verified HostContext. Validation: `make check`; full Python suite
  2694 passed / 364 skipped; TypeScript `tsc --noEmit` and 15 Node/React tests;
  real PostgreSQL capability/session/effect suites pass 7/6/6; file-size gate
  0 violations. This is not end-to-end product acceptance: Management audit
  and complete CAS, durable AG-UI Binding/State admission, Worker client-state
  recovery, Client State projection, React HITL runtime evidence, real-process
  reconnect/restart drills, Trench pilot and production gate remain open.

- Task/Turn/Segment lifecycle implemented (2026-08-24, ADR-026,
  `CTX-TURN-*` cards 1-9, `codex/ctx-turn-lifecycle-01`, stacked on the
  `CTX-INHERIT-CLOUD-01` review closeout): a final model answer now closes
  a Turn (`TURN_COMPLETED/FAILED/CANCELLED` with `turn_id/turn_index`)
  instead of always closing the Segment. `conversation` Tasks stay in the
  new `SessionStatus.AWAITING_TURN` and keep one Segment across turns —
  the next human message re-arms the Segment to `ready` with a new
  deterministic Turn; `one_shot` (and every legacy admission, which reads
  as `one_shot`) additionally writes the compatible `SESSION_COMPLETED`,
  so all existing terminal consumers keep working unchanged. MESSAGE
  admission rejects a second normal message while a turn is
  `running/waiting_approval` (`turn_in_progress`), clarifications keep
  continuing their own turn, and API idempotency replays the same turn /
  conflicts on drift. Per-turn consumers are migrated: Memory extraction
  and title generation run after every successful Turn with a per-turn
  window and receipt anchoring, the workspace returns to `prepared` on
  `TURN_COMPLETED`, AG-UI emits one `RUN_FINISHED` per Turn (plus
  `RUN_STARTED` for the next turn) and the task stream stays open in
  `awaiting_turn`. Crash reconciliation heals a crashed one-shot
  `TURN_COMPLETED(closes_segment=true)` -> `SESSION_COMPLETED` window
  idempotently without re-invoking the model. Context coverage now fails
  closed on an uncovered gap between the active Capsule and the truncated
  History window and records explicit truncation omissions. The public
  task API adds `task_status`, `current_turn_status`, `turn_id`,
  `active_segment_id`, `interaction_mode` while keeping `status`.
  Latest validation: full repository `2677 passed / 349 skipped`, Context
  PostgreSQL `8/8`, Event PostgreSQL `15/15`, Cloud PG+MinIO composition
  `33/33 PASS`, and `make check` green (size `1462`, Mypy `723`, Eval
  `10/10`). The
  ADR-026 acceptance matrix covering multi-turn single-Segment continuity,
  one-shot legacy compatibility, admission conflicts, idempotency replay,
  crash healing and per-turn AG-UI boundaries. Not yet done: the optional
  explicit legacy Task upgrade path (last in the ADR-026 rollout order),
  full Cloud PostgreSQL+MinIO E2E with multi-worker crash drills, and the
  Trench 16-input cross-service acceptance.

- Cloud Context inheritance review closeout landed (2026-08-24,
  `CTX-INHERIT-CLOUD-01` closeout on
  `codex/cloud-context-inheritance-01`): automation handoff seeds
  (`source=session_handoff` / `actor_kind=automation`) no longer pollute
  the materialized History tail or the INITIAL/CONTINUE mode tally; SQL
  truncation is detected via limit+1 and surfaces as
  `history_tail_truncated` / `history_prefix_uncovered` omissions instead
  of silently dropping the prefix; the card's claims were narrowed to
  "Cloud Worker consumes authoritative materialization + bounded Child
  inheritance" — ordinary multi-turn Task continuity is owned by ADR-026.
  Validation: focused `15 passed`, Context PostgreSQL `7/7`.

- Cloud Context inheritance is ready for review (2026-08-23,
  `CTX-INHERIT-CLOUD-01`, `codex/cloud-context-inheritance-01`): Cloud Worker
  now consumes one PostgreSQL-authoritative materialization generation for
  recent History, active Capsule and confirmed scoped Memory. Durable children
  explicitly choose `fresh`, `capsule`, `fork_tail` or `resume`; non-fresh
  inputs are bounded, source-attributed, checksum-protected and frozen into the
  Child `TASK_PREPARED` Event. Handoff acceptance/files/validation/failures/
  questions/Artifacts are model-visible under a 2048-token auxiliary budget;
  any compiler-side truncation is explicitly marked,
  while credentials, hidden reasoning, raw tool output and Provider-private
  continuation remain omitted. The activated path also fixed PostgreSQL History
  to return the newest bounded text tail from one read-only Repeatable Read
  snapshot and made planner metadata JSON-native so
  canonical Event replay remains exact. Validation: focused `33 passed / 7
  dependency-gated skipped`, Context
  PostgreSQL `6/6`, Cloud PostgreSQL+MinIO composition `33/33`, no-filter full
  repository over real PostgreSQL+MinIO `2952 passed / 0 failed / 13 skipped`,
  and `make check` green (size `1441`, Mypy `718`, Eval `10/10`). Containers,
  networks and volumes were cleaned. Trench production acceptance is unchanged.

- Maintainer line acceptance closed (2026-08-21, gate 5, reviewed at
  `cloud-agent@5bab4b57`): the complete 59-path delta from
  `e2f76046^1..5bab4b57` was reviewed across Host admission/freeze,
  HTTP/auth, durable delegation, Effect replay, concurrency and recovery;
  no new P0/P1/P2 Cloud blocker was found. Independent validation passed
  `make check` (file-size `1441`, Ruff, Mypy `713`, Eval `10/10`) and a
  no-filter full-repository run over real PostgreSQL + MinIO (`2938 passed /
  0 failed / 11 skipped`); the isolated containers, network and volume were
  removed. `COMPOSE-CLOSEOUT-AUDIT-FOLLOWUP-01` is `Done`. PR #257's
  Backend and Cloud real-service checks are green; the inherited Packaged
  Tauri stop-stream failure remains a separate non-Cloud repository gate.
  Trench real acceptance (gate 3, 16 deployment inputs) is the remaining
  product delivery gate.

- Accepted-baseline delivery gates closed (2026-08-21, `cloud-agent`,
  PRs #255-#257): gate 4 — both inherited repo failures root-caused and
  fixed (mem0 spike insert lagged the 25-column governed-memory schema;
  the fenced effect-consumer replay minted a competing payload artifact
  before the schedule dedup — lookup-by-ledger-key now returns the
  stored dispatch for business-identical replays). Gate 1 — Host
  admission contract freeze (ADR-017): v30 host_manifest_freezes stores
  one immutable manifest per connector profile revision; admission
  get-or-fetches it BEFORE the atomic transaction and the binding
  carries the REAL manifest digest; the Worker consumes the frozen
  manifest (discovery disabled in the regression), unbound host-context
  sessions build a local-only surface per their frozen contract, and
  pinned-but-unfreezable admissions fail closed with 503. Gate 2 —
  real HTTP/auth-boundary E2E: the actual FastAPI app on a real
  uvicorn socket, RS256-signed Host Grants verified against a
  PostgreSQL authority registry (only the JWKS resolver is a test
  seam), covering 401/403 paths (anonymous, garbage grant, disallowed
  origin, missing scope, consumed jti), full-body idempotent replay,
  409 conflict, and worker completion of the HTTP-created session.
  Validation: no-filter full-repo over real PG+MinIO 2938 passed /
  0 failed / 11 skipped; make check green (mypy 713 files). Remaining
  gate: Trench real acceptance (inputs pending); maintainer line
  acceptance is closed above.

- Strict-revision closeout (2026-08-21, `cloud-agent`, PR #254):
  expected_revision is now a strict int in BOTH SessionCommand and
  SessionCommandAcceptedPayload — a corrupted JSON true/float/string is
  rejected instead of silently coerced to the integer a fingerprint was
  computed over (bool/float/string rejection tests added). The
  adversarial run-key regression now derives its payload from
  SessionCommand.event_payload() and corrupts exactly one field
  (command_id), so the core fingerprint stays correct by construction
  and the test cannot go falsely green if the algorithm evolves. The
  audit follow-up card's ownership list was regenerated from the actual
  `e2f76046^1..HEAD` diff (46 paths incl. the deleted research_binding,
  PROGRESS.md and every touched test) and records all seven rounds
  (#248-#254); it stays `Review` until the maintainer accepts the line.

- Review-round P2 closeout (2026-08-21, `cloud-agent`): the run-event
  pre-check now validates through the CORE contract instead of a local
  copy — the payload must parse as SessionCommandAcceptedPayload (UUID
  command/session ids, enum kind, bounded fields), rebuild into a
  SessionCommand, match kind=run/session/key/empty payload, and the
  accepted fingerprint must equal the command's own core-computed
  fingerprint. A durable event with a self-consistent fingerprint but a
  non-UUID command_id (injected via raw SQL, i.e. direct store
  corruption the validating append path would reject) now fails closed
  into idempotency_conflict instead of being rebuilt as 202 accepted
  (regression reproduces exactly that injection). Governance: the audit
  follow-up rounds #248-#253 now have an ownership card
  (COMPOSE-CLOSEOUT-AUDIT-FOLLOWUP-01) listing the actual branches and
  owned paths; F4/F5's stale branch/ownership lines point to it. Note:
  the no-filter full-repo number is subject to external-model drift —
  the DeepSeek smoke test failed transiently in the maintainer's run on
  an empty provider reasoning_content, independent of this line.

- Fifth review round: truncation prefix + run-key semantics (2026-08-21,
  `cloud-agent`): closes the two P1s found in PR #251. Canonical CJK
  summaries keep the longest original prefix fitting the per-child
  JSON-escaped budget via binary search — the previous cut emptied
  4000-char Chinese answers into the shared fallback (both producer and
  verifier read that fallback, so equality held while the answer was
  gone); regressions now require non-fallback, original-prefix,
  near-budget canonical forms plus the 16-child command-contract
  reconstruction. The run pre-check validates the persisted event
  completely (type, kind=run, session, key, empty payload,
  self-consistent fingerprint) before rebuilding; a cancel wearing the
  run key returns idempotency_conflict through the create replay (the
  reconciler propagates the conflict instead of the stale admission
  body). Standard full-repo selector over real PG+MinIO: 2926 passed /
  2 pre-existing failures / 11 skipped; `make check` green.

- Fourth review round: command-contract closure (2026-08-21,
  `cloud-agent`): the canonical child summary now budgets the exact
  serialization the command contract measures (json.dumps with
  ensure_ascii — CJK escapes to 6 bytes/char) at 3 KiB per child with
  whitespace-free ends, so the worst legal epoch (16 children with long
  Chinese answers) produces a wakeup payload that reconstructs into a
  valid SessionCommand (regression drives the real wakeup service over
  real PostgreSQL and validates the consumer's exact reconstruction;
  previously 16 CJK summaries measured 66,947 escaped bytes and were
  rejected). Truncation boundaries landing after a space can no longer
  break the Worker verifier's exact match (canonical form is
  edge-whitespace-free; the recovery side's defensive strip became a
  no-op). queue_cloud_run now looks up the persisted run event by
  command key BEFORE submitting — the crash window where the run event
  committed but the receipt body was never synced heals on replay
  (rebuild from the event + receipt re-sync) instead of re-submitting
  into idempotency_conflict and returning a stale ready/no-command body
  forever (regression simulates the exact window). Validation, standard
  full-repo selector over real PG+MinIO: 2925 passed / 2 failed /
  11 skipped — both failures (mem0 logical-reset spike, fenced
  effect-consumer replay) pre-exist on the PR #250 tree per the
  maintainer audit and are unrelated to this line; `make check` green.

- Third review round: multi-Worker wakeup closed (2026-08-20/21,
  `cloud-agent`): wakeup processing now serializes per parent (FOR
  UPDATE on the parent stream row) and emits a deterministic,
  per-epoch-idempotent wakeup event — 8 concurrent workers on one child
  produce exactly one wakeup; two children terminalizing concurrently
  join into one wakeup carrying both results (the prior race could emit
  8 duplicate wakeups or strand the parent with zero). Cancelled
  children settle legally (shared canonical reader includes
  session_cancelled; 2048-byte UTF-8-safe truncation shared by producer
  and verifier keeps worst-case 16-child payloads inside the 64 KiB
  command contract while preserving exact-match verification). API
  create idempotency is closed end to end: duplicate run commands are
  rebuilt into the accepted shape from the persisted event — 16
  concurrent same-key creates ALL return 201 with one identical full
  body, and the crash-after-run-commit replay now heals instead of
  returning a stale ready/no-command body forever. New real-PG
  regressions: same-child×8, distinct-children concurrent join,
  cancelled-child verification, 16-thread full-API create. Validation:
  2431 non-PG + 461 real-PG tests, `make check` green. Remaining
  follow-ups unchanged (Host manifest freeze at admission, Trench
  inputs; E2E still application-level API, not HTTP/auth).

- Second audit round closed on the durable delegation chain (2026-08-20,
  `cloud-agent`): the six P1 findings of the PR #248 review are fixed
  with real-PG evidence. Wakeup trust: only HARNESS-actor resume commands
  can wake a waiting parent (a USER resume neither resumes nor injects —
  restore fails closed without the trusted wakeup); every delivered
  child result is re-derived from the child's own terminal event inside
  the wakeup transaction AND re-verified by the Worker (terminal link +
  matching projection status + identical summary) before injection.
  Real answers: the wakeup reads `metadata.assistant_message`, not the
  lifecycle `summary`; the E2E's parent model can only finish after the
  child's real answer arrives in its conversation. Concurrency:
  admission idempotency claims keys with INSERT ... ON CONFLICT DO
  NOTHING (16 threads → 1 create + 15 identical replays); delegation
  losers roll their child back with the transaction and replay the
  winner's link (16 threads → 1 materialize + 15 winner replays, no
  orphans). Multi-child: the wakeup evaluates the durable
  ParentContinuation — parallel delegations keep the parent suspended
  until every epoch child is terminal, then one wakeup carries all
  results and the parent injects one real result per delegated call.
  Two-phase heal: a replayed create whose run command was lost re-
  submits it under the same command key and syncs the stored body. The
  wakeup append position derives from the event stream (MAX sequence),
  not the lagging projection. Validation: 2431 non-PG + 457 real-PG
  tests passed, `make check` green; new suites:
  `test_postgres_default_chain_scenarios.py` (forged resume,
  two-children join, replay requeue) and
  `test_postgres_concurrent_idempotency.py`, all registered in the
  compose runner. Known follow-ups unchanged: Host manifest/credential
  freeze at admission, Trench cutover inputs.

- Default-composition durable delegation proven end to end (2026-08-20,
  audit-fix branch on `cloud-agent`): the 2026-08-20 maintainer audit of
  PR #247 found all three "fixes" dead on the default path — the durable
  child could never materialize (fabricated `derived.local` parent
  binding + capability mismatch), the parent wrote SESSION_COMPLETED
  before SESSION_SUSPENDED with a contract-violating payload, and the
  idempotency hash diverged between API replay and PG admission (plus
  non-serializable attachment/UUID payloads). All closed on the real
  path: admission now freezes a binding for every cloud session
  (Host-bound pins the Host grant; internal sessions pin a
  deployment-authority binding) inside the atomic v25 transaction with a
  round-trippable snapshot; the tool loop suspends the parent on
  `suspend_after_turn` by freezing a `SUBAGENT_DELEGATED` join-state
  event (conversation, counters, tool-call identity) BEFORE any terminal
  event; the child runs READ_ONLY on a `research` tool profile (no
  `agent.research` — durable depth 1 is additionally enforced against
  the delegation link) with a binding narrowed to
  `{agent.execute, evidence.read}`; the wakeup command carries the
  child's terminal summary and the resumed parent injects it through the
  completed-tool continuation (`SESSION_RESUMED` now legal for logical
  resumes); idempotency uses ONE canonical hash computed by the API from
  the raw payload, stores the full 201 body atomically (run-command
  composition syncs it afterwards), replays it verbatim and 409s on
  hash conflict; child admission + delegation link commit in one
  transaction (no orphan children). Fixed three latent default-chain
  bugs the old component tests could not see: `load_task_binding` wrote
  a partial snapshot JSON no consumer could validate,
  `AttemptAuthorityEvidence.persist` recovered without the worker lease
  (cloud path always raised), and the workspace-projections CHECK
  rejected the `research` profile (v29 migration). New E2E
  `tests/agent_storage/test_postgres_default_chain_e2e.py` drives the
  REAL default API + Worker loop + `agent.research` over real
  PostgreSQL + MinIO with only the model transport scripted (registered
  in the compose runner). Validation: 2431 non-PG + 452 PG tests
  passed, `make check` green. Known follow-ups (explicitly not closed):
  Host-connector manifest/credential freeze at admission (Worker still
  discovers live at gateway build), and the Trench cutover chain.
- Agent Layer phases B–D executed (2026-08-18, PRs #208-#216): Phase B
  closed with `AL-TASK-BIND-CON-01` (immutable binding snapshots and
  capability intersection), `AL-CONNECTOR-PG-01` (v24 registry, immutable
  revisions, CAS bindings, real-PG evidence) and
  `AL-TASK-ADMISSION-PG-01` (v25; one-transaction admission across events,
  projections, task index, binding and idempotency with mid-transaction
  crash-injection rollback). Phase C closed with `AL-AUTH-WORKER-01`
  (P0.4: `BoundHostExecutionAuthorityResolver` derives Attempt authority
  from the frozen binding with fail-closed drift/expiry and narrowing-only
  revalidation), `AL-HOST-EGRESS-01` (P0.2 implementation side: pinned
  immutable connector profiles with memory-only ephemeral credentials) and
  `AL-HOST-EFFECT-01` (uncertain write receipts reconciled through the
  pinned profile path; blind retries structurally absent). Phase D's
  in-repo portion closed with `AL-QUERY-API-V1-01` (task-level AG-UI
  cursors survive rollover) and `AL-HOST-CONFORMANCE-01` (two-vocabulary
  fake hosts pass one shared 18-test suite over the real admission and
  effect paths; zero-branch gates). 14/16 cards Done:
  `AL-API-DECOUPLE-01` (#217) additionally moved
  `agent-runtime`/`zebra-agent-worker` out of the API's core dependencies
  into a `[local]` extra with lazily imported seams, so a cloud-only
  deployment packages the API without Worker or Runtime execution. The
  remaining two (`AL-TRENCH-CUTOVER-01`, `AL-LEGACY-REMOVAL-01`) are
  hard-gated on `EMB-TRN-READ-E2E-01` real-stack acceptance evidence and
  stay Locked until the maintainer provisions the deployment inputs
  (Trench/Zebra HTTP endpoints, both stacks' PG/Redis/object-store health,
  Grant exchange, Worker restart hook, and the Trench session cookie).
- Agent Layer Phase A executed (2026-08-18, PRs #204-#207 on `cloud-agent`):
  `AL-BOUNDARY-CON-01` lands the `agent-control-plane` workspace package
  (core-only dependency, boundary gate, `AgentAction` route vocabulary);
  `AL-HOST-CONTRACT-V1-01` freezes the capability/grant-scope separation,
  single-segment JSON-pointer resource binding rules, digest-canonical
  manifest v1, uncertain effect receipts and the ephemeral credential seam;
  `AL-WORKER-GENERIC-01` deletes the Worker's Trench tool/argument/resource
  branches — resolution now runs generically from manifest binding rules,
  legacy manifests are enriched by the Host adapter in integrations, and a
  vocabulary gate forbids Host names in Worker production code;
  `AL-CONNECTOR-CON-01` freezes immutable outbound connector profiles
  (bare-HTTPS origins, secret-free credential refs) and namespace bindings
  with published/deprecated/revoked lifecycle plus the operator-only
  registry Port. Phase B implementation cards (`AL-CONNECTOR-PG-01` from
  migration v24, `AL-TASK-BIND-CON-01`, `AL-TASK-ADMISSION-PG-01`) remain
  `Locked` awaiting activation.
- Agent Layer direction ratified (2026-08-18, `AL-PLAN-01` `Done`): Zebra
  Agent Layer = Agent Control Plane + Host Integration Plane, landing first
  as a logical `agent-control-plane` application package inside `apps/api`
  (no new microservice yet), with the Runtime untouched. The five
  architecture decisions are recorded in ADR-017; the authoritative
  engineering plan is `docs/cloud-agent构建实施方案.md` (review baseline
  `main@bb3a1bce`, key claims re-verified on ratification day). Sixteen
  `AL-*` implementation cards are registered `Locked` in four phases
  (boundary/protocol, connector/task-binding, execution authority/egress,
  API/conformance/migration); highest-leverage starters are
  `AL-HOST-CONTRACT-V1-01`, `AL-WORKER-GENERIC-01` and
  `AL-CONNECTOR-CON-01`, which together free the Worker from all Trench
  vocabulary and enable zero-branch second-Host onboarding.

- Snapshot date: `2026-08-16`
- 非产品决策收口（maintainer directive "除接入 Trench 外相关的功能全部
  做完，多租户也要开发完毕，用户体系是外挂的"）：多租户三切片全部落地——
  v23 迁移把租户 namespace 持久化到 session 投影（TASK_PREPARED host
  context 绑定一次），API 会话/任务/审批/流/AG-UI/users/tenants 内存读面
  全部按调用方租户隔离（跨租户 404，未绑定会话保持 operator 域），默认
  Cloud Worker 经 `TenantScopedAuthorityResolver` 在每次 Attempt 前持久化
  `execution_authority_resolved`（issuer 钉定、租户 namespace per-scope、
  外来 issuer fail closed）；顺带修复 `validate_event_payload` 的
  python-mode dump 泄漏 datetime 到 PostgreSQL Jsonb 的缺陷。扩展体系
  `EXT-PLUGIN-01`/`EXT-HOOK-01` 与 `ARCH-129-ACP-01`/`ARCH-129-CTX-01`
  按 blanket activation 全部实现并登记 `Done`。剩余 `Locked` 均为治理性
  门控而非工程缺口：`EXT-MARKETPLACE-01`（私有云 GA 前置）、Mem0 消费链
  （Provider admission: DENIED）、`AGENT-DEF-STO-01`（本地 SQLite Registry，
  云端产品定位推迟）。rig E2E 在 authority 事件入流后仍 `PASS` 11/11。
- Agent Definition chain closed: the full runtime chain
  REG（`AGENT-DEF-PG-01`，v19 迁移 + `PostgresAgentRegistry` + draft/version/
  release/eval evidence）→ DRAFT（`AGENT-DEF-DRAFT-01`，物化服务 + API）→
  BIND（`AGENT-DEF-BIND-01`，`AgentDefinitionSnapshot` + TASK_PREPARED +
  投影镜像 + 恢复校验）→ MEM（`AGENT-DEF-MEM-01`，Definition 域 governed
  Memory，v21 迁移）→ TRUST（`AGENT-DEF-TRUST-01`，内容信任与威胁模型）→
  EVAL（`AGENT-DEF-EVAL-01`，`AgentVersionPublicationGate`）→
  PUB（`AGENT-DEF-PUB-01`，受控发布 API + enforcement_mode，v22 迁移）全部
  `Done`；真实 PostgreSQL 矩阵 437 passed，本地套件 1290 passed，`make check`
  （file sizes/ruff/mypy 649/eval gate 10/10）全绿。`AGENT-DEF-STO-01`（本地
  SQLite Registry）按产品定位继续推迟。
- Durable positioning (2026-08-16, maintainer): the product is the cloud
  agent; the local agent exists to develop and prove the agent runtime and
  is not an independent product goal. Recorded explicitly in `AGENTS.md`
  (Product Positioning) and the `README.md` introduction; mainline
  prioritization follows cloud product value per ADR-012.
- Maintainer batch closeout: the entire 2026-08-10 to 2026-08-12 cloudline
  stack (`CLOUD-INTEGRATION-REG-01`, `CLOUD-TRN-NEXT-PLAN-01`, the three
  `QA-CLOUDLINE` quality baselines, the three `ARCH-CONFIG` boundary cards,
  `CLOUD-DEPLOY-PROFILE-CON/01`, the three `CLOUD-COMMAND` cards, the three
  `CLOUD-LIVE` cards, `CLOUD-REC-PROD-CON/PG-PITR/S3`, `CLOUD-DEPLOY-HELM-01`,
  `CLOUD-REAL-SVC-CI-01`, `CLOUD-K8S-GVISOR-E2E-01`, the `EMB-AUTH`,
  `EMB-AGUI`, `EMB-HOST-GW` and `EMB-HOST-RUNTIME` cards) was fast-forward
  merged into `zebra-cloud-trench` at `ca88aeba`, and the rebased
  `CLOUD-EFFECT-COMP-CLOSE-01` implementation merged as `bbd6108d`. All of
  these cards are recorded `Done`; per-card prose in
  `docs/AGENT_TASKS.md` is preserved as historical evidence. The preserved
  dirty-mainline handoff snapshot was kept on
  `codex/cloudline-worktree-snapshot` (removed 2026-08-17 during branch
  cleanup; superseded by mainline history). Follow-up correction
  (2026-08-17): the post-review gaps the card owner had reopened on
  `codex/cloud-effect-comp-close-01` — unknown Memory commit recovery
  (`cloud_memory_recovery`), fail-closed execution preflight
  (`execution_preflight`), receipt read validation, and the real-PostgreSQL
  compose runner under `tests/compose/cloud_effect_composition/` — were
  merged back into `zebra-cloud-trench`; `CLOUD-EFFECT-COMP-CLOSE-01` is
  `In Progress` again until its focused test acceptance criterion is
  re-verified. Verification closeout (2026-08-18): the real-PostgreSQL
  compose runner passes `19 passed` with
  `ZEBRA_CLOUD_EFFECT_COMPOSITION_TEST_RESULT=PASS` (isolated PostgreSQL +
  MinIO); one contract gap found and fixed — cross-session receipt lookups
  now raise a session-scoped `GovernedMemoryConflictError` instead of the
  generic identity-reuse message. The card is `Done`.
  Registry hygiene (2026-08-18): stale cards whose PRs merged in July
  (`CTX-SEG-01` #176, `FINOS-HAR-03` #169, `SUBAGENT-UX-01` #177,
  `WEB-UX-01` #178) and `CLOUD-WORKSPACE-CP-PLAN-01` (all seven successors
  `Done`) are closed; the registry now reflects reality with
  `EMB-TRN-READ-E2E-01` as the only open engineering item.
  `ARCH-RUNTIME-V2-PLAN-01` is `Done` (2026-08-18): the proposal's §2/§10
  were delta-aligned to the post-#194 `main` — the review confirmed the
  v2 direction was validated by implementation (Gate B–G cards all `Done`;
  every originally-missing symbol exists in code), and residual increments
  must be activated as new path-bounded cards.
  PR #194 merged 2026-08-18 (`91251fa5`): `main` again carries the full
  cloud mainline; branching returns to main-based flow.
  `EMB-TRN-READ-E2E-01` was re-attempted on the merged main and correctly
  produces the structured `BLOCKED` result (all 16 deployment inputs
  enumerated); it remains
  `In Progress` and fail-closed pending isolated cross-service inputs.
  Host cleanup follow-up (`QA-RIG-SCRATCH-VOL-01`, `Done` 2026-08-18): the
  2026-08-18 Desktop cleanup found seven leaked zebra RAM volumes — five
  `ZEBRACPE2E*` rig scratch volumes (the effect-default E2E fixture only
  detached on mount failure) plus workspace-CP probe mounts; all were
  ejected and their mount points removed, and the rig fixture now owns its
  scratch volume through a context manager that force-detaches on every exit
  path, so repeated rig runs no longer accumulate volumes on the host.
  `In Progress` and fail-closed pending isolated cross-service inputs.
- `CLOUD-EFFECT-DEFAULT-E2E-01` is `Done` with the full 10-scenario matrix
  passing on the rig: the two 2026-08-16 fault-injection scenarios verify
  that killing the Worker during the post-tool model turn recovers to a
  deterministic suspension with zero re-execution, and that rotating the
  control-plane epoch mid-execution rejects the stale terminal mutation
  while the effect reaches deterministic uncertain reconciliation. The
  completed-tool continuation recovery (`recover_approved_continuation`
  completed adjudication plus the `continue_completed_tool` harness path,
  covering executed and failed terminal outcomes) and command-consumption
  skip logging shipped with regression tests; the suspended-command-lane
  recovery follow-up is closed: the rig failure was a fixture bug (killing
  only the `uv` wrapper orphaned the worker, which suspended the session
  itself via model-call timeout); the scenario now kills the whole process
  tree and the killed session recovers through the completed-tool
  continuation to `session_completed` with zero re-execution.
  `CLOUD-WORKSPACE-CP-E2E-01` is `Done`: the automated
  `workspace_cp_provisioned_side_effect` scenario passes on the gVisor rig
  and the full runner returns `ZEBRA_EFFECT_DEFAULT_E2E=PASS` (11/11
  scenarios). The macOS APFS chmod fixture blocker is fixed by applying the
  mode change from inside the colima VM plus a guest-side write probe.
  `CLOUD-WORKSPACE-CP-PLAN-01` is registered as `Planning` for the P0.3
  Workspace Control Plane, splitting seven path-bounded successor cards
  (contract, PostgreSQL authority, provisioning provider, API command
  surface, Worker runtime wiring, GC/reconcile, default-entrypoint E2E).
  Previously `In Progress` with its execution tier
  validated on a test-only gVisor rig: the default Worker executed a real,
  policy-approved `command.run` side effect inside a gVisor sandbox through
  the durable command lane; PostgreSQL holds exactly one `succeeded` Effect
  with terminal Event and payload binding, MinIO holds both finalized
  versioned payloads, restart cycles do not duplicate the side effect, and a
  no-tool session reaches `COMPLETED` with governed Memory finalization.
  `lease_loss_uncertain_reconcile` stays skipped pending a fault-injection
  design. Composition tier (no engine) still closes green with `BLOCKED`
  (2). Recorded findings: inline execution never populates outbox
  `claim_fencing_token` (dispatch-consumer lane owns that). The
  post-approval wedge was root-caused by an instrumented rig experiment
  and fixed on 2026-08-15: `accept_persisted_event` drove guard-committed
  events through the legacy `index_event`/`upsert` path that the cloud
  Event-derived adapters forbid, aborting before projections advanced and
  leaving the event store ahead of the projection row, which made every
  terminal append conflict. The fix mirrors the recorder's transaction
  path (advance the view, index through fenced `index_worker_event`,
  save projections) and carries a regression test; the approved
  side-effect session now completes with a final model turn on the rig
  and the E2E matrix asserts it. The post-start fail-closed resume
  defense intentionally stays; genuine mid-execution Worker death
  checkpointing, the lease-loss fault-injection scenario and
  command-consumption failure logging remain on the successor card. The
  suspended-command-lane item closed on 2026-08-16: a local reproduction
  with a real hanging gateway proved that the exact durable death shape
  (completed approved tool plus a dangling model request from the killed
  Worker) already recovers through the completed-tool continuation to
  `completed` with zero re-execution — locked by a regression test — and
  the earlier `suspended` observation was rig-specific; the E2E death
  scenario now asserts completion. The worker loop additionally skips
  poisoned ready sessions with a logged reason instead of crashing the
  whole Worker on `WorkerExecutionError`. Previously: the repository now carries a fail-closed runner
  (`tests/compose/effect_default_e2e/`) that drives real PostgreSQL 17.5,
  MinIO, the committed API application object, the default Worker entrypoint
  and a provider-shaped OpenAI-compatible stub model. The composition
  scenarios (infrastructure, session acceptance, worker fail-closed with zero
  Effect side effects across repeated cycles, handoff Effect read) pass and
  are recorded in `docs/CLOUD-EFFECT-DEFAULT-E2E-01.md`. Source review and a
  host prototype proved runtime provisioning precedes the first model call,
  so the six execution-tier scenarios stay explicitly
  `gvisor_engine_absent`: the runner reports
  `ZEBRA_EFFECT_DEFAULT_E2E=BLOCKED` (exit 2) and never derives a PASS from
  composition-tier evidence. The execution tier needs a runsc-capable engine
  and its implementation slice; the local colima `zebra-gvisor` VM's runsc
  sandbox does not start under nerdctl yet.
- `CLOUD-EFFECT-COMP-CLOSE-01` is `Done` after maintainer activation and
  rebase onto the merged cloudline. It is a narrow application-composition
  gate: the default Cloud Worker now composes the typed
  `CloudWorkerComposition` (Effect dispatch, projection transaction,
  deployment namespace, cloud Artifact and Provider Continuation factories)
  instead of an unsafe `ControlPlaneStores` cast, the API handoff reads the
  narrow `EffectStateReadPort`, and cloud Memory finalization commits through
  the governed aggregate. It does not make the platform production-ready.
- `CLOUD-TRN-NEXT-PLAN-01` is in `Review` on
  `codex/cloud-trench-next-plan-01`, intentionally stacked after the regression
  fix. The inspected next-step plan is recorded in
  [Zebra Cloud 与 Trench 下一阶段执行计划 v1.0](./docs/Zebra%20Cloud与Trench下一阶段执行计划_v1.0.md).
  It makes the first product milestone the production Trench read-only vertical
  slice, but first gates it on a green cloud mainline, coherent PostgreSQL +
  gVisor production composition, stateless command-only API, durable replay plus
  Redis live tail, real-service CI, production recovery and deployment evidence.
  `EMB-HOST-RUNTIME-01` and the Trench-side `TRN-HOST-READ-AUTH-01` successor
  are now activated in isolated worktrees; no P4+, Memory runtime or Agent
  Definition runtime work is activated.
- `QA-CLOUDLINE-PY-01` is `Review` on
  `codex/qa-cloudline-py-01`. It owns the Python size/Ruff/Mypy gate after the
  Lease/API regression fix. The integrated Zebra line now passes Mypy over
  `617` source files and the full backend is `2210 passed, 275 skipped`; the
  existing concurrent PostgreSQL/Memory size and export fixes were validated
  as an isolated handoff snapshot, and the dirty `zebra-cloud-trench`
  worktree is preserved unchanged.
- `QA-CLOUDLINE-DESKTOP-01` is in `Review` on
  `codex/qa-cloudline-desktop-01`. It split the remaining Desktop stylesheet
  size violation without changing the composer CSS contract and made the
  long-stream/stop assertions event-driven. Node 22 build, all Desktop static
  checks, file-size validation, and the eight Playwright tests pass. The default
  Tauri check remains environment-blocked by the global USTC Cargo mirror;
  direct rsproxy Cargo validation passed with `--locked`. A macOS packaged
  `.app` build also passed, while packaged WebDriver execution remains a
  Linux CI concern because `tauri-driver` reports that macOS is unsupported.
- `QA-CLOUDLINE-CI-01` is in `Review` on `codex/qa-cloudline-ci-01`. It keeps
  the canonical Quality jobs intact, adds loopback proxy bypass to Desktop and
  packaged jobs, and updates the packaged driver helper to the durable
  cancellation and suspended-state contracts. The local Gate 0 matrix is
  green; the previous PR #194 failures are confirmed stale and predate the
  Lease, atomicity, stylesheet, and event-driven assertion fixes. Real OS
  sandbox smoke and the 20-cycle soak pass locally; canonical remote workflow
  evidence is still outstanding.
- `ARCH-CONFIG-BOUNDARY-01` is in `Review` on
  `codex/arch-config-boundary-01`. ADR-021 freezes the provider-neutral
  configuration boundary and the dependency contract passes: reusable packages
  cannot import `apps/*` composition roots, and the five current config imports
  are tracked as exact successor inventory for Integrations/Security.
- `ARCH-CONFIG-INTEGRATIONS-01` is in `Review` on
  `codex/arch-config-integrations-01`. Model, DeepSeek beta, SCM and credential
  builders now accept typed provider settings; `agent-integrations` no longer
  imports or depends on `zebra_agent_config`. App roots perform the mapping and
  preserve environment, retry, credential and network behavior.
- `ARCH-CONFIG-SECURITY-01` is in `Review` on
  `codex/arch-config-security-01`. Security credential policy now accepts only
  the minimal provider/token reference and has no `zebra_agent_config` import;
  redaction and provider validation remain unchanged. The package dependency
  inventory is now empty.
- `CLOUD-DEPLOY-PROFILE-CON-01` is in `Review` on
  `codex/cloud-deploy-profile-con-01`. ADR-022 and executable settings
  validation freeze the deployment/storage/runtime axes: local is lazy SQLite,
  cloud/production require PostgreSQL + gVisor + quota, and invalid mixes fail
  closed.
- `CLOUD-DEPLOY-PROFILE-01` is in `Review` on
  `codex/cloud-deploy-profile-01`. API, Worker, Storage, migration and
  application Compose now consume the validated storage/runtime axes; full
  Python validation is green, Compose config passes, and the actual image build
  is currently blocked by a Docker Hub authorization timeout.
- `CLOUD-COMMAND-API-CON-01` is in `Review` on
  `codex/cloud-command-api-con-01`. ADR-023 and the core contract freeze the
  durable command envelope, stable idempotency/revision admission and accepted
  Event payload; route/Worker execution remains reserved for its successors.
- `CLOUD-COMMAND-RUN-01` is `Review` on `codex/cloud-command-run-01`. Its owned
  slice adds the stateless API command submission seam and Worker
  run/resume/message wake-up without Runtime side effects in API. Full Python
  validation is green: `2128 passed, 271 skipped`; `make check` is green.
- `CLOUD-COMMAND-CTRL-01` is `Review` on `codex/cloud-command-ctrl-01`. Cloud
  stop/cancel/suspend/resume now use the durable command seam and Worker-side
  control service; local operator behavior remains compatible. Full validation
  is green: `2134 passed, 271 skipped`; `make check` passes.
- `CLOUD-LIVE-WIRE-CON-01` is `Review` on `codex/cloud-live-wire-con-01`. ADR-024
  and the shared post-commit publisher seam freeze durable-first ordering,
  duplicate tolerance and replay-barrier degradation before Redis composition.
  Full validation is green: `2138 passed, 271 skipped`; `make check` passes.
- `CLOUD-LIVE-PUBLISH-01` is `Review` on `codex/cloud-live-publish-01`. Cloud
  API/Worker now compose one namespace-bound Redis publisher around direct Event
  appends; SSE consumption remains next. Full validation is green:
  `2145 passed, 271 skipped`; `make check` and the real Redis runner pass.
- `CLOUD-LIVE-SSE-01` is in `Review` on `codex/cloud-live-sse-01`. HTTP SSE now
  captures a Redis replay barrier, drains durable Events, then tails Redis with
  duplicate filtering and durable polling fallback. Full validation is green:
  `2147 passed, 271 skipped`; `make check` is green.
- `CLOUD-REC-PROD-CON-01` is in `Review` on
  `codex/cloud-rec-prod-con-01`. Its recovery contract freezes PG physical/WAL,
  immutable object copies, restore epoch and identity rotation, machine-readable
  drill evidence, and the read-only → single Worker → ingress sequence. Full
  validation is green: `2147 passed, 271 skipped`; `make check` is green.
- `CLOUD-REC-PG-PITR-01` is in `Review` on
  `codex/cloud-rec-pg-pitr-01`. Its isolated physical base-backup/WAL runner
  restores to a named point, excludes a post-target Event, rebuilds Projection,
  rotates Lease epoch and records cleanup. Real runner and full validation are
  green: `2147 passed, 271 skipped`; `make check` is green. Measurements remain
  local-only (`RPO 0.077309s`, `RTO 6.462744s`).
- `CLOUD-REC-S3-01` is in `Review` on `codex/cloud-rec-s3-01`. Its independent
  versioned MinIO backup-copy/delete/restore runner verifies the PostgreSQL
  Artifact ref, checksum, metadata, namespace and cleanup without reading a
  Worker-local payload. Real runner and full validation are green:
  `2147 passed, 271 skipped`; `make check` is green. Evidence remains local-only.
- `CLOUD-DEPLOY-HELM-01` is in `Review` on
  `codex/cloud-deploy-helm-01`. Its fail-closed chart renders migration/API/
  Worker, Service, Secret refs, non-root/read-only pods, resources, PDBs and
  gVisor RuntimeClass. `helm lint/template` and static tests pass. A real
  isolated Helm install now proves migration hook ordering, API/Worker `2/2`,
  production `/health`, gVisor `/proc/version`, UID `65532`, Worker recovery,
  and cleanup; managed rollout evidence is still not claimed.
- `CLOUD-REAL-SVC-CI-01` is in `Review` on
  `codex/cloud-real-svc-ci-01`. Its canonical workflow now runs separate
  application, Redis live, PITR, S3 and fresh-restore matrix runners with
  bounded timeouts and always-retained evidence. The integrated Zebra line
  `741a471f` also re-ran application Compose after seeding a valid test-only
  Host registry; the local Docker matrix is green. `actionlint` now passes the
  canonical quality workflow after removing duplicate proxy keys, and the
  Linux container quota smoke reports real `ENOSPC`. No remote Actions or
  managed rollout is claimed.
- `CLOUD-K8S-GVISOR-E2E-01` is in `Review` on
  `codex/cloud-real-svc-ci-01`. The fail-closed Kubernetes runner and dedicated
  workflow are implemented. An isolated Linux `colima-zebra-gvisor` cluster
  now passes the full runner (`WORKER_RESTART_RESUME`, quota, NetworkPolicy and
  cleanup); this is local task evidence, not remote canonical CI or managed
  production rollout evidence.
- `EMB-TOOL-CON-01` is in `Review` on
  `codex/cloud-real-svc-ci-01`. `ToolContract`/`ToolResult` now carry Host
  execution location, scopes, risk, bounds, idempotency and typed receipt
  metadata; transport, JWT and Trench implementation remain separate tasks.
- `EMB-AUTH-CON-01` is in `Review` on
  `codex/cloud-real-svc-ci-01`. The provider-neutral Host Grant/JWT contract
  pins algorithms, issuer/JWKS, exact origins, clock skew and bindings; JWT
  decoding, HTTP and PostgreSQL replay remain separate adapters.
- `EMB-AUTH-PG-01` is in `Review` on
  `codex/cloud-real-svc-ci-01`. Migration v17, namespace-bound Host registry,
  secret-free Grant audit and atomic PostgreSQL `jti` replay now pass the real
  Compose runner (`4 passed`) and the existing control-plane migration runner
  (`11 passed`); HTTP/JWT and Trench remain out of scope.
- `EMB-AUTH-HTTP-01` is in `Review` on
  `codex/cloud-real-svc-ci-01`. Cloud/production HTTP now requires an injected
  Host Grant authorizer before route dispatch, and CORS uses normalized exact
  HTTPS origins without reflection; focused auth/HTTP (`5 passed`) and existing
  HTTP/command/live/stream (`52 passed`) matrices are green.
- `EMB-AUTH-01` is in `Review` on `codex/cloud-real-svc-ci-01`. A signed RS256
  PyJWT decoder with bounded injectable JWKS resolution now composes with the
  PostgreSQL registry/replay authorizer; the production HTTP factory wires that
  authorizer by default for the concrete cloud store bundle, while explicit
  injection remains available for tests and alternate roots. The real Host
  PostgreSQL/API matrix is `5 passed`, with no raw token in HTTP/audit evidence.
- `EMB-AGUI-CMD-01` is `Review` on `codex/cloud-real-svc-ci-01`. The bounded
  `run`/`resume`/`stop` envelope resolves `threadId` to the active durable
  Segment and calls only the existing command service; focused command tests
  pass (`5`), with no Worker execution import or construction.
- `EMB-AGUI-STREAM-01` is `Review` on `codex/cloud-real-svc-ci-01`. The AG-UI
  SSE route validates exact durable cursors, replays and live-tails the Event
  Store, and emits official projected events with a lossless polling fallback.
  Replay/reconnect/live-tail tests pass in the combined matrix.
- `EMB-AGUI-API-01` is `Review` on `codex/cloud-real-svc-ci-01`. Command-only
  API composition, durable AG-UI replay/live tail and existing Host Grant HTTP
  gating pass together; it remains a parent review gate until this branch is
  merged and mainline gates are repeated.
- `EMB-HOST-GW-01` is `Review` on `codex/cloud-real-svc-ci-01`. The typed Host
  gateway verifies manifest digest and workload identity, intersects scopes,
  validates resource/idempotency/SSRF boundaries and returns bounded receipts;
  focused tests pass (`7`) and the Integrations package is `143 passed,
  3 skipped`.
- `EMB-TRN-READ-E2E-01` is `In Progress` on `codex/emb-trn-read-e2e-01`.
  Zebra now owns a fail-closed real-service runner for Trench/BFF/Zebra
  read-only acceptance, with nine named scenarios, secret-free evidence and a
  business-table snapshot invariant. Its contract tests pass (`4`), Ruff and
  targeted Mypy pass; the integrated Trench branch passes the focused backend
  (`66` API, `49` cleaning), migration SQL, frontend build/test/lint, and the
  Zebra branch passes the full quality gate (`2209 passed, 275 skipped`). The
  five local Cloudline runners (application, Redis fan-out, PITR, S3 recovery,
  and fresh restore) are green. The real cross-service run is still `BLOCKED`
  because this machine has no isolated Trench/Zebra HTTP, PG, Redis,
  object-store, Grant exchange or Worker-restart inputs; no cross-service pass
  is claimed. The previously recorded Worker composition seam is now closed by
  the active `EMB-HOST-RUNTIME-01` successor: `build_worker_tool_gateway`
  discovers the Host manifest, exposes its typed tools and routes Host calls
  without local fallback. The Trench-side `TRN-HOST-READ-AUTH-01` successor
  verifies the signed workload binding and preserves read-only scope/resource
  filtering. Both successors are in review on the integrated branches; the
  real cross-service runner remains fail-closed until isolated services and
  credentials are provisioned.
- `EMB-HOST-RUNTIME-01` is in `Review` on `codex/emb-host-runtime-01`. Zebra
  now carries an optional, expiry-aware HostContext from authorized API request
  through TASK_PREPARED persistence and Worker recovery; Worker discovery is
  manifest-first and fail-closed, and Host read tools are routed through the
  typed Host gateway with resource/idempotency binding. Full `make test` passes
  (`2207 passed, 275 skipped`), and `make check` plus the focused API/Core/
  Worker/Integrations/Effect Guard matrix pass. The branch does not claim
  deployment or a real Trench call.
- Gate 3 combined API/Integrations matrix is `204 passed, 3 skipped`; no Trench
  business Tool or Kubernetes gVisor E2E completion is claimed.
- `CLOUD-INTEGRATION-REG-01` is in `Review` on
  `codex/cloud-integration-regressions-01`. It fixes two regressions found on
  `zebra-cloud-trench`: Worker heartbeat now starts from the recovery-renewed
  Lease checkpoint, and local/test API Store composition is lazy again while
  explicit cloud startup remains fail closed. The focused matrix passes `33
  passed, 1 skipped`; the full backend suite is `2104 passed, 271 skipped, 1
  failed`, with only four out-of-scope repository size violations remaining.
- Cloud mainline status is recorded in
  [Zebra Cloud 主线当前状态与后续工作](./docs/Zebra%20Cloud%20主线当前状态与后续工作.md):
  PostgreSQL adapters, API/Worker PostgreSQL composition, application Compose,
  isolated Redis live fan-out and local migration/recovery evidence are complete;
  production recovery and the CopilotKit/Trench production slice remain gated.
  `CLOUD-CONTROL-PLANE-PG-01`
  implementation and focused validation are complete on the isolated branch;
  sidebar closeout is approved and the task is recorded as `Done`; its API/Worker
  mapping remains a later gate. `CLOUD-DELIVERY-TXN-PG-01` is also merged to the
  cloud mainline at `9ec52b16` and recorded as `Done`; its API/Worker wiring,
  runtime selection and external execution remain out of scope.
- Sidebar review of the requested API/Worker PostgreSQL switch returned
  `ACTIVATE-BLOCKED`: the defect is confirmed, but implementation is not authorized
  while the explicit profile contract and dependency registry are incomplete.
  The follow-up contract review returned `CONTRACT-ACCEPTED` and closed
  `CLOUD-PROFILE-COMPOSITION-CON-01` as `Done`; its `CLOUD-LIVE-01` dependency was
  removed because the contract has no live-runtime scope. `CLOUD-API-WORKER-PG-01`
  and `CLOUD-COMPOSE-APP-01` are now `Done` on the cloud mainline. Local SQLite
  remains the default and cloud must fail closed rather than fall back to SQLite.
- `CLOUD-API-WORKER-PG-01` completed its authorized implementation slice and is
  now `Done` after independent Review and fast-forward merge of `d9fd0419` into
  `zebra-cloud-trench`. Focused API/HTTP/Worker and real PostgreSQL Compose
  evidence is green. It owns only shared profile selection,
  PostgreSQL stores injection and the model/tool projection compatibility seam;
  it does not activate application Compose, Redis live, `CLOUD-LIVE-01`, or any
  aggregate gate.
- Context fencing conformance child `CLOUD-AGG-FENCE-CTX-LIFECYCLE-CON-01` is
  now `Done` on its governance worktree. Its Store-level semantic gap was closed
  by `CLOUD-AGG-FENCE-CTX-SEMANTIC-01`, which is also `Done` after sidebar
  `CLOSEOUT-OK`, three zero-write regressions and a real PostgreSQL `18/18`
  focused matrix. The parent `CLOUD-AGG-FENCE-01` is now `Done` as a governance
  gate; the Model/Tool revision successor is now closed as `Done`.
- `CLOUD-AGG-FENCE-HANDOFF-DISPATCH-CON-01` is now `Done` with audit result
  `PASS`; its reserve/abort successor is `Done`, and the dispatch successor
  `CLOUD-AGG-FENCE-DISPATCH-01` is fast-forward merged and closed as `Done`.
  The mainline PostgreSQL runners pass `15/15` and `14/14` with
  `ZEBRA_HANDOFF_AUTH_POSTGRES_TEST_RESULT=PASS` and
  `ZEBRA_HANDOFF_DISPATCH_POSTGRES_TEST_RESULT=PASS`.
- `CLOUD-LIVE-01` is `Done` after completing and fast-forward merging the
  separately owned Redis live event fan-out slice at `cfbebcf7`. It remains
  limited to a provider-neutral Port, a
  bounded Redis Streams adapter and isolated evidence; the local Core/adapter
  matrix is `24/24` (including the non-blocking read and namespace validation
  regressions), the full integrations package is `127 passed, 3 skipped`,
  and the pinned `redis:8.2.1-alpine` host runner passes `1/1` with
  `ZEBRA_LIVE_FANOUT_REDIS_TEST_RESULT=PASS`. The detailed matrix is recorded
  in `docs/CLOUD-LIVE-01.md`. It does not authorize API/Worker startup wiring,
  application Compose, Runtime selection or any Redis authority.
- `CLOUD-COMPOSE-APP-01` is now `Done` on
  `codex/cloud-compose-app-01`. It owns only the non-root multi-target Zebra
  image, the application-only migration/API/Worker Compose overlay and isolated
  smoke evidence; host-side cloud composition already proves API health,
  `PostgresControlPlaneStores` and one Worker PostgreSQL cycle. The production
  `--no-dev` image now declares `uvicorn` as an API runtime dependency, and the
  complete three-container smoke passes with a temporary mirror-only Python
  base override (runtime UID `65532`) and now through the Application Compose
  default mirror with `ZEBRA_APPLICATION_COMPOSE_TEST_RESULT=PASS`. The
  Dockerfile keeps the official Docker Hub digest as its standalone default;
  that direct build remains an external review gap. The base dependency Compose
  remains a separate lifecycle.
- `CLOUD-AGG-FENCE-01` is now `Done` as a governance gate after the aggregate
  review's `PASS` evidence and maintainer continuation closeout. This unlocks
  only the recovery evidence sequence; Runtime/API/Worker selection and
  production rollout remain separate gates.
- `CLOUD-REC-01` is now `Done` as the local recovery evidence gate:
  `CLOUD-PG-MIG-01`, `CLOUD-REC-BACKUP-01`, `CLOUD-REC-RESTORE-01` and
  `CLOUD-REC-DRILL-01` are all independently validated and merged. The local
  drill proves rollback, fenced claim/reconcile races and zero-loss Event
  counts; no production RPO/RTO, PITR or DR claim is made from Compose.
- `CLOUD-PG-MIG-01` is now `Done` on `codex/cloud-pg-mig-01`. The completed
  slice provides canonical read-only SQLite snapshots, migration v16 cutover
  fencing, restricted Event-first import, Session/Workspace/Task rebuild,
  Event-derived Model/Tool projection replay, Context capsule/pointer
  verification, and fenced Handoff operation/envelope/dispatch replay with
  rebuilt-lineage checks, plus namespace-scoped idempotency and governed Memory
  replay, and rowid-evidenced Delivery Audit replay through snapshot v2. The
  PostgreSQL 17.5 runner passes `29/29` with
  `ZEBRA_PG_MIGRATION_TEST_RESULT=PASS` and deterministic cleanup. New
  zero-write regressions reject legacy Artifact, Effect and Provider
  continuation tables before Event writes; their cloud authority mappings are
  closed as explicit quarantine contracts and runtime ACTIVE write wiring remains
  gated. The PostgreSQL 17.5 runner passes `29/29` with
  `ZEBRA_PG_MIGRATION_TEST_RESULT=PASS` and deterministic cleanup.
- `CLOUD-PG-MIG-LEGACY-CON-01` is now `Done` as the governance parent after all
  three path-bounded children were explicitly activated, independently
  validated and merged.
  `CLOUD-PG-MIG-LEGACY-ARTIFACT-01` is now `Done` after merge commit `bed02e4a`
  from `codex/cloud-pg-mig-legacy-artifact-01`. Its deterministic
  Artifact legacy quarantine/export contract and evidence runner pass the local
  focused matrix (`4 passed, 1 skipped`) and PostgreSQL 17.5 runner (`5 passed`,
  `ZEBRA_PG_MIG_LEGACY_ARTIFACT_TEST_RESULT=PASS`) with cleanup.
  `CLOUD-PG-MIG-LEGACY-EFFECT-DELIVERY-01` is now `Done` after merge commit
  `62d2e601` from `codex/cloud-pg-mig-legacy-effect-delivery-01`. Its
  deterministic Effect/Delivery quarantine/export contract and evidence runner
  pass the local focused matrix (`4 passed, 1 skipped`) and PostgreSQL 17.5
  runner (`5 passed`,
  `ZEBRA_PG_MIG_LEGACY_EFFECT_DELIVERY_TEST_RESULT=PASS`) with cleanup.
  `CLOUD-PG-MIG-LEGACY-PROVIDER-01` is now `Done` after merge commit
  `5f275d4b` from `codex/cloud-pg-mig-legacy-provider-01`. Its deterministic
  Provider Continuation quarantine/export contract and evidence runner pass the
  local focused matrix (`4 passed, 1 skipped`) and PostgreSQL 17.5 runner
  (`5 passed`, `ZEBRA_PG_MIG_LEGACY_PROVIDER_TEST_RESULT=PASS`) with cleanup.
  No cloud Artifact/Effect/Provider authority write or runtime wiring is implied.
- The current cloud governance slice
  `CLOUD-AGG-FENCE-WORKSPACE-TASK-CON-01` is now `Done` with audit result `PASS`.
  Its direct Task authority gap is implemented by `CLOUD-AGG-FENCE-TASK-01` at
  `6a31929a`; the focused Task PostgreSQL regression passes `23/23` and
  Handoff/dispatch regression passes `24/24`. The repository-owned
  `CLOUD-AGG-FENCE-WORKSPACE-TASK-EVIDENCE-01` runner is also `Done` at
  `49a8c026`, passing `36/36` on PostgreSQL `17.5-alpine3.21` with deterministic
  cleanup. The parent `CLOUD-AGG-FENCE-01` is now `Done` and no Runtime or
  application Compose activation is implied.
- `CLOUD-AGG-FENCE-MODEL-TOOL-01` is `Done` at implementation commit
  `31347989`. The PostgreSQL adapter now binds a Worker Model/Tool projection
  Event to `expected_stream_revision` and the current stream; its dedicated
  runner passes `8/8` with `ZEBRA_MODEL_TOOL_POSTGRES_TEST_RESULT=PASS`, while
  the existing Control Plane runner passes `11/11`. Both runners clean their
  resources. The parent gate is now `Done` and no runtime activation is
  implied.
- `CLOUD-AGG-FENCE-PROVIDER-01` is `Done` at implementation commit
  `816a1ae0`. `delete_for_worker` now binds the current LeaseFence and
  `expected_stream_revision` to the locked Session stream before soft-delete;
  its reproducible PostgreSQL 17.5 runner passes `4/4` with
  `ZEBRA_PROVIDER_CONTINUATION_POSTGRES_TEST_RESULT=PASS` and cleans all
  resources. The parent `CLOUD-AGG-FENCE-01` is now `Done`.
- `CLOUD-AGG-FENCE-ARTIFACT-01` is `Done` as an evidence-only conformance
  slice. The repository-owned PostgreSQL 17.5 runner passes `13/13` with
  `ZEBRA_ARTIFACT_PAYLOAD_POSTGRES_TEST_RESULT=PASS` and cleans all resources;
  the existing v9 transitions already use the shared namespace, LeaseFence,
  stream CAS and lifecycle revision guards. No adapter or migration changed;
  the parent gate is now `Done`.
- `CLOUD-AGG-FENCE-EFFECT-PAYLOAD-01` is `Done` as an evidence-only
  conformance slice. Its repository-owned PostgreSQL 17.5 runner passes `7/7`
  with `ZEBRA_EFFECT_PAYLOAD_POSTGRES_TEST_RESULT=PASS` and cleans all
  resources; existing payload-aware Effect transitions bind Worker authority
  and atomically coordinate Event, Artifact and outbox state. No adapter or
  migration changed; the parent gate is now `Done`.
- `CLOUD-AGG-FENCE-DELIVERY-01` is `Done` as Delivery boundary evidence.
  Delivery is intentionally an API command claim/receipt lane, not a Worker
  Lease aggregate; its corrected PostgreSQL 17.5 runner passes `12/12` with
  `ZEBRA_DELIVERY_TRANSACTION_POSTGRES_TEST_RESULT=PASS` and cleans all
  resources. No adapter or runtime wiring changed; the parent gate is now
  `Done`.
- `CLOUD-AGG-FENCE-REVIEW-01` is `Done` with result `PASS`. All registered
  path-bounded aggregate evidence is green: Context `18/18`, Handoff
  auth/dispatch `15/15` and `14/14`, Workspace/Task `36/36`, Model/Tool `8/8`,
  Provider `4/4`, Artifact `13/13`, Effect/Artifact `7/7` and Delivery `12/12`.
  The parent `CLOUD-AGG-FENCE-01` is now `Done` after maintainer continuation
  closeout; this does not authorize runtime or application Compose activation.
- `CLOUD-PROVIDER-CONT-PG-PLAN-01` is formally `Done` after sidebar
  architecture review. `CLOUD-PROVIDER-CONT-PG-01` is now `Done` on the isolated
  `codex/cloud-provider-cont-pg-01` worktree, based on `f6c8a926`, with its Core
  contract, PostgreSQL v13 adapter/migration, cloud Worker aggregate seam,
  focused tests, Compose evidence and review fixes committed as `39bbe444` and
  `abd7a7f0`. The sidebar closeout accepted the evidence, and the next storage
  composition card `CLOUD-CONTROL-PLANE-PG-01` is now `Done` after sidebar
  closeout on its isolated implementation branch. Runtime,
  API/Provider HTTP, Desktop, local SQLite, Redis, Mem0 and application Docker
  remain excluded.
- Review task: `CTX-MEM-01` is in PR `#198` and closes the valid parts of GitHub issue `#197` with
  an exact three-user-turn tail, complete tool groups, one strict retry from
  original history, recoverable context suspension, evidence-gated memory
  promotion, and repo-scoped SQLite FTS recall under a token budget. Local
  validation: `63` focused tests, changed-file Ruff, Mypy over `158` source
  files, and release eval `10/10` pass. Full suite: `1747 passed, 8 skipped`;
  the same nine failures reproduce on untouched `main`. The current file-size
  gate is blocked by four inherited violations outside this task. PR CI run
  `30332213200` did not execute any step because GitHub reported an account
  payment/spending-limit gate.
- Verified implementation baseline: `f1e4965` (PR `#174`)
- Product posture: `embeddable Agent Runtime / feature-complete local Beta / single-host Phase A complete`
- Review task: `CTX-SEG-01` has delivered the stable Task, internal Segment,
  unified stream/routing, automatic safe rollover, and SQLite migration slice.
- Active repair task: `CTX-SEG-02` preserves the latest bounded conversation
  checkpoint across terminal follow-up Segments, removes implicit low call
  ceilings, and converts explicit hard-budget exhaustion into recoverable pause.
- Review task: `SUBAGENT-UX-01` makes Subagent use a model-native tool decision;
  simple work remains in the parent and every valid delegation records its reason.
- Active architecture task: ADR-013 replaces user-visible child Sessions with a
  stable Task boundary and backend-internal execution Segments.
- Desktop browser task: `QA-DESKTOP-E2E-01` is Done via PR `#161`
- Runtime blueprint: `ARCH-RT-BP-01` is complete on its local task branch
- Completed Embedded architecture task: `EMB-PLAN-01` on `zebra-cloud-trench`
  replaces the conflicting draft with one CopilotKit/AG-UI target, ADR-015, and
  a dependency-ordered task roadmap. Formal review closed it as `Done`; it is
  documentation-only and does not activate Phase B or any Trench implementation
  card.
- Compatibility task `EMB-AGUI-SPIKE-01` is formally `Done` on the test-only
  closeout branch. It pins `ag-ui-protocol==0.1.19`, validates the canonical SSE,
  interrupt/resume and forward-compatibility boundaries with `11/11` focused
  tests, and adds no production API/Worker, CopilotKit, React SDK or UI wiring.
- Trench `TRN-CPK-SPIKE-01` is merged to Trench `main` at `5c59b22`; its
  focused/full checks, frontend builds, Alembic checks and `git diff --check`
  pass. `EMB-HOST-CON-01` is `Done` on `codex/emb-host-con-01` at
  `ca59753b`: provider-neutral Core Host authority claims, context derivation,
  bounded limits and fail-closed validation pass `16/16` focused and `386/386`
  `agent_core` tests. JWT/JWKS, API/AG-UI, Trench and runtime wiring remain
  separately gated.
- `EMB-AGUI-CON-01` is `Done` on `codex/emb-agui-con-01` at `5485fc2e` after
  Host authority closeout. Its pure, replayable AG-UI projection passes `5/5`
  focused and `132 passed, 3 skipped` package tests; API/Worker routes, Redis
  live fan-out, Trench/CopilotKit runtime and Host transport remain separately
  gated.
- Completed storage composition task: `CLOUD-STO-SEAM-01` on `codex/cloud-sto-seam-01` is the
  first Zebra-foundation task after the maintainer reprioritized durable storage
  and memory ahead of further Trench work. It injects existing control-plane Store
  Ports while preserving the local SQLite profile and adds no cloud dependency.
  Formal review closed it as `Done`; PostgreSQL, Redis, S3 and backend selection
  remain separate gates.
- Completed authoritative storage task: `CLOUD-STO-AUTH-01` on
  `codex/cloud-sto-auth-01` extends that same flat bundle across every durable
  API/Worker collaborator that advances Session state, gates effects or governs
  memory. A/B regressions prove the legacy path is not created; no cloud backend,
  migration or Mem0 integration is selected by this task. Formal review closed
  it as `Done`; Compose, PostgreSQL and Memory Gateway remain separate gates.
- Memory contract task `MEM-GW-CON-01` is formally `Done` on `codex/mem-gw-con-01`; it defines
  provider-neutral confirmed-memory publish, search and delete outcomes. Remote
  hits contain only a Zebra `MemoryId` for mandatory Store revalidation; no Mem0
  adapter, credential, Docker or runtime wiring is part of this slice.
- Completed dependency-container task: `CLOUD-COMPOSE-INFRA-01` on
  `codex/cloud-compose-infra-01` creates the base Docker Compose dependency stack
  and a separate optional Mem0 boot-smoke overlay. Its pinned image, migrations,
  health and anonymous-request rejection are verified locally. Mem0 remains
  derived and replaceable; Zebra application containers stay locked until real
  cloud adapters exist. Formal review closed the dependency baseline as `Done`;
  no Docker-socket operation or runtime selection was made here.
- PostgreSQL Event/Projection storage: `CLOUD-PG-01` is formally `Done` with
  isolated adapters, migration checksums, CAS/idempotency, namespace isolation
  and replay-safe projections. Recorded real PostgreSQL evidence is accepted;
  it is not runtime-selected. `CLOUD-LEASE-PG-01` separately covers
  epoch-scoped, database-clock Lease fencing.
- Lease/fencing contract plan: `CLOUD-LEASE-PLAN-01` is formally `Done`; it
  freezes epoch ownership, database-time TTL, fenced aggregate boundaries and
  uncertain external-effect recovery, while its implementation children retain
  independent gates and no runtime selection.
- Memory storage implementation: `MEM-GW-PG-NATIVE-01` is formally `Done` as a
  PostgreSQL-native, storage-only Memory Gateway with migration v12 and accepted
  isolated evidence. The native admission is `PASS`; Mem0 remains
  denied/deferred and all Runtime/Worker/provider paths stay locked.
- Effect Outbox task in Review: `CLOUD-EFFECT-OUTBOX-01` now has typed Core
  dispatch states and a PostgreSQL aggregate for fenced schedule, `SKIP LOCKED`
  claim, terminal commit, uncertain reconciliation and explicit retry. Its isolated
  Docker Compose PostgreSQL 17.5 matrix passes `49/49`, including fault rollback,
  concurrency, restore epoch, namespace and response-loss cases. It is not runtime-
  selected; Worker integration and any cloud-readiness claim remain locked.
- Integrated Effect consumer task: `CLOUD-EFFECT-CONSUMER-01` runs Lease heartbeat
  on a background thread before recovery, checks ownership at Event and external
  Effect boundaries, and releases through one fenced lifecycle exit. Explicitly
  injected cloud runtimes can now schedule, claim and terminalize durable Effect
  intents; expired claims become `uncertain` for reconciliation and never auto-
  replay. The local SQLite profile still uses its existing ledger, and no backend
  selector or production cutover is included. Its isolated Docker Compose
  PostgreSQL 17.5 consumer matrix passes `58/58`, including heartbeat, stale-fence,
  crash, response-loss and reconciliation cases; dedicated containers, volumes and
  network were removed after the run. Deterministic and full-suite gates retain
  only the confirmed inherited failures.
- Local microservice integration: the reviewed Lease contract, PostgreSQL Lease,
  Effect Outbox and Worker consumer cards are fast-forwarded onto the isolated
  `zebra-cloud-trench@2759345c`. `CLOUD-LEASE-01` is formally `Done` with its
  combined evidence record; it does not select PostgreSQL at runtime or claim
  full aggregate fencing, production cutover or exactly-once external execution.
- Completed aggregate-fencing inventory: `CLOUD-AGG-FENCE-PLAN-01` traces the
  authoritative Context, Handoff, Workspace/Task, Model/Tool, provider-history,
  Artifact and delivery-audit paths and splits them into dependency-ordered cards.
  It keeps Event-derived/read-only models out of the authority layer and API
  commands outside Worker Lease fencing. It is documentation-only and unlocks only
  `CLOUD-AGG-FENCE-CON-01`; the parent gate and adapter cards remain Locked.
- Context fencing conformance is now explicitly split into a governance audit and
  a minimal semantic successor. The audit matrix covers Worker compaction,
  administrative recovery, v7 constraints, fail-closed legacy methods and
  read-only Context Materialization. It records accepted stale-fence, namespace,
  pointer and rollback evidence, but keeps the audit card open until the semantic
  successor's review closes the former Event type and capsule binding gap. The
  successor adds only Store validation, focused tests and a PostgreSQL Compose
  runner; no migration or runtime composition is changed.
- Completed authority-contract task: `CLOUD-AGG-FENCE-CON-01` adds strict
  `WorkerMutationAuthority` and `AdministrativeMutationCAS` types. It reuses the
  existing LeaseFence, permits the empty-stream revision `-1`, rejects noncanonical
  namespaces and keeps aggregate-specific revisions out of the shared type. Its
  focused `19/19`, Core `270/270`, Ruff, strict Mypy and Eval `10/10` gates pass;
  it does not implement PostgreSQL, change Store selection or touch Desktop. Its
  local acceptance unlocks only `CLOUD-AGG-WORKSPACE-PG-01`.
- Added the sole current cloud `Ready` card, `CLOUD-SCOPE-CON-01`, to freeze the
  external opaque `(authority_issuer, namespace_id)` plus bounded
  `allowed_session_ids` read scope. The contract deliberately maps to the
  injected deployment namespace in trusted composition and adds no Tenant model,
  SQL, Runtime selection, Provider HTTP, Desktop, Redis or Mem0 behavior. Its
  successors are the still-locked Provider Continuation and Session History
  adapters.
- `CLOUD-SCOPE-CON-01` is now `Done`: `OpaqueAuthorityScope` is immutable,
  rejects malformed or over-broad allow-lists, preserves the full-scope versus
  deny-all distinction, and leaves external-to-deployment namespace mapping to
  trusted composition. Focused Core `9/9`, full Core `347/347`, relevant
  regressions `32/32` and Eval `10/10` pass; only the two inherited file-size
  violations keep `make check` red. Provider Continuation and Session History
  remain independently locked pending explicit adapter activation.
- `CLOUD-SESSION-HISTORY-PG-01` is now `Done`. It adds only a namespace-scoped
  PostgreSQL read adapter, JSONB row decoding, parity/isolation tests and an
  isolated Compose runner. Local focused validation is `13 passed, 3 skipped`,
  host PostgreSQL Compose validation is `3 passed` with
  `ZEBRA_SESSION_HISTORY_POSTGRES_TEST_RESULT=PASS`, changed static checks and
  Eval `10/10` pass. Provider Continuation, complete Store composition, Runtime
  selection and external Host verification remain out of scope.
- `CLOUD-CONTEXT-CON-01` is now `Done`. ADR-020 and the Core-only
  `ContextMaterializationPort` freeze a read-only, rebuildable generation across
  Session History, the active Context Capsule and confirmed governed Memory.
  Focused contract coverage is `3/3`, related scope/Capsule coverage is `16/16`,
  full Core is `350/350`, changed static checks and Eval `10/10` pass. The
  `CLOUD-CONTEXT-PG-01` is now `Done`: its read-only PostgreSQL adapter and
  isolated Compose runner are implemented, with local Storage `149 passed, 172
  skipped`, Core `350/350`, Eval `10/10`, and host Compose `4 passed` with
  `ZEBRA_CONTEXT_MATERIALIZATION_POSTGRES_TEST_RESULT=PASS`. No Runtime,
  Worker, API, Desktop, SQLite, Redis or Mem0 path is unlocked.
- Completed and formally closed Workspace adapter task: `CLOUD-AGG-WORKSPACE-PG-01`
  adds the additive
  PostgreSQL v4 projection schema and an injected Worker transaction that validates
  current Lease authority and Event-derived Session/Workspace content before
  committing all three primary records atomically. Replay remains monotonic and
  namespace-scoped; Model Call/Tool Run indexes remain replayable follow-up views.
  Lost-response retries now adopt the canonical stored Event and projections
  rather than the regenerated request envelope. Focused Ruff, Core/Storage strict
  Mypy, microservice file-size over `907` tracked and new files, `467 passed, 64
  skipped` backend regressions and Eval `10/10` pass. The final host PostgreSQL
  17.5 matrix passes `80/80`, including stale authority, rollback, semantic
  derivation and canonical lost-response retry paths. Formal review of the
  integrated implementation and its sole `Done` dependency closed the card as
  `Done`; it unlocks only `CLOUD-AGG-TASK-PG-01`. `CLOUD-CONTROL-PLANE-PG-01`,
  not this card, owns the cloud Worker composition root and runtime backend
  selection.
- Completed and formally closed Task/Segment adapter task:
  `CLOUD-AGG-TASK-PG-01` adds PostgreSQL v5,
  a namespace-scoped Task read model, deterministic explicit rebuild and a
  connection-scoped rollover primitive. Reads never write; rebuild and rollover
  share a Task advisory lock, Handoff Event pairs are validated by common identity,
  and composite foreign keys prevent cross-Task ownership. Ruff, strict Mypy over
  `166` files, the `911`-file microservice size gate, `473 passed, 77 skipped`
  related regressions and Eval `10/10` pass. The real PostgreSQL 17.5 matrix passes
  `32/32`; formal review of the integrated implementation and its `Done` authority
  dependency closed the card as `Done` and unlocks only
  `CLOUD-MODEL-TOOL-PG-01` for the next serialized migration. Context and Handoff
  continue planning in separate sidebar tasks without writing the migration hotspot.
- Completed and formally closed Model/Tool projection task:
  `CLOUD-MODEL-TOOL-PG-01` adds replayable PostgreSQL v6 Event-derived
  projections. Its focused Worker tests pass `7/7` and its isolated PostgreSQL
  migration/projection matrix passes `7/7`; the card is `Done` after dependency
  and path review. `CLOUD-AGG-CTX-PG-01` is now also formally closed as `Done`
  after its recorded isolated PostgreSQL `14/14` and SQLite/Worker `11/11`
  evidence; Context administrative recovery remains a separate Review card and
  neither selects the cloud runtime.
- Completed and formally closed Artifact contract task: `CLOUD-ART-OBJ-CON-01` freezes provider-neutral Artifact
  object/metadata authority before any SDK or adapter. ADR-017 separates stable
  `artifact://` identity from temporary access URLs and opaque external references,
  freezes staged/finalize/compensate recovery plus fenced Worker and management
  authority, and leaves provider, key encoding, API delivery and runtime selection
  unchosen. It unlocks planning for `CLOUD-ART-PAYLOAD-PG-01`; Artifact lifecycle,
  object and payload adapters remain separately gated. `CLOUD-AGG-HANDOFF-CON-01`
  is now formally closed as `Done`: it adds a tokenized Lease-fenced SQLite
  dispatch receipt before the PostgreSQL Handoff aggregate, with `290` recorded
  related tests and a current-HEAD focused `22/22` regression check. SQLite work
  stops at this compatibility contract. `CLOUD-AGG-HANDOFF-PG-01` remains the
  next v8 migration Review gate, while Artifact payload implementation remains
  locked.
- Completed and formally closed Context follow-up: `CLOUD-AGG-CTX-ADMIN-PG-01` reuses the v7
  administrative CAS only for historical capsule recovery in an explicitly injected
  PostgreSQL store. API recovery consumes the canonical Event/Session/Workspace result
  without a second projection write; the transaction rejects missing or changed
  projections and updates the active pointer with recovery Event time. Its isolated
  PostgreSQL 17.5 matrix passes `19/19`. It does not add PostgreSQL manual compact,
  Desktop behavior or runtime backend selection. Formal dependency/path review
  closed the card as `Done`; the dedicated PostgreSQL recovery adapter and matrix
  test are now explicitly recorded in its Owned paths.
- Completed and formally closed Handoff v8 aggregate slice preserves the exact v1-v7 migration names and
  checksums while splitting migration types, execution and the v8 catalog into focused
  files. The real PostgreSQL 17.5 migration matrix passes `6/6`; v8 adds only
  namespace-scoped operation, database-guarded immutable envelope and fenced dispatch
  tables, reusing
  the v5 Task/Segment index instead of creating a second lineage authority. A canonical
  request digest binds reserve, fresh commit and lost-response replay; the atomic
  transaction covers parent/child Events, projections, Task rollover, Envelope,
  dispatch and operation state. Child Workspace state remains fully Event-rebuildable.
  Dispatch uses database-time expiry, `FOR UPDATE SKIP LOCKED`, rotated tokens and exact
  full-fence ACK; Worker recovery now threads the acquired fence and cloud drift writes
  use the existing fenced projection transaction. The isolated PostgreSQL aggregate
  matrix passes `20/20`; Core/Storage/API/Worker pass `822/822` with `102` skips.
  Formal dependency/path review closed `CLOUD-AGG-HANDOFF-PG-01` as `Done`; no
  runtime, provider, Desktop or application Compose selection was made.
- Artifact v9 preflight confirmed that the local `ArtifactPayloadStorePort` lacks
  namespace/fence/staged lifecycle semantics. The v9 card requires the reviewed
  fenced cloud lifecycle Port and reserve -> object verification -> Event ->
  finalize/compensate ordering; its object boundary is direct botocore with MinIO
  bucket versioning and exact object-version evidence. It explicitly excludes SQLite,
  Desktop, runtime selection, Effect linkage and API read composition.
- Completed and formally closed Artifact v9 review slice starts from integrated Handoff v8 at
  `cfe40713`. `CLOUD-ART-PAYLOAD-PG-01` owns the PostgreSQL lifecycle metadata,
  provider-neutral object orchestration, Worker Event binding and isolated
  PostgreSQL/MinIO fault matrix; it does not select a runtime backend or add Desktop.
  The v9 migration foundation now adds one authoritative lifecycle metadata table,
  non-authoritative mutation/audit ledgers, exact Event/stream/fence bindings and
  reconcile/retention indexes. Core supplies one canonical reservation digest, while
  `(namespace, artifact_id)` remains the logical object locator and only the S3 adapter
  derives its private key. The PostgreSQL adapter now implements the complete fenced
  Worker lifecycle, canonical Event JSON binding, DB-owned transition timestamps,
  safe compensation, audited management recovery and Session-scoped reconcile reads.
  Isolated PostgreSQL 17.5 migration/lifecycle tests pass `19/19`. Worker orchestration
  now uses a default-off injection seam with strict reserve -> versioned put/head ->
  receipt -> Event -> finalize ordering. Managed URI spoofing fails closed, external
  references remain opaque, and uncertain outcomes remain staged for management
  reconcile. The real
  PostgreSQL+MinIO matrix passes `30/30`, including lost put/Event acknowledgements,
  sequence drift, finalize failure and concurrent retention prune. Worker/Runtime
  pass `260/260` with `16` environment-gated skips; Storage passes `131/131` with
  `114` environment-gated skips. Formal dependency/path review closed
  `CLOUD-ART-PAYLOAD-PG-01` as `Done`; Effect linkage, read composition and
  Runtime/provider selection remain separate gates.
- Completed and formally closed Effect/Artifact review slice `CLOUD-EFFECT-PAYLOAD-ATOMIC-01` starts from
  `zebra-cloud-trench@b87760b6`. Its dependencies are integrated; it owns the narrow
  transaction that binds the verified Effect request Artifact to the intent Event and
  Effect outbox row. Stable request identity, finalized-only cross-Worker reads and
  terminal result Artifact binding are implemented without migration v10. Real
  PostgreSQL+MinIO tests pass `53/53`; Tools/Worker/Runtime pass `418/418` and Storage
  passes `131/131`. Formal dependency/path review closed it as `Done`; it excludes
  SQLite, Desktop, runtime selection and delivery APIs.
- Completed and formally closed Artifact read-composition review slice `CLOUD-ART-READ-COMP-01` starts from
  `zebra-cloud-trench@4480ca66` after both PostgreSQL Model/Tool v6 and Artifact
  payload v9 dependencies were integrated. It adds one-snapshot namespace-scoped
  reads over those existing facts and injects a separate required payload-read
  capability through the current API store boundary. Canonical URI, exact Event
  binding, finalized lifecycle, recorded object version and verified bytes are all
  required; cloud composition disables legacy prune. The real PostgreSQL+MinIO matrix
  passes `39/39`, full tests pass `1943` with `145` gated skips, and no Artifact table
  or migration, SQLite feature, Desktop path or runtime backend selector was added.
  Formal dependency/path review closed it as `Done`; delivery APIs and complete
  Control Plane remain separate gates.
- Completed governed-memory planning slice `CLOUD-MEMORY-PG-PLAN-01` starts from
  `zebra-cloud-trench@f9568e34`. Audit confirmed the cloud branch still has only a
  SQLite `MemoryStorePort`; Mem0 is correctly derived but its future delivery ledger
  would otherwise depend on a local fact source. This docs-only card is formally
  `Done` and freezes the
  PostgreSQL Memory authority and atomic review boundary before migration or delivery
  implementation. The reviewed plan assigns v10 to governed facts/operation receipts,
  then v11 to Mem0 delivery; final review found no open P0/P1. Session History remains
  Locked on trusted Host scope.
- Completed governed-memory Core slice `CLOUD-MEMORY-CON-01` is formally `Done` and starts from integrated
  plan `2c43af0f`. It adds provider-neutral revision/CAS, content-free operation
  receipts and tombstones, plus pure candidate/promotion/review planning while
  preserving local wrapper behavior. Worker/Admin requests bind Session CAS and
  canonical payloads without coupling retry identity to LeaseFence or regenerated
  IDs/timestamps. Core tests pass `320/320`, API/Worker pass `411` with `14` gated
  skips, strict Core Mypy and changed-path Ruff pass, and release Eval is `10/10`.
  Full tests are `1971 passed, 145 skipped` with the sole inherited 561/500 Desktop
  file-size violation reproduced on the untouched cloud mainline.
  PostgreSQL v10, Mem0 v11, runtime selection, SQLite feature work and Desktop remain
  outside this task.
- Completed PostgreSQL governed-memory slice `CLOUD-MEMORY-PG-01` is formally `Done` and starts from integrated
  Core contract `4bda7f72`. It adds v10 authority/receipt storage, exact namespace reads,
  restart-safe content-free scans, Worker/Admin aggregate transactions and repeatable
  read-only SQLite import tooling. The isolated PostgreSQL 17.5 matrix passes `29/29`;
  full tests pass `1977` with `162` gated skips and only the inherited Desktop size
  failure. Runtime wiring was deliberately removed after review exposed terminal-event,
  active-set and mixed-store recovery gaps; it remains gated on one coherent cloud
  composition. Mem0 delivery, Desktop/SQLite feature work and production cutover remain
  excluded.
- Completed and formally closed Artifact contract slice: `CLOUD-ART-LIFECYCLE-CON-01` separates the
  provider-neutral cloud lifecycle Port/domain from the unchanged local
  `ArtifactPayloadStorePort`. It can proceed in Core without touching Handoff v8,
  PostgreSQL, MinIO, SQLite, Worker composition or Desktop, and becomes the explicit
  contract dependency for Artifact v9. The Core contract now freezes exact
  Event/object evidence, Worker versus management authority, safe cleanup evidence
  and staged/finalized/compensated/pruning/pruned shapes without changing local
  behavior. Its provider-neutral contract gate is `Done`; object, payload, Effect,
  read-composition and Runtime cards remain separate.
- Completed and formally closed object adapter slice: `CLOUD-ART-OBJECT-S3-01` implements the immutable
  S3-compatible bytes boundary and MinIO versioning against the reviewed Core Port.
  Conditional put, canonical retry, digest/size verification, exact-version read and
  delete, namespace-private keys and typed provider failures pass an isolated real
  MinIO cross-client matrix (`15/15`). All storage tests pass `130` with `87` gated
  skips and strict storage Mypy passes `49` files. PostgreSQL metadata, lifecycle
  orchestration, runtime selection, signed delivery, SQLite and Desktop remain
  untouched. Its object boundary is `Done`; PostgreSQL metadata, lifecycle
  orchestration, Effect linkage, reads and Runtime remain separate gates.
- Business-baseline recovery is active before cloud-stack integration. Exact replay
  on `zebra-cloud-trench@375dca92` reproduces all `9/9` remaining failures. Four
  path-bounded microservice cards own provider expectations, SCM credential
  fixtures, Worker cancellation convergence and Core Event contract
  extraction. All four microservice repair cards are locally integrated after the
  provider, SCM, cancellation, Core file-size, backend and Eval gates pass. Desktop
  is explicitly outside the new Zebra microservice mainline.
- Agent Definition architecture task `AGENT-DEF-ADR-01` is Done: ADR-016 records
  accepted Definition control-plane decisions and updates the final architecture.
  It separates Task-level Definition configuration from Attempt-level execution
  authority and preserves ADR-012's opaque external namespace. `AGENT-DEF-CON-01`
  is now Done: its frozen provider-neutral Definition/Version/Release models,
  deterministic digest/reference validation and Registry Port are merged, with
  `355/355` focused Core tests and changed static checks passing. The follow-up
  `AGENT-AUTH-SNAPSHOT-01` is now Done on
  `zebra-cloud-trench@50ad8d1c`: it owns only the schema, resolver Port, durable
  pre-Attempt event and narrowly injected Worker seam, with recoverable
  latest-snapshot revalidation. Focused authority `6/6`, Core `355/355` and
  Worker `93 passed, 13 skipped` are green; the full suite's single failure is
  the two inherited file-size violations outside this task. No implementation
  task is currently active; the cloud mainline is waiting for maintainer
  activation of a registered successor. Local SQLite Registry work is
  intentionally deferred on this cloud microservice mainline, while storage,
  API and runtime wiring remain locked.
  The implementation order is
  `CON -> AUTH`, then `{DRAFT,AUTH} -> BIND -> MEM -> TRUST -> EVAL -> PUB`;
  PostgreSQL Registry remains a separately gated adapter.
- Web Intelligence planning: `WEB-INT-PLAN-01` is a documentation-only review
  slice defining a provider-neutral native `web.*` surface over a replaceable
  wigolo Provider, Zebra-owned orchestration/security, and durable Watch. Its
  implementation cards remain Locked; no wigolo runtime or new native Tool is
  delivered.
- Locked architecture tasks: Web Intelligence implementation, ACP entry and
  optional code intelligence
- Open product issue: none; `#148` closed with PR `#156`
- Review task: `WEB-UX-01` makes explicit `local + trusted-local` execution
  non-interactive across Desktop/API/CLI/Worker, including existing Tasks, while
  retaining fail-closed non-local defaults and hard Gateway/Runtime boundaries.
- Active extension task: `EXT-0` registers the Skill/MCP/Plugin extension
  control-plane contract (`ADR-014`, merged via PR `#180`); the **EXT-1 Skill v2
  epic is complete** — `EXT-SKILL-01..05` are `Done` (metadata v2,
  scope/namespace/digest, task-level skill-component snapshot +
  handoff/authority/recovery/API threading, the bounded admin surface with
  SQLite enable/disable state, and `skills.read` provenance + release-eval
  cases). **`EXT-MCP-01` is `Done`** — bounded protocol-version negotiation
  (`SUPPORTED_PROTOCOL_VERSIONS` with server-version validation) and a
  Streamable HTTP transport (`mcp_http.py`) with bearer-token-via-env,
  module-level SSRF guard, https enforcement, and stdio/http routing in the
  harness. **`EXT-MCP-02` is `Done`** — `McpSessionPool` with
  healthy/degraded/quarantined health classification, bounded backoff, and
  acquire/release/health/close wrapping `McpProxyTransport` (shared by stdio +
  http); `SessionState` dataclass exposed from `mcp_protocol`. **`EXT-MCP-06`
  is `Done`** — elicitation mapped onto the durable Clarification flow:
  `ClarificationContext`/`ClarificationRequestedPayload` gain optional
  `response_schema` + `elicitation_source` (existing flow byte-identical),
  `McpElicitationBridge` converts `elicitation/create` → ClarificationContext,
  and `ZEBRA_MCP_ELICITATION` gates it (default on). **This completes the EXT
  Phase A scope** (EXT-0 + SKILL-01..05 + MCP-01/02/06).
  Plugin/Hook/Marketplace remain `Locked` pending private-cloud GA. Elicitation
  is reconciled to durable HITL; sampling stays a hard non-goal.
- Completed documentation task: `EXT-PLAN-01` records the Skill, MCP, and Plugin
  extension upgrade architecture, authority boundaries, phased task map, and
  acceptance gates. It changes no product capability and does not activate the
  deferred marketplace or remote MCP work.
- Active harness task: `HAR-TOOL-RECOVERY-01` enforces the durable contract
  that a single `ToolCallStatus.FAILED` (HTTP 4xx, missing file, timeout) must
  surface as a structured observation for model-selected correction rather than
  directly producing `session_failed`. Changes: repeated tool calls become
  observations with a threshold-gated `loop_guard_exhausted` hard stop (default
  3), sequential batches continue executing remaining tools after a mid-batch
  failure (matching concurrent-batch semantics), and a provider protocol
  firewall (`protocol_invariants.py`) validates tool-call/tool-result pairing
  before every model request to prevent `invalid_request` leakage.
- Model-response acceptance is now a separate provider-neutral boundary:
  malformed body/SSE/tool-call output becomes `ModelResponseRejectedError`,
  tool-capable stream deltas are committed only after validation, one bounded
  repair is allowed within the model-call budget, and exhaustion produces a
  recoverable `SESSION_SUSPENDED` rather than `session_failed`. Provider
  transport retries and semantic repairs have separate trace counters. The
  implementation and regression cases are present in the working tree; runtime
  validation has not been executed in this session.

## Current Capability

### Durable execution

- Event Store and projections are the durable source of truth.
- Harness and Worker execution is bounded, stoppable, resumable, and recoverable.
- SQLite leases, idempotency, tool/effect ledgers, snapshots, artifacts, and
  delivery audit cover the local execution lifecycle.
- Existing Session handoff safety contracts now back internal Segment rollover
  while the legacy ordinary-user mutation remains disabled by default.
- Stable Task persistence aggregates root and child Segments behind one identity,
  one monotonic event cursor, and active-Segment message/control routing.
- Completed-Task follow-up and cancelled/failed-Task recovery create internal Segments
  automatically; unsafe lifecycle boundaries pause or fail closed.
- Immediate terminal follow-ups inherit the previous user/Assistant checkpoint;
  internal rollover no longer drops the subject needed by short replies.

### Runtime and security

- Runtime classes are `trusted-local`, `os-sandbox`, `oci-rootless`, and `gvisor`.
- Production mode requires gVisor and a digest-pinned image and fails closed on
  missing runtime capability or authority drift.
- Hard runtime modes use a read-only root, non-root identity, dropped
  capabilities, no-new-privileges, default no-network, resource limits, and
  session-labelled cleanup.
- Policy, HITL, network profiles, MCP/Web gates, credential boundaries, and
  audit remain independent of model output.
- Explicit `local + trusted-local` mode uses effective `full-trusted-local`
  authority across Desktop/API/CLI/Worker, so new and existing Tasks execute model
  tools without per-call approval. One Agent Security resolver is the authority
  source for every execution entry point. System HTTPS proxies are honored for
  local Web execution; direct connections retain public-address DNS preflight.
  Core and non-local deployments remain default-deny and approval-gated.

### Context and model integration

- Every provider request crosses a model-aware context-window hard gate.
- Large tool outputs retain complete Artifact payloads while the model receives
  bounded, checksummed projections.
- Transparent Context Capsules support compaction, inspection, recovery, and
  deterministic provider-continuation fallback.
- DeepSeek stable Flash/Pro profiles, streaming/cache/TTFT/error telemetry, and
  default-off Beta capabilities are implemented without exposing private reasoning.
- Malformed provider JSON and Tool Call arguments are rejected before execution;
  one bounded model repair is attempted, then execution suspends recoverably.
- Explicit in-process DeepSeek thinking tool loops preserve and replay private
  `reasoning_content`; default executor profiles remain non-thinking, and missing
  continuation state fails before HTTP.
- `DS-RESP-01` adds an explicit Flash/Pro DeepSeek Responses wire adapter with
  semantic SSE terminal validation, required-tool support, stateless reasoning
  replay, provider-side tool rejection, and legacy Chat Completions compatibility.
  Responses remains opt-in; plaintext private reasoning does not become durable
  Session state, and vision/web-search/custom-tool combinations fail closed.
  Focused contracts pass `55/55`; a credentialed semantic-SSE smoke passed both
  the Flash thinking tool round trip and Pro high-thinking reviewer route. Full
  validation passes `2610` tests with `326` explicit skips, the 1425-file size
  gate, Ruff, strict Mypy across 707 source files, and the `10/10` release eval.

### Product surfaces

- Zebra owns Agent execution state and can run as an independent microservice;
  Desktop and CLI are optional operator surfaces over the same Runtime.
- Authelia/external identity owns authentication. Calling business systems own
  users, organizations, membership, business authorization, subscriptions, and billing.
- Zebra accepts signed Agent authority, opaque namespace, and technical limits;
  internal Policy may only preserve or narrow that authority.
- API, CLI, Worker, and Desktop read and mutate the same durable state.
- Desktop consumes replay-plus-tail SSE, renders truthful partial output, and
  supports approval, clarification, task plans, context, and artifacts without
  exposing internal child-Session or handoff controls.
- Real Chromium exercises the live Desktop/API/Worker/SQLite/SSE chain for long
  streams, reload recovery, cancellation, and invisible cross-Segment follow-up.
- Desktop composes Lobe UI `ThemeProvider` with Ant Design X and Zebra's durable
  event projection; Lobe UI does not replace session or chat state.
- The compact Ant Design X composer is merged; it does not change conversation
  or task-launch contracts.
- Typed local tools cover bounded file, command, patch, tests, Git, Web, Skill,
  MCP, and read-only Research paths according to the task profile.
- Failed tools return structured observations for model-selected correction or
  fallback, including bounded failure reason and detail when output is empty,
  while Policy, approval, protocol, effect, and budget stops remain hard.
- API and Harness model/tool call limits are optional and default to unlimited;
  an explicit caller ceiling remains strict. A batch that cannot fit starts no
  tools and suspends recoverably instead of becoming a generic Task failure.

### Platform Console (apps/platform-web)

- The management console frontend exists at `apps/platform-web`, built on the
  `next-shadcn-dashboard-starter` template (Next.js 16 App Router, React 19,
  Tailwind 4, base-ui shadcn) with the template's Clerk auth removed — the
  console intentionally ships without a user system for this phase and the
  operator identity is a local placeholder.
- The full PRD v1.1 information architecture is implemented: 8 top-level
  navigation modules and 52 routes — the PRD §7.3 recommended route list is
  fully covered, plus Notification and Platform Health which appear in the
  §7.2 nav tree (overview, integrations with the
  7-step onboarding wizard and three-pane Manifest editor, Agent assets with
  Effective Policy Simulator, runtime center with the 12-tab Task detail and a
  dependency-free SVG Orchestration DAG, frontend capability center with the
  profile-driven Hook code generator, quality/release gates, governance and
  audit with real CSV export, and system settings).
- Data access is centralized behind `src/lib/platform/repository.ts`; it reads
  a local mock dataset shaped on the Trench/Jazz pilot so the console runs
  standalone before the Management API exists. Swapping the repository for an
  OpenAPI-generated client is the single integration point.
- PRD safety rules are enforced in the UI layer: digests and IDs render as
  copyable monospace with full-value tooltips, high-risk operations require a
  reason-bearing confirm dialog, published revisions render immutable, and no
  page displays plaintext credentials or raw Fence tokens (references and
  hash digests only).

## Latest Validation Baseline

Validated on `codex/platform-web-bootstrap-01` on 2026-08-26 (Platform
Console, `apps/platform-web`):

- `pnpm typecheck` (`tsc --noEmit`): 0 errors across 299 source files
- `pnpm lint` (oxlint): 0 errors, 92 accepted warnings (73 are the standard
  TanStack Table inline-cell pattern; the rest are template-legacy)
- `pnpm build`: production build compiled successfully, 48 routes generated
- production server route smoke: `54/54` console routes returned 200 with
  SSR content markers verified (overview KPIs/charts, Task detail timeline
  and binding digests, the 6-node Orchestration DAG, wizard step gating and
  transition, the three-pane Manifest editor, Hook code generation with real
  profile contract names)
- code review pass closed on hydration safety, dead links, PRD secret/fence
  display rules, and immutability affordances

Validated on `codex/ctx-seg-02-followup-recovery` on 2026-07-20:

- focused API/Core/Worker regression: `74 passed`
- `make test`: `1519 passed, 7 skipped`
- `make check`: file-size `899`, Ruff, strict Mypy over `419` source files,
  and all `8/8` release Eval cases passed
- all `22` deterministic Desktop checks and the production Vite build passed;
  Tauri validation was intentionally omitted per explicit scope waiver

Validated on `codex/web-ux-01-trusted-local-auto-web` on 2026-07-19:

- final focused authority, failure-observation, proxy, API, Worker and runtime:
  `101 passed`
- `make test`: `1515 passed, 7 skipped`
- `make check`: file-size `899`, Ruff, strict Mypy over `418` source files, and
  `8/8` release Eval cases passed
- every deterministic Desktop `check:*` script and production build passed
- real Chromium: `8/8`, covering the trusted-local launch default, automatic
  command execution, streaming, reload, cancellation, Segment and failure paths
- the original old Task completed a real OpenAI `web.fetch` via the configured
  macOS HTTPS proxy without approval or `private_network_blocked`
- real Zhipu Task `91fbddb3-d608-4e7c-a15b-694d6e55c9ae` recorded Policy
  `allow`, recovered from the site's expired TLS certificate, and gave the model
  the exact failure detail instead of a false allowlist explanation

Validated on `codex/subagent-delegation-model-native` on 2026-07-19:

- focused delegation and recovery regression: `39 passed`
- `make test`: `1509 passed, 5 skipped`
- `make check`: file-size `898`, Ruff, strict Mypy over `417` source files, and
  `8/8` release Eval cases passed
- isolated real-model API check answered `1+1` directly with `2`; trace and
  durable events contained no tool or Subagent activity

Validated on `codex/ctx-seg-01-task-runtime` on 2026-07-19:

- `make test`: `1501 passed, 7 skipped`
- `make check`: file-size, Ruff, strict Mypy over `417` source files, and `8/8`
  release Eval cases passed
- Desktop: every deterministic `check:*` script and production build passed
- real Chromium: `7/7` long-stream, reload, stop, invisible Segment follow-up,
  approval, and failure regressions passed
- terminal control state and approval identity now project through the stable Task
  boundary even while an internal Segment execution request is settling
- inherited workspace revision is fail-closed before the first Segment attempt;
  later approval continuations use current runtime authority instead of replaying
  the immutable creation-time revision check

Previous packaged mainline baseline:

Validated on `ARCH-RT-A4-E2E-01`, merged as `origin/main@d586a8f` / PR `#165`
on 2026-07-18:

- `make test`: `1484 passed, 7 skipped`
- file-size gate: `889` files, zero violations
- Ruff: passed
- strict Mypy: `412` source files, zero errors
- release Eval: `8/8`, `pass_rate=1.00`
- Desktop: deterministic checks, production build, and `7/7` real Chromium
  Runtime/streaming regressions passed
- Quality run `29645045918`: all seven jobs passed, including the packaged Ubuntu
  `.deb` WebDriver chain, real Linux gVisor, Workspace exhaustion, and real OS
  sandbox smoke on Ubuntu and macOS
- packaged evidence records `passed=true`, `runtime_class=os-sandbox`,
  `fallback_allowed=false`, cancellation, approval with real tool execution,
  failure visibility, and restart-durable-recovery; final screenshot shows the
  recovered failed session and Runtime Inspector value
- current main JavaScript chunk: about `1.47 MB` (`458 KB` gzip), Vite warning remains

The seven skips are opt-in real-provider/platform smokes. Linux CI runs the real
gVisor and native sandbox jobs instead of treating local skips as proof.

`UI-LOBE-01` validation additionally passes all Desktop checks, TypeScript,
Vite production build, and a real browser smoke without console warnings.

`UI-COMPOSER-01` additionally passes all `21` Desktop checks, TypeScript/Vite
build, and real Chromium desktop/mobile visual checks. The thread composer is
`117px` high instead of `183px`; the new-task and `390px` mobile variants are
`145px` and `113px`, with no horizontal overflow or browser console warnings.

The DeepSeek credentials-enabled focused run also passed all `39` contracts,
including a real thinking tool round trip.

## Governance State

- The Phase 0-8 implementation baseline is complete and historical.
- `docs/AGENT_TASKS.md` is the only executable task registry.
- All eight stale `Review` cards verified as merged are closed as `Done` by
  `QA-GOV-02` / PR `#144`.
- `QA-148-MDL-01`, `QA-DESKTOP-E2E-01`, and all Phase A Runtime tasks
  `ARCH-RT-A1-OS-01` through `ARCH-RT-A4-E2E-01` are `Done`.
- `QA-HANDOFF-CLK-01`, `QA-PKG-E2E-02`, `QA-PKG-E2E-03`, and `UI-LOBE-01`
  are `Done` via PRs `#170`, `#171`, `#172`, and `#168`.
- `UI-COMPOSER-01` is `Done` via PR `#174`.
- `ARCH-129-ACP-01` and `ARCH-129-CTX-01` remain `Locked` until explicitly activated.
- `EMB-PLAN-01`, `EMB-AGUI-SPIKE-01`, `CLOUD-STO-SEAM-01`, and
  `CLOUD-STO-AUTH-01` are formally Done for their architecture, protocol and
  local Store-composition slices. Production AG-UI, Trench and cloud backend
  selection remain separately gated.
  `MEM-MEM0-ADP-01` is formally Done as a disabled-safe integration contract;
  it is not runtime-selected. `MEM-MEM0-SPIKE-01` is formally Done for its
  pinned OSS contract evidence; the provider-neutral
  Memory Gateway contract, Core delivery-certainty contract, PostgreSQL-native
  admission Spike, PostgreSQL-native storage gateway, and PostgreSQL v11
  delivery ledger are formally Done with isolated evidence; none selects a
  Runtime backend. Mem0 remains a derived, degraded-safe index;
  PostgreSQL Event/Projection and epoch/Lease Adapters have real-service
  restore and concurrency evidence.
  The local CI-billing waiver does not satisfy merge, runtime composition, release
  or production gates. The reviewed Effect and Artifact foundations are not runtime-
  selected; full aggregate fencing, Redis, production AG-UI, Trench, analysis,
  writeback, Memory delivery/runtime wiring and GA remain `Locked` pending explicit
  gates. `MEM-GW-DEL-PLAN-01` is formally `Done` on
  `codex/mem-gw-del-plan-closeout-01`; it keeps `MEM-GW-DEL-01` locked and
  registers the Core certainty, scoped reset Spike, PostgreSQL v11 ledger and
  runtime/rebuild child cards. `MEM-GW-DEL-CON-01` is formally `Done` after its explicitly activated,
  provider-neutral Core implementation slice. `MEM-MEM0-RESET-SPIKE-01` is now
  `Blocked` on `codex/mem0-reset-spike-01`: its isolated Compose run proved the
  pinned Mem0 list endpoint has no documented bounded pagination, so exact scoped
  enumeration cannot be accepted. `top_k` is not pagination. `MEM-GW-DEL-PG-01`
  is formally `Done` on `codex/mem-gw-del-pg-01` for the metadata-only v11
  ledger, atomic v10 enqueue and PostgreSQL claim/revalidation slice. Its host
  Compose runner passes `24` real PostgreSQL tests covering fresh/v1-v10 upgrade,
  checksum, migration rollback, replay, atomic enqueue, stale ACK, namespace
  isolation, unknown and in-flight quarantine, and batch search admission. The
  parent ledger and runtime wiring remain locked by the scoped-reset gate.

`MEM-MEM0-RESET-ALT-01` is formally `Done` as a zero-production-code validation
of whether v11 `scope/generation` plus confirmed provider mappings can replace
provider-wide enumeration for logical reset. Its isolated runner passes `2`
tests with verdict `B/PARTIAL`: logical reset and known mapping deletion are
bounded, but unknown provider orphans remain unrecoverable from the ledger. The
existing reset Spike remains `Blocked`; the partial verdict does not unlock the
runtime consumer. The focused delivery runner remains `24 passed`, and the full
storage matrix remains `295 passed, 1 skipped`.

`MEM-PROVIDER-DEL-COMPLIANCE-01` is now `Done` on
`codex/mem-provider-del-compliance-01`. This docs/specification-only slice adds
ADR-018 and a test-only admission matrix for deterministic recovery, physical
deletion and complete scoped coverage. The current Mem0 verdict is logical
fencing `PASS`, ledger mapping deletion `PASS`, ambiguous-create recovery
`FAIL/UNPROVEN`, complete scoped deletion `FAIL/UNPROVEN`, and Runtime admission
`BLOCKED`. Mem0 is therefore `Provider admission: DENIED` and
`Mainline candidate: DEFERRED`; `MEM-GW-DEL-RUN-01`, the parent ledger and
Runtime composition remain `Locked`. No production code, Provider HTTP, Worker,
Desktop or SQLite composition is changed.
The focused contract suite passes `2`; changed-path Ruff, format, Mypy,
compilation and `git diff --check` pass. `make check` remains blocked by two
unrelated file-size violations: Desktop stylesheet `561/500` and PostgreSQL
storage test `765/700`.

`MEM-PG-NATIVE-ADMISSION-SPIKE-01` is formally `Done`. Its isolated PostgreSQL
17.5 profile proves the ADR-018-compatible native boundary with `8 passed` and
emits `ZEBRA_PG_NATIVE_ADMISSION_VERDICT=PASS`; the full storage matrix passed
`303 passed, 1 skipped` (`295` predecessor cases plus `8` admission cases).
The result admitted the candidate architecture, after which
`MEM-GW-PG-NATIVE-01` was explicitly activated for storage-only work. Worker,
Provider HTTP, Desktop, SQLite, Redis and Runtime remain `Locked`.

`MEM-GW-PG-NATIVE-01` is formally `Done`. Production PostgreSQL migration v12
and the provider-neutral `PostgresNativeMemoryGateway` are covered by `10`
focused Compose cases; the full `tests/agent_storage` matrix passes `313 passed,
1 skipped`, and the existing delivery runner remains `24 passed`. The card does
not select a Runtime backend or add Provider HTTP, Worker, Desktop, SQLite or
Redis composition.

## Known Follow-Ups

1. Keep the completed Embedded architecture and AG-UI/Trench Spikes parked while
   the storage branches follow their recorded merge order.
2. Keep DeepSeek thinking mode opt-in and preserve its private continuation
   fail-closed boundary.
3. Preserve merge order from `CLOUD-STO-SEAM-01` through `CLOUD-STO-AUTH-01`,
   `CLOUD-PG-PLAN-01` (now `Done`), `CLOUD-PG-01`, and the Lease contract/Adapter chain; do not
   select PostgreSQL until every authoritative Store can move as one profile.
4. Split or lazy-load the Desktop main bundle based on a repeatable bundle report.
5. For private cloud, plan PostgreSQL, object storage, multi-Worker coordination,
   Credential/Egress Broker, external-namespace isolation, and Kubernetes in
   dependency order.
6. Review the dependency Compose baseline and Mem0 contract/Adapter chain. Preserve
   its duplicate, expired-search, timeout and error-classification findings; do not
   claim real-provider compatibility or make Mem0 authoritative.
7. Preserve the PostgreSQL/Lease order: `CLOUD-PG-PLAN-01 -> CLOUD-PG-01 ->
   CLOUD-LEASE-PLAN-01 -> CLOUD-LEASE-CON-01 -> CLOUD-LEASE-PG-01`; only then may
   fenced Effect Outbox and Worker consumer cards be activated.
8. Activate Object Storage, Redis live state, recovery and Memory delivery/runtime
   wiring one path-bounded card at a time; no production claim precedes complete
   composition, migration, restore and failover evidence.
9. Continue the memory lane one path-bounded child at a time. The Core and
   PostgreSQL delivery children, provider-neutral gateway, PostgreSQL-native
   admission and storage slices are Done. The scoped reset child is `Blocked`
   on bounded enumeration; keep the Mem0 consumer, parent ledger and Runtime
   locked until their own explicit gates are reviewed.
10. Keep `WEB-INT-PLAN-01` in review until its document evidence is accepted;
    do not activate Web Intelligence contracts, Provider, security, tools,
    orchestration or Watch cards out of dependency order.
11. The former DeepSeek vision dual-channel plan registered as `DS-VIS-PLAN-01`
    is retained only as a historical record and is superseded by
    `TRN-DEEPSEEK-V41-MM-01`; do not claim or implement the old `DS-VIS-*` chain.
    The replacement keeps Artifact/session authority and bounded image validation,
    but sends the authorized image directly in the current USER message to the
    official `deepseek-flash` model. Files API, remote image fetching and derived
    OCR/vision evidence remain separate future work rather than prerequisites.

## Runtime Blueprint

`ARCH-RT-BP-01` is complete on `codex/arch-runtime-deployment-blueprint` and
records the shared Runtime contract and the separate single-host and cloud
deployment profiles. It does not activate implementation or change the status
of locked architecture cards.

The maintainer activated single-host Phase A on 2026-07-18. Work is split into
`ARCH-RT-A1-OS-01` through `ARCH-RT-A4-E2E-01`; all four tasks are merged and
every Phase A exit criterion is evidenced. Phase B and Phase C remain deferred
pending explicit activation; Phase B additionally requires database migration
and recovery-model review.

A1 now implements macOS Seatbelt and Linux bubblewrap `os-sandbox` with
capability probes, sanitized process environments, network denial, whole-process
boundaries, immutable authority, snapshots, and fail-closed platform selection.
A1 merged through PR `#160` after Ubuntu bubblewrap, macOS Seatbelt, gVisor,
Backend, and Desktop CI passed. A2 now owns Setup/Agent isolation.

A2 now implements exact external HTTPS GET egress, SHA-256 cache reuse, temporary
Credential revocation before Sandbox startup, no-network Setup execution,
lockfile verification, SPDX Setup Artifact, verified Snapshot handoff, and a new
no-network Agent handle. It reuses existing Artifact/Snapshot storage and adds no
durable state model. A2 merged through PR `#163` after all five Quality jobs
passed. A3 now enforces a dedicated capacity-limited Workspace mount in
production, kills timed-out process groups, normalizes runtime failures, and adds
real `ENOSPC`, 20-cycle native soak, long-stream, and gVisor machine-readable CI
evidence. Local validation passed `1483` tests plus all static/release gates; PR
`#164` merged after all six Quality jobs passed. A4 then delivered the final
packaged Tauri/Desktop Runtime E2E exit gate through PR `#165` / merge commit
`d586a8f`. Quality run `29645045918` passed all seven jobs. The Ubuntu `.deb`
artifact was driven through the real API, Worker, and `os-sandbox`; its retained
JSON and screenshot evidence cover no-fallback identity, cancellation, approval,
real tool execution, failure visibility, API restart, and durable recovery.

## Explicitly Deferred

- Zebra AG-UI production adapter and HostSessionGrant verifier
- Trench CopilotKit Runtime/BFF, read-only panel, frontend tools and writeback
- Memory delivery runtime wiring: `MEM-GW-DEL-01` remains `Locked`; its Core
  certainty and PostgreSQL ledger children are Done, while scoped reset/rebuild
  is Blocked and the Mem0 consumer remains gated.
- ACP entry adapter
- optional code-intelligence adapter
- Kubernetes/Kata/Firecracker and distributed Sandbox scheduling
- complete PostgreSQL runtime composition and object-storage adapters
- external authority adapter and namespace-isolated cloud control plane
- centralized Vault/KMS-backed credentials and production Egress
- ecosystem marketplace, cross-organization A2A, and autonomous production release

## Permanently External Business Responsibilities

- user registration, login credentials, MFA and identity lifecycle
- organization, membership, invitation, join/leave and account-disable workflows
- business RBAC, subscriptions, plans, billing, invoices and commercial quota

Authelia is the selected authentication provider. Zebra verifies external Agent
authority and enforces technical execution limits, but does not duplicate these
business domains. The durable decision is `ADR-012`.

## Document Responsibilities

| Document | Responsibility |
|---|---|
| `README.md` | stable product entry, setup, capability summary, boundaries |
| `PROGRESS.md` | concise current mainline snapshot and next decisions |
| `docs/AGENT_TASKS.md` | executable task status, owner, branch, paths, acceptance |
| `task_plan.md` | current task checklist only |
| `WORKLOG.md` | session-level execution history and handoff evidence |
| final architecture | target architecture and invariants |
| `docs/Zebra Embedded 生产级目标架构.md` | Embedded/Trench target and invariant boundaries |
| `docs/Zebra Embedded与Trench实施任务拆解_v1.0.md` | dependency, ownership and phase gates for Embedded delivery |
| Phase 0-8 implementation document | historical dependency and acceptance baseline |

## Required Reading

1. `README.md`
2. `PROGRESS.md`
3. `docs/AGENT_TASKS.md`
4. `AGENTS.md`

## 2026-09-05 RabbitMQ Stage 5 capacity acceptance

`RABBIT-ROLLOUT-CAPACITY-01` is in Review and accepts Stage 5 group 1. Trench
now serializes per-user cross-conversation admission in PostgreSQL. Zebra
enforces global unpublished-Outbox and per-scope execution/control ceilings,
including recovery, backfill and old-writer migration paths, while reserving
control capacity. Fair pickup retains forward progress and probes a frozen ring
of active scope heads so continuous tail traffic cannot starve a newly active
scope. Actual PostgreSQL/API regression passed 146/146, the final migration
negative proof passed 2/2, and independent SPEC/QUALITY reviews passed. Stage 5
is **1/8 = 12.5%**; rollout/shadow, production activation and later hardening
groups remain open.

Before architecture changes, also read the source-of-truth documents in the
precedence order defined by `AGENTS.md`.

## 2026-09-07 Cloud extension Turn admission

`EXT-ADMIT-01A` is in Review after independent spec and quality re-reviews
passed. A separate default-off cloud flag now admits only
message commands carrying a genuine exact-scope Host Grant with `agent.run`.
The server selects a bounded set of currently enabled Skills, derives the same
Turn identity used by execution, and atomically persists the accepted command,
RabbitMQ wakeup/Outbox records, trusted digest binding and immutable v54
snapshot. Selection is limited by the authoritative root Task's immutable Host
binding and frozen `skill_components`: issuer, namespace, workspace and exactly
one principal must remain identical, while absent or empty Skill ceilings select
nothing. Client binding aliases are rejected; idempotent retries retain their
first binding, a second pending message is rejected before Turn selection, and
clarification continuations reuse the original Turn snapshot and digest even if
live configuration changed. Configuration and stream races leave no orphan
records. Local, disabled and non-message behavior is unchanged. This slice does
not activate Worker extension loading or MCP network execution.

Worker activation has an explicit follow-up blocker in
`apps/worker/src/zebra_agent_worker/task_recovery.py`: recovery still compares
browser origin with the frozen JWT issuer. This admission slice does not modify
Worker production code, and does not claim end-to-end extension execution.

Final issuer/origin remediation evidence: 184 focused deterministic checks and
140 related actual-PostgreSQL checks passed, including a production-shaped Task
creation and message admission with distinct JWT issuer/browser origin plus
forged issuer rejection. Final full regression is 3884 passed / 812 skipped;
`make check` passed file-size, Ruff, strict Mypy over 875 sources and Eval 10/10.
The quality-review follow-up now checks exact Task authority before duplicate or
revision disclosure, preserves duplicate replay without live configuration
selection, enforces one enabled installation per exact scope and Skill under
concurrent writes while retaining disabled history, and revalidates up to 32
selected installations with one parameterized PostgreSQL lock query. Evidence:
62 service-free focused checks, 249 related real-PostgreSQL checks, full suite
3892 passed / 814 skipped, and `make check` passed. Independent quality
re-review passed with no remaining actionable defect. Final P2 remediation makes
the advisory key an opaque digest of complete deployment/scope coordinates plus
Skill identity and detects legacy duplicate Skill IDs before applying the
unique-Skill count limit. Validation: 36 service-free focused checks, 67 real
PostgreSQL focused checks with controlled lock-timeout tenant isolation, full
suite 3893 passed / 815 skipped, and `make check` passed.
# 2026-08-28: Trench Native History Host Grant V2

- Trench Host Grant broker 现在会以 `include_removed=true` 回查用户来源投影，同时校验
  active `trench.source` 与恒定大小的 `trench.history` 账本资源；他人账本在 mint 前
  fail closed，具体 period 的用户/工作区归属继续由 Trench 权威账本校验。
- 默认允许 scope 增加 `source.read` 与 `history.read`，`trench.history`
  必须携带 `history.read`。通用 Host manifest/resource-binding/Worker 路径保持不含
  Trench 词汇，业务可见性仍由 Trench 执行。
- Trench real-service acceptance 的精确 manifest 期望升级为 `trench-native-v2`，保留
  原五项事件工具并加入六项来源/历史工具；acceptance compose policy 同步版本化。
# 2026-09-03 Multi-user isolation closeout

`CLOUD-TRN-MULTITENANT-01` is in Review on `codex/fix-agui-live-tail` with the
Trench companion branch `codex/trn-perf-01`. The slice is limited to the
audited Trench authentication/internal-route/workspace boundaries and Zebra
principal-scoped admission/AG-UI/legacy-session boundaries. Existing dirty
live-tail and model-projection work remains outside this slice and must be
preserved.

The closeout now scopes admission idempotency to Host/namespace/workspace/
principal authority, applies tenant and principal fences to AG-UI and Task
transports, hides unbound legacy Sessions from Host tenants, and terminates
streams at Grant expiry. Zebra `make check` passes. The Trench companion now
uses HttpOnly browser sessions, rejects implicit development identities,
derives source workspace ownership from the authenticated viewer, hides the
legacy/internal API composition by default, and isolates browser event-task
caches by user/workspace. Trench `make check` and live HTTP negative probes
pass.

The final code review removed the remaining Host-specific product vocabulary
from generic Zebra Worker/API paths: embedded runs now receive a generic
Host-product identity boundary while Trench retains its exact product role in
the Host task context. PostgreSQL Task bindings enforce principal ownership;
SQLite remains explicitly tenant-only because it has no durable binding table.
The suspend/resume acceptance helper now binds a temporary workspace instead of
snapshotting the repository and `.venv`. Final Zebra validation passes
`make check` and `make test` (`2849 passed, 369 skipped`).

# 2026-09-05 RabbitMQ Stage 5 scoped rollout acceptance

`RABBIT-ROLLOUT-SHADOW-01` is in Review and accepts Stage 5 group 2. Zebra and
Trench now default unlisted scopes to database fallback, use one audited rollout
authority, and recheck execution/control lane authority inside the fenced
handoff transaction. The physically separate shadow lane is bounded and
side-effect free; advisory try-lock contention skips evidence without delaying
formal admission. Formal and shadow consumers require distinct percent-decoded
Rabbit principals and mutually exclusive queue ACLs. Existing credential files
remain usable and gain shadow identities through an atomic, non-rotating
`prepare-shadow` upgrade.

Exact reconciliation starts from eligible formal Outbox rows and requires full
formal/shadow IDs, scope and digest equality; controlled corruption tests prove
drifted mirror/observation rows are not counted. Final evidence is Zebra focused
63/63 and actual PostgreSQL 30/30, Trench focused 32/32 and actual PostgreSQL
1/1, isolated RabbitMQ ACL acceptance, both full `make check` gates, and
independent SPEC/QUALITY pass. Stage 5 is **2/8 = 25%**. Production activation,
commit, merge and push remain separate and were not performed.

## 2026-09-07 Cloud Worker extension snapshot recovery

`EXT-WORKER-01A` is implemented and is now in Review after independent
review. A separate default-off cloud Worker flag composes the existing exact
PostgreSQL extension snapshot/Task authority only for cloud PostgreSQL workers;
disabled, local and projected legacy Turns perform no extension reads. An
enabled unbound nonlegacy Turn performs one exact boolean existence probe so a
persisted snapshot cannot be hidden by deleting accepted binding coordinates.
The accepted command's server-selected Turn and digest now survive message
materialization. Before Attempt authority persistence or any model/tool call,
the Worker resolves the active human Turn from durable events, requires the
extension authority's root Task binding to exactly equal the independently
loaded execution binding, derives scope from the frozen verified issuer rather
than browser origin, and revalidates deployment/scope/session/Turn/digest and
the frozen Skill ceiling. Missing, tampered, ambiguous and cross-tenant state
fails closed; restart and retry reload the same immutable binding.

Validation: 32 focused deterministic checks; 59 related actual-PostgreSQL
checks passed with 1 environment-gated skip; full suite 3903 passed / 816
skipped; `make check` passed file size, Ruff, strict Mypy over 876 sources and
Eval 10/10. This slice does not register Skill tools, load package bytes, call
MCP, add credentials/UI, activate deployment flags, commit or deploy.

Spec review then found the migrated RabbitMQ Worker bypassed the legacy message
consumer: `handoff_command` materialized `command-input:{accepted.event_id}`
with trusted causation but did not preserve the accepted extension Turn, while
recovery only recognized the legacy idempotency convention. The shared canonical
materializer now parses `SessionCommandAcceptedPayload` and supplies its bound
Turn for normal messages; clarification continues the already-open Turn.
Recovery prefers `causation_id == accepted.event_id`, validates canonical key,
actor, type, content and clarification identity, and retains legacy correlation
only for compatibility. Every bound association is validated, including
completed historical Turns, before only the current Turn participates.

Remediation evidence: dedicated deterministic and real-PostgreSQL handoff tests
passed 13, including normal/restart, missing and tampered correlation,
clarification and two consecutive bound Turns; the wider RabbitMQ handoff,
admission and recovery matrix passed 68; full suite passed 3904 / 821 skipped;
`make check`, diff and file-size gates passed. Independent re-review remains.

Quality review then found the API still treated Rabbit's canonical causation as
pending, and the materializer/recovery did not share a durable command-integrity
proof. Core now reconstructs an accepted `SessionCommand` and verifies its
fingerprint plus session/idempotency continuity at Rabbit materialization and
bound-message Worker recovery. API admission recognizes the exact Rabbit
causation/key and strict causation-free legacy key, so a completed first Turn
admits the second. Recovery validates all bound history even with no active Turn,
merges/de-duplicates canonical and legacy candidates by Event ID, and rejects
distinct dual, missing or tampered materializations before any extension read.
Unbound legacy streams remain unchanged. Deterministic/Core/API/Worker checks
passed 50; dedicated actual PostgreSQL admission/handoff checks passed 16; the
full suite passed 3913 / 824 skipped; and `make check` passed size, Ruff, strict
Mypy over 876 sources and Eval 10/10. Status remains In Progress for independent
re-review.

Final quality review centralized the exact association predicate: canonical
means matching causation and canonical key; legacy means no causation and the
strict legacy key. Accepted payloads are typed before binding semantics are
inspected, partial/non-MESSAGE bindings fail, and API/Worker correlation is
indexed in one pass. Deterministic operation-count tests exercise 100/120-command
histories. PostgreSQL exposes only an exact-coordinate boolean `exists` probe,
never an untrusted digest. API indexes retain candidate lists, validate accepted
Event-ID uniqueness, merge strict associations and require exactly one result,
so duplicate canonical/legacy/history identities cannot be overwritten. Focused
checks passed 59, dedicated actual PostgreSQL checks passed 51, the clean final
full suite passed 3922 / 826
skipped, and `make check` passed size, Ruff, strict Mypy over 876 sources and
Eval 10/10. The task remains In Progress pending independent re-review.

## 2026-09-07 Cloud Worker typed Skill tools

`EXT-WORKER-01B` is implemented and in Review after independent final quality
review passed with no remaining P0-P2 finding. A separate default-off flag
composes the same PostgreSQL deployment,
extension store and private object reader into cloud Workers only. The Worker
uses only `PreparedWorkerContext.extension`; local, disabled and legacy paths
do not construct a cloud catalog or read Skill publication/object state.

The existing typed `skills.list` and `skills.read` tools accept a narrow
injected catalog. Every call revalidates each frozen installation and pinned
publication against the complete trusted scope. Disable, revision/version
drift, missing or cross-tenant state fails closed. Listing reads metadata only;
reading one file uses the ready publication receipt's exact object version and
verifies object size/SHA, ZIP manifest/content digest,
name/description/version and bounded canonical UTF-8 content in memory, without
host extraction or script execution. Restart/retry reconstructs the same
catalog from the immutable recovered snapshot.

Validation: focused deterministic and PostgreSQL/MinIO/Rabbit Worker matrix
`86 passed, 35 dependency skips`; the broker-only production composition published and
consumed the command before the real model/tool gateway executed `skills.read`.
Strict Mypy passed 878 sources; format, lint, diff and source-size gates passed,
with `execution.py` at 499 lines. Full suite passed `3945 passed, 830 skipped`.
Deployment activation, MCP,
credentials, UI, commit and merge remain separate.

Quality follow-up replaced per-installation live reads with one bounded
PostgreSQL authorization query over all frozen installations and ready
publications. `skills.read` repeats that same batch after object/ZIP validation,
so concurrent disable/upgrade discards the provisional body. Synchronous Worker
calls now use `asyncio.run` directly unless already embedded in an event loop;
gateway construction performs no catalog authorization/object I/O. Unknown
cloud adapter exceptions are logged with the original traceback and translated
to a fixed chained catalog failure, keeping parallel and durable/client results
free of backend secrets.

## 2026-09-14 Trench composer model usage projection

- `MODEL_RESPONSE_RECEIVED` now emits a `zebra.model_usage` AG-UI custom event
  containing only input/limit/cache/model/reasoning fields.
- Private prompt hashes, provider payloads and reasoning content remain outside
  the host stream.
- Focused projection tests passed `9/9`; Ruff and strict Mypy passed.
- Zebra Task reads now also project a durable, task-level public usage summary.
  This lets an authorized host recover metrics for runs completed before the
  AG-UI custom event was deployed without exposing provider or prompt internals.
- Trench hydrates that summary only when an opened conversation has no local
  usage, caps the upstream wait at 1.5 seconds, then persists it on the latest
  Turn so later refreshes stay local. A real historical conversation displays
  `9.3k / 55.8万` and `57.7%` cache hits after refresh.

## 2026-09-14 Trench composer model and reasoning controls

- Trench now exposes a plus attachment control, switchable Flash/Pro executor
  profile, and DeepSeek-native `none|low|high|max` reasoning choices with wider
  control spacing.
- Model profile and reasoning effort now survive Trench durable Turn dispatch,
  Zebra admission/event persistence, Rabbit/Worker recovery, and reach the
  Harness model gateway. Explicit profiles no longer get overwritten by the
  legacy executor-model compatibility setting.
- Image input remains intentionally hidden until the existing `DS-VIS-*` chain
  supplies authoritative image Artifacts, egress checks and durable audit.
- Focused validation: Zebra `51 passed` plus Ruff/Mypy; Trench API `45 passed`,
  frontend `70 passed`, ESLint and live browser control switching.

## 2026-09-15 - CLOUD-USER-SCHEDULE-MATERIALIZER-01

- Added an independent `zebra-agent-scheduler` cloud/PostgreSQL composition root
  with bounded polling, batch, claim TTL, attempts and graceful shutdown.
- Each Firing freezes the exact Schedule version and Task template. Retries use
  one stable key and the existing in-process `ZebraAgentApi.create_session`
  facade, retaining atomic Task admission and Outbox/RabbitMQ Worker wakeup.
- Scheduler authority uses an HMAC workload exchange for a fresh asymmetric
  Host Grant, then verifies issuer/audience/JWKS/origin, identity and resources
  and removes management scopes before Task admission. No bearer token, Cookie
  or workload secret is persisted in a Schedule, Firing or Task.
- Validation: focused Schedule/Scheduler/Broker exchange `28 passed`; Core `767
  passed`; Storage `361 passed, 799 skipped`; Broker/Scheduler group `43 passed`;
  actual PostgreSQL Schedule tests `7 passed`; size, Ruff, strict Mypy over 938
  sources and Eval 10/10 passed; full repository regression passed `4426` with
  `885` dependency skips.
- Boundary: management API, frontend, deployment activation, RabbitMQ fault
  injection and Trench browser acceptance remain later phases.

## 2026-09-16 - Cloud/Trench quality review remediation

The remaining review defects in the selected Skill and Trench pipeline paths
were corrected without changing authority boundaries. Cloud Skill metadata now
contains the server-published ID and the typed reader resolves either ID or
name. Host HTTP diagnostics preserve a bounded business message while
redacting credentials and internal paths. Trench Raw Inbox recovery is now
lock-claimed with a publish-time backoff, worker heartbeats distinguish last
success from last failure, and pipeline health reports durable/replay
capabilities from the actual database probe. Zebra's full suite (`4450 passed,
887 skipped`) and `make check` are green; Trench's focused reliability and
cleaning gates are green. Deployment and browser acceptance remain separate
gates.

## 2026-09-17 - Cloud/Trench quality review follow-up

The compatibility fallback for legacy Trench source databases is now complete:
subscription lookup handles a missing user-subscription table and returns to
the owner-scoped source path. Route-registration coverage was made compatible
with the current FastAPI/Starlette nested-router implementation without
weakening path or precedence checks, and RSSHub serialization now matches the
canonical `rsshub://` source kind. Native history source listing also probes
subscription readiness before loading ORM rows, avoiding an expired-object
failure during the legacy fallback. Native history search and event lookup
also probe the events table, covering the case where the period ledger is
migrated before event storage. The Trench Python gate is green at `127
passed`; native-history/extension/route regression coverage is `20 passed`,
the product timeline now also degrades safely when the events table is absent,
evidence and historical trace now degrade when projection tables are absent,
and the combined timeline/read/native/extension/route compatibility set is
`37 passed`;
focused reliability/review coverage is `47 passed`, cleaning is `73 passed`,
ToC tests are `79 passed`, and the frontend/ToC builds, lint, migration SQL
generation, and diff checks are green. No deployment or browser acceptance is
claimed.

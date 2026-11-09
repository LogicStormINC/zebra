- Export-owned-path addendum: zebra_erpnext/business_queries.py uses the same exported
  metric set; retain reviewed source split and the complete size/Ruff gate.

# ERP-AUTH-MIGRATION-AUDIT-20261102
- Status: Done; source/live audit verified and fixes merged/published in canonical main.
- Created Ready then claimed In Progress; owner Luke Ding / Codex.
- Branch codex/erp-auth-migration-audit-20261102, based on origin/main; preserve unrelated source releases.
- Owned-path addendum for confirmed bootstrap regression: deploy/prepare_remote.py;
  tests/test_ingress_prepare_checks.py. Reuse configured browser_origin for transport IP,
  retain signed origin/issuer, and do not execute bootstrap on production.
- Owned-path addendum for inherited maintenance fixture: tests/test_maintenance_checks.py;
  reuse Gate02 textRef setup, all original maintenance refusal assertions retained.
- Owned-path addendum for proven legacy manifest ImportError: zebra_erpnext/business.py;
  tests/test_legacy_manifest_checks.py and include it in deploy/check_auth_release.py.
  Exact five aggregate metrics shared with the existing validator; no new operation/scope.
- Remote addendum: persisted host-settings.json browser_origin only; final bounded backend
  image embeds accepted business.py constant repair, original image and rollback records retained.
- Owned paths: zebra_erpnext/{api,client}.py; tests/test_client_checks.py,
  tests/test_origin_bootstrap_checks.py, tests/test_auth_release_checks.py;
  deploy/check_auth_release.py; README.md, docs/AGENT_TASKS.md,
  docs/ERP_ORIGIN_BINDING_20261102.md, focused redacted docs/evidence/erp-origin-binding-20261102/*, WORKLOG.md.
- Owned-path addendum before final backend packaging: only ERP backend image + removal of
  exact client.py hotfix mount in erpnext-override.json; immutable two-file image from current
  accepted native-surface base, bounded offline build, no dependency/Worker/Scheduler restart.
- Temporary admission pause/restore and existing idle guard; do not submit any work.
- Scheduler follow-up scope before refresh: after concurrent accepted v117 alignment,
  resolved Compose Origin is correct but running process retains old browser-Origin env.
  Recreate Scheduler only on same image after established no-active/no-firing guard,
  pause/restore ERP admission, require unchanged model/session/firing/ledger counters.
- Remote: read-only Host/Task/Profile/Connector/JWKS/Origin/CSRF/delegation/receipt inspection;
  correct only Scheduler grant-origin configuration while retaining its schema guard and no execution.
- Main hotfix must have no dependency on unpublished administrator/native-surface features;
  merge same fix into current deployed source branch, publish both without overwriting dirty work.
- Fixed Cloud export receives equivalent changes only through canonical source archive;
  preserve prior size/Ruff baseline remediation and frozen manifests, never replace it by an old source tree.
- Preserve original Task/Run/receipts/unknown/Coverage; no task execution/retry, Controller acquisition,
  model/search calls, scheduler startup, schema migrations, or temporary Docker resources.

# ERP-ORIGIN-BINDING-20261102
- Status: Done; original fix is included in the published follow-up source/main integration.
- Owner Luke Ding / Codex. Created Ready then claimed In Progress before configuration work.
- Live origin repair verified; focused regression passed; pending source branch integration.
- Runtime 403 plus original Task 404 resolved without changing any historical binding.
- Branch codex/erp-origin-binding-20261102; isolated canonical worktree.
- Root cause: ERP ingress and signed Grant origin moved to https://192.168.101.7:18443;
  both native105 and cloud114 Host registries still trust only https://192.168.110.42:18443.
- Owned-path addendum before browser/authority separation: zebra_erpnext/client.py, tests/test_client_checks.py;
  remote ERP site config browser_origin/origin only, backend exact read-only client.py mount
  in erpnext-override.json; preserve base image and all other Compose services.
- Owned paths: docs/ERP_ORIGIN_BINDING_20261102.md, docs/AGENT_TASKS.md, WORKLOG.md;
  remote exact erpnext/erpnext-full Host registry records only (allowed_origins).
- Reuse PostgresHostAuthorityStore and immutable record replacement; append the new exact origin,
  retain old origin for existing signed grants. Preserve issuer, namespace, keys, replay/audit,
  Task/Run/Controller, historical receipts/unknown/Coverage and all unrelated configurations.
- Validate: actual signed ERP BFF GET red/green, both registries checked, trusted new+historical
  origins and foreign-origin rejection, only allowed_origins differs, no model/search/task dispatch.
- No schema migration, Docker resource creation or business replay. Preserve original image;
  one-file source hotfix must have durable matching read-only Compose override and backup;
  recreate backend only so preloaded workers use the new code; all other services remain unchanged.

# ERP-CAPABILITY-ACTIVATE-20261029
- Created Ready then claimed In Progress on2026-10-29 after explicit user approval to switch production; now Review, production activated and no-model gates passed.
- Human owner Luke Ding; executor Codex; branch codex/erp-capability-activate-20261029.
- Owned paths: deploy/activate_full_capability*.py, deploy/seed_full_capability_production.py, deploy/check_full_capability_production.py, deploy/runtime existing composition only if required by actual deployment; focused offline deployment checks; docs/AGENT_TASKS.md, docs/ERP_CAPABILITY_RELEASE_20261028.md, docs/superpowers/full-agent-progress.md, task_plan.md, WORKLOG.md.
- Activated Native API9a09d2d50d5a, Worker a8f0e494c3aa (same application plus existing Docker CLI), and ERP2d16a18f2af4. Separate durable production DB/S3/Redis/runtime and root-owned quota operator. Reuse production Host signing authority; never promote QA secrets/data.
- Preserve legacy runtime/Run identities, original ready/waiting work, company/user permissions and Search/MCP processes. No actual model/search request or original Run replay for acceptance.
- Gates: no active Run during Host replace; refreshed production backups/rollback manifests, actual115 schema and namespace separation, current signed BFF/resource/extension/memory/schedule checks, fixed image readiness, authenticated browser without response interception when accessible. Enable new conversations last.

<!-- ERP-CAPABILITY-INTEGRATION-20261028 owned-path addendum: deploy/prepare_full_capability_release.py for current transactional production backups and immutable image/config rollback manifest only. No activation, config write or consumption of original work. -->
<!-- ERP-CAPABILITY-INTEGRATION-20261028 owned-path addendum: deploy/check_full_capability_recovery.py. Explicitly recover only the known new QA Session under a real lease and release it; no command consumer or execution call. QA disabled Worker loop leaves its Session observation behind canonical accepted-command events; do not weaken source privacy guards. -->
<!-- ERP-CAPABILITY-INTEGRATION-20261028 owned-path addendum: deploy/check_full_capability_projections.py runs only the existing projection service in isolated erpnext-full for a bounded window. QA deliberately disabled Worker loop, which also disabled its projection maintenance; strict privacy reads correctly409 before maintenance. No Run claim/execution/model/tool or original namespace. -->
<!-- ERP-CAPABILITY-INTEGRATION-20261028 owned-path addendum: deploy/prepare_full_capability_legacy_qa.py. Restore exact original legacy issuer/origin in cloned Host and separate namespace API only; full release keeps explicit QA issuer. No Task binding rewrites, original DB/process writes or dispatch. -->
<!-- ERP-CAPABILITY-INTEGRATION-20261028 final release addendum: zebra_erpnext/hooks.py for asset cache version; frontend/index.tsx for obsolete administrator-only text; deploy/{check_full_capability_lifecycle,check_full_capability_extensions,check_full_capability_scheduler,build_full_capability_candidate}.py; cloned business acceptance only. Final source/image receipts and v115 migration are isolated; production remains unchanged. -->
<!-- ERP-CAPABILITY-INTEGRATION-20261028 owned-path addendum: deploy/configure_full_capability_web.py. Only QA API configuration, existing exact search TLS endpoint and public CA, TLS handshake without HTTP/search, preserve original Search/MCP/Yahoo. -->
<!-- ERP-CAPABILITY-INTEGRATION-20261028 owned-path addendum: deploy/check_full_capability_analysis.py; only cached gVisor/Python on the new QA private volume, bounded ENOSPC+CSV/JSON check, no business volumes/Worker loop/model/network. -->
<!-- ERP-CAPABILITY-INTEGRATION-20261028 owned-path addendum: deploy/check_full_capability_worker.py for real trusted allocator/resolver and idle Worker construction only; no Worker loop, provider or search invocation. -->
<!-- ERP-CAPABILITY-INTEGRATION-20261028 owned-path addendum: deploy/prepare_full_capability_quota_qa.py; dedicated new root-owned QA mount/socket/readonly-proof role only, no production paths or global proxy changes. -->
<!-- ERP-CAPABILITY-INTEGRATION-20261028 owned-path addendum: deploy/check_full_capability_host.py for authenticated cloned Frappe/TLS/Native/S3 management acceptance, isolated File/Task/memory/future-paused schedule data only; never dispatch Run or scheduler. -->
<!-- ERP-CAPABILITY-INTEGRATION-20261028 owned-path addendum: deploy/complete_full_capability_qa.py for dedicated TLS/API and secret-mounted QA readiness only. No Worker/scheduler/provider dispatch. -->
<!-- ERP-CAPABILITY-INTEGRATION-20261028 owned-path addendum: deploy/frontend_profile.py gains optional exact namespace argument, retaining erpnext default. New full runtime must bind its own published client profile. -->
<!-- ERP-CAPABILITY-INTEGRATION-20261028 owned-path addendum: deploy/{prepare_full_capability_qa,seed_full_capability,check_full_capability_payloads}.py and tests/test_full_capability_checks.py. Dedicated clone containers/network/bucket and fixed-source image only; no production cutover or provider/search calls. -->
<!-- ERP-CAPABILITY-INTEGRATION-20261028 owned-path addendum before full quota composition: cloud-patches/operator/private_workspace_operator.py; deploy/runtime/{full_workspace_proof,full_worker,full_workspace_client}.py; tests/test_full_workspace_checks.py. Reuse authenticated operator with explicit generation pin and dedicated roots/network; legacy defaults unchanged. -->
<!-- ERP-CAPABILITY-INTEGRATION-20261028 owned-path addendum before private-state guard: zebra_erpnext/capabilities.py; prevent generic ERP discovery/read from exposing Zebra coordination and private library records, using the existing shared meta_for/discover boundaries. -->
<!-- ERP-CAPABILITY-INTEGRATION-20261028 owned-path addendum before scheduler composition: zebra_erpnext/{schedules,schedule_authority,authority}.py; frontend/schedule-controls.tsx; deploy/runtime/*.py; deploy/check_full_capability_*.py; tests/test_schedule_authority_checks.py. Schedule exchange is a signed private workload endpoint with current ERP permission checks, never an ordinary user cron. -->
<!-- ERP-CAPABILITY-INTEGRATION-20261028 owned-path addendum before config correction: zebra_erpnext/client.py; resolve new runtime frontend profile without changing legacy release. -->
<!-- ERP-CAPABILITY-INTEGRATION-20261028 owned-path addendum before compatibility code: zebra_erpnext/legacy_chat.py frozen from actual running backend source; merge live gateway validator/readonly boundaries and dispatch only legacy submits/cancels to its existing implementation. -->
<!-- ERP-CAPABILITY-INTEGRATION-20261028 owned-path addendum before UI edits: frontend/{capability-controls,knowledge-controls,historical-artifacts}.tsx; frontend/protocol.mjs; zebra_erpnext/public/zebra.js generated bundle. -->
<!-- ERP-CAPABILITY-INTEGRATION-20261028 owned-path addendum before code: zebra_erpnext/{runtime,install,gateway,extensions,knowledge,schedules}.py; frontend/capability-controls.tsx; tests/test_runtime_checks.py. Preserve deployed chat-recovery host overlays separately; no production overwrite without compatibility gate. -->
# ERP-CAPABILITY-INTEGRATION-20261028
- Status: Review; seven capability integrations and fixed-image no-model isolated acceptance complete (105→114→115). Production activation awaits final user approval. Created Ready and claimed before implementation2026-10-28.
- Human owner Luke Ding; executor Codex; branch codex/erp-capability-integration-20261028.
- Scope: complete the seven resource-panel capabilities requested in the screenshot using Native contracts and current ERP authority. No simulated readiness or broad permissions.
- Owned paths: zebra_erpnext/{features,cloud,chat,api,resources}.py; focused capability/extension/knowledge/schedule adapter modules; frontend resource/settings selectors and existing composer wiring; deploy capability configuration and no-model acceptance scripts; focused tests; docs/{AGENT_TASKS,acceptance}.md; task_plan.md; findings.md; WORKLOG.md. Record exact Native source additions separately before any Cloud change.
- Preserve original Runs, existing business data, private workspace quotas and search/MCP state. Do not create model requests or scheduled jobs merely to fabricate acceptance. Stop unknown writes; recovery reads original receipts.
- Gates: deterministic authority/isolation/idempotency checks, native API contract checks, frontend build, authenticated no-model browser acceptance, truthful readiness from real deployment.

- Scope addendum before edits: deploy/check_capability_upgrade.py, deploy/prepare_capability_upgrade.py and source-freeze artifacts under ignored work/. User approved exact isolated105→114 migration/compatibility; retain original production DB and all processes.

- Owned paths addendum before edits: deploy/check_capability_compatibility.py for candidate dependency imports, native typed Task/Session/paged-event reads and current-scope guard checks on the isolated migrated clone. No production dispatch.

- Owned paths addendum before edits: deploy/check_capability_http.py; actual loopback HTTP/JWT/native PostgreSQL reads using an ephemeral QA signing key only, with unchanged production trust. No fabricated API responses or Worker/model invocation. Artifact object payload checks remain separate.

- Owned paths addendum before edits: deploy/repair_capability_summaries.py; existing Native bounded read-summary maintenance on the isolated clone only, with original canonical tables unchanged. Required by actual HTTP409 projection_not_ready; no automatic repair in the public read path.

- Owned paths addendum before edits: deploy/check_capability_sandbox.py; isolated cached digest-pinned Python image/gVisor smoke, no production config, user workspace or Docker socket inside sandbox. This does not certify quota/files/Native runtime composition.

- Owned paths addendum: docs/ERP_CAPABILITY_RELEASE_20261028.md and docs/superpowers/full-agent-progress.md for truthful phased delivery/acceptance.

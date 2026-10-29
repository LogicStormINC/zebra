# P2 ERP Page Coverage Implementation Plan

> **For agentic workers:** REQUIRED: Use subagent-driven-development for bounded implementation tasks with independent spec and quality review, or executing-plans when subagents are unavailable. Steps use checkboxes for tracking.

**Goal:** Publish typed list/report/navigation, current-page reads, unsaved full-form drafts and bounded child-row edits, then certify named ERP module chains on an isolated QA site.

**Architecture:** Extend the existing Frappe adapter and versioned Cloud frontend profile. Reuse native page/model APIs and the SDK's effect journal; business persistence continues through independently approved `business.execute` operations. Page capabilities remain constrained by fresh Host permission/company metadata and exact current-page/local-draft fences.

**Tech Stack:** Frappe 16.53.0, ERPNext 16.52.1, existing React/TypeScript panel, native Zebra client-core 0.1.0 and Python/Node stdlib checks; no new dependency.

**Status:** Plan approved; bounded canonical profile implementation started, 2026-10-23. The profile task does not activate revision 2 or implement page handlers. This delegated investigation remains read-only; the user’s existing approval authorizes subsequent full implementation, isolated QA and bounded releases without another routine confirmation. The approved full-agent design remains the scope authority; pending operations remain visible in the coverage ledger.

## Native evidence and current boundaries

Read-only inspection used the installed backend `/home/frappe/frappe-bench/apps/frappe` and native Cloud schema in `erpnext-agent-api-1`. No secret values or site configuration files were read or returned; the runtime's frontend-profile member alone was projected to its public revision/action metadata.

- The deployed frontend profile is revision 1, digest `281a801786c61aca15c454b62dce90a3522e0354ccde33ec3303e2e748730fc3`, with `erpnext.ui.document.open` and `erpnext.ui.form.fill`. There is no tracked `frontend_profile.json` in this repository. `deploy/seed_cloud.py` generates the profile; `cloud.config()['frontend_profile']` supplies its installed representation. Do not invent or hand-edit a second profile source.
- `client.py::open_surface` binds the current conversation/user/run, profile revision/digest and per-action digests. It persists an admission marker before opening a Cloud surface; an unknown credential ACK does not reopen blindly. Same-run reconnect returns its original binding.
- `client.py::proxy` allows only a bounded list of native client-session routes and effect receipts. It checks the owned conversation, active run and both credentials; receipts retain `sdk-receipt:<effect_id>` and wait for canonical Worker state. Preserve those paths.
- `frontend/index.tsx::attachClient` mounts two handlers. Its 300 ms route poll does not detect every fast route transition or same-route user edit. `assertCurrentForm` checks route, current `cur_frm`, identity and draft status; it does not yet fingerprint local draft content.
- `frappe/public/js/frappe/router.js:514-554`: `set_route` resolves after a timer and `frappe.after_ajax`; it is not proof that the intended legacy form/list/report controller is ready. Readiness needs explicit controller identity checks and a bounded deadline.
- `model/create_new.js:9-36`: `frappe.model.get_new_doc(doctype)` allocates a local `__islocal`/`__unsaved` draft and applies defaults. `frappe.new_doc` at lines 407-428 may dispatch custom create routes or Quick Entry, whose dialog has an insertion action. For this capability, use `with_doctype` → `get_new_doc` → exact `Form` route, with no Quick Entry invocation.
- `form/form.js:1845-1911`: `frm.add_child` allocates a child and directly extends supplied values; pass no unvalidated values. `frm.set_value(table, array)` clears and rebuilds the entire table, so it must not implement identity-preserving patches. `model/create_new.js:252-278` shows native child allocation marks the active parent dirty.
- `model/model.js:525-569`: `frappe.model.set_value(child_doctype, child_name, field, value)` updates local state and awaits native field triggers. Such triggers may fetch data or contain installed controller/custom-script side effects. They are not a general proof that a field change cannot persist remotely.
- `form/form.js:1546-1551`: `frm.dirty()` emits `frm.$wrapper`'s `dirty` event; `is_new` returns `doc.__islocal`. Router emits `change`. Use removable event subscriptions plus direct entry/exit snapshots; do not monkey-patch global Frappe methods.
- `list/list_view.js:3287-3290`: `frappe.get_list_view(doctype)` addresses `List/<doctype>/List`. `list/base_list.js:497-501` returns four-element native filters from `get_filters_for_args`; list data is a loaded page, not the complete business dataset.
- `views/reports/query_report.js:136-184` handles `query-report/<name>` and route options, loads report settings/scripts and refreshes. Its singleton must match the current route and report name. `set_filter_value` at lines 1623-1645 returns no awaited aggregate promise, so it cannot by itself prove completion. Opening a report with filters may run a native report or its hooks; prepared-report configuration can have server-side consequences.
- Native Cloud `ClientActionRisk` values are `presentation`, `navigation`, `local_state`, `user_interaction`, `business_write_forbidden`. Use `presentation` for read receipts, not an invented `read_only` enum.
- Installed SDK `runEffect` checks session/task/run/binding/action digest, expiry and expected UI revision, persists inflight execution before dispatch, deduplicates known effects and retries receipts. A reload with a recovered inflight effect emits `unavailable/interrupted_requires_confirmation`; it does not reapply the edit. Storage denial degrades to in-memory dedup, so cross-refresh exactly-once is not certified under unavailable storage. Handler signature is `handler(args)`, without an effect ID/context argument.

## Contract decisions

Keep current readable `erpnext.ui.context` as bounded untrusted route metadata. For fresh page values use a typed action returning a receipt; merely declaring a mounted readable does not install a value getter in this SDK. Use the names below in profile revision 2; exact schemas must use `additionalProperties: false`, finite scalar values, bounded string lengths and result schemas/max bytes.

Common `expected` shape: `{route: string[1..8], doctype?: string, name?: string, modified?: string, draft_digest?: sha256, company?: string, controller_instance?: string, load_generation?: integer, filter_digest?: sha256}`. Controller/load/filter/company fields are mandatory semantic fences for list/report row reads; their presence never elevates company authority. Cloud already carries `expected_ui_revision`; do not add a competing client-effect version. Form operations require all form identity coordinates, `modified` for saved drafts and `draft_digest` from the prior read; new drafts have `modified: ""` because the native schema does not support union types. Read-only identity collection can omit the digest. Company is derived from the owned conversation, never elevated by a browser argument. Return post-operation context/digest for a subsequent request. List navigation returns `complete:false` explicitly and does not imply complete business data.

| Action | Risk | Exact intent and bound | Native call/result |
| --- | --- | --- | --- |
| Existing `erpnext.ui.document.open` | navigation | Add source `expected.route`; destination `{doctype,name}`; permitted saved document, no arbitrary URL | Fresh Host `get` permission check then `set_route('Form',doctype,name)`; wait for exact `cur_frm.doc`; return destination context |
| `erpnext.ui.list.open` | navigation | `{expected,doctype,filters?}`; <=20 validated readable scalar filters, same bounded operators as business.query, List view only | Fresh Host describe/query permission check; native route options then `set_route('List',doctype,'List')`; wait for matching controller; return route/filter snapshot and `complete:false` for loaded rows |
| `erpnext.ui.report.open` | navigation | `{expected,report,filters?}`; <=20 known scalar filters; initially only source-reviewed report settings/controllers | Fresh Host report descriptor/access check; validated route options and `set_route('query-report',report)`; verify singleton, report name and accepted filters; return loaded/pending state, never claim report execution complete from navigation alone |
| `erpnext.ui.document.new` | local_state | `{expected,doctype}`; new empty/defaulted unsaved draft; no arbitrary defaults on admission | Fresh Host read/create/mutability check; load metadata, `get_new_doc`, route to its generated local name; verify `docstatus=0`, `__islocal` and company; return `{saved:false,context}` |
| `erpnext.ui.page.read` | presentation | `{expected,fields?:string[1..30],tables?:[{field,fields:string[1..20],start,limit<=50}]}`; explicit fields only, <=16 KiB result | Recheck Host document/field permission for saved document; unsaved draft needs fresh read/create metadata. Return visible permitted scalar/local values, stable child names/parent coordinates and per-table `has_more/next_start`; list/report mode returns metadata unless exact controller instance, completed load generation, filter digest and selected company all match; list rows additionally require fresh field and per-document authority; report rows need an audited report-specific output contract |
| Existing `erpnext.ui.form.fill` | local_state | `{expected,values:[{field,kind,text?,number?,boolean?}]}` <=30 permitted scalar cells; strengthen revision/digest and validate the entire request first | Native `frm.set_value` only on audited field/controller combinations; return changed fields, saved:false and new context; empty values rejected |
| `erpnext.ui.form.children.patch` | local_state | `{expected,field,updates?:[{name,field,kind,text?,number?,boolean?}],append?:[{row_key,field,kind,text?,number?,boolean?}]}`; <=100 total typed cells across updates and append (each array also <=100), grouped into <=50 touched rows with <=100 resulting rows and <=20 scalar fields per row | Validate parent Table permissions, child fields and every exact row ownership before mutation; update existing named rows through `model.set_value`; append with `frm.add_child(field)` then native scalar setters, `frm.refresh_field(field)`; return created row identities, changed names, saved:false and new context |

Native schema compatibility: deployed action schemas permit only primitive types, fixed objects with `additionalProperties:false`, arrays, bounds and enums, with maximum depth 4. They reject `anyOf`, union types, typed dynamic maps and nested row/value maps. Use inline tagged scalar cells: `kind` is `text|number|boolean|null`; exactly the matching value slot must be present, or no slot for null. Handlers must enforce exactly-one, finite numbers, unique fields/row cells and metadata authority because the native schema subset cannot express those cross-field constraints. List filters use `{field,operator,kind,text?,number?,boolean?,texts?,numbers?,booleans?}`; list kinds are allowed only for `in/not in/between`, between requires exactly two homogeneous operands, each list <=100. Report filters remain scalar cells. `page.read` results flatten values into `cells:[{row,table,field,kind,text?,number?,boolean?}]` plus bounded columns and page metadata; `table:""` denotes parent/list/report cells. Page metadata uses `next_start:-1` when exhausted to avoid an unsupported integer/null union. Handler request byte bounds and row/field limits apply in addition to schema array limits. For child patches, native schema cannot sum two arrays: the handler must reject more than 100 total cells across updates and append before mutation. Before any local mutation, preflight the COMPLETE serialized successful/partial receipt envelope against 16,384 bytes, including context, changed cells and created row identities; use staged/reserved identities or a conservative native maximum-length bound for not-yet-generated identities. A cell-count limit alone does not establish byte safety. Overflow rejects the whole request before mutation.

Child deletion/reordering, Table MultiSelect semantics and arbitrary bulk table replacement remain explicit follow-up contracts, not implicitly accepted parameters. A future removal contract must bind exact row identity, review linked-data loss and preserve independent business-save approval. No generic `method`, JavaScript, SQL, CSS selector, HTML, URL, controller name or callback parameter is accepted by these actions.

`page.read` never serializes `cur_frm.doc`, `locals`, `docinfo`, hidden/Password/masked fields, Report JavaScript, SQL or raw DOM. Host-readable field intersection is required even if browser metadata says visible. Native action results are capped at **16,384 bytes** (the deployed maximum), including all metadata and cells; reject oversize results or paginate rather than claiming a full page. Current local values are data, not authorization. Company-less global DocTypes still need native user/document permissions.

For list/report row reads, bind the actual controller object identity, a completed native load-generation token, canonical filter digest and selected conversation company. Reject while a newer load is pending, if any coordinate changed, or if an older load finishes after a filter/company change. Route equality and the existence of cached rows are insufficient. List output intersects fresh Host-readable fields and validates every returned document identity and company through current native document authority; omit no denied identities silently when claiming a complete page. For reports, arbitrary native column labels do not prove field/company permission: require a source-audited report-specific output-column and company-scope contract. Until that contract exists, return metadata only and mark row reading `pending_report_output_review`.

All native field/report hooks must be inventoried before their action is marked available. Installed script execution that can write externally or save documents cannot enter the `local_state` package without an independently approved backend contract. Unreviewed DocTypes/reports remain queryable through the existing permitted backend where applicable, and their page action is explicitly `pending_controller_review`; this is an implementation gap in the ledger, not a native unavailability reason.

## Chunk 1: Profile and page contracts

### Task 1: One canonical revision-2 profile

**Modify:** `deploy/seed_cloud.py`; **create:** `deploy/frontend_profile.py`, `tests/test_frontend_profile_checks.py`. The pure definition serves native schema validation and publication without running the seed.

- [ ] Write a failing contract check for the seven action contracts above, accepted native risk values, bounded schemas, result schemas and `max_result_bytes`; revision-1 action names must not change semantics in place.
- [ ] Extract the existing profile construction into the smallest reusable pure definition if necessary; keep publication native. Do not introduce another configuration registry or JSON authority.
- [ ] Generate revision 2 and all action digests using native `canonical_client_capability_digest`. Pin the combined mounted profile; a changed `form.fill` contract must have a changed digest.
- [ ] Add publication checks proving rerun does not overwrite revision 1 and does not silently reuse an existing host binding to revision 1. Binding revision 2 is a deliberate deployment action, not part of a read-only plan or test.
- [ ] Run `python3 tests/test_client_checks.py` plus the focused profile check. Native schema validation should accept all generated contracts without publishing them.

### Task 2: Shared fresh Host page authority

**Modify:** `zebra_erpnext/client.py`, `zebra_erpnext/api.py`, `tests/test_client_checks.py`; reuse `business.document`, `capabilities.describe`, `business.report_describe` and `cloud.owned`.

- [ ] Add a failing check for a fixed RPC `page_contract(conversation,kind,doctype?,name?,report?)` where kind is one of `document_read`, `draft_edit`, `draft_create`, `list`, `report`; reject every surplus argument. No browser-selected Cloud path or native method is accepted.
- [ ] Bind the RPC to current owned conversation/run/company and fresh enabled-user permissions. Return only a permission-filtered field/table schema, permitted action flags, selected company and native report/filter metadata; no values need be duplicated for a new local draft.
- [ ] For a saved document, use existing native document and company checks before returning its field contract. For new drafts require read/create and existing mutable restrictions; do not grant unrestricted Single/admin creation.
- [ ] Maintain the existing surface credentials/replay proxy. A surface opened under revision 1 stays revision 1 for that run; a subsequent run explicitly admits revision 2. If supporting an active-run successor is needed, require a separate tested release/rebind path, not silent credential replacement.
- [ ] Add role/company/document/expired-run/revoked-permission failures. Verify report arguments tolerate only the company derived by Host, consistently with gateway operation schemas.
- [ ] Run `python3 tests/test_client_checks.py`, `python3 tests/test_business_checks.py` and `python3 tests/test_business_expansion_checks.py`.

## Chunk 2: Browser implementation and race boundaries

### Task 3: Shared form/page fences and navigation

**Modify:** `frontend/index.tsx`, `frontend/protocol.mjs`, `frontend/check.mjs`; create `frontend/page-actions.ts` only if it keeps the mounted handlers meaningfully smaller without duplicating Frappe abstractions.

- [ ] Write Node assertions rejecting stale exact routes, return-to-same-route with replaced form object, changed document/company/modified, nonfinite values, unexpected keys, submitted documents and unsupported legacy controllers.
- [ ] Build canonical draft fingerprints from the bounded permitted field/table snapshot. Include stable child identities and parent coordinates; do not hash only `modified` or `__unsaved` since neither detects every local edit. Do not persist draft contents in the effect journal.
- [ ] Subscribe to `frappe.router` change and the current form's namespaced/removable `dirty` event, and compare direct snapshots at handler entry and before/after awaited native operations. Keep the display poll only as presentation fallback. A route switch and return must still invalidate an old handler.
- [ ] Mount fixed handlers for document/list/report navigation and full-form unsaved draft creation. Preflight the entire contract before applying route options; restore temporary global route options in `finally` on rejection/timeout without erasing a user's newer route options.
- [ ] Keep one narrowly scoped authorized navigation/handler token through its own synchronous completion, then defer the SDK revision bump until after its post-handler receipt check. Exact-target matching alone is insufficient when a user manually navigates to that same target; detect unrelated router events and invalidate.
- [ ] Fail closed on dirty existing forms rather than discarding changes or auto-confirming a native prompt. Native route resolution and controller readiness use a bounded deadline; timeouts return an uncertain/unavailable result and do not navigate again automatically.
- [ ] Run `npm test` and `npm run build`. Keep existing mobile/reduced-motion/keyboard behavior unchanged.

### Task 4: Bounded page reads and child patches

**Modify:** the same browser files; extend `frontend/check.mjs` rather than introduce a test framework.

- [ ] Add failing assertions for hidden/masked/Password/read-only/unauthorized fields, forged child names, wrong parent/table, duplicate updates, non-Table fields, excess rows, reserved fields and invalid scalar types. All rejected requests must leave local values untouched. Include the 100-total-cell success boundary, 101-total-cell rejection across both arrays, and receipt overflow caused by context/created identifiers despite fewer than 100 cells.
- [ ] Implement explicit selected-value reads through the intersection of fresh Host field permissions and actual visible editable/readable controller metadata; return bounded rows and page-completeness markers. For list/report reads, implement the exact controller/completed-load/filter/company fence above; metadata-only is the required fallback for unaudited report output contracts.
- [ ] Implement stable-name updates and native append without passing arbitrary row objects to `frm.add_child`, without replacing the full table, and without calling `save`, `insert`, `submit` or arbitrary RPC.
- [ ] Prevalidate all rows/fields before the first local change. During execution, recheck route/form object and user-change epoch before each awaited setter. Attribute the handler's own known dirty events separately from actual user input; inspect permitted snapshots after native triggers.
- [ ] Preserve already applied local changes on an interrupted/failed native trigger and report an explicit partial local-state result with changed row/field identities; do not automatically roll back calculations or replay setters after unknown completion. No receipt may claim atomic completion or saved:true.
- [ ] Audit the native field/report controllers for the initial published DocTypes/reports and record source references and network behavior. Unsupported hook semantics stay visible as `pending_controller_review`, with no blanket “all fields are safe” claim.
- [ ] Run Node checks and a build; run existing Python business checks to ensure no changed business-persistence path.

### Task 5: Native SDK and real browser acceptance

**Create:** `tests/test_page_effects.mjs`, `tests/browser_page_acceptance.js`; use installed SDK/native browser, no new dependency.

- [ ] Import actual installed `ZebraClientRuntime` in the Node test with a minimal in-memory Storage/fetch stand-in. Mount real page handlers, construct valid effect envelopes and drive `runEffect`; test duplicate delivery and a failed receipt retry execute one handler only.
- [ ] Test expiry, stale UI revision, mismatched action/profile digest, stale run/session/fence and replaced current form. Persist/recreate the runtime: completed receipts resend without reapplying; recovered inflight work reports unavailable. Explicitly test storage denial and document the resulting refresh boundary.
- [ ] Test list/report filter and company changes while an old load finishes: reject cached rows from the old load even when the route is unchanged. Revoke a readable field after rows were cached and verify the next read excludes/rejects that field using fresh Host authority.
- [ ] Test two concurrently delivered page effects: either the first handler's admission invalidates the second or the Host allows one outstanding mutating local effect at a time. Do not claim serial execution merely because individual handlers await setters; SDK effect polling can overlap.
- [ ] On authenticated native Frappe in QA, exercise document/list/report navigation, explicit field reads, creation of an unsaved draft and append/update of child rows. Capture exact route/controller/value identities before and after; verify no database document exists until an independently approved backend create/save.
- [ ] Test change-page during metadata wait and during field triggers, user typing during handler execution, dirty-form navigation rejection, repeated effects, receipt ACK loss, reload/reconnect, separately owned conversation, permission/company revocation, mobile viewport and reduced-motion.
- [ ] Inspect the native network calls during these fixtures: page actions must not invoke business writes, external messages or unknown write-triggering scripts. A successful browser mock is not real native acceptance.

## Chunk 3: Isolated module-chain QA prerequisites and coverage ledger

### Task 6: Prepare a reviewable isolated QA deployment proposal

**Current fact:** Native sites directory contains only `192.168.110.42`. The native Company lookup for `%ZEBRA%QA%` returned none; this naming search is not proof that no other QA-named company exists. There are zero active Workflow records. No dedicated QA site or workflow fixture has been verified. Production company is not an acceptance sandbox.

**Create during the already authorized isolated QA implementation:** `docs/superpowers/specs/2026-10-23-p2-qa-environment.md`; fixture scripts under `tests/qa/` when executing the QA work package, preserving the approved isolation scope.

- [ ] Specify a fresh QA site on an isolated stack/bench with separate database, Redis, file storage, credentials, scheduler queues and Cloud deployment namespace/private workspaces. Do not copy production database/configuration/secrets or reuse a production company as a substitute.
- [ ] Pin the observed app versions plus the candidate plugin image/source revision. Seed only synthetic fixtures, explicitly mark every created object with a UUID ownership ledger, and create QA-only ordinary roles/users and two companies for company-denial tests.
- [ ] Plan fixed QA hostnames/TLS/routing and a native Host issuer/profile binding that cannot target the production site or other Cloud namespaces. Disable external mail/webhooks/integrations and use a local mock recipient where side effects must be tested.
- [ ] Inventory installer/worker/scheduler access, available database/volume capacity and restore procedure without reading credentials into outputs. Record exact resources and rollback/removal scope before provisioning; proceed under the existing implementation approval. Do not execute `bench new-site`, `install-app`, migrations, account changes or service restarts from this investigation.
- [ ] Define an active fixture Workflow with allowed and forbidden transitions, dedicated approvals and revocation cases. A production site with no active Workflow cannot certify workflow behavior.

### Task 7: Publish the operation-level module test ledger

**Modify:** `zebra_erpnext/capabilities.py` only after the ledger schema is reviewed; **create:** `docs/superpowers/specs/2026-10-23-p2-module-acceptance-ledger.md`, focused `tests/qa/` scripts during the approved QA implementation.

- [ ] Preserve DocType/report inventory and all implementation gaps. Add each native entry/controller conversion, its fixed argument contract, current role/company/config prerequisites, side effects, source revision and separate prepared/tested/deployed/live-accepted states.
- [ ] Inventory every installed whitelisted controller and page/menu operation before claiming complete coverage. Classify unreviewed methods as pending implementation; do not expose callable native namespaces or label omissions “not available natively”.
- [ ] Define isolated fixtures for sales quotation→order→delivery→invoice→receipt; purchasing supplier quotation→order→receipt→invoice→payment; stock transfer/count; finance journal/receivables/payables/trial balance/general ledger; BOM/work order/operations/consumption/completion; project/task/timesheet/billing; lead/opportunity/customer/quotation; asset acquisition/depreciation/disposal; quality and support closure. Record native missing application/configuration reasons with evidence.
- [ ] Every chain asserts affected balances, links, quantities, taxes and document state through permission-aware native reads, not just HTTP success or a generated draft. Bind exact approvals/versions, reject unconfirmed writes, prove one execution under duplicate confirmation and fail on revoked access.
- [ ] Keep native import preview/validation/approval, full export/child-table templates, Report Builder/query/script/custom/prepared report cases and administrative settings in separate explicit ledger rows. Existing bounded CSV and stored report descriptors do not certify those paths.
- [ ] Own fixture cleanup by UUID and QA site identity. Never cancel/delete an unowned record, disable checks to remove fixtures or delete original Cloud runs to make a test pass; financial cleanup can retain audit history on the disposable QA site.

## Release and completion gates

- [ ] Independent spec review of contracts and QA topology; independent quality/security review of implementation. Parent orchestrator can use its existing reviewers; no redundant new chat is required.
- [ ] Local checks, native source/schema checks, browser fixtures and authenticated cross-service acceptance are recorded separately. No production write is needed to certify a browser-only unsaved action.
- [ ] Within the user-approved bounded release scope, preserve revision-1 profile and original Task/Run bindings; publish revision 2, bind for new surfaces and deploy a pinned app build. Confirm the actual mounted profile/digests and affected actions on the deployed browser.
- [ ] If reverting, restore the prior profile binding/image for new surfaces; preserve historical sessions/receipts, existing runs, volumes and user drafts. Do not replay lost-ACK actions.
- [ ] Commit only the reviewed changed files under the existing implementation instructions. No commit, deployment, provisioning or business mutation occurs as part of this plan-writing task.

**Completion boundary:** Page package acceptance and isolated module-chain acceptance are separate deliverables. The whole P2 package stays open until the native operation ledger is complete and each named chain has QA evidence or a concrete native prerequisite reason; generic lifecycle support and a list of 19 conversion functions are not whole-module certification.

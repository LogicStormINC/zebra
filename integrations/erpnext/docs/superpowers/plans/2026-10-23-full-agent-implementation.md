# Full ERPNext + Zebra Agent Implementation Plan

> **For agentic workers:** REQUIRED: Use subagent-driven-development for bounded tasks with independent spec and quality review. Do not claim later packages complete based on the first release.

**Goal:** Execute the user-approved full ERPNext/general Agent design with independently usable capability packages and explicit acceptance.

**Architecture:** Preserve Frappe identity/company/document permissions and confirmed business writes. Reuse native Cloud Task/events/artifacts/attachments/memory/extension/schedule authority; expose fixed-purpose Host RPCs only. Existing conversations/runs remain intact; private uploads require user-company workspace isolation.

**Tech Stack:** Current Frappe/ERPNext 16, existing Python app, React/Zebra SDK, GSAP, native Cloud API/Worker.

Approved design: `docs/superpowers/specs/2026-10-23-full-agent-design.md`. Inventory baseline: `../specs/2026-10-23-capability-inventory.json` (metadata only).

## Chunk 1: P0 capability and authority foundation

### Task 1: Private workspace and capability inventory
**Files:** modify `zebra_erpnext/cloud.py`, `chat.py`, `capabilities.py`; create bounded capability helper/tests if needed.
- [ ] Add a runnable check proving new workspace IDs differ by user and company, are opaque ASCII, and never change once bound to an existing Task.
- [ ] Derive new workspace IDs from site/user/company. Do not reuse a workspace from another user just because company matches. Preserve existing Task workspace refs; explicitly label legacy shared bindings in availability.
- [ ] Produce role-aware installed module/DocType/report/action availability, including native-only restrictions and unsupported prerequisites. Pagination must preserve next-page signals after permission filtering.
- [ ] Probe native runtime with Host grants; return safe status/capability flags rather than raw configuration or credentials.
- [ ] Run `python3 tests/test_chat_checks.py` plus focused new checks and native low-permission HTTP acceptance.

### Task 2: Expanded ERP reads/actions without arbitrary RPC
**Files:** `zebra_erpnext/capabilities.py`, `business.py`, `business_actions.py`; focused test files.
- [ ] Inventory safe report descriptors, native imports/exports, collaboration actions, business settings and installed controller conversions; keep explicit limits/reasons for unimplemented entries.
- [ ] Add native, typed, permission-aware operations for missing bounded query/aggregate/export/report-description/document-collaboration paths. Preserve exact approval binding, version conflict, company and field checks.
- [ ] Add reviewed native action mappings where source and target methods actually exist in ERPNext16. Keep module-specific unsupported conditions explicit.
- [ ] Test at least one positive and one ownership/permission or invalid-input failure for each shared operation. Do not create real stock/accounting entries; deep module E2E uses a separate QA site.

## Chunk 2: P1 attachments, resources and runtime surfaces

### Task 3: Native attachments and typed resource backend
**Files:** create `zebra_erpnext/resources.py`; modify `chat.py`, `api.py`, `history.py` as required; focused native tests.
- [ ] Read actual deployed native attachment/artifact/usage contracts. Write a failing check for invalid type/size, request digest binding and cross-conversation artifact access.
- [ ] Validate bounded named file inputs and native attachment shapes; first Task and subsequent message payloads carry identical validated attachment semantics. Store digest in immutable request coordinates; no silent duplicate dispatch on lost acknowledgement.
- [ ] Bind private uploads to verified user-company workspaces. Legacy shared Task cannot receive private uploads until a tested successor mapping exists; expose an honest reason/new-conversation path.
- [ ] Implement fixed-purpose usage, attachment, artifact list/detail/content/download APIs through cloud.owned; forward binary/text safely without exposing credentials. URLs/IDs must be resolved from owned Task/artifact data, never arbitrary URL fetch.
- [ ] Add finite history projection for current/historical resources, public run state and clarification; preserve raw/typed boundaries and no private reasoning/tool secrets.
- [ ] Run focused checks and safe real-Cloud tests with disposable files/tasks; remove only own fixtures.

### Task 4: Attachment, resources and runtime UI
**Files:** modify `frontend/index.tsx`; create focused `frontend/resources.tsx` if justified; extend `protocol.mjs`, styles and browser checks.
- [ ] Reuse AgentComposer upload/preview/remove, AgentArtifacts/AgentAssetPreview, AgentRunStatus/Clarification and usage metrics. Preserve persisted model/reasoning settings and GSAP/reduced-motion.
- [ ] Add a small capability/resources/settings entry with available/unavailable reasons; no placeholder controls claiming unsupported features.
- [ ] Wire typed backend APIs. Pending upload/file reads block premature submit; switching conversations cannot leak pending attachments or stale async results. Add message copy/download via native clipboard/blob APIs without dependencies.
- [ ] Add browser acceptance covering create/follow-up attachment, remove/invalid file, trusted artifact download, refresh, separate conversations, reduced-motion and mobile layout.

## Chunk 3: P2 ERP and page coverage
- [ ] Expand versioned frontend_profile with reviewed list/report/new-draft/read/child-table actions using native page APIs. No arbitrary JavaScript/click/RPC execution. Test route/revision/current-document fencing and idempotent receipts.
- [ ] Complete operation-by-operation native coverage ledger and named module E2E chains in approved spec. A mapped interface is not a certified business chain.
- [ ] Build isolated QA-site fixtures for stock/financial/manufacturing/asset chains; keep actual production company untouched. Track any missing installed app/configuration explicitly.

## Chunk 4: P3 web, analysis, skill and MCP packages
- [ ] Reuse validated native capability presets and configured providers/connectors. Probe deployment and credentials without printing secrets.
- [ ] Apply server-side profile ceilings, protected gateway, fixed scoped extension selection and native Policy/HITL for external side effects; no credentials or ERP database/network bypass in scripts.
- [ ] Verify an actual web search with source links, analysis file production, skills/MCP call and rejected unapproved mock write/revoked connection. No real external messages as tests.

## Chunk 5: P4 knowledge and memory
- [ ] Prove principal/company/deployment isolation before exposing memory/knowledge and automatic context injection.
- [ ] Reuse native memory CRUD and approved file search/index capability. Clearly distinguish full-text retrieval from semantic indexing; do not claim RAG if no supported backend is present.
- [ ] Verify add/search/cite/update/delete, cross-role/company denial, removed permission and subsequent-turn usage with minimal real model calls.

## Chunk 6: P5 schedules and management
- [ ] Add role-aware notification/budget controls and persist capability/skill selection per conversation; selection cannot elevate server authority. Verify native configured ceilings and refresh restoration.
- [ ] Inspect native schedule grant authority/renewal contracts, then enable minimal ERP issuer scopes only. Current short-lived Zebra Grant is not a durable autonomous business-write approval.
- [ ] Build owner/company-scoped create/edit/pause/resume/delete/run-now/history UI and fixed RPCs with version/idempotency binding; next firing rechecks user/permission/connection authorization.
- [ ] Run a short-lived read-only schedule, demonstrate firing/history and no duplicate after restart, then remove it. No recurring real business schedule or outbound message is created as a test.

## Review, deployment and completion gates (each chunk)
- [ ] Spec review then code-quality/security review; fix material findings.
- [ ] Focused checks, existing Node/Python regressions, browser affected flows. Re-run wider tests only after relevant changes or failures.
- [ ] Backup before schema/config migration; build pinned local image, deploy ERP app and only authorized isolated ERP Cloud components. Keep protected secret/config values out of output.
- [ ] Verify deployed asset version, application code, native API state and authenticated cross-service/browser behavior; save evidence under outputs evidence directory.
- [ ] Commit exact changed files; do not push externally. Update ledger with prepared/tested/deployed/live-accepted states and unresolved prerequisites.

No generic “all done” until every approved capability group is accepted or its explicit unavailable prerequisite is reported to the user; implementation gaps remain open work.

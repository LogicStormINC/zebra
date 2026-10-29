# ERPNext Zebra Cloud integration implementation plan

> For agentic workers: use subagent-driven-development for isolated implementation and independent review.

**Goal:** Embed the existing Zebra UI in ERPNext and expose installed ERPNext business functions through user-authorized, discoverable tools and controlled page actions.

**Architecture:** One Frappe app owns ERPNext authentication, permission-aware capabilities, action confirmations, conversation ownership, and a thin Zebra Host adapter. Zebra remains execution/history authority. Reuse the deployed Cloud API/Worker images in ERPNext-specific containers and a separate deployment namespace; register ERPNext as an independent Host; preserve Trench and unrelated services. Use a dedicated signing authority and HTTPS internal integration endpoints. Build the app into an immutable ERPNext image. Do not edit ERPNext/Frappe core.

**Tech Stack:** Frappe 16 / ERPNext 16, Python, React, existing @zebra-agent/react UI, small bundled frontend, existing Cloud HostGrant/AG-UI/tool protocols.

## Chunk 1: Permission-aware ERPNext capability adapter

- [x] Create `zebra_erpnext/capabilities.py` and `zebra_erpnext/business.py`: discover installed DocTypes/fields, query/get, native document lifecycle, workflow actions, reports, attachments/print, published business methods. Dynamic discovery and typed operation dispatch rather than per-page tools. All reads/writes retain user, document, field, company, and report permissions. No arbitrary Python/SQL/JS, guest, ignore_permissions, user impersonation supplied by browser, or unchecked RPC.
- [x] Mutations use a server-generated, expiring approval bound to user, canonical arguments, company and request id. Replays return prior result; state-changing actions are never blindly retried. Use Frappe storage/transactions and native document hooks.
- [x] Add small runnable checks under `tests/`, including permission rejection, private fields, privileged kwargs, digest/approval mismatch, duplicate writes. Run in the installed Frappe environment for actual document lifecycle validation.

## Chunk 2: Host adapter and embedded UI

- [x] Root owns `zebra_erpnext/cloud.py`, `chat.py`, `api.py`, `hooks.py`, app packaging, app-owned DocTypes, and deployment/build files. APIs: bootstrap, conversations, create_conversation, submit, events, snapshot, cancel; frontend uses same-origin Frappe session + CSRF. Store only Host mappings and task/run IDs; read conversation output from Zebra.
- [x] Configure independent ERPNext Host registry/signing key/resource scope. Verify task creation, AG-UI submit/observe/cancel against actual deployed protocol, and business Host gateway under signed caller authority.
- [x] Create one scoped React panel using AgentChat/AgentComposer/AgentConversationTimeline and Zebra stylesheet. Global button, open/close/expand, conversation selection, streaming, stop, reload recovery, tool approval UI. Frontend owns controlled route/form action handlers with revision and current-document checks. No arbitrary scripts or unrestricted click handlers.
- [x] Provide route/document context with bounded, permission-checked data. Expire pending UI operations when the page/document changes. Keep API failures visible and distinct from completed work.

## Chunk 3: Deployment and acceptance

- [x] Build one ERPNext image with app + bundled assets, install app on existing site after backup, retain sites/database volumes, record rollback image/config, and add only required internal HTTPS routes. Keep original running-container manifest for unrelated-service comparison.
- [x] Run deterministic checks, browser administrator login/streaming/WebSocket, read/current-document, create/save/submit/cancel on explicitly marked disposable records where supported, confirmation/replay rejection, low-permission user and cross-user isolation, page navigation, reload recovery, and stop. Use actual model calls only for bounded integration acceptance, never manufacture business records beyond test fixtures.
- [x] Independently review spec compliance then code quality/security; resolve material findings. Document actual functional coverage and remaining module-specific acceptance rather than claiming all installed workflows are certified.
- [x] Save source, operation guide, exact deployed version and acceptance evidence in this project. Do not publish or push externally.

## API contract for frontend/backend work

All RPC methods live under `zebra_erpnext.api` and return Frappe `message` JSON, except `events`, which returns SSE. `bootstrap` returns user, company choices, enabled state, capability summary. Conversation objects have `name,title,company,task_id,active_run_id`. `submit(conversation,message,request_id,context)` returns `{task_id,run_id}`; `snapshot(conversation)` returns `{messages:[{id,role,content}],status,run_id}`. `events(conversation,cursor)` emits AG-UI frames; `cancel(conversation)` requests cancellation. Business RPC is `business.execute(operation, arguments, request_id, approval_token=None)` with metadata/discovery via `capabilities.discover(query=None,doctype=None)`. Write proposals return `approval_required`, `approval_token`, exact operation and arguments; frontend confirms explicitly before execution. Cloud tool calls use the same business dispatch and require the same human approval, never an Administrator API key.

## Known implementation boundaries

The deployed Trench broker lacks the generic authority mode in current source. Do not repoint it to ERPNext; deploy an isolated ERPNext issuer. Current ERPNext is LAN HTTP; integration trust endpoints must satisfy existing HTTPS verification. Shared Cloud history/connector scopes need real cross-Host tests before activation. Existing current-user UI changed during earlier deployment: do not reuse or overwrite a user's live tab for destructive testing.

## Implementation outcome

Direct Frappe/OpenSSL Host issuer; isolated ERPNext API and Worker using the existing pinned images; separate namespace, credentials and history scopes. Dedicated capped workspace mount, same SDK packages and UI. All source is independent of Trench and ERPNext/Frappe core. Detailed deployed proof and limits: `docs/acceptance.md`. Browser document-open and unsaved form-fill passed with accepted durable receipts, actual route/form inspection, independent stored-document checks, and complete model responses.

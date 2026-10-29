# ERP Agent workbench A — approved design

The user approved direction A on 2026-10-28 after viewing the interactive Trench-style preview. This approval authorizes implementation and deployment; no additional design handoff approval is needed for this scope.

## User experience

- Fullscreen uses a quiet left session sidebar, a single compact header, a readable central conversation and a sticky Trench composer. Business review/resources open on demand in a right drawer. A compact embedded mode remains available.
- Sidebar supports search, new, switch, rename and delete using existing owned-conversation APIs. Company context lives in the sidebar/header without multiple stacked toolbars. Keep per-conversation model/reasoning persistence.
- Retain native Markdown rendering, tables with their own horizontal scroll, code blocks, sources, existing safe files and local copy/export. Primary answer controls are compact; secondary controls live under More. Do not add fabricated metric cards from prose; preview numbers were example content.
- Show one compact truthful task state, with skeleton/loading, streaming, ready/queued/running, stopping, waiting for input/approval, completed, disconnected and failed states. Connection loss retains drafts and the exact pending request identifier. Reconnect observes existing work and never automatically repeats a business/model request.
- Approvals show target, operation, company and actual proposed changes. Read current values through the existing permission-scoped business get RPC when useful. Missing/unreadable current values are explicitly unknown. Child row deletion/reordering must be visible; exact raw parameters remain available. Native confirmation is unchanged and can occur only after an explicit user click. Show a concise receipt from the actual server result with an ERP document link, never a fabricated success or a full JSON banner.
- Switching conversations retains unsent text in memory and cannot display another conversation's async errors, drafts or confirmation results. No private drafts in shared/global persistent storage.
- Desktop and mobile maintain a visible composer and independent content scrolling. Overlay drawers support Escape/focus restoration. Icons have accessible labels and keyboard focus states. Existing GSAP handles structural transitions and microinteractions; streaming text, old history and repeated class changes do not replay entrance animations. Respect reduced motion.

## Boundaries and reuse

Use existing React/Zebra shared components, Frappe/standard browser features and installed GSAP. No new dependency, backend schema, Agent/ERP business permission or general-Worker change. API105, the recovered dedicated Worker, HRMS and existing business/Task data remain intact.

The live frontend equals `work/maintenance-ux-live/index.after.tsx` and `protocol.before.mjs` with deployed JS SHA256 `df44a50787877aea7017a6959583eac201cf220b416153e547383fe62039b4bc`. Local index additionally contains an unactivated retryFresh handler; local protocol only adds read-only Fresh status projection. Preserve the prepared retry source, but do not expose its mutation callback on native105 without an explicit supported capability. Do not deploy unreleased Host Python sources.

Existing same-origin RPCs can use native fetch plus the current Frappe CSRF token to avoid duplicate framework error dialogs; never relax cookie/CSRF or parse raw server stack traces into UI. Error messages render as bounded text. Unsupported attachment/command/MCP controls are hidden or explained on demand.

## Acceptance

Run existing Node checks and a focused new regression for busy ready/created states, stale async results, approval diff including removed/reordered child rows, unknown current fields and confirmation summaries. Browser-check the built app at 1440×900 and 390×844 (actual emulated viewport), long Markdown/table/code, session CRUD/settings, IME/Enter, delayed confirmation across a session switch, unknown submission/reconnect, stop double-click and reduced motion.

Build/deploy only the reviewed static bundle/CSS and asset version on the currently running Host image, initially `sha256:334476c787296a08fa4018ec18017062063490cdab0639809a2a2b6faabbad1d`. Capture current images/config and rollback metadata. Keep backend Python/API/Worker, registry, database and business volumes unchanged. Verify served asset hashes and real authenticated read/chat through the deployed app; use only new owned acceptance conversations. Do not repeat production-plan writes to manufacture UI acceptance.

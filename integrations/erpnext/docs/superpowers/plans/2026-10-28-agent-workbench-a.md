# Agent Workbench A Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Ship the approved Trench-style workbench A on ERPNext with correct conversation, state and human-confirmation interactions.

**Architecture:** Reuse the current shared Zebra components and same-origin Host APIs. Keep the recovered native105 backend intact. UI-only helpers centralize task busy-state and approval preview/receipt formatting; a bounded approval drawer owns review while Panel retains existing admission and session lifecycle.

**Tech Stack:** Existing React 19, Zebra UI packages, GSAP, browser fetch/CSRF, esbuild and stdlib Node assertions. No new dependency.

---

## Chunk 1: Implement and verify the complete bounded UI

### Task 1: Frontend A and root interaction fixes

**Files:**
- Modify `frontend/index.tsx`, `frontend/style.css`, `frontend/answer.tsx`, `frontend/motion.ts`.
- Reuse `frontend/protocol.mjs`; modify its status adapter only as needed.
- Add `frontend/workbench-state.mjs` and `frontend/workbench-check.mjs` for pure busy-state/approval-preview/receipt guards.
- Add `frontend/approvals.tsx` if needed to keep the review drawer out of the large Panel; avoid a generic component framework.
- Modify `package.json` test script to run the new check; ignore `.superpowers/` workflow state.

- [x] Run baseline `npm test`, inspect all callers of `isActive`, confirmation, send, select and protocol runStatus.
- [x] Add a failing stdlib assertion for native ready/created busy states and child-row removal/reorder in approval preview. Run `node frontend/workbench-check.mjs`, record the expected failure.
- [x] Implement the shared busy predicate, guarded confirmation results and memory-only per-conversation drafts. Preserve exact unknown-result request IDs and maintenance guard. Never retry a POST automatically. A supported capability must gate the unactivated retryFresh callback.
- [x] Implement the approved A layout and approval drawer with real current values from existing business get, human-readable differences, exact JSON fallback and real result receipt. Use existing Frappe document navigation. Keep native confirmation request identical.
- [x] Use native fetch for same-origin RPC with `credentials: 'same-origin'`, `Content-Type: application/json` and current `X-Frappe-CSRF-Token`; reject unsafe method paths. Surface one bounded inline error, preserving the exact pending request after uncertain responses. No global Frappe error popup.
- [x] Consolidate answer actions, source/resource access and input controls. Keep Markdown safe and tables independently scrollable. Never add fake stats or enabled controls unsupported by the capability catalog.
- [x] Limit GSAP to new structural UI and pointer/focus feedback; suppress activity class-flash and history/token reanimation. Include drawer/sidebar keyboard and reduced-motion behavior.
- [x] Run `npm test` and `npm run build`; test the actual built bundle with a deterministic browser RPC fixture (clearly isolated from production). Cover desktop/mobile layout, conversation switching while confirmation is delayed, model persistence, composer Enter/IME, stop/reconnect/ready, Markdown and approval diffs.
- [x] Independent SPEC then QUALITY review; address concrete failures before server activation. Keep implementation in this existing authorized checkout; preserve inherited `cloud-patches/fresh-slice-sha256.json` and all other work.

### Task 2: Parent-controlled deployment and actual acceptance

**Files:**
- New versioned static deployment context under `work/` with a Dockerfile based on the verified current Host image.
- Update public delivery evidence and `docs/superpowers/full-agent-progress.md`.

- [x] Verify current Host JS/CSS/hooks, image IDs, service status and config hashes using SSH metadata. No secrets in argv, logs or local files.
- [x] Capture rollback override/settings and existing served assets. Build an immutable Host layer containing only reviewed JS/CSS and a narrowly versioned asset hook. Do not copy local Host API/business/contract code.
- [x] Recreate only backend/frontend, clear native cache; do not migrate or restart Agent Worker/API/general Worker/Trench/XGO.
- [x] Verify served bytes and fresh authenticated bootstrap/history in the browser. Use a new owned conversation for a bounded actual chat/ERP read; no automatic model/business replay and no additional plan writes.
- [x] Record actual test boundaries and source/image hashes. Commit exact owned files without pushing; retain inherited untracked work.

The user's “按A落地” already authorizes execution and deployment of this approved design. Proceed after the reviews without another permission round.

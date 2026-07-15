# UI Workspace

`UI/` contains frontend-only workspaces for Zebra Agent.

Current workspace:

- `desktop/`: Tauri + React + Tailwind CSS + TanStack Query + Ant Design + Ant Design X desktop operator shell

Current live frontend integration:

- API health probe against `/health`
- approval inbox against `/approvals`
- approval detail against `GET /approvals/{id}`
- session creation against `POST /sessions`
- session message append against `POST /sessions/{id}/messages`
- bounded UTF-8 text attachment selection for both writes, with at most four
  files, 64 KiB per file, 128 KiB aggregate, removable pending chips, actionable
  validation errors, successful-submit clearing, and safe metadata readback
- approval decisions against `POST /approvals/{id}/approve` and `POST /approvals/{id}/reject`
- session controls against `POST /sessions/{id}/suspend`, `POST /sessions/{id}/resume`, and `POST /sessions/{id}/cancel`
- local commit delivery against `POST /sessions/{id}/commit`
- pull request planning or execution against `POST /sessions/{id}/pull-request`
- session detail lookup against `GET /sessions/{id}`
- event replay readback against `GET /sessions/{id}/stream`
- workspace diff readback against `GET /sessions/{id}/diff`
- repo memory inventory against `GET /sessions/{id}/memory`
- user and tenant memory inventory against `GET /users/{id}/memory` and `GET /tenants/{id}/memory`
- cross-scope memory overview against `POST /sessions/{id}/memory-overview`
- memory governance signals against `POST /sessions/{id}/memory-governance`
- memory pressure action hints against `POST /sessions/{id}/memory-action-hints`
- memory backlog pressure signals against `POST /sessions/{id}/memory-pressure`
- memory pressure escalations against `POST /sessions/{id}/memory-escalations`
- memory follow-up windows against `POST /sessions/{id}/memory-follow-up-windows`
- memory overdue flags against `POST /sessions/{id}/memory-overdue-flags`
- memory overdue age buckets against `POST /sessions/{id}/memory-overdue-age-buckets`
- memory overdue type rollups against `POST /sessions/{id}/memory-overdue-types`
- memory overdue visibility rollups against `POST /sessions/{id}/memory-overdue-visibility`
- memory overdue trend signals against `POST /sessions/{id}/memory-overdue-trends`
- memory overdue intervention hints against `POST /sessions/{id}/memory-overdue-interventions`
- memory overdue escalation lanes against `POST /sessions/{id}/memory-overdue-escalation-lanes`
- memory overdue recovery paths against `POST /sessions/{id}/memory-overdue-recovery-paths`
- memory overdue resolution checkpoints against `POST /sessions/{id}/memory-overdue-resolution-checkpoints`
- memory overdue resolution outcomes against `POST /sessions/{id}/memory-overdue-resolution-outcomes`
- memory overdue closure decisions against `POST /sessions/{id}/memory-overdue-closure-decisions`
- memory overdue archive recommendations against `POST /sessions/{id}/memory-overdue-archive-recommendations`
- memory overdue retention guidance against `POST /sessions/{id}/memory-overdue-retention-guidance`
- memory overdue retention windows against `POST /sessions/{id}/memory-overdue-retention-windows`
- session, user, and tenant queue summaries against `GET /sessions/{id}/memory/queue-summary`, `GET /users/{id}/memory/queue-summary`, and `GET /tenants/{id}/memory/queue-summary`
- direct memory review decisions against `POST /sessions/{id}/memory/{memory_id}/confirm` and `POST /sessions/{id}/memory/{memory_id}/expire`
- scoped queue preview, queue sweep, and bulk memory review against `POST /*/memory/review-queue-preview`, `POST /*/memory/review-queue`, and `POST /*/memory/bulk-review`
- artifact list, detail, and content reads against `/sessions/{id}/artifacts*`
- artifact prune control against `POST /sessions/{id}/artifacts/{artifact_id}/prune`
- delivery audit readback against `GET /sessions/{id}/delivery-audit`

This directory is intentionally isolated from the Python workspace so frontend tooling does not leak into the core agent runtime.

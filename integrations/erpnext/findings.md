# Capability integration findings
- Screenshot is ERPNext resources.tsx, backed by features.py.
- Current catalog hardcodes web/extensions/knowledge/schedules=pending.
- Task creation hardcodes research/read_only/none; grant only agent.run/erpnext.read/artifact.read.
- Resources resolve only active segment; no extension/knowledge/schedule BFFs exist yet.
- Native105 ERP is a pinned custom runtime; newest Cloud code cannot be blindly copied.
- Prior P3-P5 plan describes exact Native scope requirements and separate private-filesystem/S3 gates. Its old acceptance must be refreshed from actual deployment.
- Root repo dirty/untracked files and ERP cloud-patches/fresh-slice-sha256.json are preserved.

- Refreshed live facts: API105 image6e4b2cdfa32b; dedicated readonly Worker812202f8891b; active ready1/waiting_input1, no running. No restart permission inferred from idle running count.
- All104 applied migration version/name/checksum tuples match cloud-agent8b4da99f through105; target adds106–114.
- Historical private-HTTP prototype used its own migration106. The actual live ledger remains105. Do not apply that prototype106 beside mainline106 host_manifest_binding_policy.
- User explicitly approved backup, isolated migration and compatibility validation; no live database/API/Worker cutover yet.
- Local generic Host chat.py differs substantially from the deployed chat-recovery/host overlay; runtime source must be frozen and compared, not blindly deploy local root.

- Isolated migration passed:138 original tables preserved by original columns, target151 tables, exact114 ledger and repeat migration idempotence.
- Native reads passed22 Task bindings/132 scope refusals/3791 events/39 bounded pages; read-only all151-table parity.
- Real TCP HTTP/RS256/native DB11 cases passed using ephemeral QA keys. Owner reads200, unsigned401, wrong workspace404, expired403, missing extensions.read403.
- Historical usage409 required existing explicit bounded summary preparation on22 Tasks; only two derived summary tables changed. No Task/model replay.
- Production configured physical-runtime image is absent. A genuine cached pinned Python3.12.12 candidate cold-started under gVisor435.6ms/UID65532/caps0/networknone; full Native quota/workspace/analysis still pending.
- Seven product capabilities are NOT yet fully connected or activated. See docs/ERP_CAPABILITY_RELEASE_20261028.md for exact next gates.

## Full capability implementation boundary2026-10-28
The actual running ERP Host has an independent readonly chat implementation and
Production Plan-only proposal manifest. Its cloud grant has exactly agent.run/
erpnext.read and1-byte Artifact budget. Root source has newer lock/fresh retry
paths and must not replace old dispatch blindly. New runtime_ref is immutable
per Conversation; missing means native105. New release selection requires both
enabled and acceptance_passed from server config. Management/model preferences
merge without deleting capability selections. All new/full functionality remains
unactivated while S3/quota/schedules and actual compatibility are incomplete.

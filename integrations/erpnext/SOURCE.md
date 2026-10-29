# Source of truth

This directory is a synced export of the Zebra ERPNext integration app.

- Canonical repository: https://github.com/LogicStormINC/zebra-erpnext (private)
- Synced from branch `main` at commit `b22d412` (2026-10-29)
- It contains the Frappe app (`zebra_erpnext/`), the embedded agent workbench
  (`frontend/`), deploy tooling (`deploy/`), tests, and the pinned cloud
  runtime overlays (`cloud-patches/`) used to build the ERP host images.

2026-10-29 changes carried in this sync: zebra rebrand + monochrome theme,
componentized settings console (plugins/tools/files/knowledge/schedules),
full frontend profile revision-2 page-control actions, full-runtime browser
chat BFF fixes (surface grant namespace, versioned client-state contract,
client-session header), plugin proxy RPCs, and the stop/delete stuck-state
fixes. Update this export with `git archive` from the canonical repo.

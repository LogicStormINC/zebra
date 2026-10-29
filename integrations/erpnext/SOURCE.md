# Source of truth

This directory is a synced export of the Zebra ERPNext integration app.

- Canonical repository: https://github.com/LogicStormINC/zebra-erpnext (private)
- Synced from branch `main` at commit `2e8606a` (2026-10-29)
- It contains the Frappe app (`zebra_erpnext/`), the embedded agent workbench
  (`frontend/`), deploy tooling (`deploy/`), tests, and the pinned cloud
  runtime overlays (`cloud-patches/`) used to build the ERP host images.

2026-10-29 delivery carried in this snapshot: zebra rebrand + monochrome
theme, componentized settings console with plugin market, frontend profile
revision-2 page-control actions, full-runtime browser chat BFF fixes (surface
grant namespace, versioned client-state contract, client-session header),
plugin proxy RPCs, stop/delete stuck-state fixes, and the copy-session-id
menu action with a hardened clipboard interaction. Update this export with
`git archive` from the canonical repo and refresh the commit above.

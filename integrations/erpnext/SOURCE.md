# Source of truth

This directory is a synced export of the Zebra ERPNext integration app.

- Canonical repository: https://github.com/LogicStormINC/zebra-erpnext (private)
- Synced from branch `codex/erp-auth-export-20261102` at commit `cf190d309bb255820b926295bd8c15ff8928298e` (2026-11-02)
- Source gate fix: `439fb72`; validation evidence: `docs/evidence/ca-baseline-gate-02/source-validation.json`
- Canonical main now contains current deployed ERP capabilities and this authentication repair (publication `c418ecaec7e601f2968a06b7cc1a26fba9b2dae9`).
- This export retains the Gate02 reviewed compatibility lineage; build normal ERP Host releases from canonical main, not by replacing them with this older compatibility tree.
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

CA-BASELINE-GATE-02 exports the reviewed source through git archive, including
cohesive App/Runtime/tool modules and exact construction closure. Original
frozen manifests/deployment evidence/native baseline Python remain unchanged;
versioned source projection separately verifies archived originals and candidate
bytes. Current119 offline compatibility is not deployed105 or migration acceptance.
No deployment or production data transfer was executed.

Migration authentication audit: browser_origin and signed authority origin are separate;
legacy manifest shares the aggregate metric contract, bootstrap transport uses configured
ingress, and the no-network release preflight rejects stale source overlays. The exact
source export keeps Gate02 size/Ruff rules and original frozen manifests. No Runtime
execution code or historical data was changed by synchronization.

2026-11-02 focused allocator parity port: canonical878ed20
(`codex/erp-allocator-refusal-20261102`) supplies the signed refusal, bounded helper
budget, safe diagnostic and exact bind-detection repair. These changes are ported
into this existing split compatibility tree, not a replacement of its frozen
originals or an assertion that this entire directory equals canonical main.
The matching standalone checks are retained; deployed117 acceptance used the
canonical source overlay recorded in the focused Cloud incident document.

2026-11-03 reply robustness parity: canonical `388131c` based on `878ed20`.
The focused split port retains existing compatibility profiles and frozen originals.
Generic receipt recovery, full read parameter schemas, bounded discovery and safe
startup timing are ported into their current responsibility files. The complete
canonical delta (including its newer force-stop adapter and frontend acknowledgement)
is retained in `cloud-patches/reply-robustness-20261103.patch`; it applies to the
canonical878ed20 tree, not to the split export. Rebuild frontend with its existing
locked dependencies; generated JS is deliberately not duplicated inside this patch.
Production117 uses that canonical overlay. This port does not imply that old split
adapter lifecycle/admin features equal all later canonical capabilities.

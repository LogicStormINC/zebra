# Cloud extension inventory correction

CLOUD-EXTENSION-INVENTORY-01, locally delivered 2026-10-20.

`extensions.list` previously treated configuration as execution availability:
MCP `catalog_verified` was always false and every authenticated record suggested
refresh; enabled Skill installations could be listed even when not mounted in
this Turn, leading to an unnecessary `skills.read` failure.

The existing MCP selection checker now lives in agent-core application and is
reused by the API and management tool. Its exact scope/configuration/auth/tool
checks remain; a selected connection loads its pinned stored digest, not a newer
catalog. Missing catalogs report false; missing checker configuration reports
unknown. Integrity/backend errors remain redacted tool failures, never verified
success. Reads do not refresh/discover or send MCP frames. Verified catalog
metadata is not a claim that a remote tool was executed or that future execution
authority, DNS/SSRF or cancellation checks may be skipped.

Skill records keep installation metadata and add `installed`,
`available_this_turn`, `unavailable_reason`, and `read_name`. A readable name is
present only for an enabled exact installation/revision/version in the frozen
Turn snapshot and the actual prepared live Skill catalog. Disabled, unselected,
changed or unavailable records never invite reading by name. This changes no
selection or permissions. Worker execution and management share one prepared
catalog; live Plugin revocation and the existing fresh permission/lease authority
are checked. Writes still apply to future eligible Turns and do not acquire new
post-write catalog I/O; their unverified metadata stays unknown.

Validation: 158 focused tests passed, 1 existing skip; Ruff clean; full Mypy1318
and file gate3218/0violations passed. Tests cover mounted/unmounted Skills, disabled
or changed versions, missing live catalogs, pinned digest mismatch, missing or
foreign MCP configuration, unknown status, denied authority, Plugin revocation,
shared Worker wiring, and existing API/Skill/MCP lifecycle compatibility.

Built an offline same-base Worker layer with five verified source hashes. Idle
check showed zero leases/pending commands before replacing only Worker. Updated
Worker `9e809d7c44b6` is healthy, startup has no errors; image
`zebra-worker:cloud-extension-inventory-01`. Environment, security, resources,
mounts, network and startup configuration are unchanged. APIs/Search/TLS were not
recreated, original Search PIDs/cooldown/MCP process preserved.

Updated-Worker operator read-only metadata inspection of real stored records
returned MCP verified=true/tool_count=1/no refresh advice; two installed Skills
correctly marked not_selected_for_turn or disabled, both without read names.
That inspection uses no fabricated active Run or lease and is not claimed as
live Run execution-authority E2E; deterministic tests cover that boundary.
Before/after protection captures are exactly equal:17extension heads,126snapshots,
model/tool counters,2originalpartialTurn status/body/request/metadata hashes,
Search identity/PIDs/cooldown; zero leases/pending. No new Run/model/search/remote
MCP request, Trench logic change, push or remote deployment.

Evidence/scripts: primary checkout `.artifacts/cloud-extension-inventory-01/`.
`update_worker.py` is consumed; do not rerun activation. `verify_services.py` and
`capture.py` are read-only. The optional Docker inspect `Init` field was absent on
Search; final verification treats absent optional values as null without another
service mutation.

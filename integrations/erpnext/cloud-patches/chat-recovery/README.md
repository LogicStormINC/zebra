# Native105 ERP chat and Production Plan approvals

This folder consolidates the exact deployed source overlays. `provenance.json`
records independently reviewed source freezes and activated image IDs. All 27
production files were compared with the running API, Worker and ERP Host.
The consolidated Docker recipes have the same files as those reviewed layers;
the deployed images retain their original layer history.

The dedicated Worker admits only the new signed ERP chat source generation.
It retains native Task admission, binding, Fresh authorization, Lease, Attempt,
event recorder, SQL extension snapshot, SQL provider continuation and derived
checkpoint handling. It exposes plan/clarify, ERP discover/read and optionally
Production Plan approval preparation. It has no physical workspace, Docker
socket, command runtime or Artifact payload strategy. Old Tasks are preserved.

`erpnext.propose` prepares an approval record. It cannot confirm one. Independent
authenticated cookie and CSRF confirmation performs the native ERP transaction,
with permissions, company, payload digest, expiry, document modification check
and idempotent receipt retained. Only Production Plan create/update/submit are
enabled in this deployment; native ERP pages remain available for other work.
Explicit approval-preparation requests use the existing native answer/evidence
contract: a genuine successful Host-tool receipt is required, a file Artifact is
not. Pending approval never means the business mutation has completed. The
conservative intent route is bounded to 4000 characters; ambiguous or mixed
requests retain native inference. Structured Host intent is the upgrade path.

Recovery fixes resolve the actual published connector in API105, recover the
real bound empty extension snapshot, permit explicitly frozen read tools without
Effect payloads, compile authoritative Context without a physical directory,
and use native incremental projection routing instead of repeated full-history
source backfill. Tool schemas publish the existing validator's argument names
and bounds, including `aggregate.metric` and the 50-row query maximum.

## Rebuild prerequisites

Use local tags whose image IDs have first been checked against these bases:

| Build argument | Required image ID |
|---|---|
| WORKER_BASE | sha256:fbdfb5d3cbbabc360342b86841d4c0a83fc52098bacc47ed189fdf2a6f5fe3b9 |
| API_BASE | sha256:2156443eea6ad9330853d16ece204dfa0995a41e5b5b677063386216797daaef |
| HOST_BASE | sha256:ba23a96a08671aba0766f111876f1b60e72a8e4a17f9dc5d1c5e5d30ef2070b4 |

Build the three Dockerfiles using those verified tags and `--network=none`.
Do not pull a repository named `sha256` or migrate the database. Native105 has
104 migration records because version 71 is intentionally absent; compare the
entire version/name/checksum ledger, not the number of rows.

Keep the dedicated chat service's nonroot/read-only/cap-drop configuration and
its three public CA mounts. The original general Worker stays stopped. Keep
private environment and settings files on the server; never commit credentials.
The chat service requires the existing containment/Fresh/site flags plus
`ZEBRA_ERPNEXT_CHAT_READONLY=enabled`. The optional approval flag is
`ZEBRA_ERPNEXT_PRODUCTION_PLAN_PROPOSALS=enabled`. Host settings use strict booleans
`chat_readonly_enabled` and `production_plan_proposals_enabled`.

After changing the published Host manifest, publish a new native connector
profile and binding and use a new conversation. Do not rewrite frozen bindings
on previous Tasks. Keep attachment admission disabled. Release maintenance only
after the services are ready, then verify using real authenticated HTTP, native
events and actual ERP records. Preserve failed acceptance attempts.

## Small runnable regressions

Run from this folder:

```sh
python3 check_proposals.py
python3 check_effects.py
python3 check_context.py
python3 check_projection.py
python3 check_approval.py
```

These are isolated stdlib source checks. They cover actual guard branches,
published parameter bounds, human cookie/CSRF checks, default payload behavior,
nullable Context roots and incremental routing. They do not invent production
permissions, successful model calls, approvals or Task lifecycle evidence.
Live acceptance results are recorded in the delivery evidence and progress log.

`check_api105_native.py` additionally runs inside the API105 image with a captured
public connector-profile/manifest packet on stdin. It exercises the actual
native binding builder, five drift refusals and default caller compatibility,
with no database or provider calls. The accepted public manifest digests are
pinned; resource-rule order is preserved rather than alphabetically reordered.
`check_approval_native.py` separately reads an owned acceptance Task's real
canonical proposal events in a read-only transaction. It proves the existing
native parser/quality gate accepts successful approval-preparation evidence,
rejects missing evidence, and leaves the original Artifact inference unchanged.

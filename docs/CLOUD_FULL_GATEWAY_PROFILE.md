# Cloud full-gateway authority

`full-gateway` is an explicit, durable Task network profile for Cloud Agent
tasks that need both Web tools and MCP proxy tools. It is **not**
`full-trusted-local`: the latter remains a local-operator mode and must not be
used as a Cloud shortcut.

- Web fetch/crawl/extract use the existing HTTPS-only, public-host, no-redirect
  HTTP gateway. Search requires a configured `ZEBRA_WEB_SEARCH_ENDPOINT`; the
  native pipeline may fetch individual search results through the same gateway.
- MCP calls still route through the MCP proxy and retain the existing approval
  decision. Host tool visibility and Host data access remain bound to signed
  scopes and resource references.
- OCI/gVisor sandboxes keep `--network none`. This profile does not grant shell
  commands a direct network route, bypass Host permissions, or waive policy
  checks, resource limits, output bounds, or audit events.
- Existing Tasks retain their frozen profile. A Host must create a new Task
  generation when switching to this profile. PostgreSQL migration v60 widens
  only the profile constraint; it does not rewrite historical Tasks.

Release requires both Zebra API/Worker and Host clients to be upgraded. Apply
v60 before admitting `full-gateway` Tasks, configure a reachable HTTPS search
endpoint if search is required, and run a real Cloud task through Web fetch,
search, MCP approval, and Host read/write authorization before rollout.

The Host probes `GET /capabilities/runtime` with its own single-use Host Grant
before creating a new Task. A second Grant is required for `POST /tasks`:
reusing the probe Grant binds it to the wrong method/path and yields 403.
The probe declares contract version, required schema version and accepted
network profiles; a missing or incompatible probe blocks Task creation while
keeping the Trench conversation intact. Existing Tasks are not re-probed.

Local incident acceptance on 2026-10-01: the old API accepted neither the
profile nor PostgreSQL v60. After applying v60 and replacing both API and
Worker with matching images, an existing conversation resumed. A new Task
initially failed 403 when the probe Grant was reused; after separate Grants,
the same new conversation successfully created and completed a Task. The
production release gate remains separate: verify the deployed Worker image,
the database version and one real new Task, not only `/health`.

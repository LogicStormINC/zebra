# Cloud extensions rollout checklist

Status: local API/Worker activated; authenticated management/catalog and real
Trench Agent MCP fetch verified. Remaining broader rollout gates are below.
This document complements cloud-mcp-catalog.md, not a new runtime design.

## Execution closure (2026-09-09)

Real Trench flow materializes the human message before AG-UI RUN. Forward the
verified grant/admission through AG-UI and bind RUN/RESUME to that existing Turn,
not a second message. Atomic PostgreSQL append and the post-commit publishing
decorator must both support the binding. Resume recovers the same snapshot;
configuration changes apply on the next Turn, not by mutating an active one.

Cloud aliases must satisfy model-provider normalization: server hash shortened
to 24 hex characters gives 63-character provider names; retain collision checks
and original remote tool/connection identity. No endpoint or credential change.

Trench task network profile is now mcp-proxy-only, not none or full-trusted-local.
Exact snapshot selection, current-user authority and live per-frame checks still
apply. Trench generation trench-native-v10 and task key v11 avoid silently reusing
old frozen no-network tasks; never rewrite an existing runtime authority digest.

Authenticated browser conv_1788883798514_259bde -> session
acb66aa8-c137-4a54-bed4-1fe9a08cbcfb: policy allow, executed MCP SSE fetch with
actual example.com response, streamed model deltas, completed Turn and title.
Elapsed about 19 seconds; remote fetch accounted for most of it. Focused tests:
64 admission/recovery/PG, 12 publication, 21 MCP transport, 23 Trench runtime
passed; one optional live transport test skipped. Mypy 907 source files passes.
Same-conversation no-tool reply also passed; browser reload retained both replies,
semantic title and the exact conversation route. No tool call was requested for
that ordinary-chat regression.
This is one real-user public-page acceptance, not full multi-user/revocation or
Skill-upload acceptance. Those checklist gates remain open.

## Live rollout evidence (2026-09-08)

- Applied v51-v56 with the existing migration runner: current schema v56,
  original 250 session streams preserved. No original tables cleared.
- API and Worker rebuilt with paired extension switches and read-only operator
  key mount; health checks passed with zero restart loops. Key bootstrap is
  exclusive-create and retains an existing valid key. Never regenerate it.
- Broker only added extensions.read/manage. Its running workload secret and
  TTL were retained in memory during compose recreation, not replaced with
  the different values/defaults in the older env file. Future Broker recreation
  must preserve those live values too; the env file discrepancy is unresolved.
- Production Host authorizer previously required agent.run for every endpoint.
  It now requires operation-specific extension scopes for extension paths;
  ordinary execution retains its original requirement. Signed PostgreSQL tests:
  8 passed, including denied read-to-write and extension-to-session escalation.
- Trench BFF management grants now omit unrelated history resource refs.
  Backend focused regression: 30 passed. Settings tests: 4 passed after fixing
  catalog refresh to send no body, as required by the API (not an empty object).
- Trench API was absent on port 8000. Restored with the existing local launcher,
  localhost TLS endpoints and matching Worker host-tool credentials. Original
  browser login/session list recovered. A temporary incorrect broker hostname/
  port combination was corrected to the launcher's broker.localhost:8444.
- Real browser: MCP list, connection creation, enable and reload passed for
  the user's requested SSE server. Anonymous management returns 401.
- API-container public TLS, SSE discovery and full catalog parsing passed
  (one tool); Worker DNS resolves public IPs. Governed refresh initially returned
  503, then a manual retry succeeded (200) and one catalog version persisted.
  Added exception-type-only diagnostics; transient 503 root cause is unconfirmed.
- Real browser new conversation requested MCP fetch, but Agent correctly
  reported it unavailable. Database has zero turn_extension_snapshots.
  Root code gap: RouteAdapter does not pass admission into handle_agui_command;
  AG-UI submits RUN/RESUME while submit_session_command only admits MESSAGE.
  Connecting only a keyword argument is insufficient: RUN/RESUME turn identity,
  replay, pending-command handling and Worker recovery need regression checks.
  No Worker MCP execution success is claimed. Test conversation:
  conv_1788882003217_38aee7. Normal reply and title persistence did work.
- Skill upload and MCP credential/deletion UI remain outside delivered scope;
  existing Skill listing/toggle are present. No complete feature claim.

## Pre-activation findings (historical)

- Existing compose.application.yml does not pass extension switches or mount
  the operator MCP key. Setting only host environment variables is insufficient.
- Running acceptance API/Worker were built before the extension rollout.
- Last database preflight found schema v50, without extension/catalog tables.
  Recheck immediately before migrating; this is not a current migration claim.
- Acceptance broker scope list omits extensions.read and extensions.manage.
  Configuration routes require those signed scopes; agent.run alone does not
  authorize reading or changing extension configuration.
- Active Trench BFF/settings have not delivered Skill/MCP management. A raw
  successful adapter call does not demonstrate the UI or Worker authority path.

## Prepared overlay

Append docker/compose.extensions.yml to the SAME project, base files and ignored
environment file used for the running installation. Do not accidentally create
a second project or replace the deployment namespace/database environment.
The overlay adds API read/manage/publication/refresh/admission and Worker
extension/Skill/MCP recovery switches. It preserves base socket/workspace mounts.
It does not alter the broker, network policy, database, or existing sessions.

Required operator environment (no secret values belong in Git):

- ZEBRA_MCP_SECRET_HOST_ROOT: existing absolute dedicated key directory.
- ZEBRA_MCP_KEY_HANDLE: key handle relative to that directory, without .json.
- ZEBRA_MCP_KEY_VERSION: matching key document version.

Inside both services the directory is read-only at /run/zebra-mcp-secrets.
The existing mounted_mcp_protector verifies the handle/version and a base64
32-byte master key; key files must be 0400/0600 and readable by container UID
65532. Check permissions FROM INSIDE the container, not only on macOS.
Do not mount this directory into agent sandboxes, source uploads or browsers.
Docker must not auto-create a missing secret directory. Preserve the same key
across restarts; replacing it makes existing encrypted credentials unreadable.

## Activation sequence

1. Finish Trench settings/BFF management, using signed current-user grants.
   Grant Broker and registered Host ceiling must both allow the explicit
   extensions.read/manage operations. Preserve all existing scope restrictions;
   do not mint blanket scopes or send browser cookies to external MCP services.
2. Verify actual env/project, existing secrets, current schema and no active
   Turns before controlled restart. Render Compose privately; rendered output
   contains secrets and must not be published as a test artifact.
3. Build matching migrate/API/Worker images. Use existing zebra-migrate service
   to run the reviewed, lock-protected migrations against the intended database.
   Migration failure blocks API/Worker activation; never drop tables to recover.
4. Start API/Worker together with the overlay. Keep existing other services and
   environment unchanged. Verify health, a normal conversation and native tools.
5. In Trench settings add the user's SSE connection, refresh its tool catalog
   and enable it. Keep the private URL out of tracked fixtures and documentation.
6. Send a new Turn requesting a public webpage. Verify selected snapshot,
   Worker tool execution, remote content, streamed response and persisted result.
7. Verify user B cannot list/use user A's connection; revoke during execution;
   verify new calls are denied, no credential reaches responses/logs, and normal
   chat still works. Reload settings and restart Worker to verify persistence.

Removing the overlay on BOTH API and Worker returns to extension-disabled
composition; keep migrated tables and encrypted credentials. Do not claim an
in-flight extension Turn is resumable after disabling its required runtime.

## DNS acceptance boundary

Host adapter testing succeeded after a single-host Mihomo fake-IP exclusion.
Do not assume containers share host DNS results. Check resolution from Worker:
configured MCP hosts must resolve to public addresses, retaining pinned sockets
and redirect rejection. Do not whitelist the 198.18.0.0/15 benchmark range.

## Reproducible configuration check

```sh
pdm run pytest -q tests/compose/application/test_extensions_overlay.py
```

Uses docker compose config with fixture variables and --env-file /dev/null;
starts no services, reads no operator env file, and does not migrate databases.
Checks paired execution switches, read-only/no-auto-create key mounts, preserved
base mounts, required operator settings and extension-disabled default behavior.

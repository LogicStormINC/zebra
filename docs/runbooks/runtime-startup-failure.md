# Runtime startup failure and isolation readiness

## Contract

The selected Cloud sandbox isolation is mandatory. An engine that does not
advertise the configured gVisor handler is unavailable, not an invitation to
fall back to runc or the local development runtime.

OCI capability checks are read-only and bounded to three probes. Each probe
has a two-second subprocess deadline, with 0.2/0.4-second backoff only for
transient engine availability/timeouts. Missing handlers and invalid capability
responses fail immediately. Engine identity pinning retains its independent
bounded checks and fails closed. Container creation/restoration is not retried
by this mechanism because its side effects may already have occurred.

After a Worker has prepared a command, an exhausted/unavailable runtime must
close its Turn. RuntimeStartupError uses the existing setup-failure finalizer:
TurnFailed and SessionFailed are durable, the lease is released, AG-UI emits
RUN_ERROR, and Trench receives an error terminal instead of indefinite running.
The public error says the task has not started; operational details stay in
Worker logs. No model or tool is invoked during failed runtime preparation.

## Operator check

The Worker health check now runs this same isolation preflight, not merely
docker version. It also checks configured model credentials and process liveness.
Run without replacing the running services:

```sh
docker compose --env-file docker/trench-acceptance.env \
  -f docker/compose.application.yml run --rm --no-deps \
  --entrypoint /app/.venv/bin/python zebra-worker \
  -m zebra_agent_worker.runtime_preflight
```

An unavailable JSON result with exit code 1 blocks readiness. This is a capability
probe, not full sandbox/network/quota/model acceptance. A healthy Docker daemon
alone does not establish that the chosen isolation can execute.

The outer OrbStack Docker daemon in the investigated deployment advertises runc
but no runsc (the earlier Docker Desktop label was inaccurate).
Use a configured compatible sandbox host with the required handler; do not change
isolation merely to make health green. Restart/recreate services only after the
host/configuration is ready and application images have built successfully.

Old commands stranded before this fix are not replayed or silently mutated by
the preflight. Cancel/retry them through authorized product controls after runtime
repair. Source tests and image builds do not prove historical-task recovery or
live end-to-end execution.

## Local VM connection verified 2026-10-07

The existing OrbStack Ubuntu machine `zebra-gvisor` advertises runsc. Its current
verified IP is 192.168.139.232. Control-plane services stay on the outer daemon;
only sandbox Docker operations cross the authenticated TLS bridge at port 2376.
The installed `zebra-docker-tls.service` uses the existing socat dependency and
requires a client certificate. The VM Docker daemon was not restarted.

Persistent VM configuration:

- `/etc/systemd/system/zebra-docker-tls.service`, sourced from
  `docker/local-gvisor/zebra-docker-tls.service`.
- `/etc/zebra-gvisor/bridge.env` and root-only server key, server certificate, CA.
- `/etc/tmpfiles.d/zebra-workspace.conf` maps the unchanged local quota workspace
  to `/mnt/mac/private/tmp/zebra-trench-live-workspaces`.

Local client credentials live under the Git-ignored
`docker/trench-acceptance/secrets/local-gvisor/client/`. Only this client directory
is mounted into the Worker, read-only; neither the CA signing key nor server key
is mounted there. Group 20 grants the container access to the 0640 client key.
`docker/compose.local-gvisor.yml` removes the outer Docker socket and supplies
TLS verification and certificate paths. Always include this overlay; using only
the original application Compose file does not supply the TLS credentials.

User-operated activation, after successful build:

```sh
cd /Users/lukeding/Desktop/playground/2026/product/zebra-agent
bash docker/local-gvisor/recreate-application.sh
```

This performs an ephemeral preflight first and only then recreates API/Worker
with the existing images and TLS overlay. It does not migrate/delete data or
replay user tasks. Cancel the old stranded Turn and retry after activation.

Acceptance before activation: authenticated Docker info exposes runsc; anonymous
TLS access is rejected; an ephemeral Worker reports ready; real OciRuntime
provisions, executes, writes shared test bytes and destroys a gVisor sandbox.
The dedicated shared-volume capacity is 10,527,662,080 bytes, below its 10 GiB
limit. The disposable test directory permits VM-remapped UIDs to write; existing
business paths were not chmodded. This is Runtime adapter acceptance, not a full
fenced Worker/Host/model/browser Turn or multi-user filesystem isolation proof.

Repeat the smoke check without touching user tasks:

```sh
docker compose --env-file docker/trench-acceptance.env \
  -f docker/compose.application.yml -f docker/compose.local-gvisor.yml \
  run --rm --no-deps -v "$PWD/docker/local-gvisor/smoke.py:/run/smoke.py:ro" \
  --entrypoint /app/.venv/bin/python zebra-worker /run/smoke.py
```

Certificates expire 2026-11-06 UTC. Rotate the CA/server/client credentials before
expiry, preserving permissions; reload/restart the bridge under operator control.
If the VM IP changes, reissue the server IP SAN and update both bridge.env and
the ignored acceptance address. Never disable TLS verification to bypass this.
Rollback restores the prior Worker endpoint/configuration; the outer daemon still
cannot satisfy gVisor, so rollback is not a functional sandbox fallback.

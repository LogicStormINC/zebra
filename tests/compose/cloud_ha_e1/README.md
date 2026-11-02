# CA-HA-03: isolated two-host E1 preparation

This fixture uses the existing running OrbStack `zebra-gvisor` Docker engine and
Ubuntu `192.168.101.7` as two compute hosts. It creates only labelled, newly named
resources. It does not replace production services or resume an old cluster.
All runtime evidence here is **synthetic**. No real IdP/provider/Coverage quality,
physical-host power-loss, storage-HA or production acceptance is implied.

Each host runs one API and one migrated Worker, each limited to2CPU/2GiB;
execution slots4 each. Both engines retain their existing runsc configuration.
The VM hosts fresh PostgreSQL17.5, Redis8.2.1, MinIO2025-04-22, Rabbit4.3.5,
Host Grant Broker, fixed32-principal authority and deterministic model fixture.
Dependency memory/CPU/PID/log limits are in compose.yml. Persistent dependency data
uses a NEW24GiB ext4 loop filesystem labelled`zebra_ha_e1` inside the VM.
Each engine has a separately labelled512MiB tmpfs workspace volume. This is a
shared workspace ceiling per node; per-session mounts are needed before claiming
larger workspace capacity. No filesystem or certificate configuration is global.

The supported native model adapter/reviewer profile is exercised through an
explicit transport simulation. Only owned containers map`api.deepseek.com` to
127.0.0.1; their certifi file contains ONLY this fixture CA, mounted read-only.
Node Caddy listens on127.0.0.1:443 and proxies the local deterministic fixture.
Only`synthetic-only` credentials are supplied. `check_model.py` must confirm
resolution, peer, certificate and marker, including negative checks, BEFORE Tasks.
These capabilities attest executable native wiring, not real provider health.
Do not manually insert capabilities or relax native execution/recovery gates.

## Operator sequence

Use the existing task branch and freeze source/archive/image IDs before starting.
The scripts are specific to this environment's verified paths/UIDs/GIDs; re-audit
those facts before reuse. Private files stay under ignored`.artifacts/cloud-ha-e1`.
Never print compose config, credentials, JWTs, raw AMQP bodies or private keys.

1. Build `docker/Dockerfile` target`worker-engine` natively on both engines with
   `--build-arg ZEBRA_INSTALL_RABBITMQ=true`,1CPU/3GiB build limits. Record image IDs
   and source hashes. API/Worker runtime source must match the reviewed candidate.
2. Run`prepare.py NEW_PRIVATE_DIRECTORY` once. It refuses overwrites and reuses
   the existing Rabbit preparation helper. Run`check_authority.py` locally.
3. Run`bundle.py vm PREPARED NEW_OUTPUT --image sha256:...` and the corresponding
   `server` command. The mode0600 archives exclude the CA signing key and carry
   explicit TLS file owners. Preserve all original private preparation files.
4. In the VM, create the NEW24GiB ext4 file/mount, label as above. Never format an
   existing file or mount an unrelated device. Create owned postgres/redis/object/
   Rabbit directories inside it; PostgreSQL directory owner70. Record the exact
   loop device, file, filesystem UUID and mount. Do not modify fstab or auto-start.
5. On each engine, exclusively create the external workspace volume
   `zebra-ha-e1-20261102-workspaces`, owner label`zebra.ha.owner=ca-ha-03-e1-20261102`,
   local driver type/device tmpfs, options`size=512m,uid=65532,gid=65532,mode=0770`.
   Reconcile and validate an existing matching volume; never silently repurpose it.
6. Extract each private bundle only into its new recorded runtime directory.
   Confirm server127.0.0.1:443 and all new ports are free. Existing server443
   listeners on192.168.101.7/100.93.3.5 remain untouched.
7. Use dedicated SSH reverse forwards from server127.0.0.1 ports25432,26379,29000,
   28082,28444,25672 to the VM's same ports. Record the exact owned PIDs/commands;
   validate rather than duplicate or auto-restart a tunnel of unknown state.
8. Run`verify.py RUNTIME_ROOT --control` in the VM and without`--control` on the
   server. It checks exact scope/endpoints, image pins, workspace ownership/options/
   mount targets, file types and bounded data mount. Use shell`set -e` or explicit
   `&&`; a failed gate MUST stop the dependent launch.
9. Start only the new control services. Apply the existing Rabbit provision helper
   to this new loopback broker. Run the reviewed`docker/migrate.py` operator root
   against ONLY new`ha_e1`; its serial connections use declared external reserve.
   For a source delta, use Dockerfile.delta over the verified frozen Rabbit base and
   record both IDs/source hashes. Then run`initialize.py` as an explicit operator with the budget marker empty.
   It checks empty events, NOSUPERUSER/DB budget, idempotent fixture registry,
   empty-namespace cutover, bucket versioning and bounded Rabbit identities.
10. Start only node-tls, then run`check_model.py` inside the exact prospective app
    image/environment on BOTH hosts. Run`check_wire.py` for native SSE/tool and synthetic
    usage decoding. Keep all peer/cert/marker receipts. A wrong
    fixture must reject before Tasks. Only then start each API/Worker pair.
11. Verify TLS live/ready for both APIs AND fresh control/capability-backed Worker
    health files. API readiness alone does not certify Worker readiness. Capture
    actual IDs/image hashes/quotas/mounts/versions/RTT and root source provenance.

Example dependent launch (inside the intended host; no private config output):

```sh
set -e
python3 "$E1_ROOT/verify.py" "$E1_ROOT" # add --control on VM
# Run model preflight inside the pinned image before first Task.
docker compose --env-file "$E1_ROOT/compose.env" -f "$E1_ROOT/compose.yml" up -d api worker
```

The initial small normal-direct budget2 rejected competing idle maintenance.
E1 preparation uses pool4/normal8/read2/control2/probe1 and peak fleet2+2+8+1+1:
238+external4+server_reserved3=245<=256. This is a frozen staging budget, not a
production database recommendation. Actual load/fairness/queue-age proof is pending.

All services use restart=no. Stop/remove only exact receipt-owned resources;
retain receipts, data and source. Never stop Docker/the production host or blanket
prune containers/volumes. Quiesce and prove old app/socket exit before any staging
recreation; this fixture does not certify rolling upgrade/rollback transitions.

## Remaining acceptance

10kTasks/1mEvents baseline, fixed E1-A/E1-R/E1-C and overload warmup/steady windows,
full fault matrix, SQL/CPU/queue/p95/p99 measurements, and production/real-provider/
IdP/browser acceptance remain separate gates. Do not call them passed from this
bootstrap or a successful single Task. No original business Run may be replayed.


Known inherited optional-test boundary: the current real-PG AGUI native-expiry
fixture injects ScriptedModel without worker-budget/1. It fails before recovery
on both the original9e3 recovery module and this candidate. The unchanged recovery
regressions pass against the separate owned QA database; this fixture failure is
recorded separately and is not represented as full native HTTP acceptance.

## Actual acceptance boundary (2026-11-03)

See `docs/evidence/ca-ha-03-e1/validation.json`: four running apps match source
0fd9f0c1; both node TLS probes and fresh Worker control health pass. One NEW Task
was POSTed once, admitted201 and provisioned gVisor, then failed closed with
WorkerBudgetError before transport: native CLI composition has no trusted exact
request counter. Zero model reservations/tool calls; retain the original failure.
`check_wire.py` proves decoding only, not successful guarded Task execution.

Before another new Task, compose a trusted counter through the existing
ModelRequestBudgetFactory and verify exact bytes/output bounds. Do not inject a
heuristic, spoof capabilities, disable budgets or replay the failed Task. Each
Host Grant is single-use, including GET: exchange a fresh grant per readonly
request with the same original external bindings. An admission grant replay403
is expected. E1 full dataset/load/fault/soak remains not run. SSH tunnels depend
on the Mac; the VM control/data plane is single-node, and tmpfs workspaces are
not cross-node durable. This environment is not production HA acceptance.

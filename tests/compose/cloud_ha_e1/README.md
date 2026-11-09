# CA-HA-03: isolated two-node E1 preparation

Current compute nodes are OrbStack `zebra-gvisor` (192.168.139.232) and fresh
`zebra-ha-e1-node2` (192.168.139.154), sharing one physical Mac. Ubuntu192.168.101.7
is retained as an unqualified WAN candidate with its API/Worker held; strict
deadlines were not relaxed. Only labelled, newly named resources are created.
Production services and old workloads are preserved.
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
   the existing Rabbit preparation helper. From the repository root, run
   `python -m tests.compose.cloud_ha_e1.check_authority`.
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
docker compose --env-file "$E1_ROOT/compose.env" -f "$E1_ROOT/compose.yml" up -d api worker runtime-cleanup
```

The initial small normal-direct budget2 rejected competing idle maintenance.
Two local engines need one independent cleanup process each. E1 preparation uses
pool3/normal8/read2/control2/probe1 and peak fleet2+2+8+2+1:
240+external4+server_reserved3=247<=256. The earlier cleanup1/pool4 profile was245;
never run cleanup2 under that old profile (262 exceeds256). Cold-switch all app
roles to the matching profile before adding the second cleaner. This is a frozen staging budget, not a
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

## Meter v2 source candidate (not deployed)

`uv run python tests/compose/cloud_ha_e1/check_metering.py` checks exact request
bytes/hash, multibyte input, cap/body negatives, the actual provider function and
HTTP handler. The synthetic unit is compact JSON UTF-8 bytes: normalized request
and structured message bytes, excluding transport/SSE framing. `prompt_tokens`
and `completion_tokens` carry these explicitly synthetic units. HTTP re-encodes
parsed JSON; the guarded caller additionally rejects wire differing from that
encoding. This is not a DeepSeek tokenizer or arbitrary raw-HTTP byte accounting.

Source wiring now permits the trusted operator Cloud bundle to carry the existing
ModelRequestBudgetFactory. Defaults still provide none. Explicit fixture factory,
frozen model output cap and new image/Task checks remain next; do not run this
probe against the old constant-usage service and call it accepted. Use an existing
RuntimeAssembly/ModelInvocationPolicy cap (e.g.1024 for this fixture), not a proof
that changes wire or understates its output ceiling. Preserve reservations,
settlement, single-use grants and the original failed Task.

## Frozen Bundle operator assembly (source candidate)

The initial private node bundle intentionally is not launchable as an app until
execution approvals are generated. `prepare.py` sets `/e1/catalog.json` and
`/e1/publication.json`; both must exist before full `verify.py`. Use `--release`
with a full source SHA to give new scripts/configs their own immutable directory.
Never overwrite the running model scripts or old private release directory.

1. Build reviewed delta images natively. In the dedicated VM start only the new
   loopback registry via `verify.py RELEASE --registry-only` then Compose `up -d
   --no-deps registry`. It is bounded by the existing24GiB data mount and has
   .25CPU/384MiB, no restart,127.0.0.1:28081 only. Forward only this loopback port
   over a separately recorded SSH tunnel. Do not modify daemon registry settings.
2. Push both exact platform images into that private registry; create and inspect
   their immutable multi-architecture manifest. Record manifest/config/source
   hashes before using its digest as the engine image pin. This is test registry
   infrastructure, not registry/storage HA certification.
3. In the exact candidate image, UID65532, load the final effective app env and
   run `prepare_execution.py NEW_PRIVATE_OUTPUT --image-digest sha256:...
   --evidence-digest sha256:...`. Both arguments must come from actual receipts,
   not offline unit-vector placeholders. Catalog baseline uses the real settings;
   its two configuration URI fields are excluded by the existing baseline contract.
4. Keep the raw publication-token in an operator-only private directory, never
   mount it into API/Worker. Install only catalog.json/publication.json as regular
   mode0600 files owned65532 at RELEASE/execution/. Check both nodes' effective
   baseline against the catalog without printing key/config/env contents. Run
   check_composition.py against the generated assembly; all its checks are offline.
5. After exact old app processes exit and app PG connections are zero, verify
   full new release and start only its owned apps/model. Verify source/fixture
   hashes, native TLS binding/wire probes and fresh readiness. Register the new
   scoped management trust, materialize through the native management HTTP API,
   record only actual passed fixture evaluation evidence, then publish through
   the same gated API. Save operation IDs before requests; reconcile unknowns.
6. Only then exchange a fresh business grant and POST a NEW Task with the exact
   published definition_id and definition_environment=test. Each readonly request
   also needs its own fresh grant. Retain the original failed Task untouched.

The approved model output cap1024 and cumulative budget200000 are synthetic test
configuration. Runtime uses the existing frozen Bundle, reservation and settlement
contracts. This does not configure a trusted real-provider tokenizer.


The fresh `orb2` node uses root-owned bundles, Docker GID104, the same pinned
engine image and CA, and its own512MiB tmpfs workspace volume. It has no control
data services. Six transient loopback socket proxies target primary192.168.139.232;
no TLS/SNI rewriting or global proxy changes. Node leaf SAN includes192.168.139.154.
The control gateway targets primary+orb2; keep the unqualified WAN worker held.
Copy the complete installed strict gVisor runtime, including gvisor-bin sidecars,
and verify hashes and real nonroot/read-only/network-none execution. A rootfs
write probe must target a directory writable to the test UID before checking EROFS.
Both logical nodes share one Mac; this is not physical-host or durable-storage HA.


For E1-A deterministic short tasks, the separately frozen provider variant
recognizes `[zebra-ha-e1-short-v1]` only in user text and emits a fixed final
response without tools. Ordinary/system-marker requests retain pwd; no policy,
Runtime9b budget or Native7 approval changes. Both branches use the same exact
byte meter, output cap and HTTP limits. Run `check_metering.py` before any variant
promotion. Freeze the external fixture source/hash separately from the runtime
image source/hash in the load manifest; Native7 TLS/SSE/meter qualification is not
provider semantic quality, capacity or full E1 acceptance. First validate a NEW
native short Task once, retain its receipt, then prepare load/corpus tests.


New E1 preparation explicitly opts into the runtime's existing Cloud deferred
provisioning. Its existing fresh-binding/materialization/no-MCP/no-skills guards
remain authoritative; local defaults and isolation are unchanged. This changes
the non-model configuration baseline and requires a NEW Native approval before
cold switching idle staging apps. Runtime image9b remains frozen; provider b15
remains separately frozen. Verify a NEW no-tool Task creates no OCI object, then
a NEW pwd Task still provisions/cleans at first approved tool, retains the original
budget deadline and exact exit proof. Never mix Native7 eager and new deferred
measurements into one capacity claim. Native8 runtime acceptance is pending.

## Cross-host PostgreSQL fault evidence

The disposable PostgreSQL pair used OrbStack and 192.168.101.7. These
runs are individual correctness drills under F-04. The numbered F1 cases
require separate repeats at the load and observability envelope in
`docs/contracts/cloud-ha-v1/README.md`.

| Boundary | Evidence in WORKLOG history | Observed result |
| --- | --- | --- |
| Receipt visibility | `60e2f001` | One signed POST withheld while replay was paused; original GET recovered the exact sealed response. |
| Fencing | `dd22b6ff`, `f233af86` | Owner mismatch refused promotion; after explicit fence, a preexisting old-writer connection could not commit. |
| Replica rebuild | `7d404a9a` | New cross-host standby restored remote_apply and confirmed the original STOP receipt over verified TLS. |
| API handover | `2a213987`, `fc7d0337` | Fresh writer composition accepted new admissions; original signed GET recovered the in-flight POST receipt without resubmission. |
| Worker recovery | `4a0ad909`, `27d1269a`, `d51599fe` | Pending Run consumed once; unresolved model reservation and uncertain tool dispatch preserved without a second invocation. |

The fence used an operator-controlled container stop. The signed HTTP
fixtures used a fixed test verification key. Model and tool side effects
were synthetic, and the individual drills used different candidates and
workloads. The E1 control plane has no continuously deployed automatic
writer election, independent fencing authority, or qualified cross-host
workspace backend. Production promotion is outside this fixture.

The tracked fixture provides environment preparation, correctness probes,
and an open-loop scheduler. Run `python3 tests/compose/cloud_ha_e1/open_loop.py`
for its saturation self-check. The scheduler preserves every planned offer,
including missed ones, and never retries submissions. Signed HTTP, SSE, dataset
preparation, and repeated fault cases still need to be wired into the runner. Keep CA-HA-03 in progress until those gates run against one frozen
candidate. Keep subsequent HA stages locked per the task registry.

The signed-admission adapter in `signed_load.py` exchanges one fresh grant
per offer and writes a private original-operation intent before issuing POST.
A missing response record alongside an intent requires original-operation
reconciliation. Use a new private evidence directory and the fixture CA
with a direct, non-retrying HTTP client. Its standalone check uses a
simulated lost HTTP response and verifies the scheduler issues no replay.
The adapter's `recover_original` reads the saved intent, exchanges fresh
authority for the same binding, and issues an original-operation GET. A
completed receipt must match the operation and canonical request hash and
pass AES-GCM authentication before its payload is returned. HTTP status
and incomplete receipts remain visible to the caller.

The SSE adapter in `sse_load.py` defaults to 256 streams split evenly
between the two direct fixture endpoints. Each stream exchanges a fresh
grant and must deliver a nonempty event ID before the readiness barrier
opens. An early closure invalidates the steady window. Supply a dedicated
TLS client with at least 256 stream connections plus grant-exchange
headroom. The standalone check simulates early EOF; live capacity and
cursor-resume fault measurement are separate.

Run `run_load_diagnostic.py --help` for the short live adapter check.
It requires the private original SSE fixture, a fresh synthetic task
template/workspace, principal file and fixture CA. It caps the window
at three seconds and never overwrites an evidence directory. The first
live run held four streams, accepted all five planned offers, and
verified all five original GET receipts. It used the existing staging
runtime and no baseline dataset. See WORKLOG for the private run ID.

`native_corpus.py` generates 100 canonical synthetic events per Task using
the migrated PostgreSQL schema and native deferred position allocator.
Supply `ZEBRA_E1_CORPUS_DSN` for a dedicated loopback database named
`zebra_e1_corpus_*`. It writes a new namespace in 50-Task transactions
and checks source/index identity. The default is 10,000 Tasks. This is
the synthetic structural corpus only. Preserved legacy/Coverage/receipt
samples and application composition into the generated namespace are
separate prerequisites for the full E1 baseline.

## OrbStack node2 boot recovery

The boot units are specific to the disposable `zebra-ha-e1-node2` VM and
the named corpus containers. Verify the first node is `192.168.139.232`, the
five container names in the unit are owned by the rehearsal, and the relay
ports are unbound before activation. On node2, install
`node2_dependency_relay.py` as `/usr/local/lib/zebra-e1-node2-dependency-relay.py`
with mode 0700, and install the two service files under `/etc/systemd/system`
with mode 0644. Stop any previous test-owned transient relay first.

Run `systemd-analyze verify` on the two files, then `systemctl daemon-reload`
and `systemctl enable --now zebra-e1-node2-relay zebra-e1-node2-corpus`.
After a named VM stop/start, check both units, all five container states and
the node2 TLS `/health/ready` endpoint. To retire this fixture, disable and
stop the corpus unit, then the relay unit, and remove the installed files.
The relay uses loopback listeners and a fixed first-node dependency address.

### Fenced peer writer routing

The isolated node2 PostgreSQL relay reads `/run/zebra-e1-node2-pg-route` for
each new connection to port 25432. With no file it uses the source writer.
Atomically install a root-owned file with `closed` before fencing the old
writer. After confirming the old writer is stopped and the peer has been
promoted, atomically replace the file with `promoted` to route to the peer
writer on loopback port 25437. The selection lasts until the next node reboot.
Keep the old writer fenced through reboot. On a read-only rehearsal rollback,
close the route, stop the promoted copy, restore the source and then remove
the route file. Keep the proof gate closed to new admission until a new
synchronous proof follower is configured and checked.

### Rebuilt PostgreSQL standby restart

On the isolated node2, verify that `zebra-e1-f04-rebuilt-standby` has the
`ca-ha-03-e1-20261102` owner label and is in recovery on its original
`zebra-e1-f04-standby-data` volume. Enable Docker restart for that read-only
replica with `sudo docker update --restart unless-stopped zebra-e1-f04-rebuilt-standby`.
After a named VM stop/start, verify a changed boot ID, the same container
and volume, `pg_is_in_recovery()`, and zero replay gap on the source.
Promotion candidates and fenced writers use restart policy `no`.
To roll back the replica startup setting, apply `--restart no` to the same container.

### Worker incarnation recovery and VM restart

The active incarnation-enabled Workers use host identity directories under
`/run`. The transient recovery timers and these directories are lost on VM
restart. The node2 corpus boot unit above predates incarnation registration.
Its container start alone does not make an incarnation-enabled Worker ready.

For a persistent candidate, mount a root-owned state directory from
`/var/lib` read-only into the Worker. Keep the identity, exit witness and
restart lock in that same host directory. Stop the recovery timer before
planned shutdown. On boot, start Docker and the scoped cleanup dependency
before reconciling the previous Worker incarnation. Inspect and persist the
old exit proof before starting the Worker. Publish the new identity after
start, check it from inside the Worker, then enable periodic recovery.
Missing or mismatched old exit evidence requires explicit reconciliation.
The periodic crash filter deliberately skips clean and SIGTERM exits, so
planned boot startup requires its own entry point.

Apply the same identity gate to an image replacement and to rollback. Compare
the host-published container ID and start time with Docker, and verify the
identity through the Worker's own parser before sending new commands. Before
capacity or fault injection, require a fresh signed synthetic Task to reach
`session_completed` on each Worker. A sealed 201 or a drained command can also
belong to a suspended Task.

Accept this configuration with a named isolated VM restart, both node
timers, an old exact exit receipt and a new synthetic command on the
restarted node. A healthy Docker process alone is insufficient evidence.


### F-09 Scheduler fixture

The new bundles reserve two Scheduler processes and reuse the private executor
connection caps already measured on the corpus Workers. The optional
`scheduler` profile runs the regular Scheduler entry point with a unique
claimant per node. Stage it only on the two isolated OrbStack nodes, one process
per node, with the existing node2 TLS loopback relay to the control Broker.
The WAN bundle does not contain a workload credential.

The fixture Broker and authority share a newly generated workload secret with
both Schedulers. Only the first synthetic bearer account can request Schedule
management rights. A Scheduler workload signature can exchange runtime rights
only for that account. Deploy the fixture authority and Broker configuration
together on the isolated control node and verify a fresh signed firing before
injecting a fault. Existing prepared bundles and their receipts are retained.

### Checked execution-measurement entry (CA-HA-03)

Run preparation and execution through `run_execution_measurement.py` with the
repository `.venv/bin/python`, never as two unchecked shell commands. It uses
that same interpreter for dependency checks and both stages; a preparation
failure exits before the execution stage. Pass `--prepare`, `--execute` and
`--evidence` with the reviewed isolated scripts and their existing evidence
directory. The scripts must validate their own run ownership and configuration;
this entry does not allocate resources or authorize a load run. Do not rerun
historical artifact scripts or replay original Task POSTs.

Offline regression (no service or Task creation):

```sh
.venv/bin/python tests/compose/cloud_ha_e1/check_execution_measurement.py \
  --fixture .artifacts/cloud-ha-e1/execution-qualification-1793892399/measure.py
.venv/bin/python tests/compose/cloud_ha_e1/signed_load.py
```

The regression executes the frozen observer's actual `read_original` function
with the native signed-receipt reader and a fake transport: 16 finite callers,
one active receipt query, all503 observations retained, no Task POST/retry.
The fixture keeps the existing receipt=1 budget and8s HTTP deadline. A503 is
an observation failure; the original POST evidence remains authoritative.
`--legacy` deliberately reproduces the old preparation failure and must fail.

Capacity acceptance is paused pending dedicated resources and the derived
queue issue documented in `docs/CA-HA-03_capacity_decision.md`. The retained
stopped Task has a canonical cancelled session and no lease, but its pending
command still consumes one scope admission slot. Do not delete it or infer a
handled command from a physical executor ACK. Startup stop proof does not cover
model/tool blocking stops or complete E1-R acceptance.

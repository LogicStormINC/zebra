# R12 Runtime, Credential, Egress and Resource Boundary

## Decision

Cloud task execution remains fail-closed on the configured gVisor runtime. The
trusted Worker may control the OCI engine, but neither API nor an untrusted task
receives that engine authority. A release must prove the selected engine and
runtime in the target environment; a chart render or healthy idle Worker is not
runtime execution evidence.

## Enforced boundary

| Concern | Enforcement |
| --- | --- |
| Image identity | OCI task images require a `sha256` digest |
| CPU, memory, processes, tmpfs | Docker create receives explicit CPU, memory, PID and tmpfs limits |
| Filesystem | Read-only container root, one contained workspace bind, non-root UID/GID |
| Privilege | All capabilities dropped and `no-new-privileges` enabled |
| Network | Task container uses `--network none`; remote access is mediated by bounded Host/MCP gateways |
| Deadline | Execution is capped by `SandboxSpec`; timeout destroys the container/process tree |
| Output memory | stdout and stderr are drained concurrently and retained only up to `max_output_bytes` per stream; result flags report truncation |
| Workspace disk | Cloud admission requires a storage-enforced workspace quota |
| Credentials | Per-command environment injection is rejected; Host/MCP credentials stay in the trusted Worker path and are not mounted into task sandboxes |
| OCI engine | Engine endpoint/configuration is pinned; API no longer receives the Docker Socket or `DOCKER_HOST` |
| Archives | Existing materializers reject traversal and symbolic-link entries before extraction |

`max_output_bytes` is a retained-byte boundary for each stream, not a combined
stdout/stderr budget. Both pipes continue to drain after the boundary so a child
cannot deadlock by filling one pipe. Truncation is UTF-8 safe and is preserved on
normal completion and timeout. Larger durable outputs require a future streaming
artifact protocol rather than increasing Worker memory capture.

## Trusted Worker and Docker Socket

The Compose pilot still gives the Worker access to the engine socket because it
is the trusted runtime provisioner. This is host-level authority and therefore
must never be mounted into API, scheduler, migration, task containers, or model
tools. Production should prefer a dedicated, identity-pinned engine endpoint;
compromise of the Worker remains equivalent to compromise of that engine.

## Kubernetes release gate

The Helm chart proves control-plane Pod hardening under `runtimeClassName=gvisor`,
but it does not by itself prove the Worker's per-task OCI engine, shared workspace
mount, or task lifecycle. Until R14 supplies a real task execution and cleanup
run on the target cluster, Helm evidence is `NOT_ENABLED` for task-execution
release approval. An idle healthy Worker is not sufficient.

## Evidence

- Focused runtime/security/Compose suite: `751 passed, 11 skipped`.
- Bounded-output and adapter suite: `33 passed`.
- Current local Docker engine advertises `runc` only, not `runsc`; no new local
  gVisor smoke claim is made. The real target-runtime proof belongs to G2/G3.

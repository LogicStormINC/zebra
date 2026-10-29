# Private workspace acceptance before execution activation

Production remains API-only on schema105. Keep the Worker stopped, Host admission paused and attachments disabled until the relevant gates below pass. Preserve current HRMS16.52.0, original Task bindings, all histories and unrelated services.

## Reviewed source requirements

Reuse the native Task/workspace/binding stores and the existing pinned fresh ERP authority probe. The privileged allocator must use only the host standard library. A fixed image helper independently verifies the active Task, canonical stored binding, current expiry and capability ceilings, and live Host user/company authority. Only root-owned configuration chooses its image digest, restricted network and credentials; Worker requests carry bounded UUID identities, operation and nonce, never executable commands or paths.

The allocator reserves at most32 leaves and8GiB, counting recorded reservations and actual orphan image allocations. Each leaf is a256MiB ext4 filesystem. Preserve a2GiB free-space floor. Existing unknown files are refused, never reformatted or pruned. Bound the complete request, including lock waits, proof helper and filesystem subprocesses; a socket timeout alone is insufficient. A lost acknowledgement must permit verification of the existing allocation without formatting it again.

Persist phases and filesystem UUID durably. A restart must validate backing image, exact mount, UUID, mode and ownership before returning it. Worker verification compares authenticated receipt, root-owned persistent UUID metadata and independently observed filesystem identity/capacity. The Worker receives neither root allocation credentials nor block devices nor the Docker socket. Its parent mount uses rslave propagation from the shared host parent; ordinary command containers receive only their own leaf.

## Disposable physical QA

Use unique QA sibling paths, separate operator state/key/socket and no production mounts. Record the paths and image/source digests before any mutation. Retain failed fixtures for diagnosis; clean only explicitly inventoried QA resources after mounts and processes are stopped.

1. Exercise the real Unix socket with UID65532 and authenticated bounded requests. Wrong UID, MAC, replayed nonce, malformed or oversized input and proof refusal cannot allocate a volume.
2. Allocate two distinct owned leaves; repeat an acknowledged request and simulate lost acknowledgement. Both return the original UUID/backing identity. A contradictory owner cannot adopt an existing leaf.
3. Write separate canaries under UID65532. Each isolated OCI command mounts one leaf only, with read-only root, network none, cap-drop ALL and no-new-privileges. Demonstrate the other leaf, credentials, socket and ERP/DB endpoints are unavailable.
4. Exhaust one filesystem and verify ENOSPC while the other canary and host free-space floor remain intact. Account for the filesystem's actual available capacity rather than assuming all256MiB are payload bytes.
5. Restart only the QA allocator. Verify canaries, persistent UUID, owner/mode and receipts. Reject a changed backing file, UUID or parent-backed directory. Verify interrupted allocation phases fail closed without reformatting.
6. Exercise bounded helper/process timeout and lock contention; verify no orphan helper container and no unsafe later allocation from a timed-out request.

These checks prove filesystem and process primitives. They do not certify native Task authorization when their identity source is a fixture.

## Native and joint acceptance

On disposable PostgreSQL and the disposable Frappe/Caddy site, create native user/company-scoped Tasks and bindings using the actual admission path. Use the compiled helper without a source import hook. Verify active segment, canonical digest, current expiry/ceiling, revoked user/company, stale Run and wrong workspace refusal. Prove two actual principals/companies retain separate files and cannot access each other's artifacts. No production identity or model replay is a fixture.

After physical and native gates pass, validate authenticated HTTP ingress, browser refresh and per-conversation state, a minimal real model/file/artifact round trip, Stop/recovery and historical resource access. Record prepared source, candidate images, QA acceptance and production acceptance separately. Schema106 migration or Worker activation requires the corresponding reviewed changes and preservation checks; source review or a healthy container is not this gate.

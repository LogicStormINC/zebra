# Production workspace hard-quota failure, 2026-10-22

## Confirmed evidence

Conversation conv_1792651644999_cea0c6, Run eca40e4a-8294-48e8-a42a-8e140495f1f8,
Session83042ed6-f5b0-46df-90b2-d6fabec08470, Trench Turnc8f55dbd-9ecd-470c-be66-e51e689f6b30.
Read-only inspection: model_request_started and model_response_received each1;
then4tool starts (sources.list, subscriptions.list_history, skills.list, files.list),
no durable tool completion, turn_failed/session_failed with WorkspaceQuotaError.
No provider HTTP failure is established. Public model_execution_failed is the
fallback exception label, not the actual fault category.

The configured10GiB hard quota remains enabled. The root /var/lib/zebra/workspaces
is a dedicated bind, but statvfs reports499694788608bytes (~465.4GiB), exceeding
10737418240bytes. Running the real quota validator reproduces this exact error.
The real OCI engine preflight returns ready without creating a sandbox/model call.
The workspace tree is16KiB; host root has69GiB available. Filesystem ext4.
Prior ownership repair remains effective; Worker restarts0. This is a separate
storage-enforcement deployment gap after the earlier PermissionError repair.

## Approved repair plan (completed below)

Keep source and quota policy unchanged. Provide the existing workspace path with
one durable ext4 filesystem bounded by the configured10GiB. A preallocated image
backed loop mount is the Linux-native fallback if no dedicated volume is available;
using tmpfs would lose durable workspace data and is unsuitable.

1. Record current mounts, API/Worker configurations, file hashes/ownership, active
   leases/pending commands/Trench active Turns, Search/MCP identities and cooldown.
2. Require no active work; stop API admission and Worker, then recheck authority.
3. Preserve the entire original directory under an adjacent rollback path; create
   a distinct10GiB backing filesystem outside that directory. Never format a device
   discovered by guessing and never overwrite existing files. Verify backing file
   identity, size, filesystem, mount target and at least20GiB remaining free space.
4. Mount at the exact old path, copy existing content with ownership preserved,
   retain65532:65532 ownership, and register the mount for host reboot. Service
   startup must require the mount; otherwise boot could silently expose the old
   unbounded root. Do not run general compose down or touch Search/MCP containers.
5. Recreate only application services requiring a new bind mount. Keep the five
   existing Compose layers, image digests/settings/grants/high/v2/schema105 intact.
6. Verify actual quota checker succeeds from Worker, all original file hashes
   match, Worker UID can write/delete a private bounded probe, and engine preflight
   remains ready. Check application health and protected Run events unchanged.
7. Without models, validate the real local files.list path against an isolated
   bounded test directory, not the original failed Run. A directory listing is not
   a full real-model or full sandbox-lifecycle acceptance claim.

Rollback: stop admission/Worker under idle guards, unmount only this exact mount,
remove only the newly added mount configuration, restore the original directory
and prior Compose identities. Preserve backing file/new writes for reconciliation;
never auto-delete either copy. Original failed Run is not retried or rewritten.

## Permission and boundaries

Persistent storage/mount change and brief API/Worker interruption were explicitly
authorized through the user-input tool after the second-disk inspection.
No new model/search requests were sent during diagnosis. No source fix is claimed.
Follow-up error classification can reuse the existing runtime_unavailable contract,
but hiding the message alone does not fix the storage-capacity rejection.


## Second-disk inspection, still read-only

User clarified that two physical disks are mounted; this was not authorization
for the proposed migration. Fresh lsblk/findmnt/df inspection confirms:

- NVMe512GB system disk: ext4 root466GiB, available69GiB; current workspace
  resides here. Existing dedicated bind still exposes the entire filesystem.
- SATA480GB disk: /dev/sda1 ext4 mounted /data, filesystem440GiB,
  available417GiB. Root-owned755. Existing top-level dbgpt and lost+found remain
  untouched; no claim that the disk is empty. /data already has an fstab entry.
- /data mount options rw,relatime; no active project-quota mount option observed.

Preferred bounded backing location is a NEW dedicated /data/zebra directory,
with a persistent10GiB filesystem backing file there, keeping the application's
existing /var/lib/zebra/workspaces mount target. Reuse existing second-disk mount;
no disk repartitioning, formatting /dev/sda1, or alteration of /data/dbgpt. A plain
move to /data would still expose440GiB and fail the unchanged10GiB validator.
Reboot ordering must require /data before the workspace loop mount, and the mount
before API/Worker. The user subsequently explicitly approved this second-disk migration.


## Completed production activation

User approved the exact second-disk plan. No product source or application image
changed. Fresh guards showed0active leases,0pending commands,0active Trench Turns.
Only API and Worker were stopped/recreated with the exact existing five Compose
layers; image digests, environment values, commands, user, mounts and security
settings matched before/after. Both services healthy; both readiness URLs return200.

- New backing file: /data/zebra/workspaces-10g-20261022.ext4,
 10737418240bytes. Physical backing allocation10737422336bytes was verified after
 mkfs (which can discard preallocated holes); original content unchanged.
- Existing application mount target: /var/lib/zebra/workspaces.
 Native ext4 loop mount; statvfs capacity10464022528bytes <=10737418240bytes.
 Quota flag remains true in both API and Worker; actual validator passes in both.
- Original directory: /var/lib/zebra/workspaces.pre-quota-20261022.
 Full file hashes, directory/file modes, UID/GID match the mounted copy after
 activation and the self-cleaning acceptance check. Root remains65532:65532/755.
 /data/dbgpt is untouched; no physical disk/partition was formatted.
- Persistence: /etc/systemd/system/var-lib-zebra-workspaces.mount, active+enabled,
 RequiresMountsFor=/data/zebra and Before=docker.service. RequiredBy=docker.service
 creates the exact dependency symlink; systemctl confirms both dependency directions.
 No Docker/server reboot was performed. This verifies configuration, not boot E2E.
 The mount dependency intentionally prevents Docker startup if workspace storage
 cannot mount; operator rollback must remove/reload that dependency BEFORE stopping
 the mount, otherwise systemd could stop dependent Docker services.

No-model checks: real quota validator in API/Worker; OCI engine preflight ready;
Worker65532 writes/reads a private temporary file; real WorkspaceListTool lists it;
path escape and independent quota claims by non-mount subdirectories are rejected;
temporary directory removed. No sandbox was created by this acceptance check;
no real-model or full sandbox-lifecycle/page E2E claim is made.

Original failed Runs eca40e4a... and5602158d... remain failed, with exact events and
model counts unchanged. Four protected prior Sessions also unchanged. Search/TLS/
Yahoo/MCP and other stable service IDs/start times/restart counters/configuration
match baseline, Exa control hash unchanged. Existing Caddy/pgAdmin restart loops
remain outside scope; their container IDs/configurations are preserved.

Operator scripts and receipts: /home/ubuntu/releases/20261022-workspace-quota/,
local private .artifacts/cloud-workspace-quota-20261022/. Maintenance used a short-
lived network-none pinned-image operator helper with explicit host mount/admin
capabilities, never exposed to API/model tools; application privileges unchanged.
No database migration, model/search call, original Run replay, global proxy/IP change or
Search/MCP restart. Public generic error classification was not changed; the
underlying quota configuration fault is removed for subsequent work.

Recheck without models (only a private self-cleaning workspace directory):

```sh
docker exec -i zebra-application-zebra-worker-1 python - \
  < /home/ubuntu/releases/20261022-workspace-quota/verify_worker.py
```

Rollback under idle guards: stop only API/Worker, disable the mount unit and
explicitly daemon-reload; assert docker.service Requires no longer includes this
mount BEFORE stopping it. Unmount exact workspace, restore preserved original
root, remove only the new mount unit, daemon-reload, then recreate API/Worker from
unchanged five layers. Keep backing file/new writes for reconciliation. Never
reformat an existing filesystem, delete either data copy or retry an original Run.

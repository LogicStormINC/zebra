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

## Minimal repair prepared, not activated

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

Persistent storage/mount change and brief API/Worker interruption have been asked
through the user-input tool. Until explicit authorization arrives, no filesystem,
service, runtime configuration or original Run mutations are permitted.
No new model/search requests were sent during diagnosis. No source fix is claimed.
Follow-up error classification can reuse the existing runtime_unavailable contract,
but hiding the message alone does not fix the storage-capacity rejection.

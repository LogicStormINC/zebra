# Cloud service-tool dependency and sandbox readiness repair

Task CLOUD-RUNTIME-READINESS-20261028. User reported repeated `model execution
failed` on conv_1793155124388_279977 and requested root-cause remediation.
No original Run replay, new model request, external search, or Search/MCP restart.

## Evidence and root cause

Original Turn12da1f18-febc-429d-9914-7da5119cee04;
Rundb3183fd-2e50-4cad-a59f-ff2d3739e9ca;
Task61ef1bda-068d-4ecc-85e3-342eec3c87f4. Created02:38:45UTC.
One model response succeeded in3327ms, normalized_error=null. It proposed
sessions.search, sources.list, subscriptions.list_history. All three started;
no completed tool result was durably recorded. This does not prove the parallel
Host reads never reached their service. At02:39:21UTC, RuntimeCapabilityError
became the generic model_execution_failed terminal. Original attempt_count1.

1. LocalToolGateway.execute unconditionally prepared DeferredRuntime except a
   small set of web/Skill/Artifact/Cloud MCP tools. SessionSearchTool uses the
   scoped history store, not a workspace. This unnecessary preparation reached
   OCI create. Plan/clarification markers and MCP directory disclosure had the
   same unnecessary dependency; their handlers/authorization remain intact.
2. runtime_instances reserved d0221872-89c4-45ae-a939-3b9f026f3fad at02:38:51.890;
   container_id remained null. Configured zebra/runtime@sha256:33735bd63cf84d7e388d9f6d297d348c523c044410f553bd878c6d7829612735
   was absent locally. Docker journal02:38:52 records mirror403, and02:39:21
   records canceled upstream image resolution. The30s cloud administration
   deadline explains the failure. No container was created. This is distinct
   from the preceding2s canonical persistence budget incident.
3. Frozen production healthcheck checked Docker version, model-key presence and
   PID only. Existing runtime_preflight also checked handler but not image.
   exception_attempt_result fell through to model execution failed for runtime
   errors; the durable error_type was the only distinction.

We have no evidence establishing when/why the image was absent or its intended
contents. Do not claim it was deleted by a particular actor or prove equivalence
between the nonexistent reference and the replacement base image.

## Minimal source changes

- Existing runtime-free branch includes sessions.search, agent.plan,
  agent.clarify, agent.tools.search/describe. Actual workspace execution remains
  guarded by DeferredRuntime; underlying tool validation, scoped store access,
  pre/post cancellation checks and MCP call policy remain unchanged.
- Cloud instance-backed Docker create uses --pull=never. Unknown images fail
  immediately; runtime invocation cannot download dependencies implicitly.
  Local compatibility create is unchanged. Exact image pin remains required.
- Read-only runtime_preflight checks the exact image locally after fresh daemon
  capability check, with bounded2s inspect and no pull/container creation.
  Repository default Compose already invokes this preflight; frozen production
  override now invokes it too.
- RuntimeCapabilityError has FAILED/runtime_unavailable/retryable=false and
  `execution sandbox unavailable`. No automatic model/tool retry, success
  relabeling, raw stderr/secret leakage, or weakening of auth/quota/isolation.

## Validation

84 targeted no-model regressions pass, plus Ruff/compileall/diff checks.
Covers history reads, malformed input, cancellation before store read, workspace
still requiring runtime, MCP authorized catalog/unknown-tool refusal, actual
Cloud MCP boundaries, deferred preparation and lifecycle, runtime failure
classification, image readiness, and cloud no-pull command generation.

Exact old/new Worker images with network=none/read-only/tmpfs and real isolated
SQLite history adapter:

| Image | sessions.search | Sandbox preparations | Runtime failure category |
| --- | --- | --- | --- |
| prior | runtime_error | 1 | model_execution_failed |
| patched | executed | 0 | runtime_unavailable |

This is deterministic no-model route verification, not a repeated business Run.

Server already held the digest-pinned Python3.12 base:
`swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/python@sha256:52331dac368d5bcf1c00d30a782753d28bb7286a12b7bb629f388cec4cfd6fb2`.
An owned isolated container using that exact local image passed gVisor/network
none/read-only root/cap-drop ALL/no-new-privileges/uid65532/workspace read-write
and <=10GiB filesystem checks in444ms. Removed only the owned container and
empty scratch directory. This is a Python/shell sandbox baseline, not evidence
of a full engineering dependency toolchain (Git/npm/test runners).

After activation, actual Worker imports passed fresh runtime_preflight and
sessions.search through the real SQLite adapter in an isolated TemporaryDirectory,
with preparation forbidden: executed,0preparation,0model,0search. No production
Task/Run was created; native business end-to-end model acceptance not claimed.

## Production release and preservation

Only idle Worker recreated after0effective leases/0pending commands/0active
Trench Turns. Existing schema105, API/frontend/Redis/Search/TLS/Yahoo-egress and
MCP session container identities/start/restart/cooldown retained. Other products
untouched; preexisting pgadmin/caddy restart loops excluded from exact restart
counter comparison, no fixes attempted there.

New Worker `zebra-worker:runtime-readiness-20261028` image:
`sha256:145133fe22ea1e99d38f48d6bf40ebe073d378f2693d63be4ee01a738ddb8bf5`.
Four-module overlay on previous accepted Worker, retaining canonical budget fix.
All preimage module hashes matched source before overlay. Runtime User=zebra.
Only configuration changes: sandbox image replaced by the verified existing
Python digest; healthcheck appends runtime_preflight with15s healthcheck bound.
Security/mounts/other environment unchanged. Old immutable Task facts untouched;
new configuration does not rewrite old frozen runtime identity or resume it.

Original23event hash preserved:
`99dc91b0fbdc01f16e6e2cfc2e95d881a89e13b43358b031f21e30d4274f452f`.
Still1model request/0web.search, failed, no final answer. All existing Trench Turn
status/answer/request/cursor rows compared equal across activation.

Private evidence and complete Compose chain:
`/home/ubuntu/releases/20261028-runtime-readiness/`.
Latest overlay `worker-override.json` must remain in subsequent deployments;
source integration alone does not replace the old production override.
Local safe evidence `.artifacts/cloud-runtime-readiness-20261028/remote-safe/`.
Rollback only Worker after idle checks using deployment-plan.private.json
before_files; preserves Search/MCP. That rollback restores the known-bad image
reference, so is emergency rollback only, not a sustainable operating version.

## Limits

No new model request authorized or made this round. Prior one-line real acceptance
was insufficient for tool/runtime paths; this round verifies those directly with
no-model execution, but does not assert all research/business flows are proven.
Readiness is not a guarantee against a later daemon/disk/provider outage. Old
LockNotAvailable incident exact holder remains unknown; not claimed repaired by
this slice. Original failed Run is deliberately retained, not replayed or relabeled.

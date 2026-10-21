# Native script Worker contract v1

Producer: CA-P3-01B; native script ABI remains `cloud-agent.native-script/1`.

| Artifact | Meaning |
| --- | --- |
| script-bundle.schema.json | Explicit script extension wrapping the unchanged Bundle1 |
| script-plan.schema.json | Exact runner, bindings, scopes and source/manifest lock |
| script-assembly.schema.json | Resolved nonsecret assembly, dedicated reader discriminator |
| definition-v3.schema.json | Immutable Definition3 with the complete resolved assembly |
| snapshot-v3.schema.json | Immutable Task snapshot3, including its exact Definition3 |
| invocation-event.schema.json | Fenced started/completed invocation facts, not Coverage proof |
| example-script-bundle.json | Deterministic illustrative closure; not an operator approval |

The embedded base Bundle still declares script ABI `unsupported`: its existing
20-domain reader is unchanged and must reject this outer object. Only the new
explicit script extension reader adds the script plan. Never strip the wrapper
and claim the base envelope authorizes script execution.

Manifest/source bytes follow [ABI1](../native-script-v1/). Source stays in the
private operator `execution-catalog/2`; snapshots contain manifests and digests,
not source or credentials. The example does not provision or approve its image,
Python, scopes or assets. Runtime execution requires current approval and Host
permission, a compatible Worker, PostgreSQL fencing and a real isolated runtime.

The existing generic Definition materialization resolver understands the wrapper.
The pinned `/management/v1/runtime-publication` and bundle-validation/1 contracts
remain Bundle1-only; this directory does not extend those scoped HTTP contracts
or provide an asset upload/distribution API. Overdoze integration is a later slice.

See [implementation and recovery rules](../../NATIVE_SCRIPT_WORKER.md).

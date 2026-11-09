# CA-P5-03 — Optional authenticated Worker process binding

Implemented composition metadata, not a new identity/qualification/activation service.
[Versioned artifact](contracts/runtime-worker-process-v1/contract.json), [fixed interop vector](contracts/runtime-worker-process-v1/golden.json).
No new HTTP endpoint, schema, compatibility algorithm or source v1 gate response field.

The existing Worker observer generates its actual process UUID and uses real runtime preflight plus
snapshot compatibility. An executor knows its own container ID, but previously had no authenticated
mapping to this UUID. With ZEBRA_RUNTIME_INSTANCE_ID and a separate per-instance32-byte
ZEBRA_RUNTIME_INSTANCE_BINDING_KEY configured, composition emits one signed JSON line containing
that actual observer UUID/namespace/instance reference. Default unset remains silent and unchanged.

The envelope carries contractVersion, base64url unpadded payload and hmac-sha256 hex signature. Signing
input is UTF8(runtime-worker-process/1) + LF + exact decoded payload bytes. The decoded JSON contains
only contractVersion, instanceId, namespaceId, processId. A consumer verifies raw bytes before trusting
fields, then rejects unknown/missing/mismatched fields. Encoding avoids cross-language JSON escaping
ambiguity. The golden key is public fixture data, never an operational credential.

Keys are private workload material, unique per instance. They never enter ZebraAgentSettings, Bundle
snapshots, public API responses or logs. The key is not an Agent identity_key/access/refresh token and does
not change business/BFF authentication. Sandbox execution retains its existing separate empty/private
runtime environment; workload environment must not be mounted/passed into agent sandboxes.

Process instance reference is transport metadata excluded from the non-model baseline HMAC, as gate
transport settings already are. Old task recovery must not drift when a new container is assigned an ID.
The optional ID requires canonical UUID and a configured Runtime gate; invalid/missing keys fail startup,
not silent fallback. Existing configure_runtime_gates still performs cloud/PostgreSQL/namespace checks.

A signature alone does not prove image provenance, current process liveness, compatibility, complete
fleet, or safe stop/activation. The Go owner must bind the exact approved image/container and launch key,
reject conflicting bindings, and compare the resulting process UUID against fresh scoped Native qualified
observations for the exact candidate/old snapshots. All existing v1 false safety flags retain their meaning.
Untrusted model/script text or arbitrary log JSON is never authority. No generic log-to-auth conversion.

Focused tests cover malformed config/key, secret suppression, baseline invariance, signed exact payload,
tamper rejection and existing observer behavior. Full gates and pinned successor source are recorded in
evidence. Historical v1 artifact/source manifests remain historical; the new additive composition delta is
reported explicitly, not retroactively substituted for the old published source commit. No production
migration/deployment, Task/Controller/SDK/BFF mutation or Coverage/history rewrite.

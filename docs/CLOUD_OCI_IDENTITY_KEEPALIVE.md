# CLOUD-OCI-IDENTITY-KEEPALIVE-01

2026-10-14; Luke Ding / Codex; local integration only. No new Run or model calls.

Explicit Docker TCP+mTLS native engines now use a verified persistent HTTPS connection for fresh daemon ID reads. Every mutating command still checks current daemon identity first. Certificate/issuer/hostname validation, public/private credential-file drift, full instance labels, lease/fence checks, writable workspace checks and original CLI commands are retained. Context-selected, unverified TLS, Unix, Podman and custom-runner paths retain CLI reads.

The helper has a bounded response, a cumulative10s deadline with socket interruption, serialized connection access, one read-only reconnect on a closed keepalive connection, and no mutating-command retry or CLI fallback on identity failure. Explicit cleanup closes the connection; unused engine lifetime cleanup releases it too. No new dependency or authority/result cache.

45 focused engine/helper/runtime/Worker checks pass; targeted mypy and Ruff pass. Final no-model remote provisioning measurements completed; local Worker updated with exact deployed source hashes and successful actual remote runtime preflight. Measurements use synthetic instance lifecycle bookkeeping rather than production canonical lease/Task tables; they certify the engine path only, not whole Run or production fencing acceptance.

## Final same-source measurements

Three alternating before/after pairs on the same remote gVisor daemon/image/runtime limits, including create, exact-label inspect, start, writable-workspace check and cleanup. The existing workspace mount was only checked with test -w; no content was read or written. All six isolated containers removed.

| Engine path mean | Before | After | Reduction |
|---|---:|---:|---:|
| provision | 11.529s | 7.374s | 36.04% |
| pin initialization + provision | 12.987s | 8.882s | 31.61% |

Before inclusive samples:9.716/15.956/13.288s; after:7.265/9.633/9.747s. Mean saving4.105s. Small sample, substantial remote variability; no P95/whole-Run/browser/model-first-token certification. The lifecycle collaborator uses synthetic instance state, so PostgreSQL authority queries are not included. Native production fencing code is unchanged and existing deterministic checks pass.

Actual Worker image built and activated locally; source hashes match final measured code. No new Run/model call, push or remote deployment. Private raw proof and source hashes: .artifacts/ttft-analysis-20261014/keepalive-final.safe.json and keepalive-summary.safe.json in the primary checkout.

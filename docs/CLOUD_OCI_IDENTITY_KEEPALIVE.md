# CLOUD-OCI-IDENTITY-KEEPALIVE-01

2026-10-14; Luke Ding / Codex; local integration only. No new Run or model calls.

Explicit Docker TCP+mTLS native engines now use a verified persistent HTTPS connection for fresh daemon ID reads. Every mutating command still checks current daemon identity first. Certificate/issuer/hostname validation, public/private credential-file drift, full instance labels, lease/fence checks, writable workspace checks and original CLI commands are retained. Context-selected, unverified TLS, Unix, Podman and custom-runner paths retain CLI reads.

The helper has a bounded response, a cumulative10s deadline with socket interruption, serialized connection access, one read-only reconnect on a closed keepalive connection, and no mutating-command retry or CLI fallback on identity failure. Explicit cleanup closes the connection; unused engine lifetime cleanup releases it too. No new dependency or authority/result cache.

45 focused engine/helper/runtime/Worker checks pass; targeted mypy and Ruff pass. Final no-model remote provisioning measurements and local Worker activation are pending. Measurements use synthetic instance lifecycle bookkeeping rather than production canonical lease/Task tables; they certify the engine path only, not whole Run or production fencing acceptance.

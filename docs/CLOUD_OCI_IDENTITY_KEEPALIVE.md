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

## CLOUD-OCI-CAPABILITY-KEEPALIVE-01 (2026-10-14)

The pre-reservation gVisor capability query now performs one fresh verified TLS /info request through the native persistent connection. Current daemon ID, ServerVersion and Runtimes come from the same response; no result/authority cache. Exact known format only; other CLI formats/custom runners/context/Unix/Podman remain unchanged. Original2s probe timeout and TimeoutExpired semantics remain so existing readiness retry behavior is retained.

47 focused checks and targeted Ruff/mypy pass. Isolated native PG primitives (3 cold fixtures) have median progress recovery111.64ms, initial inputs109.39ms, ready-input reread49.53ms and context snapshot18.22ms. They exclude full Host authority/recorder writes and are not attributed timings of historic business Runs. No PostgreSQL recovery/context optimization is made without evidence. Final same-source remote initialization/capability paired timings completed and local Worker activated; no model calls.

### Pre-reservation measurements and remaining boundary

3 alternating read-only pairs (current verified source, same daemon/settings):

| Mean stage | Before | After | Change |
|---|---:|---:|---:|
| capability query | 1.259s | 0.272s | -78.39%, saving0.987s |
| initialization + capability | 2.688s | 2.015s | -25.04%, saving0.673s |
| initialization only (unchanged logic) | 1.429s | 1.743s | +21.98%, reflects variability; no initialization saving claimed |

Capability samples before1.540/1.537/0.702s; after0.278/0.266/0.272s. Engine initialization still incurs a cold fresh /info read. Read-only instrumentation: certificate context/client certificate processing around1–2ms total, TCP+TLS connect208–218ms, full initialization854–2050ms. Subsequent instrumentation partitions remaining first-response wait into headers427–1138ms and body209–913ms. Server processing vs network delay cannot be distinguished from these client-side observations. Do not blame local memory/crypto or cache authority/daemon results to hide this wait.

The original3.4–5.7s historical interval has not been fully attributed: the isolated storage primitives exclude full Host binding/authority and recorder writes, and historical event timestamps are backfilled. This slice addresses the confirmed capability-query overhead only. No live full-Worker/browser/TTFT SLO is inferred from these measurements.

47 current-source focused tests pass, targeted Ruff/mypy pass. Deployed Worker source hashes match measured source; actual remote preflight passes and Worker is running/healthy. Native storage fixtures assert zero model_request_started and are cleaned up. Remote probes perform no reservation, sandbox creation, Run submission or model invocation. Raw proof under primary .artifacts/ttft-pre-reserve-20261014/. No push/remote deployment.

## CLOUD-OCI-CLI-CONNECT-01 (2026-10-15)

Validated explicit INFO CONNECT routing now also applies to the native pinned Docker CLI private environment. Explicit mTLS/host flags, fresh identity, exact labels/ID, PG authority/fence and mutation retry behavior remain unchanged. No global environment modification; absent configuration keeps existing behavior.

66 focused runtime/worker regressions, targeted Ruff/mypy passed. Three alternating real Worker/gVisor lifecycle pairs with real isolated PostgreSQL authority/fence: provision mean 5.264s→1.776s (66.26% reduction). Pinning 21–27ms. All six containers removed and temporary PG schemas dropped. No model calls in lifecycle proof. Evidence .artifacts/oci-cli-connect-20261015/results.safe.json; real Trench startup acceptance pending local activation.

- CLOUD-OCI-CLI-CONNECT-01 local activation/real acceptance: three newFlash/high/general/v2 reply Runs all1 model round/0 tools; first model mean7.278s vs historical11.138s (34.7% reduction), Host completion mean11.585s vs16.973s (31.7%). reserve→model mean2.516s vs6.707s. Historical-v-current observational comparison, not concurrent model A/B or browser TTFT. Worker healthy/hash match/preflight ready; derivative one-source image, no dependency changes; no push. Detailed evidence primary .artifacts/oci-cli-connect-20261015/REPORT.md.

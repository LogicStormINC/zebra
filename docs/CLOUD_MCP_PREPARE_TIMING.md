# Cloud MCP preparation and phase timings

CLOUD-MCP-PREPARE-TIMING-01, locally delivered 2026-10-20.

The accepted Run `10234587-9ace-4bea-bbaf-9b45af40d8cb` spent 17.943 seconds
in its first MCP call. A runtime registration appeared 3.709 seconds after that
call started. The generic local gateway prepared a sandbox before dispatching
remote Cloud MCP, even though this transport executes Worker HTTPS/SSE and never
uses the OCI workspace. That visible window also includes related checks; it is
not a measurement of pure container startup or guaranteed recoverable time.

## Minimal correction

`LocalToolGateway` takes exact selected names from the explicitly composed
`CloudMcpTransport.model_tools`. Only these names join the existing bounded
runtime-free routing. There is no `mcp.*` prefix exemption. Non-Cloud MCP,
unknown/spoofed aliases and ordinary workspace/command tools retain the previous
runtime preparation path and its quota/isolation checks. Tool resolution, normal
Policy/effect handling, per-frame live scope/lease/credential and Plugin guards,
input/output bounds, DNS pinning, SSRF/redirect controls and cancellation checks
remain in place. No new authorization is inferred from a timing or tool label.

## Timing fields

The existing tool result metadata carries `runtime_prepare_ms` when execution
uses a deferred runtime. This measures only `ensure_ready` inside that tool
dispatch; selected Cloud MCP reports zero because it did not prepare a runtime.
It does not claim that an eagerly prepared runtime never existed elsewhere.

Successful Cloud MCP results also carry a bounded numeric `mcp_timings_ms` map:

| Field | Boundary |
| --- | --- |
| `total` | Session creation/initialization, call and session cleanup; excludes outer tool projection and output normalization |
| `initialize` | Initialize request, including opening SSE when needed |
| `initialized_notify` | Delivery of notifications/initialized |
| `tools_call` | The exact tools/call request and its result |
| `authorization` | Sum of live frame authorization/credential resolution spans |
| `dns_ssrf` | Sum of existing preflight and connection-time public DNS/SSRF checks |
| `connect` | Admitted socket connection, including controlled proxy negotiation if configured |
| `tls` | TLS handshake with unchanged hostname/certificate validation |
| `sse_open` | SSE GET until response headers, including its connection work |
| `sse_endpoint_wait` | Reading and validating the same-origin endpoint event |
| `http_post` | POST until response headers; SSE also closes the acknowledgement response |
| `initialize_result_wait` | Reading/parsing initialize result after the POST |
| `tools_call_result_wait` | Reading/parsing tools/call result after the POST |

Only reached phases appear. Fields are milliseconds and repeated low-level
phases accumulate within one call. Parents contain children: do not add all
fields together. `http_post` can include server waiting before headers, so it is
not purely network time. SSE call-result waiting is separate from initialization
waiting. An optional bounded `other_result_wait` labels other methods without
using arbitrary remote text as a metric key. This is elapsed-time attribution,
not remote server CPU or distributed clock synchronization.

Handshake/authorization/call exceptions retain their original propagation and
emit `cloud_mcp_timing status=failed phases_ms=...` with only internal phase names
and numeric durations. No exception text, URL, session header, credential or body
is included. Success uses the existing result/event path; no new telemetry SQL,
service, dependency or global timing state was added. Local transports without
the optional timing collector keep the same wire behavior.

## Validation and local Worker

The new regressions first reproduced unwanted preparation and missing timings.
The final focused suite passed **414 checks**, with **1 environment-dependent
skip**; full Mypy passed **1319 source files**, Ruff passed on changed paths and
the file-size gate passed **3220 files / 0 violations**. Cases cover exact Cloud
selection, workspace and non-Cloud compatibility, spoofed aliases, cancellation,
Plugin revocation, live lease/credential checks, malformed arguments, DNS
rebinding/SSRF, TLS failure, bounded framing, output handling and numeric redacted
timing accumulation.

The old Worker image had 127 filesystem layers. A normal source overlay hit the
engine's layer ceiling; a one-layer overlay built but could not start. The final
offline build copies that same immutable image filesystem into a flat image and
adds the six source files. Image environment/startup/user/labels are preserved,
source hashes match, and the final image has three layers. No dependencies were
downloaded, global Docker configuration changed or running service flattened.

Before replacement: zero effective leases/pending commands. Three historical
running projections are from August with released expired leases and no pending
commands; they were inspected, not rewritten or resumed. Worker-only replacement
is healthy: `12694c55ae77`, image `zebra-worker:cloud-mcp-prepare-timing-01`
(`e179099d4ac8`). Environment, mounts, network, credentials volume, startup,
security and resources match the prior Worker.

Both an isolated `--network none` image process and a separate process in the
updated Worker passed the same real-gateway/offline-wire smoke: zero Cloud MCP
preparations, one required workspace preparation, eight fresh frame guards for
two calls, unchanged eight captured SSE HTTP requests and closed streams.
These are deterministic checks, not real remote executions or measured speedups.

APIs, original Search/TLS container IDs/start times/restart counts, persistent
Search processes and Exa cooldown hash are unchanged. Schema, model/tool event
counts, 17 extension heads, 127 snapshots, the accepted Run's complete durable
evidence and both original partial Turn hashes are unchanged. No new Run, model,
search or remote MCP request was sent; no original MCP/Search process or session
was restarted. High/v2, model rounds, prompts, Trench product logic and session
reuse are outside this change. The real 46.162-second question was not replayed;
no numerical page performance improvement is claimed yet.

Local evidence is under `.artifacts/cloud-mcp-prepare-timing-01/` in the primary
checkout. `activation.consumed` marks the completed update: do not rerun activation.
`verify_services.py`, `capture.py` and recorded source/protection proofs support
read-only follow-up. Local integration only; no push or remote deployment.

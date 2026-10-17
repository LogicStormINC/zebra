# Cloud controlled public egress connector

CLOUD-EGRESS-CONNECT-01 adds an explicitly configured numeric-IP SOCKS5 connector
to Cloud native HTTPS and DoH. Local defaults are unchanged. Final live/page
acceptance is recorded below; a network probe is not page performance proof.

## Configuration and lifecycle

Cloud Worker setting `ZEBRA_WEB_EGRESS_SOCKS_ENDPOINT` is a JSON pair, for example
`["127.0.0.1",18446]`. The numeric relay must be reachable from the Worker network
namespace. OrbStack host loopback is reachable through its host control address;
normal Cloud sidecars can share the Worker's network namespace. Hostnames,
credentials, zero/multicast/scoped addresses and invalid ports are rejected.
Local profile rejects this setting. Cloud and production profiles compose it
explicitly; API and model clients do not inherit the route.

Provision the trusted egress outside the Agent with its own credentials and
supervisor. The optional foreground operator launcher reuses native SSH:

```sh
python scripts/cloud_egress_tunnel.py VERIFIED_SSH_ALIAS --port 18446
```

`--interface en0` is an optional macOS operator-only diagnostic/development route.
It does not belong in generic runtime logic. SSH host-key checking is strict,
interactive authentication disabled, and listening is loopback only. An existing
operator supervisor owns restart; never create SSH per task/request or put SSH
keys into Worker/sandbox/task inputs. Local activation uses native launchd rather
than a new daemon implementation. Do not use nc idle timeouts on persistent SSH.

Before taking tasks or creating model clients, the Worker makes one bounded
SOCKS CONNECT to the fixed existing DoH service (1.1.1.1:443), with no task data,
HTTP/model request or cached authority. An unavailable route fails startup; there
is no transparent fallback. This checks the remote channel, not just the listener.

## Request and security boundaries

- `public_egress.connect_address` is shared by public HTTPS and configured DoH.
  Fresh DNS and whole-answer public-IP checks remain in the original resolver;
  only the validated numeric address is sent to SOCKS. No relay-side target DNS.
- HTTPS keeps its original hostname, SNI, CA and certificate verification. There
  is no HTTP CONNECT proxy delegation or system-proxy fallback in this route.
- The operator-bound private search backend retains its exact endpoint admission,
  fresh private DNS pinning and direct TLS connection. Private URLs are not sent
  to an external egress. Model, host-authority and internal API clients are unchanged.
- Only Cloud gateway wiring passes the immutable endpoint to the existing native
  child scope. The parent explicitly overwrites private child configuration even
  when disabled; ambient child configuration cannot opt the local path in.
- The original live authority callback is required and keeps running while queued,
  connecting and reading. Success is never cached by the connector. The existing
  parent deadline, post-response check and kill/reap provide request cancellation.
- Each request owns its native child lease. Cancelling one child closes its channel,
  not the shared operator SSH transport or a sibling request. The scope still has
  two bounded children, idle retirement and original cleanup behavior.
- SOCKS reads/writes have one absolute handshake budget and bounded fields. Bad
  authentication methods, status/version/reserved bytes, EOF or invalid addresses
  close the socket without replay. A failed relay is never retried on a direct route.
- Target and relay socket address families are independent. Direct IPv6 preserves
  its original sockaddr; a relayed numeric IPv6 target can use an IPv4 relay.
- DoH retains only execution-child-local HTTP transport, with the original idle
  expiry and failure retirement. Every DNS query/parser validation runs again.
  No cross-task DNS answer, authorization or target-connection cache is introduced.

Browser/crawl-specific transports keep their existing path; this connector covers
the native public HTTPS/DoH path. Transient stream v2 is independent of web-pipeline
v2. Neither mode, thinking level nor autonomous tool choice is changed here.

## Validation before activation

Focused no-model suite: 158 passed across public connector, MCP TLS, DoH scope,
DNS, private search, cancellation, Worker execution wiring and config. New direct
regressions cover Cloud-only composition/readiness, fragmented protocol/deadline,
IPv6 target/IPv4 relay, bad replies, original-hostname TLS failure, DNS rebinding,
ambient proxy rejection and private backend isolation. File sizes, all tracked
Python Ruff, Mypy (1291 sources) and deterministic eval (30/30) pass.

Fixed4 ABBA no-model cohort uses the production connector; it injects only phase
observers, never socket routing or DNS answers. Both variants have identical native
DoH scopes and source; only the operator endpoint differs. Predeclared gate is
zero failed fetches, cold median improvement >=10%, >=3/4 cold pairs improve.

| Pair | Cold disabled ms | Cold enabled ms | Follow-up disabled ms | Follow-up enabled ms |
|---|---:|---:|---:|---:|
| 1 | 3580.5 | 1893.6 | 1422.6 | 1166.1 |
| 2 | 2237.6 | 1592.0 | 2645.6 | 1366.9 |
| 3 | 2454.8 | 1919.8 | 1161.8 | 1434.4 |
| 4 | 1722.0 | 1684.6 | 2792.8 | 1146.8 |
| Median | 2346.2 | 1789.1 | 2034.1 | 1266.5 |

Cold improves23.7%/4of4; follow-up improves37.7%/3of4. All32 website GETs and32
fresh DoH queries succeed. Each variant retains eight DoH connections across its
16 requests; all32 target TLS handshakes remain fresh. Upstream caches are not
controlled. Egress startup is excluded: a supervised, already-ready route is
required, not per-request SSH construction. No favorable fifth pair or resampling.

Actual connector cancellation: revoked request lifetime528ms including startup;
sibling returnsHTTP200 in1643ms, both children reaped. These are not measurements
of signal-to-cancellation latency. Callback probes are no-op diagnostics; fresh
signed authorization is separately checked by the actual page path.

## Local deployment and page acceptance

Pending until normal-source image/config checks and fixed4 actual high/Flash/v2
page ABBA complete. Use one candidate Worker source image for both variants; only
its endpoint changes. Preserve existing API/pool/startup, schema103 native generic
plan settings, private search configuration and Trench. No model invocation is
allowed before the no-model gate above.

## Reproduction and evidence

Use the project Python environment with the correct workspace paths:

```sh
python scripts/check_cloud_egress_connector.py --verify /absolute/path/to/cohort.json
pytest tests/agent_runtime/test_public_egress.py -q
```

Live acceptance requires the prebuilt endpoint plus `DOH_COLD_TRACE` set to a fresh
output folder. `--cancel` reuses the original revocation/sibling probe with only
production-connector completion observations. Raw evidence and source snapshots
are private under `.artifacts/cloud-egress-connect/`; no credentials, response
text or private model reasoning is retained by network observers. Local operator
service configuration contains no SSH private keys or task authority tokens.

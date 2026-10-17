# Independent egress cold-route acceptance — 2026-10-17

## Decision

CLOUD-EGRESS-ROUTE-01 finds a stable local network-subpath improvement: with an
already-ready independent egress, cold fetch batch median is 2.070s → 1.675s
(19.1%, four of four matched blocks). This is about 395ms per measured batch,
not a measured percentage improvement in page first-body time.

The smallest viable next integration is an operator-configured, ready and reused
egress connection for Cloud native network children. It must keep fresh local
DNS/public-IP validation, numeric-IP routing, original-hostname verified TLS,
live authority callbacks and existing per-request cancellation. No model,
prompt, quality gate, high-thinking/v2 or Trench change is needed.

This slice delivers the route prototype/runner and evidence, not a production
connector. The normal Worker still uses its original network path. No model or
real-page cohort was run, no services restarted, no global proxy setting changed.

## Controlled comparison

The same Worker, source overlay, CA bundle, URL, headers, parser, DNS validation,
DoH composition and native cancellation code run in all variants. There are
fresh children and fresh DoH/target TLS connections for each two-URL batch.
Cold refers to client connections; upstream resolver/CDN caches are not controlled.
The remote host runs no Agent or model for this comparison.

| Route | Diagnostic connection path |
|---|---|
| A | Existing Worker → local Mihomo proxy → public targets |
| B | Worker → pre-established SSH SOCKS → same remote egress; SSH itself uses local proxy |
| C | Worker → pre-established SSH SOCKS → same remote egress; only SSH uses physical-interface binding |

A known SSH host was reused, with normal SSH host-key/authentication checks.
Both SOCKS listeners bind host loopback only. OrbStack exposes them to the Worker
through its host control endpoint. C uses the native per-process command
`ProxyCommand=/usr/bin/nc -b en0 %h %p`; no global routes, proxy policies, TUN or
business-service configuration change. macOS interface binding is a diagnostic
mechanism, not a proposed portable Cloud runtime dependency.

The child-only adapter sends numeric public addresses using SOCKS5 CONNECT;
there is no remote hostname resolution for tool targets. Original DNS response
validation and original target hostname TLS verification remain in the Worker.
The configured private relay address is a control endpoint, not an admitted
website destination. This cohort covers Fake-IP recovery with A/IPv4 answers;
generic IPv6/relay-family behavior is not accepted by this prototype.
The adapter rejects private/reserved/multicast destination
IPs before touching that endpoint. No system-proxy flag is enabled and no
credential or authority token is sent to the relay by these probes.

Four fixed matched triples: **ABC / CBA / ACB / BCA**. Every pair ordering is
balanced 2/2. No retries or favorable replacement within the accepted cohort.

| Block | A ms | B ms | C ms |
|---|---:|---:|---:|
| 1 | 1896.6 | 3213.0 | 1656.1 |
| 2 | 1976.4 | 3117.7 | 1693.8 |
| 3 | 2215.3 | 2982.1 | 1803.8 |
| 4 | 2163.4 | 3794.2 | 1569.7 |
| Median | 2069.9 | 3165.4 | 1675.0 |

All 24 fetches return HTTP 200/nonempty; all 24 DNS queries are fresh. There are
48 cold TLS handshakes, not cached website answers or retained target sockets.
A→C improves 19.1% and B→C 47.1%; C wins every matched block against both.
Site medians A/B/C are PostgreSQL 2065/3157/1668ms and Redis 1291/2101/1009ms.

SSH transport is already established in B and C. C setup measured **617ms**,
excluded from request timing. A six-second idle-window SOCKS control passed.
The candidate requires a ready reused egress; rebuilding SSH for each request
would add more setup than the observed median A→C saving. This is cold HTTP/TLS,
not a claim that an entirely cold egress service has become faster.

## Local proxy and upstream wait

Actual Worker phase medians, milliseconds; nested phases must not be summed twice:

| Phase | A | B | C |
|---|---:|---:|---:|
| Fresh public DNS, including DoH connection/query | 450.7 | 823.2 | 268.6 |
| DoH TLS | 306.0 | 245.4 | 94.6 |
| DoH response headers | 108.3 | 274.3 | 78.7 |
| PostgreSQL TLS | 632.8 | 691.6 | 308.1 |
| PostgreSQL response headers | 256.8 | 605.0 | 275.7 |
| Redis TLS | 314.4 | 259.5 | 61.1 |
| Redis response headers | 146.7 | 416.7 | 112.0 |

B and C use the same remote egress host. Redis has the same resolved public IP
in every B/C sample. Its TLS and header improvements support attributing a
substantial part of the delay to the client-side proxy-carried route rather than
the remote site's work. PostgreSQL DNS rotates addresses, so do not attribute
every per-request difference solely to the local proxy or claim a production p95.
The earlier B-only feasibility cohort is retained and not substituted for A/B/C.

A separate remote-only two-URL mechanism probe uses the same DoH parser extracted
from production, numeric public-IP pinning, matching Accept/encoding/user-agent,
verified hostname TLS and HTTP/1.1. It reports:

- DoH query totals 24.6/40.0ms, TLS 11.8/14.8ms, header waits 4.2/18.4ms.
- PostgreSQL total 903.5ms, target TLS 189.2ms, header wait 338.1ms.
- Redis total 153.5ms, target TLS 9.8ms, header wait 99.6ms.

Remote Python 3.8/OpenSSL 1.1.1 differs from the Worker's Python 3.12/OpenSSL 3;
this is mechanism evidence, not the causal performance baseline or projected
page latency. Header wait still combines server and network waiting. There is no
remote origin trace to split every hop. The remote probe installs no files,
packages, daemon or model on that host; its source is sent through SSH stdin.
An earlier mechanism probe negotiated Redis HTML because it lacked matching
Accept headers; it is preserved separately and not used for this comparison.

The physical-interface preflight reaches the SSH host (TCP39ms/banner90ms),
while a separate direct physical-interface TCP attempt to 1.1.1.1:443 times out
at3s before TLS. Broad direct routing is therefore not established by this test.
The candidate directly reaches the controlled egress and routes verified HTTPS
through it; no blanket global-direct change is justified.

## Cancellation, authority and failure boundary

The same direct SSH transport carries two concurrent real native requests.
One is revoked after its SOCKS channel connects. The original parent callback
terminates/reaps its child; its sibling returns HTTP200, and closing the scope
reaps both children. Cancelled call lifetime513ms and sibling1650ms include
startup/network time; 513ms is not a measured signal-to-cancellation latency.
The shared SSH transport remains alive through this check.

Fresh callback activity is checked in the cohort, but the callback is a diagnostic
no-op. This is not new signed-JWT end-to-end authorization acceptance. Existing
fresh authorization code is unchanged; 80 focused DoH/native cancellation/DNS
regressions pass. The actual-route check covers revocation/sibling isolation,
not every malformed SOCKS response or production relay-failure scenario.

The first direct tunnel command incorrectly used `nc -w 5`; its idle timeout
closed the tunnel before measurement. Eight C requests then failed at the local
relay. That complete failed cohort is retained and rejected by the verifier;
fast failures never count as speedups. Only the diagnostic command was repaired,
removing its idle timeout while retaining SSH setup/liveness controls. A new
complete predeclared triple cohort ran after readiness/idle checks. No application
request timeout, DNS/security rule or production test fixture was loosened.

## Minimal production integration boundary

Do not ship the diagnostic monkeypatch as a production driver. A focused follow-up
should use one explicit numeric-IP connector shared by `mcp_http_egress.py` and
`doh_transport.py`, composed only by Cloud settings/gateway wiring:

1. Operator-only relay endpoint and readiness/lifecycle; local default unchanged.
   Relay/SSH credentials remain outside agent requests and disposable sandboxes.
2. Reuse current sockets/stdlib protocols; keep public-IP admission before relay
   CONNECT, exact hostname TLS and fresh DNS on every request. No DNS-answer cache.
3. Reuse native child deadline/check/kill/reap, preserve original cancellation
   errors, bound protocol reads, fail closed on bad/unavailable relay. No automatic
   replay, route fallback or task rerun.
4. Validate protocol rejection and real revoked/sibling behavior through that
   explicit connector; then evaluate one fixed actual-page cohort with high
   thinking/v2, autonomous tools and fresh signed authority.

The current evidence supports this optional route, not a new HTTP client library,
new global proxy policy, a macOS-specific runtime branch, or a claim that model
waiting has improved. Production route composition/page verification remain OPEN.

## Reproduction and retained evidence

Runner `scripts/check_cloud_egress_route.py` imports the existing child observer
and URL set. Its process-only `EGRESS_DIAGNOSTIC_ROUTES` maps B/C to trusted
numeric relay address/port pairs. These are diagnostic settings, not production
feature flags. Run inside an isolated Worker overlay, with fresh output folder:

```sh
python scripts/check_cloud_egress_route.py --selfcheck
python scripts/check_cloud_egress_route.py --verify /absolute/path/to/triples.json
```

The verifier requires complete fixed order, successful results, 24 fresh DNS
responses, 48 TLS handshakes and 32 relay channels. It rejects the failed tunnel
cohort. `--cancel` separately runs the real tunneled revocation/sibling probe.

Private `.artifacts/cloud-egress-route/` retains initial feasibility `cohort.json`,
accepted `triples.json`, `triples.log`, executed-source snapshots, phase metrics,
failed-tunnel cohort/log/source, setup-error log, direct interface/TLS preflights,
remote mechanism variants, cancellation proof, SSH process/socket evidence and
proxy-config digest. Website text/model reasoning/secrets are not collected.
Normal API/Worker images/health/restart counts are verified separately.
Both owned SSH process groups and the Worker overlay were removed. The original
global proxy configuration digest is unchanged. No push, deployment or model run.

Local delivery: runner/evidence document integrated into cloud-agent-trench as
55614acf. Actual primary DoH/native cancellation/public-DNS regressions pass85,
including preserved local DNS recovery changes. Diagnostic Ruff/selfcheck/trace
verification pass in the primary environment. All21 existing tracked dirty file
hashes were intact before appending only this task's governance notes. Original
API/Worker images remain healthy with zero restarts; both owned tunnel listener
ports are closed and the global proxy configuration digest is unchanged.

# Actual web.fetch TLS and upstream wait — 2026-10-17

## Result and delivery boundary

CLOUD-FETCH-TLS-01 is a diagnostic/acceptance slice. No additional production
transport change is justified by this cohort. Existing pending Cloud DoH reuse
improves follow-up fetch batches, but does not pass the cold-request gate.
No model or page cohort was run, and normal services/configuration were unchanged.
Fresh authority callbacks, fresh DNS/public-IP checks and request cancellation
remain the existing production contracts; these probes do not constitute a new
end-to-end signed-authorization acceptance.

## Reproduction

Run `scripts/check_cloud_fetch_tls.py` in an isolated Worker source overlay with
`PYTHONPATH` pointing to the overlay and `DOH_COLD_TRACE` to an empty output folder.
The script imports the existing cold-child observer rather than duplicating it.
It replaces only the diagnostic child command; actual fetch parsing, projection,
TLS verification, DNS parser and native kill/reap remain production code.

- Fixed four A/B pairs, order AB/BA/AB/BA; all adverse samples retained.
- A: existing one-process-per-request native dispatcher.
- B: pending execution-scoped two-child DoH reuse composition.
- Each variant: two concurrent official PostgreSQL/Redis fetches from cold
  children, followed by the same two URLs in the same scope.
- 32 website GETs, 32 fresh DoH GETs; every website result HTTP 200/nonempty.
- The URLs match the previous research scenario; no model, task admission or SQL
  instrumentation is involved. This is a network subpath test, not first-body E2E.
- Two separate two-fetch mechanism probes add CPU timing and Linux TCP_INFO.
  They are not additional acceptance pairs and are excluded from cohort medians.

Offline cohort verification (use the project Python environment):

```sh
python scripts/check_cloud_fetch_tls.py --verify /absolute/path/to/cohort.json
```

The verifier checks fixed order/completeness, successes, live callback activity,
32 fresh DNS responses, 32 target TLS handshakes and the 8 avoided DoH handshakes.
The live callbacks are no-op probes of the existing check seam, not fresh JWTs.
The existing deterministic regressions separately cover revocation and cleanup.

## Fixed results

All times are batch milliseconds; simultaneous requests overlap.

| Pair | A cold | B cold | A follow-up | B follow-up |
|---|---:|---:|---:|---:|
| 1 | 3243.0 | 3500.6 | 2690.0 | 2610.0 |
| 2 | 2859.5 | 4127.1 | 2972.8 | 2826.3 |
| 3 | 2477.1 | 2575.2 | 2801.2 | 2027.4 |
| 4 | 2786.7 | 2988.6 | 3103.0 | 2324.5 |
| Median | 2823.1 | 3244.6 | 2887.0 | 2467.2 |

Follow-up improves 14.5%, 4/4 pairs; cold is 14.9% slower, 0/4 pairs improve.
B has only eight initial DoH TLS handshakes vs A's sixteen. Both still execute
sixteen fresh DNS queries and sixteen fresh target TLS handshakes. Warm DNS
transport reuse cannot remove a first target handshake. These are small local
cohorts, not a production p95 or a causal explanation for every cold difference.

## Where the time goes

| Measured phase | Median ms | Range ms |
|---|---:|---:|
| Container-visible TCP connect | 1.0 | 0.6–8.3 |
| Runtime imports, excluding stdlib/boot | 202.2 | 196.3–239.6 |
| DoH TLS | 563.5 | 432.4–958.4 |
| DoH response headers wait | 184.9 | 99.8–924.5 |
| PostgreSQL TLS | 1086.5 | 883.2–1581.7 |
| PostgreSQL response headers wait | 470.5 | 289.4–771.5 |
| Redis TLS | 541.4 | 442.7–1122.2 |
| Redis response headers wait | 215.8 | 138.4–411.4 |

DNS + target TLS + target response headers account for median 90.6% of the
PostgreSQL fetch operation, excluding child startup/imports. DNS already includes
its TLS/headers; these nested timers are not summed twice. This identifies the
fetch subpath bottleneck, not the entire model/search critical path.

Separate mechanism traces show DoH TLS 617–627ms with 2.35–2.36ms CPU;
PostgreSQL TLS 777ms with 1.59ms CPU; Redis TLS 386ms with 2.09ms CPU.
Earlier CPU-only mechanism traces also retain PostgreSQL 1066ms/1.69ms CPU.
Local cryptographic CPU does not explain the wall time. Off-CPU time can include
network, proxy/remote waiting and scheduling; it is not a pure server timer.

Read-only routing observation found OrbStack as current Docker context and the
probe's public IP connections forwarded through the local Mihomo SOCKS5 chain,
using the same Taiwan node for DoH/PostgreSQL/Redis. No proxy setting was changed.
Linux TCP_INFO observed local RTT 0.70–2.80ms and zero local retransmissions in
the final mechanism probe. This describes only the container-visible TCP segment,
not RTT/loss beyond the proxy. Its first 104-byte layout follows the
[Linux UAPI tcp_info definition](https://github.com/torvalds/linux/blob/master/include/uapi/linux/tcp.h).
Do not report a 1ms Internet RTT or infer zero remote packet loss.

Redis reports cache HIT and tens of milliseconds in Server-Timing while client
header wait is hundreds of milliseconds. Its edge/origin/worker fields are not
necessarily additive. PostgreSQL has varying public DNS addresses and no useful
Server-Timing; there is no remote trace to separate its server CPU from each
network/proxy hop. Certificate verification stayed enabled; observed TLS is 1.3.

## Minimal decision and next gate

Retain the existing scoped DoH reuse and all identity/DNS/SSRF/cancellation guards.
Do not add retries, speculative requests, hard-coded fastest site IPs, DNS answer
caches, weaker TLS settings or a new target connection pool on this evidence.
None removes the first validated connection's remote wait, and extra requests
could increase cold load. No additional production fix landed in this slice.

The next useful experiment is the same bounded cold cohort on an isolated egress
network without this local proxy chain, retaining hostname TLS verification and
fresh DNS/public-IP pinning. Do not globally change the user's proxy or conflate
an egress-route improvement with a generic Cloud runtime code improvement.
Only after cold gains are stable should a real high-thinking/v2 page pair run.

## Evidence and checks

Private raw evidence is in the network worktree `.artifacts/cloud-fetch-tls/`:
`cohort.json`, `cohort.log`, `cohort-profiler.py.snapshot`, `metrics.json`,
`routes.json`, `target-routes.json`, `mechanism.json`, `tcp-mechanism.json` and
`tcp-mechanism.py.snapshot`. Website text, credentials and model reasoning are
not retained by these observers. Separate mechanism probes total four additional
website GETs and four additional DNS GETs; no resampling of the four-pair cohort.

Focused existing DoH scope/native cancellation/public-DNS regressions: 80 passed.
Diagnostic Ruff and offline trace verifier pass. No claim of full-suite, SQL,
model-round or real-page performance acceptance. Temporary overlay is removed
after evidence collection; API/Worker images, restart counts and service config
are unchanged. Primary unrelated dirty files remain untouched.

Local integration: diagnostic runner/document committed as faee9401 on
cloud-agent-trench; normal production transport source is unchanged by this slice.
Actual primary regressions, including the preserved local DNS recovery changes:
85 passed. All 21 pre-existing tracked dirty file hashes were verified intact
before appending only this task's governance notes. Temporary overlay removal,
original API/Worker images, healthy state and zero restart counts were verified.

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

Completed after the no-model gate above. Fixed four new conversations, ordered
A1/B1/B2/A2; A disables only the explicit endpoint, B enables it. Both use one
candidate source/observer image and identical API/config, with a fresh Worker per
case and the operator SSH channel already ready. The agent chooses all tools.
Prompt: official release dates and two major features each for PostgreSQL18 and
Redis8, official sources with links, concise answer. All four completed, using
DeepSeek Flash, thinking enabled/high, transient_v2, zero provider retries and
zero failed tools. Each committed exactly one answer; no forced tool sequence.

| Case | First visible answer s | Host whole turn s | Model rounds | Tools | Nonempty SQL calls |
|---|---:|---:|---:|---:|---:|
| A1 | 21.471 | 24.893 | 4 | 5 | 4015 |
| B1 | 12.671 | 14.995 | 3 | 4 | 3166 |
| B2 | 13.961 | 16.343 | 3 | 4 | 3225 |
| A2 | 12.999 | 16.573 | 3 | 4 | 3207 |
| A mean | 17.235 | 20.733 | 3.5 | 4.5 | 3611 |
| B mean | 13.316 | 15.669 | 3 | 4 | 3195.5 |

Observed mean first answer improves22.7%, whole turn24.4%, SQL calls11.5%.
These are small-cohort observations, not isolated causal estimates. A1 autonomously
made one extra evidence fetch and model round; all samples are retained. B2 first
answer is slower than A2. Do not claim universal page gains, fewer required model
rounds, or a database optimization from this connector. Its code adds no SQL.
Matched official fetches provide more direct network evidence: PostgreSQL fetches
A1892.9/1890.9ms vs B1697.7/1549.5ms (mean−14.2%); Redis fetches A819.7/921.0ms
vs B646.3/727.3ms (mean−21.1%). Search stays on the original internal route.
Click-to-first-provider mean remains2.776s vs2.757s; this does not fix admission.

First body means the first visible Markdown whose normalized text contains the
first16characters of the final answer, observed from Send by MutationObserver.
Progress text is excluded. This includes the explicitly temporary ordinary draft;
accepted answer can appear later. Whole turn ends at the persisted host completed
time. SQL counts are Python driver execute calls minus empty statements, covering
the matching Worker execution plus API request scopes started between Send and
host completion+1s. They exclude background work/DB-trigger internal statements,
are not PostgreSQL-wide statement counts, and are not comparable to prior probes
with different scopes. API counters are source-identical in both arms.

A preceding A0 calibration completed with3model rounds, but the old last-Markdown
selector followed collapsed progress rather than visible answer. Its full canonical,
SQL and host completion evidence is retained; first-body time is missing, excluded
before any B result was observed. Four fresh fixed samples were declared then.
Thus five real model Runs occurred in total; none was re-executed, no favorable
replacement after inspecting B results. A2 initially encountered a stale AX input
index before text submission; fresh state resolved it, producing only one A2 Run.

Normal startup is now enabled locally: native launchd label
`com.zebra-agent.cloud-egress` supervises a loopback-only prebuilt SSH channel;
only the new endpoint key was persisted in ignored `docker/trench-acceptance.env`.
Worker image9953a04d uses the twelve source hashes measured in the page cohort,
normal entrypoint and original compose files; API imageeb4f695b and Search245b675f
are unchanged. All three are healthy with zero restarts. All previous environment
values match their original digests after excluding the new Worker-only key.
Normal Worker remote-readiness probe succeeds; temporary observers are absent.
Global proxy configuration digest, schema103 generic-plan function settings,
private search and Trench source/config are unchanged. No remote publication.

Primary combined regression suite passes163tests (including its existing DNS/Teredo
checks); this is focused validation, not a full repository test-suite claim. The
accepted B2 result was checked read-only after restoring normal services.

Operational boundary: this machine's explicit SSH route depends on its existing
verified SSH identity, network and launchd session. Production operators must supply
a supervised reachable endpoint of their own. On initial readiness failure Worker
fails startup; a later outage fails the affected request without direct fallback.
For local rollback remove/empty only `ZEBRA_WEB_EGRESS_SOCKS_ENDPOINT`, recreate the
Worker with the original compose files, then stop the owned launchd service if no
consumer needs it. Do not change the global proxy or weaken DNS/TLS admission.

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

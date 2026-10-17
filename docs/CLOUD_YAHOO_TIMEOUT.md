# Yahoo timeout ownership and real-tool completion

CLOUD-YAHOO-TIMEOUT-01, 2026-10-17. Source `2f6648c8`, locally integrated as
`7ceaeea8` into `cloud-agent-trench`. Only the search service was replaced.
Normal API and Worker images, signed authority, thinking and transient-v2 configuration
remain unchanged. No Trench changes, Provider calls, pushes or remote deployment.

## Confirmed cause and limits

The previous tool cohort failed two simultaneous Yahoo requests at08:28:07 UTC.
The native traceback points to `OnlineProcessor._send_http_request`, before Yahoo's
manual response/redirect parsing. It establishes an initial HTTP request timeout;
there is no historical TLS/header trace to distinguish proxy connection wait from
Yahoo upstream wait. It does not establish that a cold redirect chain caused this failure.

A concrete secondary defect is reproducible in the pinned SearXNG implementation:
`searx.network.request` waits on `run_coroutine_threadsafe(...).result(timeout)`
and raises its synchronous timeout without cancelling that request's Future.
`Network.call_client` has one configured retry: `retry_on_http_error: [0]` also
allows a native RequestException retry. Isolation logs show native HTTP attempts
continuing for approximately another5s after the first engine deadline, and
`add_unresponsive_engine after ResultContainer.close`. Failed work can therefore
outlive the response and overlap subsequent searches. This is the repaired defect;
it is not proof that every original Yahoo delay was caused by leaked work.

The minimal change adds `future.cancel()` in that one exception handler. The
native async transport retains ownership of its cleanup; cancellation propagates
through its retry loop rather than cancelling a shared event loop or client.
The exact upstream source context is asserted at image build time, so an upstream
change requires review. The base ships unchecked-hash bytecode: the Dockerfile
also recompiles this module with checked-hash invalidation. A source-only image
was explicitly rejected by the behavioral check because its old bytecode still ran.

No timeout/retry inflation, cookie fabrication, query rewrite, engine fan-out,
provider/parser upgrade, new dependency or proxy routing change was introduced.
Yahoo remains5s, overall search6s. Existing native status0 recovery, CAPTCHA/403/429
behavior, YBV persistence and expiration remain unchanged.

This closes the demonstrated orphan-request defect, not Yahoo availability as a
whole. A genuinely slow/unavailable upstream can still exceed5s. Bounded successful
samples below qualify this local change, not an SLA or a claim of zero future timeouts.

## Route diagnosis retained, not promoted

Two isolated native instances used the normal proxy and the ready explicit SSH
exit. Plain `socks5` was an invalid candidate here: local DNS returned a198.18/15
proxy Fake-IP that cannot be forwarded at the remote exit. Its failures and native
suspension responses are retained; they are not treated as Yahoo availability data.
The existing Cloud public connector already uses fresh validated numeric addresses
and is unaffected by this diagnostic misconfiguration.

The valid native `socks5h` experiment delegates Yahoo hostname resolution to the
exit, as the existing HTTP CONNECT proxy already does. Both routes completed all
8requests, with no stable reason to promote a route switch. Cloud's private search
endpoint admission, fresh authorization and DNS/SSRF checks were never bypassed.
Production Yahoo continues using its original proxy. No global proxy edits.

## Focused checks and search qualification

`scripts/check_yahoo_deadline.py` runs inside the pinned SearXNG interpreter with
no external network. It exercises the original synchronous wrapper and native retry
loop using a blocked synthetic client, plus a concurrent independent request:

- Original immutable image: fails because its transport Future survives the deadline.
- Source-only patch with stale bytecode: same expected failure.
- Final image and normal running search container: pass; cancellation reaches the
  timed-out request, no post-deadline retry, sibling completes.
- Existing `check_yahoo_zero_status.py`: passes in the final running container;
  normal200, one0 recovery, persistent0 failure, CAPTCHA/403/429 retain their behavior.
- Runtime search diagnostics/source fidelity/private TLS/public egress/DoH-scope
  regression group:65passed. Changed Python Ruff and `git diff --check` pass.

A new declared fixed4 AB/BA/BA/AB native cohort compared the original and patched
image with identical settings/proxy, two concurrent real queries per arm. All16
requests succeeded with7results each and no unresponsive engines. Initial cold
parallel maxima were2039.5ms original and2018.6ms patched. Remaining maxima:
867.5/865.0,977.6/1193.8,1064.7/1120.1ms (original/patched). There is no stable
normal-response speed improvement; cancellation ownership is the accepted benefit.

After those checks, normal search was replaced using the repository Compose entry.
Final image: `ea7241c97288`; `/healthz` healthy, native checks green. Original sorted
environment digest matches; an ordered-list digest differed only because Compose
reordered keys. API `eb4f695b` and Worker `9953a04d` were not rebuilt or restarted.

## Fresh complete real-tool progress comparison

The previous incomplete cohort remains in `CLOUD_PROGRESS_BOUNDARY_IO.md`.
After search activation, both arms use the same repaired backend. A fresh fixed4
AB/BA/AB/BA cohort executes two searches and two official fetches per arm, followed
by the existing canonical-progress checks, using original tool thread behavior.
These are real tools and scratch PostgreSQL facts, not model-selected actions or
full signed Host/fenced Worker admission. No production conversation is rewritten.

| Pair | Baseline boundary ms | Candidate boundary ms | Baseline total ms | Candidate total ms | SQL A/B |
|---|---:|---:|---:|---:|---:|
|1|561.1|562.0|5163.0|3159.2|572/515|
|2|546.7|505.2|3556.6|3341.1|522/519|
|3|561.7|562.0|3461.7|3546.1|518/521|
|4|554.5|565.6|3273.8|3286.7|449/515|

All16searches and16official fetches succeeded. Boundary median557.8→562.0ms
(+0.76%),1of4paired wins; median total3509.2→3313.9ms. Observed SQL median520→517
is dominated by duration-dependent live checks and is not a causal SQL reduction.
The predeclared gate (>=5%, >=100ms, >=3of4wins, zero failures and no median total
regression) fails. Therefore the progress candidate is **not activated**, and no
high-thinking/v2 page model calls are authorized by this result. High/v2 remain
configured for ordinary user sessions; autonomous tool decisions are unchanged.

## Reproduction and rollback

```sh
docker compose -f docker/web-search/compose.yml build searxng
docker compose -f docker/web-search/compose.yml up -d --no-deps searxng
docker exec -i zebra-web-search-searxng-1 /usr/local/searxng/.venv/bin/python - < scripts/check_yahoo_deadline.py
docker exec -i zebra-web-search-searxng-1 /usr/local/searxng/.venv/bin/python - < scripts/check_yahoo_zero_status.py
```

An explicit `ZEBRA_SEARXNG_IMAGE` override remains operator-controlled; do not use
an unpatched override and claim this cancellation fix is present. Rollback only
search to the prior pinned upstream image with that override and the same Compose
command; it restores the demonstrated cancellation defect. No DB migration required.

Private evidence: `.artifacts/cloud-yahoo-timeout/` in `zebra-network-child-reuse`,
including invalid-route failures, valid route samples, cold/warm search cohort,
red/green/stale-bytecode checks, complete8-arm progress data and failed gate.
Owned diagnostic containers/anonymous volumes, Worker source overlay and scratch
schema/login were removed. No credentials were written to an artifact file.
The managed egress remains active. Original environments,18 unrelated tracked dirty
file hashes and global proxy digest were verified unchanged; only existing governance
files receive append-only updates. This is focused acceptance, not a full-suite or
long-running availability qualification.

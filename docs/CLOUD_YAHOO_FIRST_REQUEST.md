# Yahoo first-request tail: native phase evidence and minimal repair

CLOUD-YAHOO-FIRST-REQUEST-01, 2026-10-17. Branch
`codex/cloud-yahoo-first-request-01`, source `ef8b6dbf`, local integration
`000db762` into `cloud-agent-trench`. The preceding deadline cancellation fix is
retained. Only Search is replaced; normal API/Worker source and configuration stay
unchanged. The unaccepted progress/thread-I/O candidates are not activated.

## Reproduced failure and actual boundaries

The first four fully observed cold/warm cycles completed16queries.32native HTTP
attempts show8new connections,16status307 and16status200. For new connections:

| Boundary | Median ms | Range ms |
|---|---:|---:|
| TCP to local proxy |2.2|0.6–105.2|
| Local HTTP CONNECT reply |7.3|1.8–199.5|
| CONNECT reply to TLS completion |582.3|498.2–1127.6|
| TLS completion to first Yahoo response header |213.3|166.1–230.7|

The result-page body itself also costs time: median664.8ms, range462.3–943.5ms
for status200 attempts in this sample. HTTP CONNECT200 is an admission boundary,
not evidence that the proxy has already finished resolving/dialing its remote
Yahoo destination. APPCONNECT therefore includes remote forwarding/handshake wait;
it must not be described as local TLS computation time.

A later fixed image-pair batch reproduced two initial failures at~5015ms on the
baseline. Those requests were uninstrumented timing controls; their coarse native
traceback again points to the initial `_send_http_request`. They are retained,
not rescored as successful5s answers or omitted from acceptance data.

A bounded four-cycle follow-up with complete phase instrumentation reproduced two
more5s search failures. At the failing cold cycle:

| Metric | Parallel request 1 ms | Parallel request 2 ms |
|---|---:|---:|
| Local proxy TCP connect |1.4|0.6|
| CONNECT200 seen |2.1|2.3|
| Client TLS first outgoing record |2.3|2.5|
| First server TLS record |2409.5|2399.6|
| TLS complete |2409.9|2796.9|
| First Yahoo307 header |2735.7|4908.0|

For request2, another~2111ms passes after TLS before that first307. Its first
response consumes4908ms, leaving almost none of the engine's5s total budget for
Yahoo's cold YBV validation redirects. Request1 reaches the result page, but the
additional validation/header/body wait also crosses the engine deadline.

**Confirmed mechanism:** remote forwarding/TLS-flight wait plus Yahoo response
and cold-validation tail consume the fixed engine budget. Local proxy admission
is not the slow component in the reproduced failure. The evidence does not split
remote proxy DNS/TCP, intermediary packet loss and Yahoo processing into exact
separate causes; it does not prove the identical network hop failed in the original
08:28incident. No evidence justifies increasing timeout, discarding identity checks,
changing TLS verification or forcing a new connection for every request.

## Rejected changes and retained adverse observations

- Two native instances retain their clients through two80s idle periods. Original
  reuse succeeds at902–1268ms; forcing MAXAGE_CONN30 takes1714–3965ms and triggers
  cold validation again. No idle TTL/connection flushing change is promoted.
- One native instance completes24queries in12consecutive two-lane batches with
  no5s timeout. This does not establish indefinite HTTP/2 stability.
- In the failing fully instrumented isolated cycle, both immediate follow-up HTTP
  probes were closed without a response. Detailed process-crash logs were not
  retained, so the cause is unresolved; do not call it a confirmed Curl crash or a
  repaired recovery failure. Subsequent native real-curl cancellation/recovery
  checks and all live-page Runs succeeded, but do not erase that observation.
- An initial16query batch did not load the observer because its import path was
  missing. Its latency data is retained under `uninstrumented-startup/`, excluded
  from phase attribution. The observer now asserts it produced native phase data.
- Old invalid socks5/Fake-IP and inconclusive warm route experiments remain in
  `CLOUD_YAHOO_TIMEOUT.md`; no favorable samples are substituted for them.

## Minimal implementation

Reuse SearXNG's existing per-engine `proxies` support and the Cloud exit already
prebuilt/supervised for public fetch/DoH. The pinned Yahoo module maps an explicit
operator `SEARXNG_YAHOO_PROXY` to that native setting. Unset/empty leaves existing
outgoing and environment proxy behavior intact. No new driver/pool/dependency.

Normal local Cloud Search now has only this new non-secret key in the existing
ignored `docker/web-search/secrets/service.env`:

```dotenv
SEARXNG_YAHOO_PROXY=socks5h://0.250.250.254:18446
```

The address is the local OrbStack-accessible endpoint of the already supervised
SSH exit, not a portable default embedded in the engine. Other deployments must
explicitly configure their own prepared endpoint. Native pooling and hostname TLS
verification remain; other engines keep their original proxy route. A native
initialization probe verifies Yahoo alone receives the operator endpoint.

Both the old HTTP CONNECT route and this socks5h backend route delegate Yahoo
hostname resolution to their exit. Cloud's private search endpoint still uses its
original fresh authority/DNS/SSRF/pinned TLS checks; public web.fetch/DoH retain
fresh DNS/all-IP validation and existing controlled numeric-IP connector. No
Worker authorization or DNS answer cache is introduced.

The same pinned image adds numeric Curl timing collection. Only Yahoo native
exceptions and successful native attempts >=2s emit timing metadata. No raw URL,
query, headers, cookie/YBV, body, auth data or exception message is logged. Slow
successful307 is included because an engine can exhaust its remaining budget in
subsequent validation without an earlier native exception. Cancellation/success/
exception identity is preserved; no retry or automatic fallback is added.

Exact-context build assertions and checked-hash bytecode compilation apply to each
patched module. Yahoo5s/search6s, native0-status recovery, YBV TTL/persistence,
search language and autonomous tool selection are unchanged. No Trench/global
proxy/model/reasoning/stream-product changes.

## Fixed no-model route comparisons

First fresh fixed4 AB/BA/BA/AB cold cohort, two native queries per arm, same image,
settings and observer; only Yahoo proxy varies:

| Pair | A original parallel ms | B prepared exit parallel ms |
|---|---:|---:|
|1|2084.2|1672.3|
|2|2854.0|1515.5|
|3|2596.9|2600.3|
|4|3519.4|1555.0|

All16queries succeed. Median2725.4→1613.7ms(-40.8%),3of4wins; B3 is retained.
This compares whole exit paths, including destination geography/upstream behavior,
not only the implementation cost of the local proxy.

A separate predeclared fixed4 cold+warm cohort includes the warm nonregression gate:

| Pair | Cold A/B ms | Warm A/B ms |
|---|---:|---:|
|1|1947.0/1308.5|1163.0/787.0|
|2|1351.5/2631.4|1073.5/1069.4|
|3|1600.2/1301.7|810.0/773.8|
|4|1419.8/1385.2|1402.3/767.5|

All32queries succeed. Cold median1510.0→1346.8ms(-10.8%),3of4wins; warm
1118.3→780.4ms(-30.2%),4of4wins. Gate requires zero candidate failures, >=10%
cold median improvement, >=3of4cold wins and warm median no more than10% worse.
It passes. The much slower B2 is retained; no deterministic latency/SLA claim.
The separate diagnostic-image comparison containing two baseline timeouts is
retained as an adverse batch, not combined into these successful medians.

Focused evidence:

- Runtime search diagnostics/fidelity/private TLS/public egress/DoH scope:65passed.
- Native no-network timing check: red on old image, green on new; numeric error
  and >=2s success logs, privacy, malformed/unrelated host suppression and original
  success/error/cancellation identity all checked.
- Native proxy opt-in check: unset/empty defaults and native explicit proxy mapping.
- Existing native deadline/sibling and0-status/CAPTCHA/403/429 checks pass.
- Real curl local HTTP cancellation then immediate socket reuse:12cycles on old
  accepted image and12on final image pass. This is a real transport check, not a
  remote Yahoo availability or all-TLS-cancellation guarantee.
- Full native server smoke confirms only Yahoo uses the new setting;4queries
  succeed. Ruff/whitespace checks pass. No unrelated fixture/full-suite expansion.

## Actual high-thinking/v2 page cohort

Only after the native gate passed: exactly4new real page Runs in A1/B1/B2/A2 order,
same public PostgreSQL18/Redis8 question, Flash/high/transient_v2, autonomous tools.
Both variants use the same new Search image; only the Yahoo operator setting varies.
Each arm recreates Search clients; the existing native YBV volume is preserved.
No API/Worker restart, forced tool plan, prompt change or favorable Run replacement.

| Arm | First answer prefix visible s | Send→canonical complete s | Model rounds | Search/fetch | Failed tools |
|---|---:|---:|---:|---:|---:|
|A1|17.610|20.693|4|3/2|0|
|B1|13.282|16.266|3|2/2|0|
|B2|11.430|14.311|3|2/2|0|
|A2|14.664|17.600|4|3/2|0|

All4complete, canonical responses record enabled/high and retry_count0, both
official sources are fetched. Mean first-prefix16.137→12.356s(-23.4%); whole
19.147→15.289s(-20.1%). Both A Runs autonomously add a model round and search;
these are observed product results, not isolated transport causality or a fixed
expected improvement. Ranking/exit geography, model variation and native YBV state
also limit attribution. No scoped SQL observer is installed; no SQL gain is claimed.

First-body measurement is Send-click→first visible16-character prefix of that
Run's rendered final answer, including ordinary allowed provisional draft display.
Visible Markdown snapshots are timestamped, not hidden framework/reasoning state.
The initial DOM completion marker did not recognize the running control; before
any B model sample, whole completion was uniformly defined as canonical completed
wall time minus the observed Send wall time for all4Runs. A1 is retained with valid
first-body/canonical completion, not excluded as a calibration Run. One disabled
B1 click before SPA navigation finished sent nothing; only the later actual Send
is recorded, with one Run and one Send marker per arm.

B2 result retained read-only:
`http://localhost:3000/dashboard/strategy/conv_1792228659833_bd7113`.
DOM listeners/binding and loopback receiver are removed; no UI/product code edit.

## Local state, reproduction and rollback

Final Search image `19f3942fe0f3`, default tag `zebra-searxng:failure-timing-01`.
Normal base Compose entry only, no diagnostic mounts or temporary override. Operator
key remains enabled in the normal ignored env file. Original API `eb4f695b` and
Worker `9953a04d` images/environment/zero restarts verified; all3healthy. All other
Search environment values,18unrelated tracked dirty-file hashes and global proxy
digest match their prior values. Native managed egress remains active.

```sh
docker compose -f docker/web-search/compose.yml build searxng
docker compose -f docker/web-search/compose.yml up -d --no-deps searxng
docker exec -i zebra-web-search-searxng-1 /usr/local/searxng/.venv/bin/python - < scripts/check_yahoo_failure_timing.py
docker exec -i zebra-web-search-searxng-1 /usr/local/searxng/.venv/bin/python - < scripts/check_yahoo_egress_config.py
docker exec -i zebra-web-search-searxng-1 /usr/local/searxng/.venv/bin/python - < scripts/check_yahoo_deadline.py
docker exec -i zebra-web-search-searxng-1 /usr/local/searxng/.venv/bin/python - < scripts/check_yahoo_zero_status.py
```

Rollback route only: remove/empty the new operator key and recreate Search using
the same base Compose command. This keeps safe timing logs and the earlier timeout
cancellation fix. Keep the prepared exit supervised while enabled; unavailable exit
fails natively, with no ambient route fallback or replay. No migration or business
DB rewrite. No push/remote deploy/new dependencies/global proxy/Trench change.

All bounded diagnostic batches, failures, exact phase rows, cold/warm gates, native
checks,4page Run identities/canonical whitelists/DOM snapshots and final-state hashes
are under private `.artifacts/cloud-yahoo-first-request/` in the feature worktree.
Owned isolated containers/anonymous volumes, temporary Compose override and local
receiver are cleaned. No scratch DB was needed this turn. Remaining boundary:
upstream Yahoo can still be slow or unavailable; this repair reduces a demonstrated
route-dependent tail and adds safe failure attribution, not a zero-timeout promise.

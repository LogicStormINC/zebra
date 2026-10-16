# Native web-wait and Worker residual profile

Task WEB-WAIT-PROFILE-01, owner Luke Ding, executor Codex.
Basea2de702a, local cloud-agent-trench only. No new model request or old Run replay.

## Scope and reusable evidence

Reuse current-runtime A1/A2 safe traces and the existing fixed web-fetch probe.
Profile direct public HTTPS in a short native child on the currently accepted
normal Worker. Parent _native_network_call retains the original deadline and
kill/reap loop; diagnostic cancellation callback is a no-op, so these no-model
HTTP samples do not include production control SQL. Real safety behavior is
covered separately by existing native TLS/cancellation tests.

Six requests alternate the same PostgreSQL announcement/Redis GA blog, three
perURL, fixed order with all outcomes retained. They do not clear OS/CDN caches
or claim fleet p50. Only timing/byte count/public text hashes are retained, not
raw HTML/headers/credentials. Child imports, DNS preflight/connection resolution,
TCP, TLS, response-header read, bounded body+gzip and text projection are timed.
Nested DNS preflight/resolver durations must not be added together.

## Network result

All six return HTTP200; same-URL projected text hashes agree. PostgreSQL total
2.22–2.54s; Redis1.70–2.30s. The previous9.31s fetch is not reproduced or fixed.

| Stage | PostgreSQL (3samples) | Redis (3samples) |
| --- | --- | --- |
| Child imports |358–374ms|344–424ms|
| Native DNS preflight |10–306ms|9–72ms|
| Second connection-time DNS |6–15ms|2–6ms|
| TCP connect |1–61ms|1–1.4ms|
| TLS handshake |1010–1074ms|407–613ms|
| Response headers |397–548ms|347–484ms|
| Body read and bounded decoding |141–294ms|364–645ms|
| Text projection |3.6–5.1ms|17–24ms|

Projection/HTML parsing is not the dominant measured span. The socket path and
TLS/response/body consume most elapsed time. Actual DoH fallback is not seen in
these six. Do not attribute the historical9.31s outlier to TLS, DNS or a server
TTFB without its missing child-stage evidence. Keep timeout and no-retry rules.

## One minimum implementation

Python stdlib HTTPConnection.connect sets TCP_NODELAY on its socket. Our
PublicMcpHttpsConnection replaces that connector to pin an admitted IP but omitted
the default. Native probe verifies baseline option0 at connect versus candidate1.
Restore the same socket option after TCP connect and before TLS. Ignore only
ENOPROTOOPT like stdlib; other errors still close the socket and propagate.

One production file/seven added lines. All class consumers checked: public
fetch/search, trusted search-backend subclass, MCP and GitHub skill importer.
No TCP/HTTP retry, TLS relaxation, proxy/global network setting, connection
reuse/pool, DNS/authority cache, deadline or50ms control-check change.

An eight-request fixed PostgreSQL ABBA/ABBA probe compares old socket behavior
with the option enabled; four per mode, all200/same bytes/projected hash:

| Sample median | Old option0 | Option1 |
| --- | ---: | ---: |
| Full native operation |2738.04ms|2638.61ms|
| TLS |1706.44ms|1281.52ms|
| Response headers |309.06ms|465.98ms|
| Body |205.88ms|94.66ms|

Both modes contain substantial network variation. About3.6% total difference in
this small sample is NOT a stable or causal latency claim. This restores a
missing native default; it does not prove the9s outlier or whole Agent latency
solved. No new real-model pair was used to obtain a favorable score.

## Worker residual, without double counting

Reconstruct measured Worker ranges from end timestamp minus method duration;
merge intervals, subtract unioned Provider/tool-handler spans, then assign the
remaining intervals by the order below. Categories do not overlap and sum to
the previously reported residual. SQL/connect overlays are separate views of
these same intervals, never additional wall time.

| Exclusive remaining Worker interval | A1 | A2 |
| --- | ---: | ---: |
| Progress catch-up |3861.59ms (99calls)|2488.56ms (66calls)|
| Canonical append |3147.54ms (54calls)|1979.87ms (37calls)|
| Event preparation |1086.63ms|699.91ms|
| Transient public-call activation |819.50ms|380.78ms|
| Control reads outside tool handlers |93.96ms|47.15ms|
| Context/input/other listed setup |500.11ms|474.54ms|
| Unassigned remainder |1092.11ms|785.29ms|
| Total |10601.45ms|6856.10ms|

Overlays inside the residual: connection-open intervals2521.13/1683.04ms;
explicit SQL intervals4861.59/3178.67ms. These are diagnostic-instrumented old
Runs, not an uninstrumented latency benchmark. Repeated checkpoint advancement
and durable event processing are the dominant platform stages; do not add all
350/140 cancellation-read durations from inside network handlers to this residual.

This analysis does not justify bypassing fresh Run/source/fence validation or
combining unknown canonical outcomes with derived progress. Further connection/
transaction batching needs an explicitly scoped design and same-work proof;
no such abstraction is introduced here.

## Checks and local activation

New regression fails3cases on original code, then validates normal option,
unsupported-option fallback and other socket errors before TLS.242focused tests
pass: native TLS/certificate/SSRF/private/rebinding, proxy/trusted backend,
search/fetch/gzip, real network cancellation/peer EOF/child reap and GitHub import.
No fixture or other source repair. Clean tracked-source make check passes:
Ruff, mypy1283, file-size3094, eval30 and existing standalone failure gates.

Actual candidate image (without the experimental per-socket toggle) independently
fetches both public pages with HTTP200 and exact prior projected text hashes;
real TCP_NODELAY=1 is checked before TLS. Times3573ms/1578ms further illustrate
network variability, not a stable speedup. The first candidate container probe
had closed stdin and produced zero samples; it is excluded, then the same
invocation with interactive stdin runs both requests. No source or test change
was made to accommodate that launcher error.

Normal Worker6f3a5d8b is healthy/zero restarts;80source fingerprints and original
six Compose/environment/commands/search checks pass. API907fcc00 image and exact
start timestamp unchanged. Zero active Host intents checked before Worker-only
replacement. No diagnostic launcher or global socket/proxy setting is active;
the only behavior change is the native default on newly created pinned sockets.
Local integration preserves primary's27unrelated dirty entries.

Private .artifacts/web-wait-profile-20261016 contains the fixed probes, safe
profile rows, interval decomposition and service/source receipts. No model or
business-data writes, schema change, push/npm publication or remote deployment.

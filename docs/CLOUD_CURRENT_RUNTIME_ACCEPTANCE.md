# Current Cloud runtime: first-body acceptance round

Task `CURRENT-RUNTIME-ACCEPTANCE-01`; owner Luke Ding, executor Codex.
Measured2026-10-16, base33150b9f, local cloud-agent-trench only.
This closes the current-version two-search measurement, not the full stream
refactor/SQL80%/STOP/product acceptance gates. No production source changed.

## Fixed scope and retained configuration

Use two new authenticated Trench page requests with the same prompt:
“请联网搜索并核对 PostgreSQL 18、Redis 8 的正式发布日期和各两项主要新特性，
只采用官方来源并附链接，简明回答。”
Flash/high/exploration/transient_v2 remain selected. Canonical model receipts
confirm enabled/high/retry0 for all8requests. Both Runs commit one answer and
complete;10tool executions succeed, no sandbox provision or Provider400.
No historical Run resumed. Both observations are retained; no third model Run
was issued to obtain a better score.

| Identity | A1 | A2 |
| --- | --- | --- |
| Conversation | conv_1792147053625_0f7da7 | conv_1792147186643_e6a92a |
| Run | ffa3b70b-e76d-4ee8-868e-63bc68840b02 | fa7bd379-3a68-4447-b31f-5141ace20e8c |
| Cloud session | 87fa0056-a9f9-430d-aa61-7b500c7f7533 | 378c062b-187d-4608-a131-3d04d3cc9fbc |
| Outcome | completed | completed |
| Model calls / successful tools | 5 / 6 | 3 / 4 |

A1 is first execution after diagnostic process startup; A2 follows in resident
processes. Neither is a deliberately cold-cache benchmark. Network/model paths
vary and no normalized A/B speedup can be inferred from their difference.

## Actual-page timing

| Click-relative observation | A1 | A2 |
| --- | ---: | ---: |
| First visible process text | 4.64 s | 4.13 s |
| First substantive provisional answer | 35.22 s | 17.59 s |
| First official source link | 35.22 s | 18.73 s |
| Canonical answer committed | 43.65 s | 20.28 s |
| Host completed | 44.53 s | 21.13 s |
| Last recorded visible answer update | 45.76 s | 22.01 s |
| Worker entry | 2.15 s | 1.75 s |
| Actual first Provider HTTP start | 3.29 s | 2.99 s |
| Worker entry → Provider HTTP | 1.138 s | 1.238 s |

Page click/DOM observations use one performance.now clock per request. Canonical
and server spans use their own timestamps; cross-process click-relative fields
use wall-clock alignment, without a separately calibrated submillisecond bound.
Do not use them to establish a subsecond SLA. Last observed body change is not
a claim that every earlier partial candidate matched the accepted final answer.

A1's26.735s text confirms one date while asking to retrieve another source; it
is a process update, excluded from first-substantive-body timing. The35.216s
block contains the answer plus an official link. A2's17.593s block states the
verified result and a release date. Both display the provisional-verification
label before commitment. Their bodies visibly precede canonical completion;
timely draft display works in these two ordinary cases, not a private/coverage
eligibility proof.

The copied observer's old .zebra-agent-message__draft selector returns false on
the current SDK markup. Classification uses the captured visible pending label
and text timeline instead of treating that CSS flag as eligibility authority.

## Where time is spent

Provider and tool intervals below are unioned, so parallel tool durations are
not summed twice. Worker-other is the measured residual outside those intervals;
it is not a label for SQL alone.

| Worker execution decomposition | A1 | A2 |
| --- | ---: | ---: |
| Provider HTTP intervals | 17.11 s | 7.60 s |
| Tool-handler interval union | 14.13 s | 4.41 s |
| Remaining Worker time | 10.60 s | 6.86 s |
| Worker total | 41.84 s | 18.87 s |

A1 fetches the PostgreSQL announcement in9.31s; A2 fetches the same official URL
in2.00s. The corresponding read transport occupies nearly the same interval,
so this is not a long queue before the network operation. DNS/connect/TLS/
response/parse inside that operation are not separately timed yet. Do not call
the whole9.31s remote server TTFB without that breakdown.

A1 also chooses an additional read batch to verify Redis's date and then makes
one candidate correction: removing an uncollected PostgreSQL release-notes URL.
That correction is valid citation enforcement, not the earlier publication-date
intent false positive. A2 chooses both official announcements directly and
needs no correction. Keep model tool choice and citation checks intact.

First text → Redis publication is about1.3ms in both first calls. Copied API
first-draft hooks record one event in each request window but scope is None
because the Task context has no session_id there. Their wall-clock correlation
is about3ms after Provider text; this is window-correlated diagnostics, not an
identity-certified new API-tail metric. About0.65–0.72s text→DOM is observable
across aligned clocks, but this round does not split coalescing/BFF/SDK/paint
and should not label that span entirely frontend rendering.

## SQL evidence and limitations

| Explicit active-Worker scope counters | A1 | A2 |
| --- | ---: | ---: |
| Startup SQL before first Provider HTTP | 395 | 395 |
| Startup TaskIO connections | 53 | 53 |
| Whole active-Worker scope SQL | 3117 | 2078 |
| Whole active-Worker scope TaskIO connections | 771 | 433 |

These counts include observed cursor calls/SET, using the same safe launcher as
prior samples. They exclude independent API/Host/consumer/maintenance scopes and
server-internal statements; they are not whole-system SQL. Different model/tool
work makes3117vs2078 unsuitable as an optimization percentage. No v1 comparison,
frame10x test,600s observation or100executing-Run matrix was run here.

The historical C1 startup was398SQL/53connections; current startup395/53 retains
local progress query reductions, but this historical comparison is not the
inclusive >=80% gate. Startup is now a small portion of these searches; continuing
one-query reductions cannot explain away their17.6–35.2s first bodies.

The page network capture includes repeated502s on an older ClientSession while
new measured ClientSession reads succeed. The prior-session poll cause is not
attributed or repaired here. A2 network-event buffer reports truncation; do not
claim complete HTTP request-rate or stream-chunk accounting from that buffer.
DOM observer/canonical/Worker traces are separate retained evidence.

## Normal restoration and next gates

After both Runs completed, zero-active-intent guard passed. Original normal
API907fcc00/Worker506d0d80 images, entrypoints, commands and six Compose files
were restored. Both healthy/zero restarts;79source identities, environment and
search image/config/proxy checks pass. Browser observer/listener removed and
Network diagnostics disabled. Reloaded A2 under normal services shows the
committed answer, official links, Flash/high and usable composer; no new Run.

A runnable private summarize.py reconciles both page/Run/canonical/provider/tool
records and asserts expected thinking/high/v2/no-failure/count/terminal bounds.
No new source tests/full-suite run was needed for this documentation/diagnostic
slice; prior code validation is not relabeled as new full-system acceptance.

Remaining acceptance order:

1. Profile web-fetch DNS/connect/TLS/response/parse and Worker-other boundaries
   on existing paths, before choosing a minimal shared fix. Preserve high effort,
   Agent-selected tools and real citation gates; no product-name routing rule.
2. Use the existing full-runtime plan to measure deterministic same-work v1/v2,
   including API/Worker/consumer/authorization/background totals and all outcomes.
   See CLOUD_STREAM_RUNTIME_ACCEPTANCE_PLAN.md; >=80% remains OPEN.
3. Complete separately owned STOP/revocation/takeover/display convergence,
   Redis faults and capacity/GC integration acceptance. These gates remain OPEN.

Safe private evidence: .artifacts/current-runtime-20261016, including both full
public DOM timelines, filtered canonical receipts, SQL/stage traces, summary,
redacted network observations and page-A2-normal.png. No private reasoning,
credentials or full model prompt was exported. Local integration only; no push,
npm publication, schema operation or remote deployment.

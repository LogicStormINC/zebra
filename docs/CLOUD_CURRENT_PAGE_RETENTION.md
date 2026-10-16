# Current page latency and temporal source evidence

Task CURRENT-PAGE-RETENTION-01; owner Luke Ding, executor Codex; base `83ef58bb`.
Local cloud-agent-trench only. The current-version cohort is fixed at two new
searches; no retry or historical Run replay selects a better result.

## Actual page acceptance before this slice's source change

Both authenticated Trench requests ask the same official PostgreSQL18/Redis8
release-date/two-feature question. Canonical receipts confirm deepseek-flash,
thinking enabled/high, transient_v2 and retry0 for all 11 model calls. Both Runs
commit one answer and complete. They use 16 tools: 15 succeed, one A2 web.fetch
fails with reason gateway_unavailable; the Agent subsequently finds other sources.
There is no Provider400, runtime provisioning or canonical Session failure.

| Current-version observation | A1 | A2 |
| --- | ---: | ---: |
| Conversation | conv_1792154751924_4114e8 | conv_1792154958027_a9e87e |
| Run | db61abf3-431f-4cef-a315-6350e768f433 | 6caf871d-197c-41f9-bdb7-8aad724b53b9 |
| First visible provisional process | 4.710s | 5.390s |
| First substantive answer | 38.056s | 55.449s |
| First official link | 38.564s | 55.449s |
| Host completion | 42.343s | 60.275s |
| Last observed answer update | 42.722s | 60.727s |
| First Provider HTTP | 3.408s | 3.164s |
| Worker entry to Provider HTTP | 1.207s | 1.160s |
| Model calls / tool attempts | 5 / 7 | 6 / 9 |

These observations fail a ten-second substantive-answer goal. A process message
and provisional commentary are not counted as substantive body. DOM evidence
uses one performance.now clock per request; cross-service fields use wall clocks
without submillisecond calibration. No normalized before/after speedup is claimed.

The original observer's first-answer heuristic also catches tool-loop commentary;
substantive body is identified separately from the recorded final-answer prefix.
Its draft CSS selector did not match the visible provisional notice, so that
boolean is not used as proof. Screenshots show the raw final text found in the
accessibility main was a non-visible announcement, not a second displayed answer.

## Where time remains

Union Provider and tool-handler intervals before subtracting them from Worker
elapsed time. Nested stage sums are not added as extra wall time.

| Worker elapsed attribution | A1 | A2 |
| --- | ---: | ---: |
| Total Worker interval | 39.541s | 57.647s |
| Provider HTTP intervals | 16.309s | 23.472s |
| Tool handler union | 10.577s | 23.178s |
| Other exclusive Worker time | 12.655s | 10.997s |
| Progress within that residual | 3.756s | 3.502s |
| Canonical append within that residual | 3.768s | 3.629s |
| Event preparation within that residual | 1.704s | 0.867s |

Active-Worker scoped SQL totals are3577/4630 for different work, not overall
system SQL or a reduction percentage. Startup has403SQL each,53 Task I/O borrows
and44 resolver/open invocations. Whole active scopes have751/1155 borrows and
427/745 open invocations. These distinguish adapter borrowing from physical-open
attempts; they exclude independent API/consumer/background scopes and internal
trigger statements. Eight more startup SQL executions than historical395 include
retained transaction-reset work; do not report socket reduction as SQL reduction.

The remaining substantial platform residual is real; model/network variation
also dominates the slow A2. This cohort does not establish overallSQL80%, STOP,
GC/capacity, multiworker or a page-first-body SLA.

## One measured source defect and minimum fix

A2's public progress explicitly says the GitHub release text shows02May but omits
the year, then performs another release-note read to recover it. The captured
[official release HTML](https://github.com/redis/redis/releases/tag/8.0.0) contains
`relative-time datetime="2025-05-02T11:20:31Z"` at that exact displayed timestamp.
The existing shared readable-HTML parser drops every attribute, including this
source-owned evidence. Both full extracted text and bounded model preview lose it.

Only `agent_runtime.web_content` changes: visible time/relative-time elements
retain a normalized, stdlib-validated date/datetime annotation. Date-only evidence
remains date-only; no midnight/timezone is invented. Hidden/ignored/main-landmark
and UTF8 byte limits remain enforced. Arbitrary attributes are not copied. No
product/domain router, forced tool choice, new dependency, quality-gate bypass,
provider setting, network retry, authority cache or deadline change is introduced.

The same captured HTML now retains the full UTC timestamp in the actual
ToolOutputProjector model preview. This is deterministic evidence completeness,
not proof that the model will always avoid another call. No post-fix third model
Run is issued and no new end-to-end latency reduction is claimed.

## Verification and local activation

The new no-framework `scripts/check_web_time_evidence.py` fails on the original
parser and passes after the fix: both element types, date-only semantics,
hidden/ignored/main boundaries, invalid attributes, output-byte/preview limits
and unchanged text/plain. Existing web-content and transport regressions20pass.
Two initial test commands referenced nonexistent optional test files and ran no
cases; the corrected existing-file command is the20-case result, no fixture fix.
The summary initially treated failed tool returns as successful tools; corrected
to16 attempts/15 successes with the failure retained, without changing any sample.

Final clean tracked-source `make check` passes: Ruff, mypy1285, size3100, eval30
and both existing progress fault checks. Temporary API/Worker diagnostic launchers
are removed and original normal images restored before source activation. Only
the Worker then receives the parser overlay: image8b8e16a6 is healthy/zero restarts.
Verification covers89source fingerprints/originalsixCompose/env/commands/search.
APIcfc1dcf8 and its post-diagnostic-restoration start time are unchanged by that
source update; API was recreated for temporary diagnostics earlier in this turn.
The actual Worker passes the new boundary check and produces an identical SHA256
model preview for the captured HTML, including the original UTC timestamp.
DOM observer/listener and temporary screenshot-download element are removed;
the retained A2 screenshot is a pre-fix cohort result, not a post-fix model proof.
No schema, manual app data repair, npm publication, push or remote deployment.

Private evidence: `.artifacts/current-page-retention-20261016/`, including the
fixed prompts/identities, whitelisted receipts, safe trace counters, compact DOM
timelines, runnable reconciliation and same-HTML before/after model preview proof.

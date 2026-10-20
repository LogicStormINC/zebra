# Cloud runtime incident repair — 2026-10-20

Task: CLOUD-RUNTIME-REPAIR-20261020. Owner: Luke Ding / Codex.

The five bounded code fixes are deployed to 192.168.110.30. Native search is
registered again, but real NBOPC search acceptance is **not passed**: the single
authorized query reached SearXNG and Yahoo exhausted its existing five-second
engine budget. No second query, model request, original Run replay, or original
event repair was performed. Do not describe this as complete search recovery.

## Root causes and minimal changes

| Symptom | Confirmed cause | Change / retained boundary |
| --- | --- | --- |
| No ordinary web.search | Worker configured search.zebra.test:18445; strict public URL parser rejected explicit ports and the legacy registrar silently omitted search | Allow a port only for the explicitly configured private backend. Keep origin, port, path and fixed-query pinning, fresh DNS at admission/connect, TLS/SNI, cancellation and redirect refusal. Public web.fetch/result URLs still reject ports. Invalid configured endpoints now fail composition; unset endpoints still disable search. |
| model execution failed after clarification | Frozen messages retained provider_reasoning_required but intentionally excluded private reasoning; provider serialization raised ValueError before HTTP | Reuse existing durable child-conversation rebasing. Pair the real clarification receipt first; preserve public evidence, execution counters, mutation verification scope and bounded action fingerprints. Continue with a fresh provider-safe context, without storing/fabricating reasoning or retrying an uncertain prior attempt. Exact safe continuations retain their existing path. |
| Blank files.search path killed the Run | Blank argument classified as workspace escape; policy denial became terminal | Report malformed path as invalid_arguments, reusing the existing nonexecuted read-only observation. Schema states omit/use dot for root. Actual traversal/absolute escape remains a hard denial; writes gain no new authority. |
| Correct returned video URL failed citation checks | Link was present in authorized source content_text, but ledger only collected explicit reference fields and images | Collect bounded literal HTTPS links only from successful readonly source receipts marked verified_result and containing a valid source URL. Retain as observed media links, separate from independent source citations. Limit source-body inspection to 65,536 characters and ledger media refs to 128; original output budgets remain. Failed reads, arbitrary prose and model presentation arguments do not supply body evidence. Explicit video fields are also recognized. |
| Correct retained result shown as execution error | delivery_requirements_unmet suspension fell through to generic RUN_ERROR | Project a typed interrupt. Paired Host protocol adapter retains the committed answer and authoritative blocked/partial assessment, without treating it as completed or replacing it with a clarification question. Real clarifications/approvals retain waiting-input behavior. |

The paired Trench edit only consumes the existing delivery protocol; no product
prompt, tool-selection, frontend or business logic was changed. Neither default
engine selection nor Exa selection was forced. Yahoo default, optional Exa fast,
cooldown and fallback configuration remain byte-identical.

## No-model validation

- Focused Zebra regression: 258 passed, including both web pipelines, configured
  ports, native child protocol, real scratch TLS, private-address denial, query
  validation, path policy, clarification, child recovery, verification state,
  evidence gates and AG-UI projection.
- Cancellation and search-diagnostic regression: another 68 passed. These use
  scratch peers; no public search/model requests were added.
- Trench protocol regression: 30 passed, including real clarification retention.
- File-size gate: 3,223 tracked files / zero violations. Ruff clean; mypy clean
  across 1,319 source files. Both progress-safety checks pass.
- Full `make check` is not green: deterministic eval is 24/30 (0.80). The
  unmodified 948b8a43 baseline reproduces the same result. All 30 replay metrics
  and terminal outcomes match after excluding generated Session IDs. No old
  fixtures/eval expectations were expanded or changed to hide the baseline.
- New amd64 overlay images were built without network/dependency installation.
  Disconnected Worker image check confirms search registration, unauthorized
  profile filtering, correctable nonexecuted blank path, denied traversal and
  receipt-derived media. Exact source hashes verified in all three live services.

Saved production snapshots, without invoking their Runs:

- The two clarification transcripts (13/24 messages) had 4/6 provider serializer
  failures; both now serialize with zero failures. Public evidence/action
  fingerprints and verification/dedupe metadata are retained.
- Video candidate at sequence86 still rejects three unobserved URLs. Final
  candidate at106 passes using the exact video link already in the source body.
  No URL replacement or relaxed unsupported-link gate is used.
- Full original 110-event stream projects to 117 AG-UI frames and maps through
  the real Trench adapter: zero RUN_ERROR, terminal blocked, committed answer and
  original assessment retained. This is a read-only protocol replay, not a
  browser acceptance or historical state rewrite.

## Production update and preservation

Before replacement, effective active leases, pending Zebra commands and queued/
claimed/running Trench Turns were all zero. Running source hashes matched the
local base for every changed file. Compose configuration comparison admitted
image changes only; no environment, command, mount or migration changes.

| Role | Previous image | Current image |
| --- | --- | --- |
| Zebra Worker | zebra-worker:release-20261019-2a6966be | zebra-worker:runtime-repair-20261020 |
| Zebra API | zebra-api:release-20261019-2a6966be | zebra-api:runtime-repair-20261020 |
| Trench API | trench-backend:release-20261019-c80a2f9 | trench-backend:runtime-repair-20261020 |

All three are healthy, without startup tracebacks/model-execution failures.
Broker, Search and search TLS container IDs/start times/restarts, Search config
and Exa control state are unchanged. Private before/after receipts confirm
runtime environment/command hashes and mount sets unchanged; four original
Sessions retain identical event counts, event hashes and model-request counts:

- f8ad1c5c-ffed-496b-a10c-3d8705e4136c
- 8ca25785-d9a6-46ea-bae4-e27c548951ba
- bdb6ff04-bf67-42a3-b1ae-d5efc45ba4f9
- e6c05bae-a8d1-4525-90ee-96c4080eef01

High reasoning remains controlled by the existing unchanged admission/Run
settings. Stream v2 admission is still enabled. The separate web_pipeline_v2
setting remains false, exactly as before; it was not confused with stream v2.

Release overlays and immutable source manifest:
`/home/ubuntu/releases/20261020-runtime-repair/`.
Previous images/configuration remain available. To roll back the affected roles,
use the original release JSON without this task's image override, with
`up -d --no-deps --no-build` for only zebra-api/zebra-worker or trench-api after
the same idle preflight. Never include Search in the rollback command.

## Actual NBOPC acceptance and remaining issue

Exactly one operator-authorized `web.search` invocation used the normal live
Worker registry/native transport and existing private backend, without creating
a Run or replacing a model provider. This does not claim a new authenticated
Run/page E2E. Cancellation/policy checks ran128 times.

| Measurement | Result |
| --- | --- |
| Tool elapsed | 6,049.68 ms |
| Tool status | failed / search_incomplete |
| Official NBOPC result | Not observed; no hit@5/recall claim |
| Extra model requests / new Runs | 0 / 0 |
| Automatic repeat, alternate engine or Exa request | None |

Read-only logs at04:48:49 UTC identify Yahoo engine timeout. Existing numeric
instrumentation reports curl28, HTTP status0, proxy CONNECT200, total5,004.319ms.
The configured127.0.0.1:7890 proxy listener exists. Therefore backend registration,
private TLS admission and JSON failure reporting worked, but the Yahoo upstream
request did not return an HTTP response within budget. These error-path metrics
alone do not isolate TLS versus subsequent upstream/proxy waiting. No evidence
supports simply increasing timeouts, changing global proxy, resetting cooldown,
or asserting Google-equivalent recall.

Stop boundary: the failed sample is retained. Further search probes/model/page
acceptance are not silently repeated. A focused follow-up should inspect the
Yahoo egress path with bounded timing and an explicitly agreed fresh sample.

Private evidence: `.artifacts/cloud-runtime-repair-20261020/`; do not commit raw
event/credential-bearing snapshots. Safe receipts include saved-replay,
paired-projection, image-smoke, source-manifest, eval-baseline, preservation and
nbopc JSON. The frozen Trench archive tag/branch remain unchanged.

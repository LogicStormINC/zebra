# B1 additional research audit — 2026-10-17

## Outcome and boundary

The startup-admission cohort's B1 completed successfully but used five model
calls and eight tools, compared with three calls/four tools in A1, B2 and A2.
This is autonomous research-path variation, not Provider retries, quality-gate
rejection or duplicated tool execution. No production fix is justified by the
current evidence. This audit does not claim a new performance gain or SQL saving.

B1: conv_1792231623512_33c29d, Run b009ee61-6682-4e1a-a983-6cad1acabd5d,
session81c3b480-d726-48fb-93e6-3aa3e3cec164. These identifiers distinguish it from
older experiments also named B1. Same public question in all four cases asks for
PostgreSQL18/Redis8 official release dates and two main features, with official
links. All completed with high thinking, Flash, transient_v2 and zero tool failures
or Provider retries. The transport flag is not web_pipeline_v2.

## Actual eight-call sequence

Times below are receipt envelopes relative to the first proposed tool call;
parallel pairs overlap. They are not pure network durations.

| Batch | Calls | Proposal → last completion | Finding |
| --- | --- | --- | --- |
| 1 | Search `PostgreSQL 18 released announcement postgresql.org`; search `Redis 8 release announcement redis.io` |0–2.119s|PG dated announcement found; Redis results have a release landing page, Redis Software notes, GitHub release list and third-party pages; no Redis GA announcement.|
| 2 | Fetch PG announcement; fetch `https://redis.io/release/` |3.578–5.846s|PG source is necessary. Redis current marketing page does not supply the required historical GA date.|
| 3 | Search `"Redis 8" generally available blog redis.io May 2025`; search `redis.io blog Redis 8 GA new features vector set` |7.365–8.845s|Both return the same GA announcement; second also supplies the version documentation.|
| 4 | Fetch `https://redis.io/blog/redis-8-ga/`; fetch `https://redis.io/docs/latest/develop/whats-new/8-0/` |10.673–11.998s|GA source already gives publication date and multiple features. Version documentation overlaps those facts.|

The initial Redis query differs from B2's `Redis 8 general availability announcement
redis.io blog`. The backend answered both; it was not a Yahoo timeout recovery.
A1 also had imperfect initial results, yet its results included the GA URL and it
used it directly. Search-result quality and source selection both matter.

Of the four additional calls relative to the siblings:

- One refined search is legitimate recovery from the missing GA source. Removing
  it without an alternative source would undermine the requested official date.
- The initial Redis landing-page fetch is low value for the historical-date gap.
  Its returned current product copy is not the required evidence. No GA URL was
  present in this fetched text. This is a source-choice detour, not lost tool data.
- The two parallel follow-up queries overlap on Redis8 GA/features. One suffices
  in this retained sample; this does not prove either will always return enough.
- Fetching both GA and version documentation is overlapping research for this
  small request. The GA text already includes Published2025-05-01, vector-set
  beta, integrated data structures and performance improvements. It is not an
  empty result: ~12068characters reach the model, with bounded middle omission;
  the needed introductory facts survive. The extra documentation is ~5943chars.

Thus three calls are low-value/overlapping in hindsight, and one is required
recovery after the original bad source search. None are exact duplicate arguments.
The second search and documentation fetch run alongside useful work, so deleting
three calls would not save the sum of their individual elapsed times. Earlier
source selection could avoid a whole recovery cycle, but that is a counterfactual,
not a measured implementation speedup.

## Disjoint first-body accounting

Existing offline checker reconciles DOM visible final-answer prefix16 against
canonical event receipts. All intervals sum to observed first body. Tool spans
merge overlaps; handoffs include event/policy/progress and other scheduling gaps.
No private reasoning is recorded or inferred.

| Interval | B1 | B2 | Difference |
| --- | ---: | ---: | ---: |
| Send → first model request |2.109s|1.977s|+0.132s|
| Earlier model request/receipt envelopes |5.250s|2.354s|+2.896s|
| Search execution union |3.281s|2.527s|+0.754s|
| Fetch execution union |3.297s|1.920s|+1.377s|
| Final candidate → visible prefix |2.330s|3.661s|-1.331s|
| Other handoffs |1.360s|0.892s|+0.468s|
| First body |17.627s|13.331s|+4.297s|
| Send → canonical completed |20.805s|16.256s|+4.549s|

A1/A2 first body12.427/13.163s, whole16.184/16.122s. B1 model Provider
latencies803/1123/1225/929/4300ms, retry0. Canonical envelopes above also include
receipt processing; neither metric is pure thinking time. Final candidate timing
was faster in B1 than B2 and cannot explain its regression. Startup is not the
main B1 penalty. No new whole-turn SQL observation was added in this audit;
extra-tool counts cannot be converted into a SQL reduction percentage.

## Shared-path inspection and minimal decision

Verified running Worker9953a04d imports the same AGENT_EXECUTION_GUIDANCE as source.
HarnessModelStep.build_initial_messages appends it to the system identity; callers
requesting subsequent completions preserve that conversation. The current guidance
already specifies matching edition/version, dated primary announcements, assessing
snippets before generic landing-page fetches, independent parallel queries, and
stopping when the requested facts are supported. The search normalizer passes the
observed five candidates, URLs and snippets; the GA result is genuinely absent
from B1's first result set. There is no evidence of a missing message or a replay
in this chain. No quality revision/Provider recovery caused the extra models.

The highest-value target is earlier discovery/selection of the dated primary
source, not parsing micro-optimization or yet another connection pool. However,
adding the same guidance again has no demonstrated causal mechanism. Hardcoded
source paths/query rewrites, tool ceilings, automatic fetching or removing fresh
checks would change autonomy/quality boundaries and are rejected for this slice.
A general source-selection change needs a separate varied-question evaluation,
including product/edition ambiguity and genuinely necessary multi-source checks,
before a release. This audit does not silently expand into that project.

No production patch was made, no services replaced, and no new model/page Runs
were issued. The retained four real-page cases are the comparison evidence, not a
new before/after acceptance. A new real-page A/B remains **not performed** because
there is no justified candidate to compare. Repeating unchanged code could produce
a faster random sample but would not validate an optimization.

## Reproduce

From the feature worktree zebra-network-child-reuse, using the primary environment:

```sh
/Users/lukeding/Desktop/playground/2026/product/zebra-agent/.venv/bin/python scripts/check_cloud_search_critical_path.py .artifacts/cloud-start-admission-reuse A1 B1 B2 A2
```

The checker verifies completed/high/retry0/v2, pairs calls, merges parallel spans,
reconciles every first-body interval, and rejects failed tools. Owned public tool
arguments/results were read from canonical session_events into ignored
`.artifacts/cloud-start-admission-reuse/tools-{A1,B1,B2,A2}.safe.json`; no private
model reasoning, account credentials or request headers were collected. These
local evidence files are not committed and require this operator's retained data.

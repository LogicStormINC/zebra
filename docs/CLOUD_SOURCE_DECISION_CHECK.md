# Source-choice decision checklist experiment — 2026-10-17

## Decision: do not promote

The historical B1 b009ee61-6682-4e1a-a983-6cad1acabd5d already had explicit
source-matching and stop guidance. It did not fail quality checks. Its overlapping
queries and announcement+documentation fetch were proposed before the primary
fetch completed. Thus “search after enough evidence” is not its exact timeline:
a poor initial query led to a landing-page detour, then overlapping prospective
evidence collection. Public model commentary gives no detailed decision rationale;
private reasoning was not read. We cannot identify a unique internal model cause.

A hypothesis was tested rather than declared a fix: replace the existing web prose
with a five-step per-batch check, fix required facts to the original request, assess
remaining gaps, prefer one suitable source covering multiple facts, and avoid new
goals from optional answer details. Same system-message location, no new prompt
layer or tool/route/schema changes. Prompt grows2305→2675bytes; no token reduction
claim. Composition/safety checks and64targeted tests/Ruff/mypy pass, but these
checks do not prove model behavior.

## Fixed four real-page pairs

Exactly8new Runs, A1/B1/B2/A2/A3/B3/B4/A4, four different questions: Python3.13
release date+2features; SQLiteWALconcurrency+one limitation; Node22/24LTSdates+
codenames versus first release; original PG18/Redis8dates+2features.
No favorable replacement. Same original authority/DNS/SSRF/cancel/high/Flash/v2,
APIca0a85f2/Search19f3942f/env/entrypoints and accepted Worker9e1a5f95 base.
Only model_step_support.py differs. All8canonical completed, retry0, no toolfailure.

| Question | Body A→B | Whole A→B | Models A→B | Tools A→B |
| --- | ---: | ---: | ---: | ---: |
| Python |13.126→9.592s|14.722→11.317s|3→3|4→3|
| SQLite |11.721→13.195s|14.265→19.917s|3→4|2→2|
| Node |13.241→14.409s|16.080→17.220s|3→4|4→6|
| PG/Redis |11.807→12.886s|19.784→15.173s|4→3|4→4|

Visible body is earliest DOM frame matching the final answer's normalized16char
prefix; this can include provisional v2 draft text. Whole uses Send→canonical
completion. One sample per question/arm; no p95 or statistical population claim.
A median body12.466s→B13.040s, Amean12.474→B12.520s; wholemean16.213→15.907s.
Totals13→14models,14→15tools. This does not demonstrate generic reduction.
Both PG/Redis arms found the correct GA announcement immediately; the original
B1 bad result set was not reproduced. Do not compare historical5models/8tools to
a new3/4Run as a causal improvement.

Python drops one overlapping search but still fetches two corroborating pages.
Node candidate uses two searches+four announcements; control uses table+search+
two announcements. Both cover required facts, but candidate does more work.
SQLite artifact reading targets missing middle content, not repeat fetching.
Optional answer expansion remains despite the new guidance. Reject the checklist;
no deterministic source choice, forced tool count, reranking or hardcoded URL added.

## Separate concrete defect discovered

B2 SQLite and A4 PG/Redis each generate2candidates. Re-evaluating their original
public candidate against their unchanged collected references reproduces a false
citation failure. Regex consumes the Chinese right parenthesis as part of a URL:
SQLite becomes “https://www.sqlite.org/wal.html），要点如下”; PG release-notes URL
gets a trailing “）”. Both URLs were collected; unknown URLs must still fail.
A separate small task will repair this delimiter. It does not fix historical B1
source choice. No old Run/data is replayed or changed by offline evaluation.

## Evidence and status

Source snapshot and retained public frames/receipts: ignored feature artifacts
.cloud-source-decision-check under .artifacts, including summary.safe.json,
frozen-source.safe.json, canonical/tools/page records and citation-replay-{A4,B2}.
The exact artifact directory is .artifacts/cloud-source-decision-check/.
No credentials, headers or private reasoning collected. Captured Run identities
are in summary.safe.json. New quality correction must be measured separately,
with original guidance, not combined with this rejected prompt.

Source remains experimental on codex/cloud-source-decision-check-01. No production
implementation integrated. Only this report/task/progress log is locally integrated.
Normal Worker restored9e1a5f95, API/Search/env preserved; no remote push/deploy,
global proxy/Trench change or unrelated fixture repairs. Existing prior classification
and connection/egress improvements remain active.

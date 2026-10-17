# B1 fixed-evidence source decision replay — 2026-10-17

## Decision

Do not promote a production change or start a new page performance cohort yet.
Clarifying tool capabilities did not reduce proposed work. Lossless structured
search output improved the first choice in this small sample, but saved only one
proposal overall and did not remove the consistently overlapping fetch batch.
It is an experimental lead, not a demonstrated generic optimization.

No new global prompt/checklist, source ranking, URL rewrite, forced search/tool
limit or Trench change. Existing normal API/Worker/Search images, environment and
restart counts verified unchanged before/after. Fresh authorization, DNS/SSRF,
cancellation, high/Flash and transient_v2 production paths remain unchanged.
The decision probe itself is not an authorization or v2 end-to-end acceptance.

## Frozen input and protocol

Historical B1: Run b009ee61-6682-4e1a-a983-6cad1acabd5d,
session81c3b480-d726-48fb-93e6-3aa3e3cec164,
conversation conv_1792231623512_33c29d. See CLOUD_B1_EVIDENCE_AUDIT.md.
Goal asks for official PG18/Redis8 release dates and two features per product.

Freeze the original eight successful tool outputs, eight proposals, public tool
arguments and model-visible artifact_uri/result_count/truncated metadata.
Fixture SHA256 ff532034f1322593e91a166966cec5b9999d13bbf64c6483f3c2e77e7f64dc92.
No new web queries/fetches or historical Run writes. Each probe asks the native
streaming gateway for just the next response; proposed tools are never executed.

Four checkpoints, two repetitions, three variants: exactly24 valid completions.
Variant order rotates by checkpoint/repetition; all adverse outcomes retained.
Same native initial guidance/acceptance inference, user goal and public history;
deepseek-v4-flash-executor-v1, resolved deepseek-flash, thinking enabled, high,
automatic tool selection, normal output budget. Provider retries disabled for
this finite diagnostic; all valid responses report retry0.

- A: current tool descriptions and original result text.
- D: only search/fetch capability descriptions clarify snippets versus fetched
  text, provider rank versus authority, and successful fetch versus relevance.
  No additional research/stop instructions; argument schemas unchanged.
- R: only search-result layout becomes ordered JSON records with position,
  title, URL and snippet. Same exact fields, order and whitespace in each snippet;
  no extra facts, scores, labels of authority, reranking or new search results.
  Fetched page text and observation metadata remain unchanged.

Checkpoints are independent counterfactual decisions against the original public
history, not a chained simulated Run. A choice at checkpoint19 does not change
the frozen history used at checkpoint32. Do not sum proposal counts into claimed
actual tool executions, model rounds, SQL or wall-clock savings.

## Findings

| Fixed evidence available | A original, two probes | D descriptions, two probes | R result layout, two probes |
| --- | --- | --- | --- |
| After seq19: PG announcement; Redis top5 omit GA |1 suitable refinement;1 guessed GA URL|1 suitable refinement;1 product landing fetch|2 suitable refinements|
| After seq32: PG and Redis product page fetched |Both search plus unobserved URL fetch|Both launch2overlapping searches|1search+observed product link;1search only|
| After seq45: both recovery searches returned GA |Both fetch GA+version docs|Both fetch GA+version docs|Both fetch GA+version docs|
| After seq58: GA+docs bodies available |Both answer, no tools|Both answer, no tools|Both answer, no tools|
| Total next-response tool proposals across8probes |12|12|11|

The historical landing detour was reproduced under D, while A varies between a
useful refinement and an unobserved URL guess. This rules out interpreting any
single newly successful decision as a deterministic fix. A proposed GA URL absent
from the observed results remains a URL-provenance violation even if it happens
to be a real page; those proposals were not executed. Missing historical Host
context limits extrapolation to the complete production request.

All6probes at seq45 choose announcement+documentation together. That behavior
survives both capability wording and lossless layout changes. The need for the
documentation is prospective: the announcement has not been read at this point.
The fact that its later body covers all required facts is hindsight. No public
rationale establishes whether the model expected distinct feature coverage or
preferred redundant confirmation. Do not invent a private explanation.

All6probes with the complete original bodies stop collecting and give the correct
two release dates with feature discussion. This supports a distinction between
source selection/parallel scope and inability to stop after complete evidence.
It does not certify every detailed statement, concise formatting or citation:
the normal runtime quality gate is not executed in this diagnostic.

Tool definitions were not missing necessary inputs: current query/URL schemas
work, and the original five candidates are preserved. Result expression can
influence choice: R has2/2appropriate first refinements versus1/2for A and D.
But R still selects an unnecessary product link in one later decision, leaves
all announcement+docs pairs intact and increases input tokens. With only2probes
per cell, a one-proposal difference is insufficient for promotion or significance.

Native usage totals (including reused context, not new uncached billing):
A input72374/output2729; D72742/2762; R76558/3268.
Total input221674/output8759. No latency or SQL percentage is derived from these
single-response requests; no end-to-end model-turn reduction measured.

## Reconstruction and protocol limitations

Use actual native HarnessModelStep initial messages, registry-generated contracts
and tool_result_message observation rendering, with a reduced three-tool catalog:
web.search, web.fetch, artifacts.read. Original Host directives/full catalog and
private reasoning are unavailable to this public-evidence reconstruction.
Synthetic empty reasoning_content is explicit protocol scaffolding on every
historical assistant message; it is not a reconstruction of original reasoning.
Never retrieve, persist or display historical/new private reasoning.

Initial protocol batch24requests all returned400before generation;2additional
diagnostic requests confirmed the public acknowledgement also needs the field.
Those26rejections are retained separately, not behavioral samples. Corrected
protocol produced the fixed24valid responses; no failed/unfavorable behavioral
sample was replaced. The final script stops on the first Provider error to avoid
repeating a protocol fault. This defect was in the diagnostic reconstruction,
not a new production Provider regression.

## Reproduction, acceptance and next boundary

Offline executable check (no model/network):

```sh
.venv/bin/python scripts/check_cloud_source_replay.py self-check /absolute/path/fixture.safe.json
```

The check validates exact ordered search-field roundtrip, unchanged non-search
history, A/D content equality, unchanged argument schemas, empty synthetic
continuation and native tool pairing. Ruff passes. No production source changed,
so no broad fixture/test repairs or service rebuild was performed.

Private public-test evidence is retained in the feature worktree under
.artifacts/cloud-source-replay/: fixture, manifest, all24valid proposals, original
24rejections, protocol diagnosis, summary, source hashes and before/after normal
service identities. Only owned /tmp diagnostic files are removed after export.

The minimal justified action now is retaining this replay check and rejecting
another unproven prompt/formatter promotion. A structured-result candidate first
needs consistent gains on fixed evidence from different questions without fact
loss, extra token/decision cost or citation regression. Only a qualifying candidate
should proceed to finite real-page pairs with fresh authorization, high/v2 and
autonomous tools. No new page cohort, deployment, push or speedup claim this turn.

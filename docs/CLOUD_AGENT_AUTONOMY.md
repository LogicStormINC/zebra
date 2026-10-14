# Cloud Agent autonomous execution guidance

2026-10-15 CLOUD-AGENT-AUTONOMY-01: first implementation slice.

The main Agent decides whether to answer, use tools, plan or delegate in its normal
model call. No separate classifier or mandatory research stage is added.
Shared guidance is injected once during initial message composition and remains
present with a Host identity override and without delegation tools. The Host
identity scopes proactive tool use and failure recovery to the actual request.
Transforming supplied text is distinguished from verifying external state.

Trench forwards a goal-only acceptance contract. Product mode still selects
capabilities; runtime inference and explicit contracts retain evidence, citation,
operation and coverage requirements. Research answer guidance is conditional on
actual research. Core keyword inference is unchanged in this slice.

Answer revision feedback addresses listed missing requirements using existing
content/evidence first. Tool availability, budgets, authorization and fresh
post-mutation verification are unchanged. agent.plan and durable plan recovery
are reused. No new database schema, dependencies or model calls are introduced.

Validation:103 focused Zebra tests,45 Trench contract/capability tests, changed-path
Ruff checks. A negative control removes guidance injection and proves the new
regression test fails. The offline model directly answers with tools available:
one model request, zero executions. These tests prove runtime behavior, not the
real provider's semantic decisions. No full-suite or live behavioral gain claim.

Manual acceptance: start a new local Trench turn with a supplied-text reply,
then contrast with a request to verify actual connection state. Check whether
the first replies directly and the second performs relevant verification.
Also test focused facts, complex research and required operation verification.
Unseen paraphrases are needed to assess generalization. No model calls were made
by this implementation/verification turn.

Local activation:Worker healthy, all four source hashes matched, runtime preflight
ready; Trench hot reload completed and /api/health/live returned alive. The local
Worker image derives from the previous verified image with four source replacements;
no full Dockerfile build was run for this slice. Integrated commits5cadc4e6 (Zebra)
and e6f82a8 (Trench); no push. Real model decisions remain unverified.

## 2026-10-15 real-model paired acceptance: FAILED

The user authorized exactly two real UI-submitted new sessions, same Flash/high/
general configuration, both transient_v2. Supplied-text reply used2 main-model
rounds/3 tools (sources.list, files.list, subscriptions.list_history), Host completion
24.793s. Connection verification used3 rounds/13 tools, completion47.326s.
Both completed without tool failures. The first still expands the expression
request into account inspection; offline success did not establish semantic success.
Run IDs ef0a7336-cced-459d-973b-04fce6282186 and
d49fd141-25aa-449d-a5bc-df29dcc2d589. Next: inspect actual first-turn assembled
inputs; do not claim the simple-task behavior fixed. No third test/model submission.

2026-10-15 follow-up diagnosis: failed turn selected zero memories; no personalization
record exists for this principal. Host contract is goal-only. Running Worker offline
composition confirms new guidance and scoped Host wording are loaded. Provider
serialization forwards messages without adding a compulsory research stage.
Candidate02 clarifies phrase/acknowledgement deliverables versus real state checks
and forbids unrequested onboarding/account overviews in that expression context.
This is semantic guidance, not a keyword classifier or tool restriction.103 focused
regressions pass. One same-configuration real paired retest follows local activation.

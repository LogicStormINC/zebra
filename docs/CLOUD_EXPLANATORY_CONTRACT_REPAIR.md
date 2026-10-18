# Explanatory task contract boundary

CLOUD-EXPLAIN-CONTRACT-01, 2026-10-18. The shared fallback information-request
markers omitted the Chinese explanatory verb 说明. An explanation mentioning
deletion was therefore classified as change and required change_applied and
result_verified, suspending an otherwise informational answer.

Minimal repair: add 说明 to the existing information-request list. Existing
explicit/compound action detection still takes precedence; inferred actual
changes and operations retain verification, explicit Host contracts remain
authoritative, and actual mutating tool results still require fresh evidence.
No prompt, model, tool-choice, Trench or verification-gate change. This remains
a bounded lexical fallback, not a semantic intent classifier.

Red-first reproduction: four explanatory cases failed before the one-marker
repair. Afterwards 59 focused quality/mutation/explanation tests pass, plus
7 factual lookups / 11 compound action checks and 12 publication noun/action
checks. Ruff passes. Runtime inference is composed by Worker task recovery;
only Worker activation is required. Local activation and one high/v2 page
acceptance follow; no retry/interception or original partial-Run mutation.


## Local acceptance

Source 19517d08 is integrated into cloud-agent-trench. Worker-only derived image
replaces exactly the shared task_contracts.py module. Its base module SHA256
matched the checked-out parent before replacement; effective environment,
command, mounts and security settings were verified unchanged. No active lease
was present. The first activation failed at Docker CLI TLS initialization before
changing the container; preserving the host Docker context resolved it. Worker
is healthy, live offline inference checks pass. API and Search container IDs,
images, StartedAt, restart counts and environment hashes remain unchanged.

One new page Turn used the exact previous failing question in a fresh
conversation conv_1792319798327_978aff. Turn
4c3a0256-1197-4e8f-a52f-00c248f3af4c / Run
d4ea45ea-06db-47b6-9314-5e57da21b4b8 completed with task_type=answer,
high reasoning and transient_v2. Exactly one scoped suggestion POST returned
HTTP 200 / ready / deepseek-flash in 3.247 s. The three follow-ups and three
quick actions were automatically stored on this exact Turn and matched the
actual HTTP response. After real page reload, snapshot HTTP 200 returned the
identical stored result and all six labels displayed. Zero suggestion or new
Turn POSTs after reload, no response interception, no model/provider retries.
The single new conversation contains one Turn and one Run.

Both original partial Runs and the previous awaiting_input sample retain
identical status/answer/request/metadata fingerprints; Trench .env and frontend
dedupe sources unchanged. Evidence: .artifacts/cloud-explain-contract-01/ on
the task worktree, including before/after-runtime.json, page-before.json,
page/db-after.json, page/browser-acceptance.json and page/after-refresh.jpg.

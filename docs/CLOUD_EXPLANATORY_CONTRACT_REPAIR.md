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

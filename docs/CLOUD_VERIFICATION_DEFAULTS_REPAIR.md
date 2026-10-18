# Explicit mutation contract verification defaults

Task: CLOUD-VERIFICATION-DEFAULTS-01, 2026-10-18.

## Cause and minimal repair

`parse_task_contract` previously selected the explicit Host task type but inherited
missing verification fields from text inference. An explicit change/operate
contract with an explanatory goal could therefore omit verification and its
matching action outcome. Defaults now follow the final mutation type, replacing
the opposite type-specific default while preserving generic inferred outcomes.
Explicit requireVerification and requiredOutcomes fields remain authoritative;
this does not exempt actual observed mutations from fresh evidence checks.

`needs_post_mutation_verification` previously returned false when no read-only
tool was available. Capability absence was consequently interpreted as evidence
satisfaction. Freshness now depends on recorded mutation and verification epochs,
including per-resource coverage, regardless of read capability. Valid existing
proof and explicit postcondition receipts remain accepted.

The shared finalization capability check also requires a read-only tool before
asking for another verification round. Without capability or budget, unverified
writes suspend with verification_required rather than pass or request an
impossible additional round. This changes no semantic classifier, keywords,
prompts, provider, schema, Trench logic or suggestion de-duplication.

## Offline acceptance

- Red-first reproduction: 13 failed, 14 passed before the repair.
- Complete agent-core regression: 1,710 passed, 1 skipped (11.78 s).
- Existing standalone search-intent and publication-date checks passed.
- Targeted Ruff and git diff --check passed.
- New checks cover both task-type field spellings, final change/operate defaults,
  explicit Host overrides, missing/stale/fresh/global/per-resource proof, and
  scripted harness termination without an extra model/tool round.
- Two existing outcome-matching tests now include fresh verification so they
  continue testing outcome matching rather than relying on the removed bypass.

No external model or search request was made. Harness completions are scripted.
No service was rebuilt or restarted in this task. Source acceptance is separate
from live Worker activation. The current Worker differs from the earlier task's
record; no unchanged-Worker or live-E2E claim is made. API/Search process IDs and
start times still match that record.

The two protected original Turns remain partial, high/transient_v2 with their
original feedback. Answer/request/metadata hashes match the prior saved snapshot.
Local delivery targets cloud-agent-trench only; no push or deployment.

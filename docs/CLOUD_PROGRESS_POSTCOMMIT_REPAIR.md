# Confirmed source and deferred Worker progress repair

Task `PROGRESS-POSTCOMMIT-REPAIR-01`; owner Luke Ding, executor Codex.
Branch `codex/progress-postcommit-repair-01`, base `f41ce9e8`.
Local integration and activation only; no replay of the reported failed Run.

## Incident and reproduction

Conversation `conv_1792127071549_e0f4b3`, Run
`07663699-3e1a-4f00-9fe0-47a8f41e6dd6`, failed after39.536s.
Three high-thinking model responses and five successful tools are canonical.
The third response proposed more tools; no accepted final answer exists.
Its response and commentary are committed at45/46, while Worker progress remains
at45 with that exact commentary pending. Output ID, model-call ID and text digest
all match. The subsequent TimeoutError was mislabeled `model execution failed`.
Historical logs locate the boundary but do not identify a single slow SQL query.

The standalone check reproduces this boundary without a model: append a model
response and its exact commentary, inject a checkpoint timeout, then continue
with another event. Before the patch, the exception escapes and ends execution.
A separate native PostgreSQL check injects `pg_sleep(3)` under the unchanged
publication/Task I/O deadline. It exercises the actual bounded connection and
fenced canonical append rather than a simulated database timeout.

## Minimum shared repair

`WorkerProgressRecovery.persist_with` distinguishes preparation, canonical
append, and post-append checkpoint synchronization. `WorkerProgressTimeout`
carries that stage and whether the original source sink positively acknowledged
its append. No caller infers acknowledgement from elapsed time or an exception.

The progressive event dispatcher accepts a positively committed source even
when subsequent derived synchronization times out. It leaves checkpoint repair
to the existing canonical-index reconciliation on the next sink invocation,
before another append. No canonical append is retried. In-memory commentary
reservations remain idempotent across publication and deferral, preserving the
eight-chunk quota. Timer publication and observations of store-owned Effect
receipts likewise tolerate only confirmed post-commit checkpoint deferrals.

Unknown canonical commits, pre-append timeouts, lease loss, invalid identities
and source conflicts still propagate. A required progress-storage failure is
classified `execution_progress_unavailable`, rather than model execution failed.
Safe diagnostics record stage, acknowledgement flag, function names and line
numbers; they never interpolate raw exception messages, prompts, tool arguments,
credentials or private reasoning.

The dispatch body moves to the existing model-response progress module before
adding handling, keeping public_output.py below its500line ceiling. There is no
new queue, timer, connection pool, schema, dependency or model call. The two-second
cumulative I/O/publication deadlines, fresh authority/fence/STOP checks, Redis v2
lane, prior lock-fairness and release-date contract fixes remain unchanged.

This is not permission to continue through a database outage: if the next
required preparation cannot reconcile the source, execution still stops safely
with the storage classification. A transient derived failure cannot erase an
acknowledged source, and a write whose outcome is unknown is never assumed safe
to replay. A process crash remains governed by existing durable recovery.

## Verification and operation

- `uv run python scripts/check_progress_postcommit_repair.py`: exact source gap,
  next-event reconciliation, one output per identity, unchanged reservation
  counts, unknown canonical commit propagation and error classification. Also
  covers confirmed/unconfirmed timer and store-owned Effect observations.
- Existing commentary/progress/composition/model-commentary regressions:41pass;
  response-validation/context error regressions:8pass.
- Native PostgreSQL sleep injection: returns in1838.7ms, one exact commentary,
  pending gap reconciled on the next event, exact source sequence, zero models.
- Existing native unknown commit, expired fence and publication regressions:
  4pass. No old PostgreSQL fixture or scratch account was repaired.
- Source/script Ruff, mypy1283, file-size3092 and deterministic eval30 pass.
  The final small shared-observer follow-up also reruns its affected regressions.

Normal source-only API/Worker images overlay the four changed core modules in
both roles and the two changed Worker modules only in Worker. Activation requires
zero active Host intents. Final source fingerprints, original six Compose files,
environment/entrypoints/commands and unchanged search composition are verified
before reporting local service completion. Final API233f737d / Workera287087d
are healthy with zero restarts;75 source identities and the original six-file
composition/environment/search checks pass. The final image manifest also
matches every current source byte. Private evidence is under
`.artifacts/progress-postcommit-20261016/`.

No real model acceptance is claimed in this slice. The historical failed Run is
retained; it has no accepted final answer to restore. No new message, replay,
manual status edit, database migration, push, npm publication or remote deployment.

# CLOUD-TURN-CLOSE-01: admitted Turn identity at finalization

## Incident and root cause

Conversation `conv_1792301892048_13b0f1`, Cloud session
`db605223-91df-40f3-8b24-1a7556ceee3f`, already committed its second answer
at sequence444 (8,818characters). The continuation then failed during
`append_turn_close -> ExecutionInputEventView.list_for_session -> advance`:
accumulated exact execution inputs exceeded the existing1MiB preparation cap.
The lease was released, but no TURN_COMPLETED event existed, leaving Cloud
running and the page streaming. This was a finalization failure, not ongoing
model execution. Existing execution state remained intact.

## Minimal change

Cloud execution binds immutable Turn identity from the successfully admitted
snapshot when constructing its existing event view. Finalization reuses this
identity instead of replaying/preparing model inputs. Unbound views and foreign
session snapshots fail closed. A newer message cannot change which Turn this
execution closes. Local canonical EventStore behavior remains unchanged.

Recorder still enforces fresh control/cancellation, sequence and lease fencing.
Exact input preparation keeps its1MiB/2048limits. No context truncation, limit
increase, model retry, engine change, dependency or Trench product change.

## Validation and local activation

-33focused no-model tests passed: admitted identity, second/newer Turn,
  completion/failure/one-shot, lost lease, unbound/foreign view, original1MiB
  rejection, existing finalization and execution input frontier checks.
- Ruff passes; mypy reports no issues in four source files.
- Exact previous Worker image plus only four changed application files;
  offline network-disabled image checks passed. Local Worker healthy and
  source bytes match. Environment/mount/security configuration preserved.
- API/Search identities, images, start times, restarts and environment hashes
  unchanged; persistent Exa control bytes unchanged. Original MCP process kept.

Focused command (workspace PYTHONPATH required):
`python -m pytest tests/worker/test_turn_close_admitted_identity.py tests/worker/test_execution_finalization.py tests/worker/test_execution_input_frontier.py -q`

## Original Run recovery

After checking no active execution/command/newer Turn and exact revision444,
acquired a short-lived operator lease and appended only missing TURN_COMPLETED
for original Turn `3ed953da-8228-54d2-beba-c78da214deb5`, index1, attempt1.
Used normal `commit_worker_event` transaction with lease fence and revision CAS,
canonical session/workspace projections and an idempotency key; released lease.
No raw projection edits, new Run/command/harness/model/tool execution.

Sequence445 now parks the conversation at awaiting_turn. Original answer payload
SHA256 stayed `8581071b688784c6a29a6cbe1dc0683dab570c6155a7445ed8dcd1f633f76d68`;
model request/response counts stayed20/20, tool completions stayed62. Repeating
the recovery check appended nothing. A normal asynchronous
MEMORY_EXTRACTION_COMPLETED event followed at446, with model/tool counts unchanged.
Browser reload shows both turns completed,
normal input and disabled Send instead of Pause; no Trench outbox repair needed.
This repairs completion synchronization, not semantic certification of the
answer's requested full-news coverage. No performance improvement claim.

Private evidence: `.artifacts/cloud-turn-close-01/` (regression.log,
recovery.log, recovery-idempotence.log, before/after.json, page-completed.png).
Local commit/integration target cloud-agent-trench only; no push/remote deploy.

## CLOUD-CLOSE-RECOVERY-02: recovery before model-input preparation

The Cloud composition now supplies a completion reader through the existing
Worker recorder factory and canonical replay adapter. Before Worker progress,
execution inputs, model gateway or runtime setup, the execution entry reads
only lifecycle events at the claimed revision under the current lease fence.
It excludes tool and model-response bodies. Existing per-page and cumulative
1MiB/2048-event replay limits remain, as do execution-input preparation limits.
Evidence over the bound fails closed; it is never truncated or treated as absence.
The reader uses the existing replay seek index; no schema change is required.

The last admitted command, current human Turn and latest Harness Attempt delimit
the recoverable answer. One canonical Harness ANSWER_COMMITTED with complete
assessment and no unmet requirements permits an idempotent TURN_COMPLETED.
Conversation mode parks awaiting_turn; one-shot mode then reuses the existing
Session-terminal reconciliation. A crashed TURN_COMPLETED/TURN_FAILED or SYSTEM
TURN_CANCELLED missing its Session terminal reuses the same reconciliation;
original failure/cancellation outcomes are preserved. No new command, answer,
certificate, model call or tool execution is created.

Partial/blocked delivery, or a complete label with unmet requirements, is never
upgraded to successful recovery: the existing assessment is retained and the
Run suspends as committed_delivery_incomplete, with no automatic model rerun.
Conflicting Attempt/Session identity or ambiguous answers fail closed. No legacy
Turn identity is guessed. Recorder fresh control state, ownership, lease fence,
revision CAS and idempotency keys still gate all writes. A newer human message
or control event winning the read/write race prevents stale completion. The
shared Session-terminal reconciliation accepts an optional expected revision
so a race between the two close events cannot terminate a newer revision.

Normal finish also checks the current recorder's canonical committed answer.
Only proven complete delivery for the same Attempt can normalize a following
cleanup/derived-state failure to completed; diagnostic metadata remains. Older
answers cannot override a newer Attempt/question, partial/blocked assessments,
or authoritative control state. Memory/title side effects and local event-store
behavior remain on their existing paths; Trench product code is unchanged.

Validation:82 unique focused no-model cases pass across the final80-case gate
and two added SYSTEM-cancel/failure cases (final recovery file19/19). This
includes real Recorder/projection recovery and entrypoint ordering, new-message
CAS and cancellation races, lost lease/foreign identity/Attempt, idempotence,
partial/blocked/unmet safety, cleanup result preservation, and existing input,
preflight and progress regressions. Native PostgreSQL tests use only disposable
schemas in a task-only header_scratch container. They verify a >1MiB aggregate
of tool bodies still permits exact bounded lifecycle reads, and >1MiB lifecycle
evidence and stale fencing are refused. Ruff and seven-file mypy pass. Exact
seven-file Worker derivative also passes network-disabled offline checks.

An older shared scratch server rejected its configured test credential; it was
left unchanged. Native checks then passed on the task-only isolated PostgreSQL.
No application data, credentials, limits or test fixtures were repaired.

Local activation: zebra-worker:close-recovery-02 is healthy; exact seven source
files and preserved configuration verified. API/Search ID/image/start/restarts/env
and persistent Exa control bytes match before; model/tool counters are unchanged.
Task-only test PostgreSQL removed. Evidence: private .artifacts/cloud-close-recovery-02/
(final-regression.log, final-recovery-regression.log, mypy.log, image-check-final.log,
before/after.json, counts.before/after.json). No migration or Trench change.

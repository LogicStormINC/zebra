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
the recovery check appended nothing. Browser reload shows both turns completed,
normal input and disabled Send instead of Pause; no Trench outbox repair needed.
This repairs completion synchronization, not semantic certification of the
answer's requested full-news coverage. No performance improvement claim.

Private evidence: `.artifacts/cloud-turn-close-01/` (regression.log,
recovery.log, recovery-idempotence.log, before/after.json, page-completed.png).
Local commit/integration target cloud-agent-trench only; no push/remote deploy.

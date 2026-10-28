# Canonical event versus UI publication budget (2026-10-28)

## Incident and proven boundary

Conversation `conv_1793153591356_c0a6d3`, Turn
`cfb7b0ea-e9aa-449e-b9c4-3bbbeeb875e3`, Run
`06a0abf1-b86a-4c5b-a47b-31a279a95d6e`, Task
`8954fb2e-c495-41ae-ac8b-f6c4b8f9f8f2`.

Original events show two successful model responses and two executed tools
(sources.list, subscriptions.list_history), no web.search. Sequence23 contains
the second successful candidate response; sequence24/25 fail with
WorkerProgressTimeout/canonical_append. Worker progress remains through22.
Logs show ~518ms preparation plus1393ms append work and a timeout while awaiting
COMMIT. Provider normalized_error is null; this is not a provider/model failure.

Core dispatch_public_event applied the2s UI-publication deadline to *every*
canonical fact. WorkerProgressRecovery.persist_with further capped the complete
preparation/append/checkpoint chain at2s. The outer deadline includes existing
lease/tail reads and several bounded transactions. Task I/O reserves part of
that remaining budget for native cancellation. The native commit response can
therefore exceed the residual operation budget even after the canonical event
becomes visible. committed=False means the sink did not return, not that the
server necessarily rolled back.

This is distinct from the previously unresolved LockNotAvailable incident.
No claim is made that this change fixes all lock contention or hardware stalls.

## Smallest repair

Three production modules changed, no new dependency/schema/configuration:

- public_output_lifecycle defines separate finite ceilings: UI publication and
  MODEL_RESPONSE_DELTA2s; canonical execution facts5s.
- model_response_progress passes the actual event type into the shared lock.
- Worker progress persistence uses the same event-type ceiling.

An explicit shorter parent deadline still wins. Per-connection/transaction Task
I/O remains at most2s, cancellation reserve and50ms lock timeout unchanged.
UI timers, auxiliary expressions, temporary drafts and close deadline unchanged.
No event/model/tool is retried, no exception is converted to success, and no
unknown commit is blindly re-appended. Fresh DB ownership/lease/cancel checks
remain in every existing path. Normal fast operations incur no added delay;
this change permits aggregate critical work to finish during bounded jitter.
It is not a SQL-reduction or throughput optimization.

## No-model proof

- Two deterministic regressions failed on the original code: primary request /
  response facts inherited the short UI limit.
-105 focused checks pass:93 progress/core/SQLite/PostgreSQL checks plus12 UI
  deadline checks, including the two real SQL/commit timeout cases. Final five
  canonical-deadline checks rerun after strengthening the committed-before-ACK
  fixture; all pass. Ruff, compileall and diff checks pass.
- Real isolated PostgreSQL verifies the critical pipeline can finish beyond the
  UI ceiling while individual transactions remain bounded. Scope/lease loss,
  superseded Run, unknown commit, key limits, short parent deadline, cancellation
  and no-late-UI-write checks retained.
- Exact old/new production images, network=none/read-only/tmpfs, same saved
  sequence23 response: inject2.05s aggregate callback cost and verify the native
  deadline at acknowledgement after the SQLite write. Old image reports
  storage_timeout at2059ms; new image accepted at2064ms. Each writes exactly once.
  Payload SHA256 identical;0provider/search requests. This is fault-injection
  proof, not a production latency improvement claim. The initial self-check
  mistakenly simulated a returned sink/checkpoint timeout, which is already
  deferred correctly; that result was rejected and the ACK boundary corrected.
- Disposable local PostgreSQL test container/volume removed. No production DB
  test schema or synthetic event was written.

## Production activation

Source commit `b3793278`, branch `codex/cloud-progress-budget-20261028`; only
local commit, no push or main merge. User authorized fixing the live incident;
source awaits maintainer integration. Unrelated primary dirty work preserved.

Built on exact running Worker after original module hashes matched; overlay only
three changed modules and compile them. Build compilation used root temporarily,
then restored existing runtime User=zebra. Image runtime config equals base.

Image `zebra-worker:progress-budget-20261028`:
`sha256:45cb2dd72b0e0c8c6d57ed110a3c439ebd0e55350cda40a80d86110ed3ed3aa5`.

After zero active leases/pending commands/active Turns, recreated Worker only,
retaining the five existing Zebra Compose layers and adding
`/home/ubuntu/releases/20261028-progress-budget/worker-override.json`.
Env/mounts/security unchanged; schema105 unchanged. API/frontend/Redis/Search/
Yahoo-egress/TLS/MCP container identities/start/restarts and Exa cooldown retained.
Actual running imports show UI2/canonical5. Existing healthcheck only checks
process/key/Docker availability; it is not treated as E2E proof.

Original26-event hash remains
`2cee8c7143b21ed56e6d4fd35b608e68fdb10fcacca1d2fa02f7eb75692b34b8`;
original2model requests/0search unchanged. Original Run remains failed. It has
no answer_committed event; its733char candidate must not be promoted to a final
success or rerun without authorization.

## One explicitly authorized real page Run

After deployment user authorized **one** new Run, no retry. Submitted once from
logged-in Chrome through the normal Trench page, no intercepted responses:

`http://192.168.110.42:18080/dashboard/strategy/conv_1793154759026_9a4ea0`

Prompt: 请只用一句话回复：演示环境已就绪。不需要查询资料，也不需要操作任何数据。

- Turn `a7407cf9-6a42-4aa4-aa19-6d85b9936003`.
- Run `f0e03834-c07f-4a06-a38c-5934ed9a818b`.
- Task `2aa707da-aff3-4318-bfa4-7493688c212d`.
- Exactly1accepted Run command/1executor model response, retry_count0.
- DeepSeek Flash, reasoning_effort=high, thinking enabled, transient_v2.
-0tool calls/0search; response latency1136ms.
- Turn created1793154759164, terminal synchronized1793154766106:
  admission-to-terminal6.942s. Browser submit timestamp1793154758972 gives7.134s
  to persisted terminal; exact first-paint latency was not instrumented.
- answer_committed, turn_completed present; Trench status completed/error null.
  Actual page displays “演示环境已就绪。” and normal input controls.
- Page reloaded; same answer restored, no failure/reconnect banner, no second
  executor request. Normal automatic follow-up suggestions POST count1; it is a
  separate auxiliary request, not a second executor Run or manual probe.
- Original failure retained; protected service IDs/cooldown still unchanged.

This establishes one minimal normal-page path, not every research/tool scenario
or a guarantee against an actual DB outage. No second sample was submitted.

## Evidence and rollback

Private server evidence/immutable deployment plan:
`/home/ubuntu/releases/20261028-progress-budget/`.
Local task worktree evidence:
`.artifacts/cloud-progress-budget-20261028/`, including real-page-after.png.
Saved response stays private; reports use counts/hashes, not full business text.

Rollback: after idle checks, use deployment-plan.private.json before_files to
recreate only zebra-worker with its original image. Do not replace API/frontend,
change schema, clear queues or restart Search/MCP. Do not reuse activation.once.

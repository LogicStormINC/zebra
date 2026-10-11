# Client continuation liveness — CLIENT-RESUME-LIVENESS-01

## Incident and root cause (2026-10-02)

Trench conversation `conv_1790859137314_ab1aef`, Zebra Session
`923c3daa-f04c-42e2-b564-24ddbe05b74b`, stalled after a browser receipt.
Sequence 123 contained a HARNESS resume whose producer hashed only the session
and effect identity instead of the full SessionCommand intent. Worker integrity
validation correctly rejected it, but permanent rejection did not close the wait.
Transport heartbeats kept the Trench observer lease alive despite no execution
progress. A sibling child-wakeup producer used a different hash and mismatched
event/payload idempotency keys.

## Changes

- Client receipts and child wakeups use `SessionCommand.event_payload()`;
  producer-to-consumer validation is tested against real PostgreSQL writes.
- Invalid live internal continuations emit Turn/Session failure evidence instead
  of remaining indefinitely busy. A newer canonical replacement takes precedence.
- Worker maintenance reconciles browser waits every 15 seconds. A rotating,
  32-session batch avoids starvation. Receipt and stream locks follow receipt
  writer lock order. Immutable legacy evidence is retained; repair appends a
  deterministic canonical command at most once.
  Maintenance connections have bounded connect/statement/lock timeouts and a
  five-second batch budget so a contested row does not stall normal polling.
- Recovery accepts only matching authoritative receipts or server-expired effects;
  it skips active worker leases, terminal/resumed epochs and pending stop/cancel/
  suspend requests. Unknown fingerprints are not silently repaired.
- Ordinary client actions expire after 30 seconds; user-interaction actions retain
  the existing 10-minute allowance. Expiry becomes a failed tool observation, not
  a fabricated success or a repeat of the browser side effect.
- Historical client receipts cannot unlock a new pending browser effect.
- Trench separates transport idle from business-progress idle. The configurable
  `ZEBRA_STREAM_PROGRESS_TIMEOUT_MS` defaults to 300000. Heartbeats and reconnects
  cannot indefinitely extend this observer deadline. Completed content is kept.
  Observer timeout does not claim the upstream task was cancelled: its durable
  status remains authoritative. Existing worker execution budgets still apply.
- SDK activity summary honors the running Turn even if all tools have completed.
  Trench's vendored React package and lockfile are updated together.
- Trench event-open tool instructions distinguish offering navigation from
  actually navigating, and avoid unnecessary navigation after media presentation.

## Operator repair

With the intended database URL and namespace already configured securely:

```sh
uv run python scripts/recover_client_effect_wait.py SESSION_UUID
uv run python scripts/recover_client_effect_wait.py SESSION_UUID --apply
```

The first command is read-only. The second only appends an eligible continuation;
it does not replay UI actions, remove history, or restart any service.

## Validation and delivery boundary

- `make check`: file-size, Ruff, mypy (1007 source files), 30 deterministic evals.
- Full `make test`: 4882 passed, 913 skipped (environment-dependent checks).
- Worker suite plus client-effect integration: 372 passed, 23 skipped.
- PostgreSQL receipt/wakeup/recovery suite: 17 passed using isolated PostgreSQL.
- Trench runtime/interrupt-content/skill-binding: 66 passed, including heartbeat
  and duplicate-cursor no-progress regression cases.
- SDK conversation timeline: 5 passed; Trench projection/thread: 6 passed.
- Three older skill-binding mocks lacked the runtime-capabilities response;
  they now model that endpoint explicitly without bypassing production checks.
- Incident recovery appended one canonical command without service restart.
  Zebra then wrote `turn_completed` at 244 and `session_completed` at 245;
  Trench Turn `f5c08c94-47a5-4d4f-943b-db3972a6b55e` also persisted `completed`.
  This verifies restored execution, not correctness of every answer/media asset.
- Browser confirmed the final answer and normal composer. The answer reports
  host-tool timeouts and video-page probe failure; those external dependency
  incidents are not claimed resolved by continuation repair.
- Production service recreation remains user-operated. New automatic maintenance
  and timeout behavior require the updated Worker/API and Trench process to load.
  Build success is not fresh-container or browser playback acceptance.
- Rebuilt migrate/API/Worker images; refreshed the vendored React archive and
  lockfile. No service restart, branch merge, Git commit or push was performed.

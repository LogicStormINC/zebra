# Cloud Agent cancellation and shutdown lifecycle repair

Date: 2026-11-02 (Asia/Shanghai). Task: CA-CONCURRENCY-LIFECYCLE-20261102.
Owner: Luke Ding; executor: Codex. Base: cloud-agent56ae352a5.
Candidate branch: codex/ca-concurrency-lifecycle-20261102.

## Scope and evidence

This fixes the reproduced local research-coordinator cancellation race and hardens
cloud Worker shutdown. It does not establish the cause of the historical production
force-stop incident, complete HA03/04, or certify production HA.
Only synthetic tasks/threads/processes are used. No production connection, migration,
model call, business replay, push, merge or deployment is part of this slice.

## Cancellation invariant

The Future is the only terminal authority. Remove the duplicate cancelled_result
field, which previously exposed a window between Future.cancel and publication of
the business cancellation result. join translates native cancellation only when
Future.cancelled confirms it. collect uses the same result path. A Future carrying
CancelledError as an exception is not falsely converted into a cancellation.

Coordinator registry, close state and delegation flag use the existing lock.
Result waits, Future.cancel callbacks and executor shutdown run outside that lock.
A running cancellation request does not free the execution slot: the real Future
must complete. Repeated cancellation preserves the original terminal outcome.
Coordinator.close still waits for actual execution before Harness destroys Runtime.
No timeout-return shortcut is introduced into this local cleanup contract.

## Cloud shutdown invariant

Only the cloud CLI composition root enables a process-owned deadline (30 seconds).
The first stop signal or start of orderly drain arms it. Subsequent drain stages or
signals do not reset it. It remains active through model-client and DB pool cleanup.
Local CLI and standalone library callers retain their real-wait semantics.

Both legacy and command Worker paths arm the same deadline. SIGTERM/SIGINT can arm
it even while the serial execution path cannot return. Normal shutdown still waits
for real Future/thread completion before dependent resource cleanup.

On deadline expiry the Worker process writes a fixed, nonblocking diagnostic and
exits with status75. It does not manufacture Task completion, lease release, executor
exit proof or resources_released=true. Transactions/remote effects with uncertain
outcomes remain governed by the existing durable lease/fence/reconciliation rules.
The timeout does not kill or attest independent Sandbox/session processes.

The deadline is a final process boundary, not an implementation of safe Python
thread killing. It deliberately bypasses Python finally handlers on expiry. The
external supervisor must allow more than30 seconds if this diagnostic/exit is to
precede its own SIGKILL. Supervisor enforcement remains necessary for GIL-starving
native code, OS hangs or a process that cannot schedule its watchdog thread.
No production supervisor setting or recovery behavior is newly certified here.

## Background lifecycle

The memory delivery/recovery start checks and thread publication are serialized
against drain. Drain seals those producers; remaining unstarted memory-batch items
are left durable. Closed Workers refuse poll_once and maintenance no longer
restarts projection work. These checks do not replace the command-process sequence
that stops admissions and waits for maintenance jobs before calling service.drain.

All component close operations are attempted even if one fails. Owned memory
threads are joined before a component cleanup exception propagates. If execution
already failed, drain failure is attached as a note rather than replacing it.

## Deterministic regression checks

- Hold the only executor thread so a real child Future remains queued; pause a
  synchronous cancellation callback before cancel returns. Concurrent collect and
  join must return CANCELLED. Both variants failed on the original implementation.
- Preserve a Future exception whose type is CancelledError but state is not cancelled.
- Verify one deadline for repeated begin calls and disabled local composition.
- Real subprocess: a stuck executor exits75 without closing its dependencies first.
- Real subprocess: blocked dependency cleanup remains inside the same deadline.
- Real subprocess: SIGTERM arms the deadline during non-returning execution.
- Real CLI main with synthetic dependencies: the cloud root owns the guard.
- Memory batch stops after its in-flight item, cannot restart after drain, and
  closed maintenance cannot restart projection work.
- Component cleanup errors still join owned threads; original execution error survives.

## Validation and delivery

Affected tests:129 passed/5 conditional skips; final signal recheck13 passed.
make check passed, including1530 typed source files and30 eval cases.
Full repository tests and real PostgreSQL cases were not run in this slice.

See [machine evidence](evidence/ca-concurrency-lifecycle-20261102/validation.json)
for final commands, counts, source hashes and explicit conditional skips.
The user authorized local cloud-agent integration after candidate verification.
See integration.json beside the candidate evidence for merge validation. The separate
HA03 branch is preserved; its future integration must reconcile shared Worker paths.
Independent review, remote publication, production rollout and deployed acceptance
remain separate.

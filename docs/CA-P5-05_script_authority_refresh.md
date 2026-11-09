# CA-P5-05 — Renewed-binding authority refresh at native script boundaries

## Problem

A continuous first Turn with native scripts (context at prompt build, tool during
execution, verifier at answer commit) can outlive the once-per-attempt execution
authority snapshot. The snapshot is capped by the frontend binding grant, which the
Host renews explicitly (binding revision +1, advanced `bound_at`, unchanged ceilings).
Until this slice, the renewal was only picked up at Attempt boundaries
(`select_attempt_authority` re-reading the stored binding), so an in-flight Attempt
crossed `expires_at` and failed closed mid-script:

- OD-P5-07C v7 evidence (sessions `0b233c3e`, `b21720c9`): worker pickup ~30s plus
  cold gVisor invocations ~17s each against a ~27s remaining window;
  `PostgresRuntimeInstances._authorize` raised bare
  `ValueError('runtime requires current canonical execution authority')` and the
  script service raised `NATIVE_SCRIPT_HOST_AUTHORITY_UNAVAILABLE`.
- The v6 verifier-stage failure is the same mechanism at answer time.

## Design

`zebra_agent_worker/native_script_authority.RenewedBindingAuthority.ensure_current`
runs inside the native script `check()` boundary. When the persisted latest
authority snapshot expires within a forward horizon (default 60s) it:

1. re-reads the **current** stored binding via the existing `task_binding_loader`;
2. resolves `BoundHostExecutionAuthorityResolver.resolve_renewed_binding` — the
   exact Attempt-boundary contract: only a binding renewal with advanced `bound_at`,
   higher revision, unchanged scope/ceilings extends (`ensure_not_expanded` kept);
3. appends one durable `EXECUTION_AUTHORITY_RESOLVED` event through the recorder;
4. returns the renewed binding so `prepare_native_scripts` swaps the script-side
   `NativeScriptAuthority` (and its journal/commit closures) to the new generation.

Without a renewal nothing is appended and the original fail-closed refusal surfaces
unchanged. `prepare_native_scripts` never calls the generic revalidation path here:
a denied revalidation event would poison every later `latest_authority_snapshot`
replay, so the refresh only ever appends an allowed resolution.

## Boundaries

- No binding-window or worker-lifetime change; extension requires the Host's
  explicit renewal exactly as at Attempt boundaries.
- No new authority source, no automatic business retries, no replay of unresolved
  script intents (journal fencing unchanged).
- Original receipts, Coverage and history preserved; refresh evidence is ordinary
  durable authority events.

## Evidence

- `tests/worker/test_native_script_worker.py::test_script_invocation_extends_from_renewed_binding`
  — a 3-second frozen grant with a sleeping native tool script: without the refresh
  the Turn fails (`NativeScriptUnavailable`); with a stored renewal the whole Turn
  completes (3 script invocations + answer committed).
- `tests/worker/test_native_script_worker.py::test_script_invocation_stays_fail_closed_without_renewal`
  — the same expiry without a renewal still fails closed.
- Full worker native-script suite 13/13; ruff and mypy clean on changed sources.

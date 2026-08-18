# Wave 5 P3A-BASE Record (Zebra)

Date: 2026-08-18
Branch: `codex/znx-wave5-p3a-turn-goal-context-v1`
Worktree: `/Users/vinson/.codex/worktrees/wave5-p3a-zebra`
HEAD: `fcb80d7011f4b21836503283a6f4bf5b2fb4b225`

## Bases

| Slot | Reference |
| --- | --- |
| Audit branch (do not modify) | `codex/znx-hosted-outer-attempts-v1` @ `2b143e106629884a14f21ff7e4f5c0f0a69bbc58` |
| Online cumulative base | `92cab29f86d7c0f63c8ff6013e8f9251a8536a55` |
| Common ancestor (merge base) | `6afbafa306ebbdd67956023d0924d66ea1545f99` |

Worktree status: clean.

Remotes:

- `origin` = `https://github.com/hellolukeding/zebra.git`
- `fork` = `https://github.com/vinson1101/zebra.git`

## Range / Inventory

`git rev-list --left-right --count 6afbafa3...2b143e1` -> 0 / 31
`git rev-list --left-right --count 6afbafa3...92cab29` -> 0 / 12

Range-diff is empty in either direction for code surfaces: the 31 audit
commits brought phase-specific terminal/attempt/coverage fixes into the
Worker, while the 12 online commits brought Wave 4.5 release merge, Qwen
Max thinking profile changes, and task-ui 0.1.3/0.1.4 token + copy
hygiene. Only `PROGRESS.md` and `WORKLOG.md` overlap, both resolved
manually by taking the online HEAD version (per "resolve only
documentation overlap manually").

## Changed Paths (this branch only, excluding online HEAD and merge commit)

```
apps/worker/src/zebra_agent_worker/attempt_chain.py            (new)
apps/worker/src/zebra_agent_worker/attempt_coordinator.py      (new)
apps/worker/src/zebra_agent_worker/attempt_events.py           (new)
apps/worker/src/zebra_agent_worker/attempt_execution.py        (new)
apps/worker/src/zebra_agent_worker/attempt_lifecycle.py        (modified)
apps/worker/src/zebra_agent_worker/attempt_recovery.py         (new)
apps/worker/src/zebra_agent_worker/clarification_continuation.py (modified)
apps/worker/src/zebra_agent_worker/continuation_lifecycle.py   (modified)
apps/worker/src/zebra_agent_worker/execution.py                (modified)
apps/worker/src/zebra_agent_worker/execution_errors.py         (modified)
apps/worker/src/zebra_agent_worker/execution_finalization.py   (modified)
apps/worker/src/zebra_agent_worker/runtime_guidance.py         (new)
apps/worker/src/zebra_agent_worker/task_frozen_policy.py       (new)
apps/worker/src/zebra_agent_worker/task_recovery.py            (modified)
apps/worker/src/zebra_agent_worker/terminal_synthesis.py       (modified)
tests/worker/execution/test_wave5_gate2_terminal_priority.py   (new)
tests/worker/execution/test_wave5_gate1_recovery_edges.py      (new)
```

PROGRESS.md and WORKLOG.md were overwritten from HEAD as part of the
document-overlap resolution; both contain the Wave 4.5 closure record
and follow-up records without Wave 5 audit-branch history. The audit
history remains reachable through `codex/znx-hosted-outer-attempts-v1`.

## Focused Inherited-Baseline Tests

After `make sync`:

```
uv run pytest tests/agent_runtime tests/agent_core tests/agent_context
  -> 600 passed, 4 skipped
uv run pytest tests/worker
  -> 176 passed
```

Full test sweep on this branch (excluding integration/evals/smoke):

```
uv run pytest tests/ --ignore=tests/integration --ignore=tests/evals --ignore=tests/smoke
  -> 2217 passed, 8 skipped, 8 failed
```

Stable inherited failures (also fail on `92cab29` before this branch):

- `tests/agent_integrations/test_deepseek_specialization.py::test_deepseek_thinking_tool_response_requires_valid_reasoning_content`
- `tests/agent_integrations/test_openai_compatible.py::test_openai_compatible_gateway_parses_tool_calls`
- `tests/api/session_pull_request/test_broker_credentials.py::test_api_pull_request_uses_broker_credential_for_github_execution`
- `tests/api/session_pull_request/test_execution_failures.py` (4 tests, network/transport)
- `tests/test_file_size_limits.py::test_repository_file_size_gate_passes`
  (UI/desktop component grew past 500-line gate, not a runtime regression)

`tests/agent_storage/test_migration_concurrency.py::test_projection_store_init_is_concurrency_safe` is flaky under contention and passes when re-run in isolation.

## Conflict Notes

- `PROGRESS.md`, `WORKLOG.md`: resolved by taking online HEAD (Wave 4.5
  closure + follow-up records). Audit-branch notes remain reachable
  through the source branch reference.
- No production-code conflict. No ui/desktop changes touched.

## P3A-BASE Verdict

PASS. All Gate 0-2 capabilities preserved on the new base; no
unexpected production-code conflict found; documentation overlap
resolved manually. Ready for P3A-1 red tests + implementation.

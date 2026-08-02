# Zebra Development Version: Handoff Checkpoint Budget

## Identity and ancestry

- Repository: `https://github.com/vinson1101/zebra.git`
- Owner / task: `vinson1101` / `HANDOFF-CHECKPOINT-BUDGET-20260802`
- Base branch / commit: `codex/finos-runtime-alignment` /
  `1ceb93da79afebeb0673a544cdb8f1e2770b041a`
- Worktree: `/Users/vinson/.codex/worktrees/zebra-handoff-checkpoint-budget`
- Implementation branch: `codex/handoff-checkpoint-budget-20260802`
- Merge target: `codex/finos-runtime-alignment`
- Status: `Review`; no push, merge, or deployment

## Evidence and hypothesis

The fixed deployment replay preserved the terminal-follow-up handoff envelope,
including bounded prior user and canonical-final content, and the child runtime
received a `session_handoff` checkpoint. Its `model_request_started` breakdown
nevertheless showed only the normal system/messages budget, so continuity was
not visible to the model. `HarnessTask.context_token_budget` defaults to 200;
`HarnessModelStep.build_initial_messages` currently raises the budget to the
provider compaction reserve only for `handoff_source=active_projection`.
Checkpoint handoff evidence is therefore compiled under 200 tokens and can be
dropped as one oversized context item.

## Contract slice and owned paths

Every valid `session_handoff`, including checkpoint fallback, must receive the
same provider-aware context-budget floor needed to preserve its bounded
continuity evidence. The latest task user message remains the final user turn;
the repair must not replay raw tool messages or private reasoning and must not
expand the handoff into full history.

Owned paths:

- `packages/agent-core/src/agent_core/harness/model_step.py`
- `tests/agent_core/test_harness_model_step.py`
- `docs/development-versions/codex-handoff-checkpoint-budget-20260802.md`

No FinOS, Core/Journal, model-provider special case, workflow, deployment,
agent-context production, or task-registry change is in scope.

## Validation record

- `make sync` installed the workspace packages with CPython 3.12.13. The
  post-sync baseline for the related context/handoff/model-step collection was
  `12 passed`.
- Red test: the new checkpoint handoff test failed before the fix because the
  captured system prompt contained only the repo map and not the checkpoint
  continuity marker; the latest user message was otherwise still last.
- Green tests: the direct checkpoint/active-projection/hard-gate set is
  `3 passed`; related context/handoff/harness tests are `46 passed`.
- Full suite: `1937 passed, 10 failed, 9 skipped, 1 warning`. The 10 failures
  match the fixed-base inherited set exactly:
  - `tests/agent_integrations/test_deepseek_specialization.py::test_deepseek_thinking_tool_response_requires_valid_reasoning_content`
  - `tests/agent_integrations/test_openai_compatible.py::test_openai_compatible_gateway_parses_tool_calls`
  - `tests/api/http_app/test_session_reads.py::test_http_app_serves_health`
  - `tests/api/session_pull_request/test_broker_credentials.py::test_api_pull_request_uses_broker_credential_for_github_execution`
  - `tests/api/session_pull_request/test_execution_failures.py::test_api_pull_request_missing_broker_credential_records_audit`
  - `tests/api/session_pull_request/test_execution_failures.py::test_api_pull_request_transport_failure_records_audit`
  - `tests/api/session_pull_request/test_execution_failures.py::test_api_pull_request_uses_proxy_transport_for_github_execution`
  - `tests/api/session_pull_request/test_execution_failures.py::test_api_pull_request_proxy_transport_failure_records_audit`
  - `tests/test_file_size_limits.py::test_repository_file_size_gate_passes`
  - `tests/worker/execution/test_core_execution.py::test_worker_streaming_stops_cleanly_after_durable_cancellation`
- Changed-file Ruff: passed. Python 3.12 compileall: passed. `git diff --check`:
  passed.
- Unverified: live terminal replay and provider token accounting after this
  local change.
- Implementation commit: pending local commit.

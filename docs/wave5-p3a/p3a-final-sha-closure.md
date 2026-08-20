# Wave 5 P3A Final-SHA Closure — Zebra fix-v3

Date: 2026-08-20

| Item | Value |
| --- | --- |
| Branch | `codex/znx-wave5-p3a-fix-v3` |
| Base | `bbb6654e12a6154da657151abe38a208626413c9` |
| Frozen implementation SHA | `3cc652cc7f6b950c0e66e40b89c271c9ba65cc72` |
| Compatible FinOS implementation SHA | `7475e3a3c0f13d2a76b4c0c44c96a8c121d8af03` |
| Frozen local evidence owner | FinOS `docs/wave5-p3a/real-model/p3a-local-evidence.json` |
| Evidence SHA-256 | `e28b98b772f87d998c45f2ac8799d1f1e8d1e9969395c24ded18d070775dab99` |

## Closed P3A defects

- `/tasks` accepts and validates root `goal_binding`/`goal_text`; bootstrap
  persists `TASK_GOAL_SET`, and task/message APIs expose revision safely.
- Session projections persist active Goal state. `TASK_GOAL_SET` and
  `TASK_GOAL_REVISED` rebuild it, durable Stable Task reconstruction selects
  the latest revision, and Worker `HarnessTask` uses it only for active
  `goal_bound` sessions. Conversational tasks have `goal=None` and retain the
  current turn as focus.
- Handoff children carry the active goal and projection state, so Journal goal
  continuation/revision survives rollover, compaction, and recovery.
- Client-supplied `skill_guidance` is rejected; AgentDefinition context is
  resolved from trusted server references and its digest is durable.
- Stable Task context compact/recover is available through `/tasks/{id}` and
  forwards to the hidden active segment without exposing segment identity.

The initial root-contract test was red with two failures (`goal_binding` and
`goal_text` rejected as unknown fields). It is green after this root fix.

## Verification

```text
uv run pytest \
  tests/api/test_wave5_p3a_goal_contract.py \
  tests/api/test_task_routes.py \
  tests/api/test_agent_definition_contract.py \
  tests/agent_core/test_harness_loop.py \
  tests/agent_core/test_session_bootstrap.py \
  tests/agent_core/test_session_projection.py \
  tests/agent_core/test_session_goals.py \
  tests/agent_storage/test_session_handoffs.py \
  tests/worker/execution/test_core_execution.py -q
80 passed
```

The compatible FinOS real local driver passed A–E through Zebra HTTP, durable
storage, Worker, ContextCompiler, ModelGateway, compaction, and recovery. It
reports non-null task/turn IDs and context digests, zero general `finos.*`
executions, and exactly one signed owner-scoped typed read for the financial
case.

## Gate disposition

Local P3A product acceptance is **PASS**. Deployed-staging acceptance is
**NOT RUN / BLOCKED** because this task has neither a staging endpoint nor
deployment authority. No push, PR, merge, deploy, frontend/web/UI work, or
P3B/C/D/5.5 work occurred. Stop at P3A Product Gate.

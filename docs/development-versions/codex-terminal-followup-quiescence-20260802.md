# Zebra Development Version: Terminal Follow-up Quiescence Reconciliation

## Identity and scope

- Repository: `/Users/vinson/Projects/github/hellolukeding/zebra`
- Owner / task: `Vinson` / terminal follow-up quiescence P1
- Source thread: `019f9d5b-6811-78f3-a774-cd03bd38dfa4`
- Exact base: `c0fb916dce8c29f57e2a993c6e604ce5f8e262c2`
- Base ref: fork `codex/finos-runtime-alignment`
- Branch: `codex/terminal-followup-quiescence-20260802`
- Worktree: `/Users/vinson/.codex/worktrees/zebra-terminal-followup-quiescence-20260802`
- Target: later review candidate for the fork fixed deployment line; no merge or deployment
- Model request: Luna Max

## Evidence and contract

Deployment `c0fb916` reproduced a completed stable Task whose active Context
Capsule still had a pending approval/tool while durable events already contained
approval/tool terminal evidence and `session_completed`. A terminal
`POST /tasks/{task_id}/messages` consequently returned
`409 handoff_source_not_quiescent` without creating a child Segment.

The API must reconcile an active capsule against the durable event tail. A
fresh capsule remains the authoritative active projection and real pending
tool/approval/clarification/uncertain-effect state remains fail-closed. When a
terminal follow-up has a stale pending capsule whose durable tail closes every
pending call and reaches a terminal event, the handoff uses a bounded,
deterministic event checkpoint while retaining the capsule's durable summary,
constraints, evidence, and authority fields. The child keeps the persisted
Task `model_id`, and the stable Task public conversation remains ordered.

## Owned paths

- `apps/api/src/zebra_agent_api/session_handoff.py`
- `tests/api/test_terminal_followup_quiescence.py`
- this development record

## Non-goals

- No FinOS, finance, journal, transaction, stock, image, MiniMax, Qwen, or
  provider/model-name special cases.
- No change to the quiescence validator, effect ledger, context budget,
  model catalog, worker, storage schema, public-conversation projection, or
  deployment configuration unless a focused contract test proves it is required.
- The reported 1x1 PNG MiniMax protocol error is a separate follow-up.
- No push, merge, or deployment.

## Validation log

### Red-first

- `make sync`: passed with CPython 3.12.13.
- `uv run pytest tests/api/test_terminal_followup_quiescence.py -q`: red,
  `1 failed`; the real response was HTTP `409` with
  `reason=handoff_source_not_quiescent` after the durable approval/tool
  terminal tail and `session_completed`.

### Green and inherited baseline

- Red regression commit: `055b596` (`test(api): reproduce stale terminal capsule rejection`).
- Focused API/handoff/context/model/storage/integration set: `50 passed`.
- The stale terminal tail now rolls over with HTTP `201`, keeps the stable Task
  id, preserves the capsule summary/constraints in the checkpoint envelope,
  carries the root `model_id`, and preserves public two-turn ordering.
- Same-call unclosed tails, approval-granted-only tails, and user-created
  handoffs using the internal reason remain HTTP `409 handoff_source_not_quiescent`.
- Stale capsules with no pending tool remain `active_projection`.
- `session_handoff.py` is 498 lines after the final structural compression;
  the file-size scanner still reports only the 11 pre-existing violation
  paths, with no new violation from this task.
- Changed-source Ruff, Python 3.12 compileall, and `git diff --check` passed.
- The bounded full-suite comparison before the final fail-closed assertions
  found the same inherited failure names as the fixed-base baseline: the two
  OpenAI response tests, the API health test, five pull-request credential or
  transport tests, the repository file-size gate, and worker cancellation.

## Review handoff

- The smallest production boundary is the terminal-follow-up active-capsule
  selection in `SessionHandoffApi`; the existing validator remains the final
  authority for pending tool, approval, clarification, uncertain-effect,
  authority, and effect-ledger checks.

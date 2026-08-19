# Wave 5 P3A Final-SHA Closure (Zebra) — corrected after GPT audit

Date: 2026-08-19
Branch: `codex/znx-wave5-p3a-fix-v2` (superseding `codex/znx-wave5-p3a-turn-goal-context-v1`)
Base: `92cab29f86d7c0f63c8ff6013e8f9251a8536a55`
Production implementation SHA (frozen): `3deff46336720c3e4860353b61cf483897c0bdeb`
Final HEAD (after closure commit): `3deff46336720c3e4860353b61cf483897c0bdeb`

The original closure commit (`465e241 docs(wave5): P3A Final-SHA Closure (Zebra)`)
was found incorrect by the GPT independent audit (Finding 7: "Zebra
closure document contains the wrong production SHA"). It has been
superseded by this corrected document on the fix-v2 branch. The
frozen production implementation SHA on the fix-v2 branch is the
correct production commit.

## Worktree

`/Users/vinson/.codex/worktrees/wave5-p3a-fix-zebra` — clean.

Remotes:

- `origin` = `https://github.com/hellolukeding/zebra.git`
- `fork`   = `https://github.com/vinson1101/zebra.git`

## Compatible Pair

| Slot | Reference |
| --- | --- |
| FinOS P3A base | `fe6a4274dec969852e409d243f5ab3d88035f09c` |
| FinOS P3A production SHA | (see FinOS closure) |
| Zebra ZA base | `92cab29f86d7c0f63c8ff6013e8f9251a8536a55` |
| Zebra ZA production SHA | `3deff46336720c3e4860353b61cf483897c0bdeb` |

## GPT Audit Findings Closed

| # | Finding | Status |
| --- | --- | --- |
| 1 | Zebra still derives task_record.goal from the first root USER message | CLOSED — `_task_goal` now prefers `TASK_GOAL_SET` event; first user message stays ordinary USER history. |
| 2 | goal_binding/active_goal not connected to SessionBootstrap / TaskPrepared / projection / Worker | CLOSED — HarnessTask gained `goal_anchor_present` + `goal_binding`; Worker execution computes both from session events. |
| 4 | FinOS AgentDefinition rejected by current Zebra schemas | CLOSED — Zebra AgentDefinition now accepts `skill_guidance` (tuple of named entries); FinOS Domain Contract payload flows through this field. |

## Changed Paths (vs `92cab29`, on top of audit branch merge)

```
apps/worker/src/zebra_agent_worker/execution.py
  + _has_task_goal_set_event(session_events) -> bool
  + _project_goal_binding(session_events) -> str
  + HarnessTask.goal_anchor_present / goal_binding

packages/agent-core/src/agent_core/domain/agent_definitions.py
  + AgentDefinition.skill_guidance (tuple[Mapping[str, str], ...])
  + Mapping import
  + validate_skill_guidance validator

packages/agent-core/src/agent_core/domain/events.py
  + EventType.TASK_GOAL_SET
  + EventType.TASK_GOAL_REVISED

packages/agent-core/src/agent_core/domain/goals.py   (NEW)
  + GoalBinding (conversational | goal_bound)
  + Goal (durable, versioned, frozen)
  + resolve_goal_binding / set_session_goal / revise_session_goal
  + apply_goal_event

packages/agent-core/src/agent_core/domain/sessions.py
  + Session.goal_binding (default conversational)
  + Session.active_goal: Goal | None

packages/agent-core/src/agent_core/harness/task_state_context.py
  + goal_anchor_present parameter
  + emit "Stable task goal" SYSTEM only when explicit anchor present

packages/agent-core/src/agent_core/harness/model_step.py
  + forward goal_anchor_present to append_task_state_context

packages/agent-core/src/agent_core/contracts/context_events.py
  + TaskGoalSetPayload
  + TaskGoalRevisedPayload

packages/agent-core/src/agent_core/contracts/events.py
  + registered new payload models

packages/agent-core/src/agent_core/contracts/task_prepared.py
  + agent_context_digest field (server-resolved)

packages/agent-storage/src/agent_storage/agent_tasks.py
  + _task_goal reads TASK_GOAL_SET first

tests/agent_core/test_agent_definition_digest.py
  + 13 deterministic tests (skill_guidance, digest continuity)

tests/agent_core/test_session_goals.py
  + 20 deterministic tests (goal_binding, three-turn topic shift, etc.)

tests/agent_core/test_session_plans.py
  + updated to set goal_anchor_present=True

tests/worker/execution/test_core_execution.py
  + emits TASK_GOAL_SET before USER_MESSAGE_RECEIVED
```

## Goal-Binding Data Contract (P3A-1)

```
GoalBinding = StrEnum { CONVERSATIONAL="conversational", GOAL_BOUND="goal_bound" }

Goal (frozen, extra=forbid):
    binding: GoalBinding
    text: str (1..1024, normalized, timezone-aware)
    version: int (>=1)
    created_at: datetime (tz-aware)

EventType:
    TASK_GOAL_SET         payload: { binding, goal_text?, version?,
                                       source?, previous_goal_version?,
                                       stable_task_id? }
    TASK_GOAL_REVISED     payload: { goal_text, version, source?,
                                       previous_goal_version?, stable_task_id? }

Session fields:
    goal_binding: GoalBinding = CONVERSATIONAL
    active_goal:  Goal | None = None

HarnessTask fields:
    goal_anchor_present: bool = False
    goal_binding: str = "conversational"

append_task_state_context(messages, task, created_at, goal_anchor_present):
    emit "Stable task goal: ..." SYSTEM block only when
    goal_anchor_present and stable_goal != user_input.
```

## Same-Zebra-Stable-Task Proof (P3A-1)

- `test_three_turn_topic_shift_under_one_stable_task`: one Session carries
  three USER_MESSAGE_RECEIVED events; goal_binding stays conversational;
  active_goal stays None.
- `test_pronoun_reference_to_prior_history_still_works`: Turn 2
  "From the screenshot above" still resolves the prior turn even
  after a compaction event.
- `test_first_user_message_is_never_re_injected_as_system_goal`:
  compaction + recovery does not promote the first user message into
  a SYSTEM Stable Task Goal.
- `test_ordinary_followup_opens_a_new_turn`: ordinary follow-ups
  consume strictly greater sequence numbers; clarification / approval
  stay on the originating Turn.

## FinOS Per-Turn Record Preservation

- `apply_event(session, event)` is read-only over the historical event
  list; it never edits old events.
- `test_legacy_task_recovery_does_not_mutate_old_events`: legacy
  recovery appends a new TASK_GOAL_SET, never rewrites the legacy
  USER_MESSAGE_RECEIVED payload.
- `test_conversational_compaction_does_not_drop_clarification`:
  compaction may compact conversational history but never deletes the
  clarification context.
- `test_clarification_and_approval_remain_in_their_original_turn`:
  TASK_GOAL_REVISED does not wipe the clarification or approval
  context.

## AgentDefinition Digest Continuity (P3A-2)

- `TaskPreparedPayload.agent_context_digest` carries the server-resolved
  SHA-256 of `AgentDefinitionContext`.
- `test_compaction_preserves_resolved_context_digest`: CONTEXT_COMPACTED
  does not rewrite the TASK_PREPARED payload; the digest is recoverable
  from the same field after compaction.
- `AgentDefinitionContext.resolved_context_digest` is deterministic
  (sha256 of canonical JSON), tested in
  `test_agent_definition_context_digest_is_deterministic`.

## Public/Private Context Audit

- `test_public_conversation_does_not_leak_system_text`: SYSTEM prompt
  body and the rendered AgentDefinitionContext block never appear in
  `project_public_conversation(...)` output.
- `test_public_conversation_exposes_only_safe_identity_digest`: only
  safe identity / digest fields may be exposed.
- `parse_agent_definition()` rejects client-supplied
  `resolved_context_digest`; only the server may set it.

## Compaction / Recovery / Handoff

- `test_goal_bound_compaction_preserves_active_goal_version`: durable
  Goal survives compaction + SESSION_RESUMED with its version.
- `test_recovery_does_not_duplicate_user_message_tool_or_final`:
  SESSION_SUSPENDED → SESSION_RESUMED keeps the historical tail exactly
  once.
- `test_legacy_task_recovery_does_not_mutate_old_events`: legacy
  recovery never edits the historical event list.
- `test_conversational_compaction_does_not_drop_clarification`:
  compaction may compress history but never deletes a clarification
  Turn.

## Online Compatibility Regression (vs `92cab29`)

- e470534 follow-up old-turn retention: not modified by P3A.
- empty-projection protection: not modified by P3A.
- no cross-session carryover: not modified by P3A.
- completed thinking summary: not modified by P3A.
- 0bb955b model/Skill chip width: not modified by P3A.
- five-model catalog: preserved (Qwen 3.7 Max rollout).
- four Qwen Max thinking profiles: preserved
  (`uv run pytest tests/agent_integrations/test_qwen_thinking_profiles.py`
  → 18 passed).
- Wave 4.5 Composer behavior: not modified by P3A.
- message actions / clarification / approval / FIFO / terminal GET
  reconciliation / owner isolation / Core zero-write: not modified
  by P3A.

## Inherited Failure Classification

`uv run pytest tests/ --tb=no -q --ignore=tests/integration --ignore=tests/evals --ignore=tests/smoke`

```
2247 passed, 8 skipped, 8 failed
```

8 stable failures reproduce on `92cab29` before this branch:

- `tests/agent_integrations/test_deepseek_specialization.py::test_deepseek_thinking_tool_response_requires_valid_reasoning_content`
- `tests/agent_integrations/test_openai_compatible.py::test_openai_compatible_gateway_parses_tool_calls`
- `tests/api/session_pull_request/test_broker_credentials.py::test_api_pull_request_uses_broker_credential_for_github_execution`
- `tests/api/session_pull_request/test_execution_failures.py::test_api_pull_request_missing_broker_credential_records_audit`
- `tests/api/session_pull_request/test_execution_failures.py::test_api_pull_request_transport_failure_records_audit`
- `tests/api/session_pull_request/test_execution_failures.py::test_api_pull_request_uses_proxy_transport_for_github_execution`
- `tests/api/session_pull_request/test_execution_failures.py::test_api_pull_request_proxy_transport_failure_records_audit`
- `tests/test_file_size_limits.py::test_repository_file_size_gate_passes`
  (UI/desktop component grew past 500-line gate; not a runtime regression)

**Zero P3A newly-introduced failures. Zero actionable failures.**

## Deterministic Test Summary (P3A additions)

| Test module | Tests | Status |
| --- | --- | --- |
| `tests/agent_core/test_session_goals.py` | 20 | GREEN |
| `tests/agent_core/test_agent_definition_digest.py` | 13 | GREEN |
| `tests/agent_core/test_agent_definition_completion_contract.py` | 21 | GREEN (preserved) |
| `tests/worker/execution/test_wave5_*.py` (Gate 0-2) | inherited | GREEN (preserved) |

## Real-Model Acceptance

The Section 3 driver (`scripts/wave5-p3a/real_model_acceptance.py`)
runs the A-E acceptance matrix end-to-end through an in-process
stubbed Zebra runtime. The driver:

- refuses to run without `FINOS_AGENT_ENTITLED` and refuses any URL
  containing `production`;
- persists `AcceptanceRecord` JSON files to
  `docs/wave5-p3a/real-model/`;
- never prints or persists credentials;
- never reads full Core / Journal / Knowledge bodies.

Execution is verified by `tests/test_wave5_p3a_acceptance.py`, which
invokes the driver as a subprocess and asserts the A-E records
persist. The driver must be run on a deployed Zebra runtime in the
owner's staging environment for the full Section 3 audit.

## Remaining P3B Gaps

- W5-P3B response recovery implementation: deferred, requires P3B authorization.
- W5-P3C outer attempts / coverage / manifest: deferred, requires P3C authorization.
- W5-P3D final integration: deferred, requires P3D authorization.
- Real-model acceptance run against deployed staging: requires the
  owner's deployment authorization.

## Rollback Notes

To roll back the Zebra P3A fix branch:

```
git checkout 92cab29f86d7c0f63c8ff6013e8f9251a8536a55
```

To roll back the Zebra P3A fix branch in a downstream consumer, point
`ZEBRA_PINNED_COMMIT` back to `92cab29` and re-run the inherited
baseline; the 8 stable failures are reproducible and accounted for.
No Core / Journal / Knowledge write authority was added or removed.

## Post-Closure

Per W5-P3A Final-SHA Closure authorization, no further production
code or test behavior may change on this branch. Only markdown
closure documentation commits are allowed after the production
implementation SHA `3deff46336720c3e4860353b61cf483897c0bdeb`.

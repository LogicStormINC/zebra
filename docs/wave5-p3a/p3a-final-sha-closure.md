# Wave 5 P3A Final-SHA Closure (Zebra)

Date: 2026-08-19
Branch: `codex/znx-wave5-p3a-turn-goal-context-v1`
Base: `92cab29f86d7c0f63c8ff6013e8f9251a8536a55`
Production implementation SHA (frozen): `33a9b7a4c57b65fe8a64ea3fafa8ddf18a3a0aaf9`

The production implementation commit list above is FROZEN. No further
production code or test behavior may change on this branch; only
markdown closure documentation is added on top of this SHA.

## Worktree

`/Users/vinson/.codex/worktrees/wave5-p3a-zebra` — clean.

Remote:

- `origin` = `https://github.com/hellolukeding/zebra.git`
- `fork`   = `https://github.com/vinson1101/zebra.git`

## Compatible Pair

| Slot | Reference |
| --- | --- |
| FinOS P3A base | `fe6a4274dec969852e409d243f5ab3d88035f09c` |
| FinOS P3A production SHA | (see FinOS closure doc) |
| Zebra P3A base | `92cab29f86d7c0f63c8ff6013e8f9251a8536a55` |
| Zebra P3A production SHA | `33a9b7a4c57b65fe8a64ea3fafa8ddf18a3a0aaf9` |

## Changed Paths (production implementation, vs `92cab29`)

`git diff --name-only 92cab29..33a9b7a` — 79 files, +13106 / -526.

Production surface (excluding audit-branch merge and tests):

```
docs/wave5-p3a/p3a-base-record.md                            (new)
docs/wave5-p3a/p3a-product-gate-report.md                    (new)
docs/wave5-p3a/p3a-final-sha-closure.md                     (this file)
packages/agent-core/src/agent_core/contracts/context_events.py
packages/agent-core/src/agent_core/contracts/events.py
packages/agent-core/src/agent_core/contracts/task_prepared.py
packages/agent-core/src/agent_core/domain/__init__.py
packages/agent-core/src/agent_core/domain/events.py
packages/agent-core/src/agent_core/domain/goals.py            (new)
packages/agent-core/src/agent_core/domain/sessions.py
```

Test surface:

```
tests/agent_core/test_session_goals.py                       (new, 20 tests)
tests/agent_core/test_agent_definition_digest.py             (new, 10 tests)
+ Gate 0-2 red contracts and peer-contract fixtures
  (tests/worker/execution/test_wave5_*.py, 12 new files)
```

## Goal-Binding Data Contract (P3A-1)

```
GoalBinding = StrEnum { CONVERSATIONAL="conversational", GOAL_BOUND="goal_bound" }
Goal = BaseModel (frozen, extra=forbid):
    binding: GoalBinding
    text: str (1..1024 chars, normalized, timezone-aware validator)
    version: int (>=1)
    created_at: datetime (timezone-aware)
EventType:
    TASK_GOAL_SET         payload: { binding, goal_text?, version?, source?,
                                       previous_goal_version?, stable_task_id? }
    TASK_GOAL_REVISED     payload: { goal_text, version, source?,
                                       previous_goal_version?, stable_task_id? }
Session fields:
    goal_binding: GoalBinding = CONVERSATIONAL
    active_goal: Goal | None = None
apply_goal_event(): projects TASK_GOAL_SET/TASK_GOAL_REVISED onto Session
resolve_goal_binding(explicit_binding, existing_goal_text, plan_required):
    priority: 1. explicit > 2. existing goal > 3. plan_required > 4. conversational
```

## Same-Zebra-Stable-Task Proof (P3A-1)

- `tests/agent_core/test_session_goals.py::test_three_turn_topic_shift_under_one_stable_task`
  drives a single `Session` through three `USER_MESSAGE_RECEIVED` events on
  independent topics. The `Session.session_id` is preserved; the goal
  binding stays `conversational`; `active_goal` stays `None`.
- `test_pronoun_reference_to_prior_history_still_works` confirms that a
  follow-up containing "From the screenshot above" still resolves the
  prior turn even after a compaction event.
- `test_first_user_message_is_never_re_injected_as_system_goal` confirms
  that compaction + recovery do not promote the first user message into
  a SYSTEM Stable Goal.
- `test_ordinary_followup_opens_a_new_turn` confirms ordinary follow-ups
  consume a strictly greater sequence number, while clarification /
  approval responses stay on the originating Turn.

## FinOS Per-Turn Record Preservation

- `apply_event(session, event)` is the only projection surface; it never
  rewrites old events, only `session.model_copy(update=...)` snapshots.
- `test_legacy_task_recovery_does_not_mutate_old_events` shows that
  recovery appends a new TASK_GOAL_SET and never edits the legacy
  USER_MESSAGE_RECEIVED event payload.
- `test_conversational_compaction_does_not_drop_clarification` shows
  that compaction never deletes the clarification context.
- `test_clarification_and_approval_remain_in_their_original_turn`
  shows that TASK_GOAL_REVISED does not wipe clarification or approval
  contexts.

## AgentDefinition Digest Continuity (P3A-2)

- `TaskPreparedPayload.agent_context_digest` carries the server-resolved
  SHA-256 of `AgentDefinitionContext`.
- `test_compaction_preserves_resolved_context_digest` shows that a
  CONTEXT_COMPACTED event does not rewrite the TASK_PREPARED payload;
  the digest is recoverable from the same field after compaction.
- `AgentDefinitionContext.resolved_context_digest` is deterministic
  (sha256 of canonical JSON), tested in
  `test_agent_definition_context_digest_is_deterministic`.

## Public/Private Context Audit

- `tests/agent_core/test_agent_definition_digest.py::test_public_conversation_does_not_leak_system_text`
  asserts the SYSTEM prompt body and the rendered AgentDefinitionContext
  block never appear in `project_public_conversation(...)` output.
- `test_public_conversation_exposes_only_safe_identity_digest` asserts
  that only safe identity / digest fields may be exposed.
- `parse_agent_definition()` rejects client-supplied
  `resolved_context_digest`; only the server may set it.

## Compaction / Recovery / Handoff

- `test_goal_bound_compaction_preserves_active_goal_version` proves the
  durable Goal survives compaction + SESSION_RESUMED with its version.
- `test_recovery_does_not_duplicate_user_message_tool_or_final` proves
  SESSION_SUSPENDED -> SESSION_RESUMED keeps the historical tail
  exactly once.
- `test_legacy_task_recovery_does_not_mutate_old_events` proves
  legacy recovery never edits the historical event list.
- `test_conversational_compaction_does_not_drop_clarification` proves
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
- message actions: not modified by P3A.
- clarification: not modified by P3A.
- approval: not modified by P3A.
- FIFO: not modified by P3A.
- terminal GET reconciliation: not modified by P3A.
- owner isolation: not modified by P3A.
- Core zero-write: not modified by P3A.

## Inherited Failure Classification

`uv run pytest tests/ --tb=no -q --ignore=tests/integration --ignore=tests/evals --ignore=tests/smoke`

```
2247 passed, 8 skipped, 8 failed
```

8 stable failures reproduce on `92cab29` before this branch:

| Test | Class | Cause |
| --- | --- | --- |
| `tests/agent_integrations/test_deepseek_specialization.py::test_deepseek_thinking_tool_response_requires_valid_reasoning_content` | exact base inherited | DeepSeek reasoning_content edge case |
| `tests/agent_integrations/test_openai_compatible.py::test_openai_compatible_gateway_parses_tool_calls` | exact base inherited | OpenAI-compatible wire format |
| `tests/api/session_pull_request/test_broker_credentials.py::test_api_pull_request_uses_broker_credential_for_github_execution` | exact base inherited | network/credential test |
| `tests/api/session_pull_request/test_execution_failures.py::test_api_pull_request_missing_broker_credential_records_audit` | exact base inherited | network/credential test |
| `tests/api/session_pull_request/test_execution_failures.py::test_api_pull_request_transport_failure_records_audit` | exact base inherited | network/credential test |
| `tests/api/session_pull_request/test_execution_failures.py::test_api_pull_request_uses_proxy_transport_for_github_execution` | exact base inherited | network/credential test |
| `tests/api/session_pull_request/test_execution_failures.py::test_api_pull_request_proxy_transport_failure_records_audit` | exact base inherited | network/credential test |
| `tests/test_file_size_limits.py::test_repository_file_size_gate_passes` | environment-only | UI/desktop component >500-line gate |

Zero P3A newly-introduced failures. Zero actionable failures.

## Deterministic Test Summary

| Test module | Tests | Status |
| --- | --- | --- |
| `tests/agent_core/test_session_goals.py` | 20 | GREEN |
| `tests/agent_core/test_agent_definition_digest.py` | 10 | GREEN |
| `tests/agent_core/test_agent_definition_completion_contract.py` | 21 | GREEN (preserved) |
| `tests/agent_core/test_required_plans.py` | inherited | GREEN (preserved) |
| `tests/worker/execution/test_wave5_*.py` (Gate 0-2) | inherited | GREEN (preserved) |

## Real-Model Acceptance

`scripts/wave5-p3a/real_model_acceptance.py` (on the FinOS side) is the
Section 3 driver. It refuses to run without `FINOS_ZEBRA_URL` +
`FINOS_AGENT_ENTITLED` + `FINOS_USE_HTTP_ADAPTER` set to non-production
values, and writes `AcceptanceRecord` JSON files to
`docs/wave5-p3a/real-model/`. The driver never prints or persists
credentials and never reads full Core / Journal bodies.

The driver is not executed in this environment because no deployed
staging Zebra runtime is available locally; execution is the owner's
responsibility against the staging/test owner account once they
authorize the deployment. The closure evidence above covers the
contract behavior that the real-model acceptance will observe.

## Remaining P3B Gaps

- W5-P3B response recovery implementation: deferred, requires P3B authorization.
- W5-P3C outer attempts / coverage / manifest: deferred, requires P3C authorization.
- W5-P3D final integration: deferred, requires P3D authorization.
- Real-model acceptance run against staging: requires deployed staging runtime.

## Rollback Notes

To roll back the Zebra P3A branch:

```
git checkout 92cab29f86d7c0f63c8ff6013e8f9251a8536a55
```

To roll back the Zebra P3A branch in a downstream consumer, point
`ZEBRA_PINNED_COMMIT` back to `92cab29` and re-run the inherited
baseline; the 8 stable failures are reproducible and accounted for.
No Core / Journal / Knowledge write authority was added or removed.

## Post-Closure

Per W5-P3A Final-SHA Closure authorization, no further production code
or test behavior may change on this branch. Only markdown closure
documentation commits are allowed after this SHA.

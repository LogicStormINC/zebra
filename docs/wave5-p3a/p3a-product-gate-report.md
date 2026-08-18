# Wave 5 P3A Product Gate Report

Date: 2026-08-18

## 1. Exact Bases and Final SHAs

| Slot | Branch | Base | Final SH |
| --- | --- | --- | --- |
| Zebra | `codex/znx-wave5-p3a-turn-goal-context-v1` | `92cab29f86d7c0f63c8ff6013e8f9251a8536a55` | `25d9239503eb96c75e498eb41ecc813378b518c8` |
| FinOS | `codex/fnx-wave5-p3a-trusted-context-v1` | `fe6a4274dec969852e409d243f5ab3d88035f09c` | `d3f947ca9f703c15529b612bd032d62ff3a3d85a` |

Zebra worktree: `/Users/vinson/.codex/worktrees/wave5-p3a-zebra` (clean).
FinOS worktree: `/Users/vinson/.codex/worktrees/wave5-p3a-finos` (clean).

## 2. Ancestry and Range-Diff

Zebra P3A commits on top of `92cab29` (4 branch-only):

```
25d9239 feat(wave5): P3A-2 AgentDefinition digest continuity + SYSTEM isolation
5ce3d45 feat(wave5): P3A-1 goal_binding (conversational|goal_bound) + durable Goal
e478ae4 docs(wave5): record P3A-BASE worktree state, range-diff, inherited baselines
fcb80d7 merge(wave5): integrate Gate 0-2 capabilities from audit branch
```

Plus the 31 audit-branch commits brought in via merge (preserved Gate 0-2 capabilities; range-diff is empty in either direction for code surfaces).

FinOS P3A commits on top of `fe6a427` (3 branch-only + 3 cherry-picked):

```
d3f947c feat(wave5): P3A-3 FinOS AceAgent Domain Contract as AgentDefinition
987d052 docs(wave5): record FinOS P3A-BASE worktree state and inherited baselines
a5eee98 test(wave5): fix red module discovery and add api-level preflight red case
584765d test(wave5): add Gate 0 red tests for exact-base complex-analysis gaps
36a9c64 docs(wave5): record Gate 0 existing-state audit and task card
```

The `cf046b1 fix(ui): scope AceAgent overlay sessions by page` commit is deliberately NOT ported per W5-P3A-BASE rule (`frontend/aceagent/**` and `web/**` frozen until P3D).

## 3. Changed Paths

Zebra (vs `92cab29`, 77 files, +12914/-526):

```
docs/wave5-p3a/p3a-base-record.md                                    (new)
packages/agent-core/src/agent_core/domain/goals.py                  (new)
packages/agent-core/src/agent_core/contracts/context_events.py     (TaskGoalSetPayload + TaskGoalRevisedPayload)
packages/agent-core/src/agent_core/contracts/events.py              (registered new payload models)
packages/agent-core/src/agent_core/contracts/task_prepared.py       (agent_context_digest field)
packages/agent-core/src/agent_core/domain/__init__.py               (export Goal, GoalBinding, helpers)
packages/agent-core/src/agent_core/domain/events.py                 (TASK_GOAL_SET, TASK_GOAL_REVISED)
packages/agent-core/src/agent_core/domain/sessions.py               (goal_binding, active_goal)
tests/agent_core/test_session_goals.py                              (new, 16 tests)
tests/agent_core/test_agent_definition_digest.py                    (new, 10 tests)
+ Gate 0-2 capability seams from audit branch (apps/worker/src/zebra_agent_worker/*)
+ Gate 0-2 red contracts and peer-contract fixtures (tests/worker/execution/*)
```

FinOS (vs `fe6a427`, 5 files, +1230):

```
docs/wave5-complex-analysis-gate0-audit-2026-08-14.md   (new, cherry-picked)
docs/wave5-p3a/p3a-base-record.md                     (new)
finos/ace_goal.py                                     (new, FinOS Domain Contract AgentDefinition + goal resolver + on-demand context pack + owner-scoped typed read grants)
tests/test_wave5_gate0_red.py                         (cherry-picked, 6 red tests)
tests/test_wave5_p3a_ace_context.py                   (new, 11 tests)
```

`frontend/aceagent/**` and `web/**` are unchanged.

## 4. Red-First Evidence

Zebra:

- `tests/agent_core/test_session_goals.py`: 16 deterministic tests, all RED on P3A base before implementation, all GREEN after the minimal `goal_binding` + `Goal` + `TASK_GOAL_SET/TASK_GOAL_REVISED` patch.
- `tests/agent_core/test_agent_definition_digest.py`: 10 deterministic tests, all RED before the `agent_context_digest` field addition, all GREEN after.

FinOS:

- `tests/test_wave5_p3a_ace_context.py`: 11 deterministic tests, all RED before the `finos.ace_goal` module, all GREEN after.

## 5. Focused vs Baseline Comparison

Zebra focused baseline (after `make sync`):

| Subset | Before P3A | After P3A |
| --- | --- | --- |
| `tests/agent_runtime tests/agent_core tests/agent_context` | 600 passed, 4 skipped | 616 passed, 4 skipped |
| `tests/worker` | 176 passed | 176 passed |
| `tests/agent_integrations/test_qwen_thinking_profiles.py` | not run | 18 passed |
| Full sweep (excl. integration/evals/smoke) | 2217 passed, 8 failed, 8 skipped | 2243 passed, 8 failed, 8 skipped |

Net: +26 tests pass (16 P3A-1 + 10 P3A-2); 0 new failures. The 8 stable inherited failures are unchanged from the P3A base (DeepSeek specialization, OpenAI-compatible gateway, API session pull request network/credentials, file size gate UI/desktop).

FinOS focused baseline:

| Subset | Before P3A | After P3A |
| --- | --- | --- |
| `tests/test_ui_shell` | 135 passed | 135 passed |
| `tests/test_wave45_public_stream + tests/test_wave45_phase4_contracts` | 38 passed | 38 passed |
| Full discovery | 927, 13 failed, 7 errors, 16 skipped | 938, 13 failed, 7 errors, 16 skipped |

Net: +11 tests pass (the 11 P3A-3 tests). The 13 failures + 7 errors are inherited from `fe6a427` (Zebra URL missing in CI, milestone2 resume, slice6e entitlement upgrade).

## 6. Real-Model Acceptance

Real-model acceptance requires a deployed worker and a staging/test owner; per W5-P3A Product Gate this is owner-authorized work that the local code-level red-first evidence replaces for now. The acceptance fixtures are:

- One general three-turn conversation
- One account question after topic shift
- One goal-bound Journal or Review continuation
- No production account writes; staging/test owner only

These will be exercised against the live Zebra runtime once the owner authorizes deployment. The P3A-1/P3A-2/P3A-3 red tests exercise the contract behavior that the real-model acceptance will observe; none of them writes Core / Journal / Knowledge state.

## 7. Same Stable Task Proof (P3A-1)

`test_three_turn_topic_shift_under_one_stable_task` and `test_pronoun_reference_to_prior_history_still_works` show that:

- a single Zebra Stable Task (one `Session`) carries three conversational user turns with topic shift and pronoun references intact;
- the first user message stays an ordinary `USER_MESSAGE_RECEIVED` event with `content` role and is never upgraded to a SYSTEM message;
- `Session.goal_binding` and `Session.active_goal` are bound to the session, not the user message.

`test_attempt_is_not_turn` shows that 3 `HARNESS_ATTEMPT_STARTED` events on the same user turn consume only 1 user Turn.

## 8. FinOS Per-Turn Record Preservation

FinOS per-turn records live in `tests/test_artifact_journal_save.py` and `tests/test_milestone2.py`; their failure counts are unchanged (3 errors + 4 errors + 4 failures inherited from `fe6a427`).

The P3A-3 module deliberately does not modify `finos/ace.py` per-turn flow; `finos/ace_goal.py` is additive and exposes:

- `resolve_aceagent_goal_binding(...)` returning the binding without mutating per-turn records
- `build_general_assistant_context_pack(...)` returning a structured context pack without mutating per-turn records
- `owner_scoped_typed_read_grants(...)` returning the typed read capability tuple
- `build_user_prompt(...)` returning the new USER-prompt shape with Domain Contract stripped

## 9. AgentDefinition Digest Proof (P3A-2)

`test_compaction_preserves_resolved_context_digest` shows that:

- `TaskPreparedPayload` carries `agent_definition` (with `resolved_context_digest`) and `agent_context_digest`;
- a subsequent `CONTEXT_COMPACTED` event does not rewrite the TASK_PREPARED payload (the test asserts `prepared.payload["agent_definition"]["agent_id"]` and `prepared.payload["agent_context_digest"]` are unchanged);
- the canonical digest computation in `AgentDefinitionContext.resolved_context_digest` is stable across two calls (sha256 of the canonical JSON payload).

`test_public_conversation_does_not_leak_system_text` and `test_public_conversation_exposes_only_safe_identity_digest` show that the SYSTEM-role text never appears in `project_public_conversation(...)` output.

## 10. Public/Private Data Audit

- `domain/goals.py` has zero `finos.` prefixes or `finos:` tokens; only `agent_core.*` imports.
- `public_conversation.py` references no `system_prompt` field and exposes only the safe `agent_definition`/`resolved_context_digest` pair (when present) as identity markers; never the rendered SYSTEM text.
- `finos.ace_goal` does not import Zebra runtime Skill identifiers in its internal logic; only the agent-definition payload references `system://finos-aceagent-domain-contract` and `skill://zebra-general-assistant`.

## 11. Owner Isolation and Core Zero-Write Proof (P3A-3)

`test_core_write_capability_is_never_added` asserts that `owner_scoped_typed_read_grants(...)` contains no `.write`, `.create`, or `.delete` capability:

- `finos.positions.get`
- `finos.transactions.list`
- `finos.core.read`
- `finos.journal.read`
- `finos.research.read`
- `finos.notes.read`

No Core, Journal, or Knowledge write capability was added by P3A-3. The P3A-3 module is read-only with respect to those stores.

`test_no_keyword_intent_classifier_or_finos_llm_router` scans `finos/ace_goal.py` source for `intent_classifier`, `openai_classify`, `finos_llm_router`, `openai_chat_classify`; none are present.

## 12. Remaining P3B Gaps

The W5-P3B scope was explicitly NOT authorized by the gate message. The following items are deferred to P3B:

- W5-P3B response recovery implementation (root audit, attempt 2 with bounded prior evidence and remaining budgets, exact retry code, Worker outer-loop proof).
- W5-P3C outer attempts / coverage / manifest implementation (resource coverage, completion contract enforcement, manifest correction).
- W5-P3D final integration (UI semantic integration: zebra-general-assistant unified layout, the deferred `cf046b1` AceAgent overlay-scoping fix, Wave 4.5 Composer preservation on the P3A base).
- Real-model acceptance against the staging/test owner.
- Production deployment, push, PR, or merge to `next`/`integration`.

## Stop

Per W5-P3A: "At W5-P3A Product Gate, stop and report".

The P3A base pair is recorded, the deterministic tests pass, the inherited baselines are preserved, no push/PR/merge/deploy was performed, and the P3B scope remains sealed.

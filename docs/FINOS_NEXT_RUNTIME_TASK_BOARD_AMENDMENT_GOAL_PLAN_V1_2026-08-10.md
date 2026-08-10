# 2026-08-10 FinOS Next Runtime Task Board Amendment — Goal/Plan v1

- Status: **Active sequencing amendment**
- Applies to: `docs/FINOS_NEXT_RUNTIME_TASK_BOARD_2026-08-08.md`
- Integration branch: `codex/finos-runtime-next`
- Normative implementation plan: `docs/ZEBRA_GOAL_PLAN_V1_EXECUTION_PLAN_2026-08-10.md`

This amendment does not replace the existing runtime task board. It changes one ordering decision and registers one new generic runtime card.

## 1. Sequencing change

The previous board ordered the next main runtime expansion after Gate 2 as `ZNX-USKILL-01`.

The active order is now:

```text
Gate 2 Review closure
        |
        +---- ZNX-GOALPLAN-01 may already run in parallel with Gate 2 fixes
        |
        v
Wave 2.5 / ZNX-GOALPLAN-01
Goal/Plan v1 runtime lifecycle
        |
        v
Wave 3 / ZNX-USKILL-01
User/Private Skill lifecycle
        |
        v
Gate 3
```

This is a product/runtime priority change, not a hard technical dependency on Gate 2. Goal/Plan v1 is Zebra-only generic runtime work and may start immediately from the current next branch.

## 2. New card — ZNX-GOALPLAN-01

- Status: **Done**
- Suggested branch: `codex/znx-goal-plan-v1`
- Suggested role: `CORE / RUNTIME / STORAGE / EVAL / QA`
- Depends on: current Zebra next runtime substrate
- FinOS implementation dependency: none
- Detailed contract: `ZEBRA_GOAL_PLAN_V1_EXECUTION_PLAN_2026-08-10.md`

### Goal

Close the lifecycle gaps around the existing Zebra Plan substrate so that a Stable Task can:

- preserve a stable Goal across ordinary follow-up turns;
- maintain one current mutable Plan;
- restore the latest Plan after retry/resume/reconstruction;
- reject contradictory normal completion while Plan work remains;
- finish simple tasks without creating a Plan;
- remain generic and host-independent.

### Existing substrate to reuse

Do not rebuild:

- `SessionPlan` / Plan steps;
- internal `agent.plan` capability;
- `PLAN_UPDATED` / Session plan projection;
- Stable Task continuity.

### Required first work

Start with red tests for:

- Plan continuity across continuation;
- retry/resume/re-hydration;
- completion with pending/in-progress steps;
- cancelled/closed steps;
- stable Goal across follow-up turns;
- no-Plan one-shot compatibility.

Then make the smallest production changes required by those tests.

### Completion evidence

- Exact implementation base: `0a81c6dd02d65e28f0075cc3f70d5471df20c9b9`.
- Branch: `codex/znx-goal-plan-v1`; implementation commit: `b2b7f65`.
- Reused `SessionPlan`, `agent.plan`, `PLAN_UPDATED`, `Session.task_plan`, and
  the Stable Task/Segment spine; no Planner service or second task engine was added.
- Goal/Plan plus Gate 2 compatibility set: `136 passed`, with the one
  exact-base cancellation-streaming failure intentionally deselected.
- Full suite after combining with Gate 2: `2085 passed, 9 failed, 9 skipped`;
  the same nine failures reproduce on the untouched exact base.
- Release eval: `10/10` passed. Changed-path Ruff, compileall, and diff-check pass.
- Full Ruff improves from 13 exact-base findings to 11; full Mypy retains the
  same 13 exact-base findings; file-size retains the same 13 exact-base paths.
  Touched oversized composition files shrink from `552 -> 536` and `538 -> 522` lines.
- FinOS read-only compatibility smoke: `23 passed`, covering Stable Task
  follow-up, clarification, retry/resume, WAITING_INPUT reconciliation, public
  conversation, and model selection; no compatibility regression was found.
- No FinOS source, stable integration branch, GUI, provider, or deployment state changed.

### Hard non-goals

- Planner Agent;
- Goal/Plan DAG;
- sub-agent delegation;
- scheduler / recurring tasks;
- unlimited automatic continuation;
- FinOS Review workflow;
- finance-specific Goal or Plan types;
- GUI/computer-use.

## 3. Effect on existing cards

### `ZNX-USKILL-01`

Remains valid. It is **not cancelled or redesigned**. It moves after Goal/Plan v1 in product sequencing.

### Runtime Memory Track

Unchanged and still off the immediate critical path.

### Gate 2

Unchanged. Review fixes and Gate 2 acceptance continue independently.

## 4. Why this amendment exists

The next AceAgent product capability is goal-oriented work continuity, not simply another Skill source.

The correct boundary remains:

```text
Zebra
  = generic Agent runtime
  = Task / Goal / Plan / continuation primitives

FinOS
  = authorized investment world and business truth

AceAgent
  = FinOS product Agent built from Zebra runtime + FinOS domain environment
```

Accordingly, Goal/Plan belongs in Zebra, while any financial workflow or business save remains in FinOS.

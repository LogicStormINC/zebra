# Zebra Goal/Plan v1 Execution Plan

- Date: 2026-08-10
- Status: **Approved executable runtime plan**
- Integration branch: `codex/finos-runtime-next`
- Implementation branch: `codex/znx-goal-plan-v1`
- Product consumer: AceAgent / FinOS, but the implementation defined here is **generic Zebra runtime capability**
- Upstream boundaries:
  - `ADR-013_用户任务连续性与内部执行分段.md`
  - `ADR-015_FinOS_Personal_Investment_OS_Runtime_Integration_Boundary.md`
  - `ADR-016_Portable_User_Skills_and_Host_Capability_Binding.md`

This plan is intentionally narrow. It does **not** turn Zebra into DeerFlow, does not add a Planner Agent, and does not move FinOS business workflow into the runtime.

The objective is one runtime capability:

> A Stable Task can carry a stable user goal and a mutable execution plan, keep that plan across suspend/resume/retry/continuation, and cannot claim normal completion while its own plan still says work remains.

---

## 1. Why this is now on the runtime mainline

AceAgent's next product step is not “more chat features”; it is:

> the user can hand AceAgent a goal, and AceAgent can keep track of what it is trying to finish, what it has already done, what remains, and continue the same work after interruption.

That behavior is generic Agent runtime behavior. FinOS may provide financial objects, permissions and business context, but FinOS must not define how the Agent decomposes and executes the goal.

Therefore:

```text
FinOS / other host
  -> provides user goal + authorized world

Zebra
  -> owns Stable Task continuity
  -> owns mutable Plan lifecycle
  -> owns completion coherence

AceAgent
  -> is the FinOS product identity built on the above
```

---

## 2. Existing Zebra substrate — reuse, do not rebuild

The current next branch already has the important Plan substrate:

- `SessionPlan` / plan steps;
- bounded step count;
- step states including pending / in_progress / completed / cancelled;
- internal `agent.plan` capability;
- `PLAN_UPDATED` runtime event/projection path;
- `Session.task_plan` durable projection;
- plan availability in normal Agent tool profiles.

This means Goal/Plan v1 is **not** a greenfield Planner project.

The work is to close lifecycle gaps around the existing substrate.

---

## 3. Normative model

### 3.1 Stable Task is still the only execution spine

Do not create a second task system.

```text
Stable Task
  ├─ Goal        relatively stable: what must be accomplished
  ├─ Plan        mutable: current approach / progress
  └─ Actions     tool / skill / model work performed during execution
```

### 3.2 Goal and Plan are different

**Goal** answers:

> What are we trying to accomplish?

**Plan** answers:

> Given what we know right now, how are we trying to accomplish it and where are we in that work?

A follow-up user message does not automatically become a new Goal.

Example:

```text
initial user request:
  “Find out why I have been losing money repeatedly lately.”

Goal:
  identify the major causes of the recent repeated losses,
  support conclusions with available evidence,
  and state material unknowns.

follow-up:
  “Exclude the CICC account for now.”

=> this refines scope/constraints inside the same Stable Task.
=> it must not replace the Goal with “Exclude the CICC account for now.”
```

### 3.3 Goal v1 must remain thin

Required behavior matters more than a large schema.

Minimum semantic content:

```text
objective
optional completion criteria / success condition
optional explicit user constraints
```

Implementation should first audit whether existing Task/session durable state can carry this backward-compatibly. Add the smallest optional structured representation/event only if required by red tests.

Do not introduce Goal Tree, Goal DAG, nested goals, autonomous goal generation or a separate Goal service.

### 3.4 Plan remains Agent-owned

Hosts may provide facts, permissions, resources and the user goal. Hosts must not inject a mandatory procedural plan.

Forbidden FinOS-style coupling:

```text
Investment Review must always:
1. read account
2. read journal
3. call Review Skill
4. score
5. save
```

Allowed:

```text
Goal: review the user's investment activity for the requested period.
Authorized world: selected account facts, journals, previous reviews, attachments.
Zebra/AceAgent decides the current Plan.
```

---

## 4. Required v1 runtime invariants

### GP-I1 — Plan continuity

For the same Stable Task, the latest durable Plan is the current Plan.

It must survive/re-hydrate across at least:

- ordinary continuation;
- `WAITING_INPUT` -> continue;
- retry;
- suspend/resume;
- worker/task re-claim or re-construction;
- context rebuild/compaction paths where durable task state is reloaded.

A resumed execution must not silently fall back to the original/stale task plan when a newer durable Session Plan exists.

### GP-I2 — Completion coherence

A normal task completion cannot contradict the Agent's own current Plan.

If the current Plan still contains `pending` or `in_progress` work, Zebra must not silently accept a normal `COMPLETED` terminal state.

Before normal completion the Agent must instead do one of the following:

- continue working;
- update the Plan;
- mark obsolete steps cancelled;
- wait for user/input when necessary;
- stop with an appropriate non-success state when work cannot continue.

Important one-way rule:

```text
open Plan work -> normal Goal completion is inconsistent

all Plan steps closed -> Goal completion is allowed,
but is NOT automatically proven
```

Plan closure is therefore a necessary consistency condition when a Plan exists, not a sufficient Goal evaluator.

### GP-I3 — Goal continuity

The Stable Task's user goal remains stable across ordinary follow-up turns.

Clarifications, scope refinements and “continue” messages must not replace the task goal with the latest message text.

If v1 supports explicit material goal revision, it must be auditable and revisioned/backward-compatible. Do not infer arbitrary goal replacement from every continuation message.

### GP-I4 — Plan is optional

Simple tasks must remain simple.

Examples that should not require Plan creation:

- factual one-shot lookup;
- short transformation;
- single obvious tool action.

Plan is expected for materially multi-step work where progress/continuity matters.

### GP-I5 — Plan is not private chain-of-thought

Persist/show work-state summaries such as:

```text
completed: identify loss-making trades
in progress: compare related journals
pending: compare previous reviews
```

Do not persist or expose hidden reasoning traces as Plan content.

---

## 5. Implementation card — ZNX-GOALPLAN-01

- Status: **Done**
- Branch: `codex/znx-goal-plan-v1`
- Type: Zebra-only generic runtime
- Depends on: current `codex/finos-runtime-next`
- Does **not** depend on FinOS Gate 2 completion
- FinOS dependency: none for implementation

### 5.1 Phase A — red tests / exact gap confirmation

Before production changes, add tests proving current behavior for:

1. latest Plan survives ordinary continuation;
2. latest Plan survives retry;
3. latest Plan survives suspend/resume or equivalent durable reconstruction;
4. latest Plan survives worker re-hydration;
5. task cannot normally complete with pending Plan steps;
6. task cannot normally complete with an in-progress Plan step;
7. cancelled steps do not block completion;
8. all steps closed does not itself fabricate Goal success;
9. a follow-up message does not overwrite the stable Goal;
10. a simple one-shot task can still finish without a Plan.

Existing behavior should be recorded honestly; do not write tests that fake a passing runtime seam.

### 5.2 Phase B — Plan lifecycle closure

Implement the minimum production changes needed to satisfy GP-I1 and GP-I2.

Preferred approach:

- keep one durable current Plan;
- hydrate execution from the latest durable Plan projection;
- centralize normal completion coherence in one runtime boundary rather than scattering checks across hosts;
- preserve backward compatibility for sessions/tasks with no Plan.

### 5.3 Phase C — Thin Stable Goal

Implement the minimum durable Goal semantics needed to satisfy GP-I3.

Preferred solution order:

1. reuse existing durable Task/session fields if they can unambiguously represent the stable goal;
2. otherwise add a backward-compatible optional structured goal envelope/projection;
3. add an event/update path only if explicit goal revision cannot otherwise be audited;
4. do not add a separate Planner/Goal service.

The runtime contract is more important than the exact storage shape.

### 5.4 Phase D — context integration

When execution context is reconstructed, provide the model/runtime with:

- stable Goal;
- latest current Plan;
- current task status / blocking reason where relevant.

Do not make the model infer the stable Goal from the latest continuation message.

### 5.5 Phase E — regression + example E2E

Required generic E2E scenario:

```text
User Goal:
  investigate a multi-step problem and produce an evidence-backed conclusion.

Run 1:
  create Plan;
  complete some steps;
  require user input;
  enter WAITING_INPUT.

User continuation:
  supplies clarification.

Run 2:
  same Stable Task;
  same Goal;
  latest Plan restored;
  Plan evolves;
  remaining steps close;
  final produced;
  task completes normally.
```

Also prove retry/resume recovery does not regress plan state.

---

## 6. Explicit non-goals for v1

Do **not** add any of the following in this task:

- Planner Agent;
- separate planner model;
- multi-agent / sub-agent delegation;
- Goal Tree / DAG;
- Plan DAG;
- scheduled tasks;
- background recurring work;
- automatic unlimited continuation;
- DeerFlow-style full Goal evaluator loop;
- self-generated long-term goals;
- GUI/computer-use;
- FinOS financial workflow definitions;
- Review-specific plan steps;
- user approval every time the Agent edits its own Plan.

High-risk actions remain governed by action/tool approval policy. Agent Plan edits are work-state updates, not business authorization.

---

## 7. Acceptance gate — Goal/Plan v1

Goal/Plan v1 is done only when all are true:

1. the same Stable Task preserves the latest Plan across continuation/recovery paths;
2. a pending/in-progress Plan cannot coexist with accepted normal task completion;
3. Plan closure does not itself fabricate Goal success;
4. the stable Goal is not replaced by ordinary follow-up messages;
5. simple one-shot tasks still work without a Plan;
6. no FinOS/finance-specific domain type enters Zebra;
7. no second task/workflow engine is introduced;
8. existing Skill/runtime tests remain green;
9. targeted Goal/Plan tests and repository-required gates pass;
10. implementation merges into `codex/finos-runtime-next` and publishes the exact SHA.

---

## 8. AceAgent relationship

This runtime work is necessary but not itself “AceAgent product UI”.

After Zebra Goal/Plan v1 exists, FinOS may consume it to present AceAgent as a goal-oriented Agent:

```text
User gives AceAgent a goal
  -> Zebra Stable Task owns Goal + Plan continuity
  -> FinOS supplies authorized financial world
  -> AceAgent executes and continues the work
```

FinOS does not need to change in order to implement Zebra Goal/Plan v1.

Future FinOS UI may choose to show a safe Plan summary, but that is a separate product task and is not part of this runtime card.

---

## 9. Sequencing relative to the existing waves

This task can start immediately and run in parallel with FinOS Gate 2 fixes.

For product sequencing, however, Goal/Plan v1 is inserted **before the former Wave 3 user-Skill expansion**:

```text
Wave 2 / Gate 2 closure
        |
        +---- Zebra Goal/Plan v1 may execute in parallel with Gate 2 fixes
        |
        v
Wave 2.5: Goal-oriented runtime foundation
        |
        v
Wave 3: User/Private Skill parity
        |
        v
Wave 4: Knowledge feedback loop
```

This is a priority/order change, not a statement that Goal/Plan v1 technically depends on Review Gate 2.

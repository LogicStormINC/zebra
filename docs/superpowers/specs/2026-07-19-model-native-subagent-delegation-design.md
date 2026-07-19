# Model-Native Subagent Delegation Design

## Status

- Date: 2026-07-19
- Decision: approved by maintainer
- Scope: parent-model selection of `agent.research`
- Non-goal: deterministic task-complexity classification

## Problem

`agent.research` is an optional model tool, so the runtime already creates a
Subagent only after an explicit model tool call. The current contract is still
too easy to misuse: the generic tool name attracts simple lookup requests, the
stable prompt does not define when delegation is worthwhile, and the tool call
does not record why the model delegated.

This causes unnecessary latency and cost for simple tasks and makes incorrect
delegation difficult to diagnose.

## Decision

The parent model remains the only delegation decision-maker. Zebra will not add
a keyword router, complexity score, preflight classifier, or frontend switch.
When `agent.research` is available, the stable system prompt tells the model to
prefer direct answers and direct parent-tool calls, and to delegate only an
independent, multi-step evidence-gathering objective whose isolation is useful.

The tool contract requires both:

- `objective`: the bounded evidence-gathering goal for the child;
- `delegation_reason`: why the parent cannot complete the work more efficiently
  by answering directly or using its own tools.

The reason is execution evidence, not an approval request. It is returned in the
bounded tool-result JSON and remains visible in the tool-call event and trace for
debugging.

## Prompt Ownership

`HarnessModelStep` owns the stable delegation guidance because it sees the
effective tool manifest. It injects the guidance only when `agent.research` is
advertised, appending it to the compiled System Prompt when one exists and using
a dedicated System Message otherwise. It is part of the initial parent
conversation and therefore survives every parent model call in the tool loop.

The guidance is absent when the research tool is absent. In particular, the
read-only child manifest cannot advertise `agent.research`, so children receive
neither recursive delegation capability nor irrelevant delegation instructions.

## Decision Rules Given To The Model

The model should answer directly when existing context is sufficient, the user
asks for a short explanation, or no evidence collection is needed.

The parent should use its own tool when one direct file read, URL fetch, search,
command, or other short linear operation is enough.

The model may delegate when the objective contains independent evidence streams,
broad multi-source or workspace investigation, or enough multi-step collection
that a separate bounded context materially reduces parent-context pressure.

Delegation is never mandatory merely because a task is described as research,
search, analysis, or comparison.

## Runtime Flow

1. The parent receives the ordinary tool manifest, including `agent.research`.
2. The parent either answers, calls a normal tool, or calls `agent.research`.
3. Only an explicit valid `agent.research` call creates a child.
4. The child remains depth- and budget-bounded and cannot recursively delegate.
5. The child result returns bounded JSON containing summary, sources, confidence,
   usage, and delegation evidence to the parent; the same evidence is retained in
   audit metadata.
6. A failed child is a recoverable tool observation; the parent may select a
   different tool or answer within the remaining budget.

## User Experience

There is one visible Task. Ordinary users do not see a Subagent creation button,
child thread, approval dialog, or stage boundary. Debug and audit projections may
show the delegation reason, child lifecycle, sources, usage, and fallback path.

## Hard Boundaries

This decision does not remove typed tool validation, depth and call budgets,
runtime isolation, cancellation, repeated-effect protection, or cloud authority.
These are execution correctness boundaries, not a heuristic delegation policy.

## Acceptance

1. A trivial answer produces no `agent.research` call or Subagent event.
2. A single direct tool operation uses the parent tool without a Subagent.
3. A scripted complex investigation may explicitly delegate with a non-empty
   `delegation_reason` and produces child lifecycle evidence.
4. Missing or blank delegation reason fails tool validation and is returned to
   the parent as a bounded, structured, recoverable tool observation. The model
   may retry with a corrected reason, and the invalid call produces no child
   lifecycle event.
5. A failed child can be followed by a different parent tool and final response.
6. No parent Harness or product execution path creates a child without an
   explicit valid model tool call. Internal coordinator primitives and their unit
   tests are outside this product-level invariant.
7. Full deterministic, static, Eval, and real-model simple-task checks pass.

## Rejected Alternatives

- Keyword or length heuristics: hidden rules are brittle and difficult to debug.
- A separate router-model call: it adds latency and cost to every simple task and
  can disagree with the executor.
- Mandatory delegation for complex tasks: complexity does not imply that an
  independent child improves the result.

# Stage 3 — command outcomes and Task/run replay

Owner: Luke Ding. Status: Review; isolated acceptance complete, not merged.
Task: `RABBIT-ZEBRA-AGUI-OUTCOME-01`. Original services remain unchanged.

## Acceptance boundary

1. A requested Task/run resolves to one canonical executable command, including
   only paired canonical handoff successors. Controls do not hijack that run.
2. Replay validates Task, run, exact event ID and cursor bounds; an initial
   canonical tail overlay handles an index that has not caught up. Steady reads
   stay incremental rather than rescanning every Segment on each stream tick.
3. A read-only same-database outcome reader reports only scoped durable command
   failures. Normal handled/terminal evidence takes precedence; old generations,
   physical delivery retries and cleanup failures do not become run failures.
4. API errors use fixed safe codes and no SSE ID, write no synthetic Session
   event, and cannot advance the durable cursor. Reconnect and local/default-None
   compatibility have runnable regression checks.
5. Actual PostgreSQL and API/projection tests, static checks and independent
   specification/quality review pass against the final slice.

Current slice: **5/5 = 100% accepted** after implementation and both reviews.
Stage 3 remains **5/6 = 83.3%**; supporting slice acceptance alone does not close
the process/fault/client acceptance group.

## Validation evidence

- First actual PostgreSQL outcome run: 6 passed in 5.49 s.
- Expanded outcome run: 8 passed in 6.66 s.
- API/run binding/Task stream/routes and integration projections: 40 passed in
  3.18 s. This run predates final self-review and is not the final acceptance gate.
- Expanded API/projection gate: 47 passed in 3.10 s.
- Actual PostgreSQL outcome/handoff/receipt/recovery combination: 101 passed in
  86.02 s; the outcome file contributes 10 cases, including actual composition
  DSN selection and a paired handoff successor's canonical terminal event.
- SPEC reproduced a deadline defect: an outcome database read finishing after
  authorization expiry could still emit an error frame. The shared output gate
  now checks after awaited IO and before resuming a paused consumer, and closes
  the source generator at expiry. Final API/projection tests: 52 passed in 3.35 s.
  Independent SPEC re-review: 34 passed in 2.96 s; PASS. Independent QUALITY:
  34 passed in 3.17 s; PASS (10 actual-PG cases skipped in that independent run).
  Static gate: make check passed, 838 typed files and 10 eval cases.
- Original Zebra still has only the user's existing `AGENTS.md` modification.
  Original Trench tracked diff SHA-256 remains
  `918bc8a6307051b39eec9439bea3b5c8c84ecc230851b32b1848d7a331e1fbc3`.

These are local isolated-worktree results, not deployment or production evidence.

# CA-HA-03B — connection capacity

Owner Luke Ding / Codex; same task, branch and worktree; parent359ee6ca.

1. Trace all ordinary/direct/Task I/O callers and process/thread entrypoints. Done.
2. Freeze exact paths; reuse pool, native connection close and ContextVar scope. Done.
3. Reproduce missing bulkheads; implement explicit opt-in process budgets and fleet arithmetic.
4. Compose API/Worker/child/cleanup/scheduler and fix Helm/API entrypoint.
5. Exercise real PG saturation, retained borrows, fail/close behavior and API control/read routing.
6. Run relevant checks; record remaining dedicated E1 load/independent review; commit candidate.

No production deployment/migration, old-environment restart, business replay, model calls or E1 cluster on Mac.

03B steps1–6 complete as a locally verified candidate; commit recorded by Git history.
Evidence: docs/evidence/ca-ha-03b/validation.json. No merge/push/deployment.
Parent03 stays In Progress: dedicated E1 and independent review remain.
Next: review03A/03B; freeze dedicated test topology/external clients/DB parameters and measure E1.
Do not run the E1 cluster on this Mac, auto-enable the sample profile, or unlock04 from microtests.

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
Parent03 stays In Progress: dedicated E1, independent review closure and release acceptance remain.
Next: review03A/03B; freeze dedicated test topology/external clients/DB parameters and measure E1.
Do not run the E1 cluster on this Mac, auto-enable the sample profile, or unlock04 from microtests.


Review follow-up (same card/owner/branch):
1. Independent AI review found callback cancellation bypass and terminating-overlap arithmetic. Done.
2. Cover API and transitive async PG callbacks with existing bounded dispatcher; bound metadata fanout. Done.
3. Reject profile-enabled Helm upgrades pendingHA08; document rollback/restart/repeated rollout exclusions. Done.
4. Final relevant1082pass/327skip, focused114/1skip, make check green; independent AI re-review47/1skip. Done.
5. E1 preflight: contexts unreachable, repo runners0; user now authorizes fresh server/OrbStack staging, resource checks passed; environment_unverified.
6. Record evidence and commit review fixes, no merge/push/deployment.

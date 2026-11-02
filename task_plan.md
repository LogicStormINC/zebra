# CA-HA-03 — E1 provisioning and integration

Owner Luke Ding / Codex; same task/branch/worktree. Source parent9e3cef3b.

1. Independent03A/03B review and fixes: done,9e3cef3b local commit.
2. User-authorized fresh bounded two-host staging: provisioned; no production replacement.
3. New DB121, NOSUPERUSER, empty cutover, versioned objects, Rabbit principals: verified.
4. Native model wire fixture, real authority fixture, exact volumes/endpoints/CA/peer guards: verified.
5. Migration and maintenance integration fixes: focused9green, PG12green+1 inherited fixture failure,
   independent AI review complete; commit source then build exact image delta.
6. Promote delta only into exact owned idle staging apps; verify source, budgets, health and one
   synthetic Task without retrying unknown outcomes. Promotion/source/fresh health verified;
   one Task admitted201 and reached gVisor, then failed closed before model transport because
   native CLI has no trusted exact-request counter. Original failed Task retained, no replay.
7. FullE1 baseline/load/fault matrix remains not_run;03notDone and04locked.

Do not change existing production, restore old workloads, use real provider keys or replay business Runs.

8. Next implementation slice: explicitly compose a trusted request counter through existing
   ModelRequestBudgetFactory; prove its wire/output bounds before another NEW synthetic Task.
   Do not replace it with a heuristic or weaken native budget/capability guards.

Receipts: docs/evidence/ca-ha-03-e1/validation.json. Current environment uses restart=no,
Mac-owned SSH forwards and a single VM control/data plane; not storage/host-failure HA.

# CA-HA-03 budget reference renewal

A fresh verified Host approval correctly appended an immutable Task binding.
The first model reservation had already settled, but the Task budget still
referenced the earlier binding. `start()` refused the new authority before the
pending tool executed. The original120s absolute Task budget later expired.
That Task stays suspended; this fix does not authorize replay or quota renewal.

Reuse the existing pure renewal builder in Core; the API keeps its import alias.
`save_task_binding` already owns the Task lock and CAS. If a budget exists, it
requires adjacent revision, equal prior SQL/snapshot/ledger digests and a complete
snapshot equal to the builder's legal non-expanding renewal. It changes only the
ledger's binding reference, in the same transaction as the new snapshot. All
clock/charges/unknown/receipts/journal state stays intact. Old binding rejection
and Worker startup narrowing remain unchanged. Missing or stale history is not
reconstructed automatically. No migration or dependency was added.

Validation: new real-PG regressions initially11 failed/2 passed; final17 passed.
They cover known/unknown spend, tool charge, expired clock, unchanged configuration,
including fields omitted from the binding digest, CAS requirement, rollback,
missing budget and inconsistent prior history. API/Worker unit21 passed/3 skipped.
`make check` passed. Independent AI review found no Critical/Important and ran
16 unit checks/3 conditional skips plus Ruff; it did not run PG or replace review.

A combined PG run over a Mac-to-VM connection had45 pass/1 concurrent approval
failure at the existing50ms lock bound; a single repeat failed the same way.
Those failures remain recorded. A same-node, read-only, nonroot, resource-capped
QA container then passed the single test and all46 combined checks. It reuses
already-installed pure Python pytest dependencies; nothing was downloaded or
added to the runtime image. Only the dedicatedha_qa non-superuser database/role
was used. Limits were not relaxed. This is not cross-node concurrency acceptance.

Next: freeze/build both source-matched images and real multiarch manifest; create
new native approval; cold-promote the isolated environment; verify a new synthetic
approval/continuation case within its original deadline. Preserve all previous
Tasks/receipts and the unknown original request. Full E1 and HA03 remain pending;
HA04 stays locked. Production is unchanged.

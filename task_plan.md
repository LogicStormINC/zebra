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

9. Budget composition source candidate completed: optional Cloud bundle counter propagation,
   cancellable Cloud roots; actual synthetic model byte meter and cap/body checks verified.
   Broad run3054 pass/856 skip/one obsolete lifecycle assertion; test-only fix followed by
   47 pass/2 skip and final make check. No source image promotion or Task replay.
10. Next exact files/actions: add operator composition under tests/compose/cloud_ha_e1/ using
    compose_cloud_worker+dataclasses.replace(model_request_budget_factory=...), retaining TLS
    peer/CA/namespace guards. Select model invocation max_output_tokens through an existing
    frozen RuntimeAssembly/bundle (not a counter-side wire rewrite). Register only synthetic
    test definitions through existing validated operator services. Update exact image delta
    COPY and source pins, cold promote idle owned staging only, then POST a NEW Task once.
    Full E1 and production HA remain unverified; keep03 In Progress and04 Locked.

11. Operator source prepared: main factory is invoked within its live pool; E1 parent and
    isolated child share strict counter selection.41 targeted tests, offline real Bundle
    counter and actual model meter checks pass. Full make check passed.
12. Before new apps: freeze reviewed source; native delta builds; start only registry after
    registry-only preflight; publish/verify a real multi-arch image manifest; generate actual
    private catalog/publication with that digest and source receipts; UID65532 mode0600;
    publication token operator-only; verify both effective baselines. Then full preflight and
    idle owned cold promotion. Never run the original failed Task again.

13. E8 live assembly done: immutable multi-arch manifest abfd6add..., matched runtime
    source2139/3 and both baselines; new owned API/Worker healthy; actual management
    materialize/publish passed. Native strict credential/ref/template fixes now in generator.
14. Guarded smoke39d0... admitted once and reached gVisor/isolated model boundary with
    output cap1024, but shared recursive guard TypeError on real present schema.type dict;
    no reservations/tools. Preserve failed Task. One-line tuple fix red3/green35+5skip,
    AI review19passed. Next build this exact new source, real new image index, generate
    a NEW approval with --trust-revision4 (current exact trust3), exact scoped native
    CAS3->4, materialize/publish new Definition and NEW Task. No retries of old Tasks.
    Full E1/HA03/production HA still incomplete.

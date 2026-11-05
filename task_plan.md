# Live checkpoint — frozen9b4f9ad3 / Native7

Two local arm64 logical nodes now run2API/2Worker/2cleanup on profile247; both
healthy/restored. Exact two-arch images/index/source proof and Native7 publication
passed. Two fresh full native pwd Tasks and two active-executor freeze STOPs are
verified with real exit pairs/resource absence; primary independent cleanup ran
while Worker frozen. OCI objects were not started tools. Original7 tasks/budgets/
unknown preserved. Shared physical Mac, WAN apps held, production untouched.
Next: E1 deterministic short-task/corpus/load harness, measured stages and fault/
soak gates; keep03 In Progress and04 locked. Do not replay any existing task.

# Current checkpoint — 2026-11-03

CA-HA-03 stays In Progress on the claimed worktree/branch. Monitor capacity2079
and dual-engine routing source regression are verified (native PG46, make check,
independent review). Primary still runs engine637; Broker/Authority9a; Ubuntu WAN
API/Worker held. Fresh OrbStack node2 calibration/source and both local247 static
preflights pass; no node2 app has started. Source must be frozen and rebuilt into
exact arch images/common index, then new native approval/publication and cold
matching-profile apps/cleanup on both local nodes. Preserve original tasks,
unknown receipts and f69 reconciliation. Full E1 load/fault/soak not_run,04locked,
no physical/storage HA or production rollout claimed.

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

## E1-A capacity handoff, 2026-11-05

The follow-up is authorized for the paired native reads, deterministic regressions
and new synthetic E1-A tasks against an adjacent original baseline.

- [x] Verify the clean ca-ha-03-budgets checkout and the final transaction-map artifact.
- [x] Confirm the single synthetic Task has 222 transactions, 77 lease reads and
  49 deadline checks. These counts describe this sampled Task.
- [x] Trace child require_owned -> LeaseStore.get -> native lease/epoch/STOP read.
- [x] Trace BudgetExecutionCheck -> original callback -> check_deadline.
- [x] Compare installed and checkout budget code. Installed v126 uses two deadline
  queries in one transaction; the checkout combines them into one statement.
- [x] Review all callback routes and identify pure reads that can share an existing
  work unit without extending a transaction across writes, model I/O or effects.
- [x] Reproduce the chosen transaction count reduction with a deterministic check
  and validate lease expiry, STOP, deadline, scope and rollback behavior.
- [x] Compare fresh same-seed candidate and adjacent original baseline at 4+4 slots,
  5 Tasks/s and 256 SSE. Include all receipts, rejections and unknown outcomes.
- [ ] After E1-A passes, run sustained load and cross-scope fairness, then finish
  the remaining E1-R matrix while keeping the prior F-02 state separate.

Evidence is .artifacts/cloud-ha-e1/e1-a-v126-transaction-map-1793856413/transaction-map.json.
Installed sources are session_process_child.py.installed and overlay/worker_budget.py
in that directory. E1-A and the full HA objective remain incomplete.


Paired-read result is local commit ac349add, with 59 focused regressions passing.
Candidate commits per completed Task 173 versus 222 for the adjacent original.
Mean whole-slot 8.261 versus 9.623 seconds; queue p95/p99 32.016/36.200 versus
43.858/43.933 seconds. Candidate receipts 40 completed, 34 scope 429 and one
unknown; control 36 completed, 38 scope 429 and one unknown. Both unknowns remain
after one further original signed GET. All 75 offers are retained per arm.
Evidence is .artifacts/cloud-ha-e1/e1-a-v126-ownership-unit-1793857758/adjacent-comparison.json.
E1-A still fails. Sustained/fairness and full E1-R remain outstanding.


## ac349add follow-up, 2026-11-05

- [x] Re-profile a fresh synthetic Task at the installed ac349add candidate baseline.
  Its 173 commits include 50 work units, 28 unpaired lease reads, 18 progress
  transactions and 13 latest Run header reads; 12 headers follow catch_up checks.
- [x] Share only the configured native ownership/deadline check and latest Run
  header in one read-only transaction, closing it before any page advance.
- [x] Add native same-scope/custom fallback, Run supersession, write refusal and
  independent page-write regressions. 58 focused tests passed, Ruff/mypy clean.
- [x] Run fresh same-seed candidate and adjacent ac349add control, preserving every
  receipt and every occupied attempt, including the control's two suspensions.
- [ ] E1-A capacity and queue targets remain unmet; sustained/fairness and full E1-R
  are still outstanding.

Local implementation eb0721a9. Completed Task commits 173 to 161.
All-admitted complete slot mean 7.8292 to 7.7545 seconds, an observed 0.95% change
in one pair with different failure outcomes. No significant capacity gain claimed.
Evidence .artifacts/cloud-ha-e1/e1-a-ac349add-checked-header-1793859685/adjacent-comparison.json.

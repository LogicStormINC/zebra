# Cloud Worker startup and projection repair - 2026-10-12

Owner: Luke Ding / Codex. Task: COV-POOL-STARTUP-01.

## Incident and root causes

Trench conversation `conv_1791784350642_9757c5` maps to Zebra session
`6721d0b0-f777-4f91-9746-38b7abf25874`. It failed at runtime instance binding,
before any MODEL call or web-search tool invocation. The same exception escaped
failure-finalization and restarted the Worker once.

`load_session_task_binding` correctly configures a readonly REPEATABLE READ
snapshot, but those are psycopg connection defaults, not only SQL transaction
settings. The process pool previously finished the transaction without clearing
those defaults. A later Task-index INSERT borrowed a readonly connection.

The shared pool now uses the installed psycopg_pool reset hook. It clears
autocommit/isolation/readonly/deferrable only after the borrower transaction ends.
Reset adds **zero SQL** and failed reset connections are discarded natively.
No per-caller workaround, cached authority, removed readonly proof, new dependency
or Worker failure suppression is introduced. Existing work-unit ownership remains.

Separately, the projector repair path imposed a100ms deadline on an operation
including cold DNS, connection and transaction completion. Private readonly
container probes measured cold100ms DNS timeout at91.9ms;2s budget succeeded
at458.7ms; a warmed100ms read succeeded at8.5ms. Repeating the short deadline
prevents the address cache from being populated.

Maintenance now uses the existing2s bounded I/O contract, reduces replay-header
batches256->128 and adds a1s discovery cooldown after failure. It retains the
round-robin cursor, row/byte bounds and rollback; foreground SSE does not repair
history. Logs now include the Task identity, not just an exception type.

## Verification and limitations

- Native readonly reader/writer tests failed before the shared reset, then passed.
- Cold-resolver and cooldown tests failed before the maintenance fix, then passed.
- Native Worker binds runtime and durably finalizes two consecutive synthetic
  setup failures on the same service, releasing both leases without a restart.
- Reset failure/discard, zero-SQL reset, tenant refusal followed by writing and
  concurrent Worker-thread reads/writes have dedicated native checks.
- Initial expanded test run hit a stale scratch migration95 checksum and a
  scratch role lacking CREATEDB. A new dedicated scratch database was created;
  the old test database and all business data were left untouched.
- One old malformed-legacy test attempted to overwrite an immutable source.
  It now first asserts that protection, then injects legacy corruption only in
  its generated fixture-owned schema before testing the controlled read refusal.
  No production trigger or historical migration checksum changes.
- Fresh expanded group:145 passed /10 infrastructure skips /0 failures.
  Evidence: `/tmp/zebra-pool-startup-native-fresh-20261012.xml`.
- Optional projector native fixture lacked the current reader's official v97
  privacy view. Exact official fixture composition, not predicate removal,
  resolves its10 failures: **68 passed /0 skipped in77.56s**.
  `/tmp/zebra-pool-projector-native-final-20261012.xml`.
- Final critical/concurrency group: **12 passed /0 skipped in6.82s**;
  `/tmp/zebra-pool-startup-final-critical-20261012.xml`.
- Full suite: **9041 passed /2685 prerequisite skips /0 failed in1113.41s**;
  `/tmp/zebra-pool-startup-full-20261012.log`. Late native fixture/test additions
  have the separate critical/native checks above. Static GO: sizes2956/Ruff/
  mypy1,243 and30 deterministic eval cases.

This is not live conversation replay, fleet load acceptance or a cure for the
remaining strict SQL gate. The recorded long/short6411/15653 statements still
exceed1000. Native strict command admission/receipts remain operator-controlled
and were not enabled by this incident fix. No paid task was resubmitted.

Code commit `2182508240a81236f662d24dae0f6288dea9d5c9` was fast-forwarded locally
into `cloud-agent-trench`. Primary postmerge critical checks:12 passed /0 skipped
in6.53s; `/tmp/zebra-pool-startup-primary-postmerge-20261012.xml`. Primary make
check GO2958/Ruff/mypy1243/eval30. Independent dirty-file and stash hashes are
unchanged; no remote push or retained performance-checkout cleanup occurred.

## Images and operator-only replacement

Built API/Worker images are arm64 and their two modified runtime modules match
the repaired source SHA-256. Offline imports pass with network disabled and a
readonly container root. Builds do not replace running containers.

| Component | New image ID |
| --- | --- |
| API | `sha256:0171cfead0df0885f428f8d7ab8bab940993a563e79fb5f83976877462f3396a` |
| Worker | `sha256:398be3641f8a0eed40c4e458b42e89c3b00e312942c1ed286a34a34d2b69cebd` |
| Migrate | `sha256:b0239e3a2c62cd8077d2d64cb813df5ae20c9835ba1852602110392f69b82325` |

Previous API/Worker images remain tagged `pool-incident-before-20261012`.
There is **no schema change** in this repair, so do not rerun migration just for
these changes. Keep the current acceptance env, Pro overlay and local gVisor
mTLS overlay. The stopped scheduler and dependency volumes are not touched.

After source integration and verification are confirmed, run when no Task is
in flight:

```sh
cd /Users/lukeding/Desktop/playground/2026/product/zebra-agent
docker compose --env-file docker/trench-acceptance.env \
  -f docker/compose.application.yml \
  -f docker/compose.local-gvisor.yml \
  -f docker/compose.coverage-pro-test.yml \
  up -d --no-build --no-deps --force-recreate --wait \
  zebra-api zebra-api-legacy zebra-worker
```

Then test a new ordinary conversation asking about web-search capability. The
old failed Turn remains an honest failed record; restart must not silently retry
it. Confirm no `ReadOnlySqlTransaction` at runtime binding/finalization, no Worker
restart and no repeated cold DNS repair timeout. Health alone is not that proof.
Strict coverage testing additionally requires explicit qualified admission;
Pro model selection alone is not activation of that separate rollout.

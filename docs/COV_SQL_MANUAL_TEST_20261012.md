# COV-SQL-PHASE-01 local manual-test handoff

Owner: Luke Ding / Codex. Date: 2026-10-12.

## Scope and current evidence

The user authorized local source integration into `cloud-agent-trench` and
manual-test preparation. The task is still **In Progress**, not release-approved.
No remote push, business migration, service restart or runtime flag change is
part of this preparation. Independent primary SDK/AGENTS changes and stashes
must remain unchanged. The isolated checkout is retained for open performance work.

Implemented: bounded native evidence owner for private checkpoint publication,
MODEL usage and unit acceptance; durable precharge and staged-original recovery
without repeating MODEL; fresh physical-I/O/post-lock authority; independent
final certification. Historical migration checksums are unchanged; additive
migration 99 repairs derived execution positions without unsealing originals.

Prior full checkpoint: 9,036 passed / 2,680 prerequisite skips / 0 failed;
late fixes have separate 19/12 focused checks. These are recorded evidence, not
a fresh full-suite or live cross-service acceptance of this handoff.
Controlled strict nine-record gate still **FAILS**: 6,411 client SQL / 37.9034s
long slice; 15,653 / 73.4954s short slices. Threshold remains <=1,000. Fixture
Host/model/object responses do not prove business semantic accuracy or live p95.

## Local integration/build record

- Fresh pre-merge `make check`: file sizes 2,920 / Ruff / mypy 1,243 / eval 30 GO.
- Fresh isolated PostgreSQL/Worker boundary group: **69 passed, 0 skipped,
  0 failed in 367.33s**; `/tmp/zebra-manual-merge-check-20261012.xml`.
  Includes actual staged Worker recovery, missing/corrupt/STOP refusal,
  authority-outside-transaction, bounded selection/fallback and core hooks.
- Compose validation and existing mTLS/CA file readability checks pass.
- Previous API/Worker images retained as `manual-test-before-20261012` tags.
- Pending: local fast-forward, preserved-file verification, application image
  build and offline image import/contract smoke checks.

## Operator-only replacement commands

Current running API/Worker use `compose.application.yml` **plus**
`compose.local-gvisor.yml`. Preserve that overlay: the Worker uses the verified
local Linux VM's mTLS Docker bridge, not Docker Desktop's socket. The existing
acceptance env selects `linux/arm64`. Do not replace env files, credentials,
dependency containers, volumes, or the independently stopped scheduler.

Images are built during preparation. After the build is confirmed, execute these
commands yourself when no task is in flight. Stop the old application writers
before the migration; if migration fails, do not continue to the last command.
Back up business data before running any migration. These commands do not remove
volumes or update the dependency stack.

```bash
cd /Users/lukeding/Desktop/playground/2026/product/zebra-agent

docker compose --env-file docker/trench-acceptance.env \
  -f docker/compose.application.yml -f docker/compose.local-gvisor.yml \
  stop zebra-api zebra-api-legacy zebra-worker

docker compose --env-file docker/trench-acceptance.env \
  -f docker/compose.application.yml -f docker/compose.local-gvisor.yml \
  run --rm --no-deps zebra-migrate

docker compose --env-file docker/trench-acceptance.env \
  -f docker/compose.application.yml -f docker/compose.local-gvisor.yml \
  up -d --no-build --no-deps --force-recreate --wait \
  zebra-api zebra-api-legacy zebra-worker

docker compose --env-file docker/trench-acceptance.env \
  -f docker/compose.application.yml -f docker/compose.local-gvisor.yml \
  ps --all
```

The migration image applies pending additive migrations (up to 99), not just 99.
API legacy shares the new API image and must also be replaced to avoid mixed
versions. Recreating a container with `--no-build` before successful image build
does not test the new source. Healthy containers prove readiness, not task success.

## Manual acceptance checklist

1. Start a **new** Trench conversation with an authenticated user. Record its
   conversation ID, request start time, first visible output, and terminal time.
2. Run a bounded subscription query with an explicit date/source range. Verify
   progressive updates, tool summaries, final answer and a terminal state rather
   than indefinitely retained Working. Compare results with the actual selected
   records; sample retrieval must not claim exhaustive coverage.
3. Exercise a query requiring more than one work slice. Confirm normal continuation
   advances the same task without exceptional full-history recovery or repeated
   MODEL calls. Inspect persisted Events/logs, not just visible animations.
4. Re-open the completed conversation and refresh the page. Verify durable replay
   does not duplicate final output or usage. Existing completed conversations
   should remain readable; older in-flight tasks may need explicit recovery and
   cannot be assumed equivalent to newly admitted capability-bound tasks.
5. Cancel an active test. Verify STOP becomes terminal and no later answer is
   published. Use two authorized test users to confirm isolated conversation,
   artifact and usage access; never expose another user's namespace.
6. Retain the SQL gate and report live counts separately. Passing manual function
   tests does not close the strict query budget, tenant fleet-load/fairness,
   latency distribution or independently labeled semantic-accuracy gates.

Rollback tags for pre-build API/Worker images, if created, are only image rollback
anchors. They are not a database rollback. Do not automatically downgrade after
the migration or erase coverage evidence; assess schema/source compatibility first.

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
- Code commit `b40a38bed82bddfbd2a6830bad65ff975dac79a3` fast-forwarded locally
  into `cloud-agent-trench`; isolated source branch retained for open SQL work.
- Primary modified/untracked file digest and all nine stash references unchanged
  before/after integration and build. SDK/AGENTS work was not staged.
- Fresh primary `make check` GO: sizes 2,956 / Ruff / mypy 1,243 / eval 30.
- Initial primary native group: 36 pass / 4 setup errors. Root cause independently
  traced to primary `.env.local`'s `DEEPSEEK_MODEL=deepseek-flash`, overriding the
  fixture's Pro model. Strict capability correctly refused; no guard was relaxed.
  Re-ran the same primary source/venv from an empty temporary cwd with a symlink
  to the tracked configs and absolute pytest/config paths: **40 pass, 0 skip,
  0 fail in 62.43s**; `/tmp/zebra-manual-postmerge-hermetic-20261012.xml`.
  Local model configuration was not changed. This is not a full-suite rerun.
- Build of migrate/API/Worker GO, all `arm64`. Each image's 36 changed runtime
  Python files exactly match the merged source by SHA-256. Offline imports and
  migration-99 catalog smoke checks pass with network disabled/read-only root;
  neither application entrypoints nor migration `main()` were invoked.

| Image | Built ID |
| --- | --- |
| zebra-application-zebra-migrate | `sha256:5c9eefdf62dcd4afda8f5a95cf9071bbdf5b80e4c8bd286eb41e89bd4d18aa29` |
| zebra-application-zebra-api | `sha256:bb93c4ee64702559fb2c353eb4f8b5b05d7dd62a5e269829fac49fc3ca16bbf3` |
| zebra-application-zebra-worker | `sha256:e3e59a42a7a094c46378d823c3ce3202a9f2c688b5468a5221374662aabe74da` |

Existing API/Worker/legacy container IDs and pinned image IDs remain unchanged:
running services are still the old version until the operator replaces them.

### Strict coverage profile prerequisite remains explicit

Read-only inspection of the existing running Worker reports `cloud`,
`deepseek-flash`, reviewer profile `None`, scan fallback `True`. Newly built
images retain the tracked defaults and existing operator env; image rebuilding
does not authorize enabling native coverage receipts or changing model profiles.
Strict native coverage registration requires `deepseek-v4-pro` and the exact
reviewer profile. The controlled fixture tests select that profile explicitly.
Without explicit operator selection/configuration, ordinary conversation testing
does **not** exercise the native strict-coverage operation measured above.
The user explicitly selected preparation of an inactive Pro testing overlay:
`docker/compose.coverage-pro-test.yml`. Append it **last**, after application and
local-gvisor. It aligns API, legacy API and Worker model descriptors because
native API admission compares its descriptor with registered Worker capability.
It pins the official endpoint, Pro model, reviewer profile and Chat Completions,
including the DeepSeek aliases that otherwise override `ZEBRA_MODEL_*` values.
It does not change credentials, tenant namespaces, resource budgets, TLS/mounts,
admission cutover or execution-receipt rollout. Merely creating it activates nothing.
While selected, ordinary model requests in those application processes also use
Pro and may have different cost/latency. No new image build is needed for this
environment-only overlay; the existing built runtime images are unchanged.

Compose contract tests first failed for the absent overlay, then passed after
creation. Both base-only and gVisor combinations preserve all non-model settings.
Actual local acceptance-env Compose rendering also passed without starting services.
Final application Compose suite: **16 passed / 0 skipped in 1.51s**; size/Ruff/
mypy1,243/eval30 GO. Pure `load_settings` of actual rendered API/Worker envs
confirms Pro/reviewer/gVisor and identical capability configuration digests,
without accessing the database or registering any Worker. Current image IDs
remain the three built IDs above; operator env/base/gVisor files unchanged.
Preparation is not proof of capability registration or strict task success.

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
  -f docker/compose.coverage-pro-test.yml config --quiet

docker compose --env-file docker/trench-acceptance.env \
  -f docker/compose.application.yml -f docker/compose.local-gvisor.yml \
  -f docker/compose.coverage-pro-test.yml \
  stop zebra-api zebra-api-legacy zebra-worker

docker compose --env-file docker/trench-acceptance.env \
  -f docker/compose.application.yml -f docker/compose.local-gvisor.yml \
  -f docker/compose.coverage-pro-test.yml \
  run --rm --no-deps zebra-migrate

docker compose --env-file docker/trench-acceptance.env \
  -f docker/compose.application.yml -f docker/compose.local-gvisor.yml \
  -f docker/compose.coverage-pro-test.yml \
  up -d --no-build --no-deps --force-recreate --wait \
  zebra-api zebra-api-legacy zebra-worker

docker compose --env-file docker/trench-acceptance.env \
  -f docker/compose.application.yml -f docker/compose.local-gvisor.yml \
  -f docker/compose.coverage-pro-test.yml \
  ps --all
```

The migration image applies pending additive migrations (up to 99), not just 99.
API legacy shares the new API image and must also be replaced to avoid mixed
versions. Recreating a container with `--no-build` before successful image build
does not test the new source. Healthy containers prove readiness, not task success.
After replacement, verify effective model/reviewer and successful native Worker
registration before sending a **new**, explicitly coverage-admitted task. Host
signed admission, connector availability, operator cutover and current Worker
capability remain mandatory; a normal chat completion is not strict acceptance.
If API refuses `coverage_admission_unavailable`, inspect the existing gate and
registration rather than enabling cutover, bypassing proof or changing SQL budgets.
To return to the baseline model profile later, omit only the Pro overlay during
an operator-managed application recreation. Keep gVisor and the upgraded schema;
this is a model-profile change, not database or image rollback.

## Manual acceptance checklist

1. Start a **new** Trench conversation with an authenticated user. Record its
   conversation ID, request start time, first visible output, and terminal time.
2. Run a bounded subscription query with an explicit date/source range. For a
   native strict-coverage test, first satisfy the profile prerequisite above;
   otherwise this checks the ordinary conversation path only. Verify
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

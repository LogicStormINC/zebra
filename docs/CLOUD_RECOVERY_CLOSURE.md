# CLOUD-RECOVERY-CLOSURE-01

- Status: Ready (user authorized 2026-10-02; claimed below before implementation)
- Human owner: Luke Ding
- Branch: `codex/cloud-recovery-closure`
- Status: Locally integrated into `cloud-agent-trench` (live activation not performed)
- Scope: tool failure normalization and bounded recovery, Cloud stop-command
  correctness, model stream recovery, truthful partial delivery and UI feedback.
- Owned paths: `packages/agent-core/src/agent_core/harness/**`,
  `packages/agent-integrations/src/agent_integrations/**`,
  `apps/worker/src/zebra_agent_worker/**`, associated focused tests,
  `sdks/typescript/packages/react/**`, `sdks/typescript/packages/client/**`,
  `packages/agent-storage/src/agent_storage/postgres/**` only for command recovery,
  `docs/AGENT_TASKS.md`, this document, `PROGRESS.md`, `WORKLOG.md`.
- Validation follow-up scope: API `http.py` stream predicates may be extracted
  unchanged to `http_stream_routing.py` to restore the existing file-size gate;
  Cloud composition regression tests are included in the command lane.
  API `routes.py` may defer optional usage-reader access to the usage route so
  unrelated session/task admission remains compatible with minimal compositions.
- Paired Host delivery: Trench `toc-frontend/vendor/zebra-agent`, lockfile and
  existing strategy labels/tests may consume the rebuilt React package; preserve
  all unrelated Trench edits and do not publish or restart services.
  Paired terminal-status correction also includes Trench event mapping, turn-store
  projection and strategy turn projection/tests, preserving partial/blocked outcomes.
- Lane ownership: parent owns Harness and integration; delegated command lane
  owns Worker control/consumer and command tests; model lane owns provider stream
  recovery and tests; UI lane owns SDK feedback and tests. No overlapping writes.
- Preserve all pre-existing edits. No deployment, push, or branch integration.

## Acceptance

1. Sequential/parallel expected tool exceptions produce equivalent observations.
2. Invalid inputs can be corrected; cancellation and internal invariants propagate.
3. No blind retry of uncertain mutations or bypass of denied authority.
4. Cloud stop commands use trusted authority and bad commands do not starve work.
5. Provider recovery is bounded and does not replay already completed tools.
6. Partial delivery is explicit; existing output survives unrelated failure.
7. Deterministic regression tests and available full gates are recorded separately
   from live deployment/browser acceptance.

## Implemented behavior

- Expected gateway input/I/O errors become sanitized tool observations in both
  sequential and parallel execution. Internal invariants and cancellation are
  not swallowed. The model receives correction and recovery hints.
- Transient declared read-only calls have bounded retry eligibility. Uncertain
  mutations are not transparently replayed; their state/receipt must be checked.
  Retry-After is not bypassed with immediate Harness retries.
- Invalid bridge/clarification batches receive paired tool observations and a
  bounded repair opportunity. The final permitted model call is for delivery.
- Provider retries reuse the frozen model request, including prior tool results,
  only before semantic streaming output; exhausted recovery cannot renew its
  budget in an outer attempt.
- Legacy Cloud STOP uses durable admission and trusted namespace authority,
  revokes the active lease through direct control, and replays idempotently.
  Permanently malformed or unsupported commands get durable rejection receipts
  rather than starving a session. Cloud user SUSPEND remains explicitly unsupported.
- A stopped incomplete attempt can publish a safe partial/blocked status without
  publishing its rejected candidate or claiming unverified work completed.
- SDK preserves delivered media and shows partial/failure/cancelled feedback.
  Trench consumes the rebuilt vendored package and localized status labels.

## Deliberate limits

- This is recovery within existing authority, not a permission bypass or a promise
  that every external failure can be repaired.
- No new provider/model failover service or dependency was introduced.
- Stream deadlines are checked between received SSE lines; blocked reads remain
  bounded by the HTTP transport timeout.
- No production deployment, runtime restart, GitHub publication or branch merge
  is included. Existing containers do not run these source changes automatically.

## Validation, 2026-10-02

- `uv run pytest -q`: **4,879 passed, 907 skipped**, 151.89 seconds. Skips are
  not counted as verified integrations; see the separate real-database run below.
- `make check`: file-size gate (2,338 files), Ruff, mypy (1,006 source files),
  deterministic eval release gate **30/30** all passed.
- TypeScript SDK `pnpm test` with Node 22.23.1: **53 passed**, package builds pass.
- Trench final targeted backend **78 passed**, frontend **23 passed**, TypeScript
  check and production frontend build passed. Earlier package-delivery checks
  overlap with these final checks and are not added to the totals.
- Separate temporary PostgreSQL 17 validation: **82 passed**, including actual
  lease revocation, idempotent STOP replay, delayed admitted STOP and poison-command
  receipts; the instance was removed afterward. Reproduce with an isolated test
  database in `ZEBRA_TEST_POSTGRES_DSN` and the command recovery/direct-control suites.
- `docker compose --env-file docker/trench-acceptance.env -f
  docker/compose.application.yml build zebra-migrate zebra-api zebra-worker`
  completed. Built worker `concurrent_batch.py` SHA-256 matches final source.
  Images retain the existing linux/amd64 target, not native arm64.
  Isolated read-only/network-disabled worker image smoke passed: recovery imports,
  durable cancellation method and bounded invalid-request stopping reason.
- No running service was recreated. Real authenticated Trench conversation replay
  against the new images remains a post-activation acceptance check, not a result
  inferred from these tests or builds.

## Authorized local integration, 2026-10-02

- User selected local integration only. Product edits were committed as Zebra
  `0ebfc943` and Trench `13b8ea2`, then fast-forwarded into `cloud-agent-trench`
  and `main` respectively. No push, deployment or service restart was performed.
- Local runtime artifacts, skill installations, generated environment files and
  the unrelated Trench `next-app` scaffold were excluded and preserved in place.
- Branch cleanup is limited to fully merged, unoccupied local task branches.
  Branches containing independent commits or used by other worktrees are retained.

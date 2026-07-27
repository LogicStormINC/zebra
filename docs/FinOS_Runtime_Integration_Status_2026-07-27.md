# FinOS Runtime Integration Status — 2026-07-27

This is the review snapshot for `codex/finos-runtime-alignment`. It does not
replace Zebra's product architecture or FinOS's business authority contract.

## Branch scope

- Base: `origin/main@f7d16c4`
- Committed branch baseline before this snapshot: `37708b4` (`0 behind / 1 ahead`)
- Delivery: review branch plus Draft PR only; no `main` merge or deployment is
  implied by the GitHub synchronization.
- Task card: `FINOS-RT-04` in `docs/AGENT_TASKS.md`

## Completed candidate behavior

1. Native Task attachments accept bounded JPEG/PNG bytes on Task creation and
   same-Task follow-up. Zebra generates the attachment identity and relative
   path, persists bytes under a Task-owned workspace, rejects absolute paths,
   symlinks, bad magic and cross-Task access, and restores the attachment after
   recovery or clarification.
2. The exact Task workspace is overlaid only for the selected
   `mcp.minimax.understand_image` process. MCP child environments are explicit;
   the parent environment is not copied wholesale.
3. A Task may bind one short-lived FinOS business grant after creation. The
   grant is Task-scoped, expires, rejects stale rotation and cross-Task replay,
   and is omitted from public Task/session/stream representations.
4. The provider advertises exactly eight read-only tools:
   `finos.journals.list/get`, `finos.snapshots.list/get`,
   `finos.transactions.list`, `finos.notes.list/get`, and
   `finos.securities.resolve`. Zebra exposes no FinOS Core, Draft, Journal or
   Note write tool.
5. `Dockerfile.finos` runs as the existing volume owner and now defaults its
   SQLite database and Task workspace to the two writable volume paths.
6. Focused attachment, MCP, provider, grant, policy, worker and Dockerfile tests
   pass. FinOS's external staging record reports all eight tools, a real JPEG
   MiniMax run, native stream completion and unchanged Core holdings,
   transactions and snapshots.

## Not complete / release blockers

- Full repository gates are not green for this working-tree snapshot:
  `make test` reported `1792 passed, 9 failed, 8 skipped`; `make check` is
  blocked by new file-size violations in `task_api.py` and `settings.py` plus
  Ruff/Mypy failures. These remain Draft PR work, not release-ready evidence.
- The Dockerfile path contract has a unit test, but a fresh image build,
  non-root write probe and real `/health` check still need to be recorded. The
  current workstation has no `docker` CLI, so this was not silently treated as
  a passing container test.
- FinOS provider bearer grants may use `http://` only inside an explicitly
  controlled private network. Public or cross-host deployment requires TLS or
  mTLS, a non-empty `ZEBRA_API_AUTH_TOKEN`, restricted volumes and secret-log
  review. An unauthenticated `0.0.0.0` service is not an accepted FinOS profile.
- Grants are stored in Zebra SQLite for Task recovery. This local single-host
  design is not a public multi-tenant secret store and must not be presented as
  one.
- Terminal Task attachment deletion and TTL workspace garbage collection still
  require a versioned lifecycle contract and release acceptance.
- Zebra's native text attachment window remains 64 KiB per file / 128 KiB
  aggregate. No replacement large-input framework is implemented here.
- Final merge requires resolving all full-suite/check failures and rerunning a
  controlled FinOS acceptance for expiry, replay denial, owner/account scope,
  all eight reads and zero Core writes.

## External and paused work

FinOS owns financial authorization, business data, explicit product writes and
Core confirmation. Zebra owns Agent Task/session, multi-turn reasoning, tools,
streaming and recovery. Zebra never receives direct database write authority.

FinOS shadow replay/backtesting, TradingView single-stock review, Trench and
remaining page design are paused product modules. They are not Zebra runtime
deliverables in this branch.

## Working-tree hygiene

- The untracked real broker screenshot and temporary env file were moved to the
  macOS Trash and were never staged.
- Generated caches and ignored local databases remain outside this snapshot.
- Source, tests, governance docs and build inputs are explicitly reviewed before
  staging; no blanket `git add -A` is used.

# FinOS Runtime Integration Status — 2026-07-27

This is the review snapshot for `codex/finos-runtime-alignment`. It does not
replace Zebra's product architecture or FinOS's business authority contract.

## Branch scope

- Base: `origin/main@f7d16c4`
- Snapshot: `983f082` (`0 behind / 6 ahead` of `origin/main@f7d16c4`)
- This synchronization includes `4459397` (runtime/tests), `40d6930` and
  `acac428` (governance/status), `ada7b80` (FinOS integration static cleanup),
  and `983f082` (stable Task public conversation projection) after MiniMax
  commit `37708b4`.
- Delivery: review branch and Draft PR #196; no `main` merge is implied. Exact
  build `983f082480f0c709b32fe1086b7a63a792c3c849` is deployed only to the
  isolated FinOS staging profile.
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
7. `GET /tasks/{stable_task_id}/conversation` exposes a durable public
   projection. Ordinary Task create/follow-up accepts `public_content`, while
   clarification keeps its existing `{content, clarification_id}` contract and
   rejects that extension.

## Public conversation projection contract

One stable Zebra Task remains the only conversation identity for a FinOS user
turn and every terminal follow-up. `GET /tasks/{stable_task_id}/conversation`
must rebuild its read-only view from Zebra's durable Task event index, using the
Task's monotonic cursor: each explicitly public user turn and each durable
final answer remains present in chronological cursor order, including across
internal rollover Segments. A later final must not replace an earlier turn's
final merely because both belong to the same Task or Segment.

Only explicitly marked public user text and Zebra's durable final-response
events may enter that view. Internal prompts, handoff/checkpoint data,
provider-private continuation or reasoning, raw deltas, and raw tool output
remain absent. FinOS consumes this Zebra-owned projection and the existing
native Task stream; it does not create a continuation Task, second session, or
second SSE protocol.

`public_content` is accepted only for ordinary Task create and ordinary
follow-up messages. Clarification responses retain their existing
`{content, clarification_id}` contract and reject `public_content`; they do not
create a separate public user event.

Local repair evidence: the focused projection, Task rollover, API, native Task
stream, bootstrap, message, clarification, harness, and runtime tests pass
(`61 passed`). Hosted evidence is also complete: stable Task
`0b23ea07-047e-490c-a964-4b48fe559ec0` retained two user turns and two finals in
cursor order, and FinOS consumed that projection without a local conversation
fallback. This does not replace FinOS's authorization boundary.

## Not complete / release blockers

- This branch's attributable static regressions are closed: `task_api.py` and
  `settings.py` are below the 500-line limit; the MCP Protocol's 13 Mypy errors
  and MiniMax's four Ruff line-length errors are gone. The 81 focused/provider
  and settings-contract tests pass.
- Current full-suite evidence is `uv run pytest -q -p no:cacheprovider`:
  `1795 passed, 9 failed, 8 skipped`, matching the `origin/main` baseline with
  no FinOS-focused regression. The nine failures are eight existing functional
  failures (two provider assertions, five expired credentials, one Worker
  cancellation) plus the existing file-size test.
- Repository gates remain at the main baseline: two existing file-size
  violations (`UI/desktop/src/components/CodexConversationPane.styles.ts` and
  `packages/agent-core/src/agent_core/contracts/events.py`) and four existing
  Mypy findings (`web_crawl.py:248-250` and `mcp_proxy_policy.py:195`). Changed
  Ruff checks are green; `make check` is still not green.
- A fresh `Dockerfile.finos` image build, non-root runtime, persistent workspace
  mounts and real `/health` check passed in FinOS staging. The deployed runtime
  reports `fallback_allowed=false` and `task_image_attachments=true`.
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
- Final merge requires resolving or accepting all main-baseline suite/check
  failures. Controlled FinOS acceptance for owner/account scope, all eight
  reads, real image attachment, public multi-turn projection and zero Core
  writes passed. PR #196 GitHub Actions failed to start because of the repository
  billing/spending limit; the jobs must be rerun after that external block is
  removed.

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

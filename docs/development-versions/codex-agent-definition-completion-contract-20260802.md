# Zebra Development Version: AgentDefinition Completion Contract

## Identity and ancestry

- Repository: `/Users/vinson/Projects/github/hellolukeding/zebra`
- Worktree: `/Users/vinson/.codex/worktrees/8bf3/zebra`
- Owner / task: `Vinson` / `AOR-DEF-01`
- Source thread: `019f9d5b-6811-78f3-a774-cd03bd38dfa4`
- Base branch: `codex/finos-runtime-alignment`
- Exact base commit: `c5b814500bbeebea0d4a0307f9a58c903bd5320f`
- Development branch: `codex/agent-definition-completion-contract-20260802`
- Target fixed deployment branch: `codex/finos-runtime-alignment`
- Deployment state: not requested; no push, merge, or deploy permitted
- Model request: Luna Max; no provider key or model configuration changes

## Owned implementation slice

- Versioned core `AgentDefinition` with identity, trusted context refs,
  capability/policy metadata, and `CompletionEvidenceContract`.
- Existing skill catalog resolution only for supported `system://` and
  `skill://` refs; unknown, ambiguous, or out-of-scope refs fail closed.
- Typed evidence collection from tool metadata, tool tags, validator outcome,
  and capability result; no natural-language completion parsing.
- One bounded missing-evidence observation in the existing sequential loop;
  budget/repeated-no-progress suspension remains the terminal guard.
- Durable API, TaskPrepared, workspace, recovery, rollover, and handoff
  propagation of the definition and completion contract.

## Red-first evidence

Planned before implementation:

- neutral fake profile: a no-tool final with missing typed evidence stays
  non-completed and receives exactly one bounded observation;
- arbitrary-order evidence plus a passed validator permits completion;
- repeated missing evidence suspends without another loop;
- no definition preserves the legacy no-tool completion behavior;
- create/read/recovery/rollover/handoff retain definition version and contract;
- malformed, unsupported, unknown, or changed trusted refs fail closed.

## Green evidence

- `make sync`: passed on the development worktree.
- Focused contract, persistence, trusted-context, handoff, and API tests:
  `24 passed`.
- Relevant regression set: `59 passed`; validator/provider regression set:
  `40 passed`.
- Full development-worktree `uv run pytest`: `1951 passed, 10 failed,
  9 skipped`; the ten failures exactly match the exact-base baseline below.
- Exact-base `uv run pytest` after its own `make sync`: `1937 passed, 10
  failed, 9 skipped`; no new failure is attributable to this slice.
- Exact-base file-size gate: `11` inherited violations. Development branch
  file-size gate remains at `11` violations after keeping new touched files at
  or below the repository limit.
- Owned-path Ruff: passed. Full Ruff retains `7` inherited findings outside
  this slice. `compileall` and `git diff --check`: passed.
- Release eval: `10/10` cases passed. `make check` stops at the inherited
  file-size gate before running its later checks.

## Unverified items and risks

- Live model/provider behavior is not part of this local contract slice.
- The exact-base full-suite failures are: two model-adapter contract cases,
  HTTP health response, four pull-request credential/transport cases, the
  repository file-size gate, and worker cancellation streaming.
- The exact-base static baseline retains the existing Ruff findings in
  `agent_security/mcp_proxy_policy.py`, `agent_tools/search_pipeline.py`,
  `agent_tools/web_crawl.py`, `agent_tools/web_projection.py`, and three
  related web tests; mypy retains `7` existing errors in `web_crawl.py`,
  `mcp_proxy_policy.py`, and `agent_tools/executor.py`.
- Skill content is re-resolved from configured trusted roots during execution;
  a changed or missing reference intentionally fails closed.

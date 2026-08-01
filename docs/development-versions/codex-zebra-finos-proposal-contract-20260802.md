# Zebra Development Version: FinOS Account Proposal Contract

## Identity and ancestry

- Repository: `https://github.com/vinson1101/zebra.git`
- Owner / task: `vinson1101` / `JC-03 FinOS account proposal contract`
- Base branch / commit: `codex/finos-runtime-alignment` / `f1f998a0a11030bf6885b0138225ef7b6960d42e`
- Source branch / commit: `codex/finos-runtime-alignment` / `f1f998a0a11030bf6885b0138225ef7b6960d42e`
- Worktree: `/Users/vinson/.codex/worktrees/zebra-finos-proposal-contract`
- Implementation branch: `codex/zebra-finos-proposal-contract-20260802`
- Fixed deployment branch: `codex/finos-runtime-alignment`
- Status: `Review`; not pushed, merged, deployed, or deployable

## Real failure evidence

JC-03 Task `c607d86a-f433-4806-99b0-8fb5f0e8be67` reached tool-call sequence
`952` for `finos.account_changes.propose`. The two account snapshots contained
`captured_at`, `cash`, `holdings`, `market_value`, `source_type`, and
`total_assets`, but omitted the FinOS-required `source_ref`. FinOS correctly
returned HTTP 400; Zebra sequence `955` exposed only the generic
`FinOS provider request failed`, so no Import Draft was created.

The shared contract gap is `ACCOUNT_CHANGES_PROPOSE_CONTRACT`: account entries
were advertised as arbitrary objects, so the model schema could not express the
FinOS v2 typed account, transaction, snapshot, and holding shape.

## Contract slice and owned paths

The proposal keeps the existing top-level `accounts`, `evidence_coverage`, and
`missing_evidence` fields, `side_effect=proposal`, the v2/v3 catalogs, and the
existing transport path. It will add only the nested JSON Schema needed to
describe the current FinOS contract: `account_ref` and `transactions` on every
account entry; optional snapshots with all six required source/value fields; and
typed holdings fields accepted by FinOS.

Owned paths are limited to:

- `packages/agent-runtime/src/agent_runtime/finos_journal_provider.py`
- `tests/agent_runtime/test_finos_business_provider.py`
- `docs/development-versions/codex-zebra-finos-proposal-contract-20260802.md`

## Non-goals and merge target

This slice does not modify FinOS, production execution behavior beyond the
published tool schema, natural-language parsing, transaction business rules,
model/provider special cases, stock allowlists, response error detail, new
dependencies, FinOS logs or Journal behavior, PR #196/#198 scope, or deployment
configuration. A later independent owner must implement any production repair
after this contract baseline is reviewed. The intended upstream target is the
fixed `codex/finos-runtime-alignment` branch after review and an explicit merge.

## Validation record

- Baseline command/result: `make sync && uv run pytest -q
  tests/agent_runtime/test_finos_business_provider.py` — `6 passed`
- New red test/result: the nested-contract test failed at the baseline with
  `KeyError: 'required'` because `accounts.items` was an arbitrary object schema.
- Green focused test/result: the new test plus the provider file — `8 passed`;
  related ToolContract/model-schema/worker tests — `29 passed`.
- Ruff: `uv run ruff check packages/agent-runtime/src/agent_runtime/finos_journal_provider.py
  tests/agent_runtime/test_finos_business_provider.py` — passed.
- Full Ruff baseline: `uv run ruff check .` — 7 inherited I001/F401 findings in
  unrelated web/search files; the owned files pass.
- Compile: `uv run python -m compileall -q packages apps tests` with Python
  3.12.13 — passed. The host `python3` is 3.9.6 and is not a valid project
  interpreter for this repository's existing `type` aliases.
- `git diff --check` — passed.
- Implementation head: local commit reported in the handoff below.
- Merge commit: not applicable

No live FinOS HTTP replay, deployment, Import Draft creation, or production
runtime repair was performed. No inherited test failure was observed in this
validation slice.

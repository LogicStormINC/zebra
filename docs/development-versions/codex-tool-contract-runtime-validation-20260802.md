# Zebra Development Version: Runtime ToolContract Validation

## Identity and ancestry

- Repository: `https://github.com/vinson1101/zebra.git`
- Owner / task: `vinson1101` / `TOOL-CONTRACT-RUNTIME-VALIDATION-20260802`
- Base branch / commit: `codex/finos-runtime-alignment` /
  `873de973fb6db922e16f17c72b0183f8b68fb4bb`
- Source branch / commit: `codex/finos-runtime-alignment` /
  `873de973fb6db922e16f17c72b0183f8b68fb4bb`
- Worktree: `/Users/vinson/.codex/worktrees/zebra-tool-contract-runtime-validation`
- Implementation branch: `codex/tool-contract-runtime-validation-20260802`
- Fixed deployment branch / merge target: `codex/finos-runtime-alignment`
- Status: `Review`; not pushed, merged, deployed, or deployable

## Real staging evidence

The fixed staging build `873de97` accepted a valid JSON-array string for the
`accounts` argument and a `list[str]` for `evidence_coverage`. The current
`ToolExecutor` checks only required top-level names, so both values can reach
the FinOS provider without recursive `ToolContract.argument_properties`
validation. FinOS then returns HTTP 400 and Zebra projects only a generic
provider failure. The shared repair belongs at the registered tool execution
boundary; FinOS parsing and model/provider special cases are out of scope.

## Contract slice and owned paths

`ToolExecutor` uses the existing registered `ToolContract` as the sole runtime
argument schema. It safely decodes one JSON string only when the declared
schema type is `array` or `object`, recursively validates the existing basic
schema keywords, and passes a normalized `ToolCall` to the handler while
preserving its identity fields and timestamp. Validation errors remain
`ToolArgumentError` so the existing harness projects `tool_validation_error`.

The FinOS `evidence_coverage.items` schema is completed with generic evidence
fields and a required non-blank `evidence_ref`; no FinOS repository code is
modified.

Owned paths:

- `packages/agent-tools/src/agent_tools/executor.py`
- `tests/agent_tools/test_executor.py`
- `packages/agent-runtime/src/agent_runtime/finos_journal_provider.py`
- `tests/agent_runtime/test_finos_business_provider.py`
- `docs/development-versions/codex-tool-contract-runtime-validation-20260802.md`

No `agent-core`, workflow, model router, MCP, deployment, FinOS repository, or
provider parser changes are permitted.

## Validation record

- Baseline: `make sync` used CPython `3.12.13`; the narrow existing
  ToolContract/provider/harness baseline was `43 passed`.
- New red tests: `uv run pytest -q
  tests/agent_tools/test_executor.py
  tests/agent_runtime/test_finos_business_provider.py` — `9 failed, 14
  passed`. The failures reproduced missing compound decoding, recursive type
  checks, nested required/additional-property checks, integer/bool handling,
  and the empty `evidence_coverage.items` schema.
- Green focused tests: the same command — `25 passed`; the complete
  `tests/agent_tools` suite — `157 passed`; FinOS business provider plus
  harness/tool-validation regressions — `43 passed`.
- Qwen/OpenAI tool-call regression: `39 passed, 1 skipped, 1 failed`. The
  single inherited failure is
  `test_openai_compatible_gateway_parses_tool_calls`, which rejects an
  unadvertised `files.read` response in the model payload parser before this
  executor is reached.
- Full pytest: `1,932 passed, 10 failed, 9 skipped`. All ten failures are
  inherited outside this slice: DeepSeek reasoning-content and the same
  OpenAI parser case; stale API health/credential expectations; five existing
  API pull-request credential cases; the repository file-size gate; and the
  durable cancellation race. No new owned-path failure was observed.
- Owned Ruff: passed for the executor, its tests, the FinOS provider, and its
  tests.
- Compile: `uv run python -m compileall -q packages apps tests` passed with
  Python `3.12.13`.
- `git diff --check`: passed.
- Merge commit: not applicable.
- Implementation head: `392d1fd37e6560e7205a8024cbf7091d584dc810` (code commit;
  this record is finalized by the following doc-only commit).

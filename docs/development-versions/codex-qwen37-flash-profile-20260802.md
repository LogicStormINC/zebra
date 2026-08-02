# Zebra Development Version: qwen3.7-flash Native Model Profile

## Identity and ancestry

- Repository: `https://github.com/vinson1101/zebra.git`
- Owner / task: `vinson1101` / `QWEN37-FLASH-PROFILE-20260802`
- Base branch / commit: `codex/finos-runtime-alignment` /
  `f1f998a0a11030bf6885b0138225ef7b6960d42e`
- Source branch / commit: `codex/finos-runtime-alignment` /
  `f1f998a0a11030bf6885b0138225ef7b6960d42e`
- Worktree: `/Users/vinson/.codex/worktrees/zebra-qwen37-flash-profile`
- Implementation branch: `codex/qwen37-flash-profile-20260802`
- Fixed deployment branch / merge target: `codex/finos-runtime-alignment`
- Status: `Review`; not pushed, merged, deployed, or deployable

## Verified live evidence

On 2026-08-02, the same already-configured DashScope-compatible endpoint was
probed without recording credentials, endpoint secrets, or response payloads:

- `qwen3.7-flash` text request: HTTP 200.
- Native 16x16 PNG request: HTTP 200.
- `enable_thinking=false` with image, function tool, and
  `tool_choice=required`: HTTP 200 with a `record_image_color` tool call.
- The same request with `stream=true`: HTTP 200, tool-call delta observed, and
  `[DONE]` received.
- A 1x1 image returned HTTP 400 because of the service image-size lower bound;
  this was not treated as an entitlement or capability failure.

The new explicit profile is `qwen-flash-alias-native-v1`, bound exactly to
provider `qwen` and model `qwen3.7-flash`. Its media capabilities intentionally
match the previously verified Flash native profile: text plus image, tools and
streaming with media, up to four images, 5 MiB per image, 20 MiB total, and
`image/jpeg`/`image/png` only.

## Contract and owned paths

The generic v2 registry remains an explicit profile-ID lookup. Unknown IDs and
provider/model mismatches continue to fail closed; no model-name inference,
prefix/regex matching, automatic capability grant, router, provider change,
MCP fallback change, or single-model Flash allowlist is added. The existing
dated `qwen-flash-native-v1` remains bound to
`qwen3.7-flash-2026-07-15` unchanged.

Owned paths are limited to:

- `packages/agent-integrations/src/agent_integrations/openai_model_profiles.py`
- `tests/agent_integrations/test_openai_model_profiles.py`
- `tests/config/test_settings.py`
- `docs/Generic_Model_Profile_Contract_v2.md`
- `docs/development-versions/codex-qwen37-flash-profile-20260802.md`

`configs/default.env` is intentionally unchanged because the generic explicit
`ZEBRA_MODEL_PROFILE_ID` setting already supports this profile without changing
the default model or provider.

## Non-goals and validation record

This slice does not modify FinOS, provider/router/MCP code, OpenAI-compatible
transport behavior, old profile behavior, Policy authority, default runtime
selection, live deployment, or dependencies. The live probe is evidence only;
no secret or endpoint-dependent smoke is added to the deterministic tests.

- Baseline command/result: `make sync && uv run pytest -q
  tests/agent_integrations/test_openai_model_profiles.py
  tests/agent_integrations/test_qwen_native_media.py tests/config/test_settings.py`
  — `44 passed`.
- New red test/result: the new profile test failed with
  `ValueError: unknown model profile: qwen-flash-alias-native-v1` before the
  registry entry was added.
- Green focused test/result: profile/native media/settings — `46 passed`;
  remaining OpenAI-compatible tests — `14 passed, 1 deselected`.
- Owned Ruff: `uv run ruff check
  packages/agent-integrations/src/agent_integrations/openai_model_profiles.py
  tests/agent_integrations/test_openai_model_profiles.py tests/config/test_settings.py`
  — passed.
- Full Ruff baseline: `uv run ruff check .` — 7 inherited I001/F401 findings in
  unrelated web/search files; no owned-file finding.
- Compile: `uv run python -m compileall -q packages/agent-integrations/src/agent_integrations
  apps/config/src/zebra_agent_config tests/agent_integrations/test_openai_model_profiles.py
  tests/agent_integrations/test_qwen_native_media.py tests/config/test_settings.py` — passed.
- Full compile: `uv run python -m compileall -q packages apps tests` — passed.
- `git diff --check` — passed.
- Related inherited baseline: `test_openai_compatible_gateway_parses_tool_calls`
  fails on base and this branch because a mock returns an unadvertised
  `files.read` tool call; this task does not modify that path.
- Implementation head: pending local commit
- Merge commit: not applicable

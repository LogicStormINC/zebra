# Zebra Development Version: FinOS Runtime Alignment

## Identity and ancestry

- Repository: `https://github.com/vinson1101/zebra.git`
- Upstream read source: `https://github.com/hellolukeding/zebra.git`
- Owner / task: `vinson1101` / `FINOS-RT-04-READONLY-AUTH`
- Fixed deployment branch: `codex/finos-runtime-alignment`
- Integration baseline: `1d2c1405efab534624ccaad543863ae9758bd6ab`
- Previous server build: `5e236d7737e788f36e37e6afd6d3c28b90a5337a`
- Source branch: `fork/codex/readonly-tool-authorization`
- Source commit: `d7ec9158efe034cdee5ee98898c87b9235e4702d`
- Merge commit: `98faf507165e73bfddc88491d3c154f3512e2a05`
- Current implementation head: `a716a9ba18c0bdfe9c6ff2e613f188ec6a1286bf`
- Status: `Review / not deployed`

The source commit has `1d2c140...` as its direct parent. The source branch is
retained as the merge's second parent for provenance; it is not a deployment
branch. The server build `5e236d7...` is an ancestor of the current implementation
head.

## Contract change

Zebra now accepts and durably projects an exact `preapproved_readonly_tools`
subset of the Task MCP allowlist. Automatic allowance still requires all of:

- Task policy `read_only`;
- network profile `mcp-proxy-only`;
- the classified route is the MCP proxy;
- the tool is in both the MCP allowlist and exact persisted preapproval grant.

An ungranted MCP tool remains `REQUIRE_APPROVAL`; unknown create-session fields
remain `400`; legacy requests omitting the field remain valid. The implementation
contains no FinOS, MiniMax, Qwen, or provider-name special case. It does not add
Core, Journal, Note, Draft, Shell, Git/PR, delete, or publish authority.

## Commit and validation evidence

- `cc06e28`: red contract reproducing the baseline `400`;
- `98faf50`: controlled merge of `d7ec915`;
- `5732cb8`: real HTTP `POST /tasks` and same-Task readback regression;
- `a716a9b`: focused helpers that remove all new file-size violations.

Validation:

- focused API, policy, event, storage, and worker tests: `107 passed`;
- independent API/policy/bootstrap review: `52 passed`;
- final full suite: `1,869 passed, 9 failed, 8 skipped`;
- isolated baseline: `1,864 passed, 9 failed, 8 skipped`;
- changed-file Ruff and `git diff --check`: passed;
- full Ruff: 7 inherited findings; Mypy: 4 inherited findings;
- size gate: only 3 inherited violations remain; this change adds none.

The nine full-suite failures have the same names on the isolated baseline and
cover existing model-response, credential/transport, file-size, and durable
cancellation gates. This is a staging candidate with no new regression, not an
upstream-main or release-ready claim.

## Next transition

Push this exact history only to the fork's fixed deployment branch. A FinOS
staging rollout may then package a commit reachable from that branch, verify the
runtime `build_commit`, exercise real `POST /tasks`, stream and image-tool flow,
and write the resulting image, release, rollback, data fingerprint, and acceptance
facts to FinOS `docs/staging-environment.md`.

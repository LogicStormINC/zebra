# Findings

## CTX-LC-01 - 2026-07-17

- The user split DeepSeek specialization into a separate Codex task. This task
  now owns only provider-neutral context lifecycle work; DeepSeek request and
  telemetry edits were removed before either implementation branch committed them.

- Current same-session conversation compaction is correctly placed before
  follow-up model calls, but the initial call bypasses it and
  `within_budget=false` is not a hard outbound gate.
- Context and conversation budgets are fixed and character-estimated; they do
  not reserve provider output, reasoning, tool schema, or continuation overhead.
- `command.run` and `tests.run` return complete stdout/stderr directly, so the
  first implementation rung is one shared bounded output projector backed by
  the existing Artifact boundary rather than provider-native compaction.
- Provider-native compaction is an optional continuation optimization. Session
  events plus a transparent Zebra Capsule remain recovery and cross-model truth.
- The implemented hard gate counts serialized messages and tool schemas against
  a model context window after output/reasoning/compaction/protocol reserves.
  A configured conversation target remains a soft progressive-compaction target;
  only the model-profile hard input limit fails the request.
- `command.run` covers arbitrary build commands, so no separate build tool or
  duplicate output-persistence path was added.
- The final implementation uses one request planner and hard gate for initial,
  follow-up, approval, clarification, recovery, and final-synthesis paths. Token
  counting is provider-pluggable; the neutral fallback records its estimate method.
- All large-output tool families cross one `ToolOutputEnvelope` boundary. Complete
  payloads remain retrievable by Artifact URI while model-visible evidence is a
  bounded head/tail projection with size, digest, checksum, and provenance.
- Active projection preserves protected user constraints and recent exact
  assistant/tool pairs, folds completed evidence into typed tombstones, and permits
  only budgeted, policy-checked, provenance-checked Artifact rehydration.
- Capsule Artifact persistence, `ContextCompacted`, `ContextCapsuleCreated`, and
  active-pointer CAS execute in one SQLite transaction. Worker recovery prefers the
  active Capsule and can restore a user-selected exact event tail.
- Provider-native continuation remains an optional capability contract with
  provider/model/version/TTL scoping. Missing, expired, incompatible, deleted, or
  cross-provider state deterministically falls back to the Zebra Capsule.
- Full acceptance evidence: `1379 passed, 1 skipped`; file-size and Ruff passed;
  strict Mypy passed across `379` source files; all `8` release Evals passed.

## 2026-06-18

- 当前最重要的设计基线仍然是 `docs/Codex-like工程Agent平台最终架构设计_v1.0.md`
- 仓库已经完成 `uv workspace` 和 `apps/ + packages/` 的基础重构，适合进入按阶段推进的实施模式
- 现有 `PROGRESS.md` 更像状态摘要，还缺一份明确的“任务拆解 + 阶段验收”文档
- 对这个项目来说，阶段划分应围绕核心依赖链组织：
  `core -> runtime/tools -> harness -> control plane -> context -> security -> eval -> productization`
- Phase 1 到 Phase 3 是最关键的连续闭环，如果这里没有打通，后面的 API、云端和安全服务都没有稳定依托

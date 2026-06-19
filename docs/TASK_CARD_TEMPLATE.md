# <TASK-ID> - <标题>

- Status: `Ready`
- Owner: `<姓名>`
- Reviewer: `<姓名>`
- Branch: `codex/<task-id>-<slug>`
- Worktree: `.worktrees/<task-id>-<slug>`
- Depends on: `<TASK-ID | none>`
- Owned paths: `<paths>`
- Risk: `L1 | L2 | L3 | L4`

## Goal

一句话描述可观察结果。

## Context to read first

- `AGENTS.md`
- `实施任务拆解与阶段验收.md`
- `02_Codex-like工程Agent平台_多人协作任务分配与RACI_v1.0.md`
- `AGENT_TASKS.md`
- `PROGRESS.md`
- `<ADR/Contract/Code>`

## Scope

- 必须实现：

## Out of scope

- 禁止实现：

## Acceptance

- [ ] 行为验收：
- [ ] Unit：
- [ ] Integration：
- [ ] Contract/Compatibility：
- [ ] Security/Recovery：
- [ ] Documentation：
- [ ] `make check`：通过

## Evidence

- Commands:
- Test report:
- Trace/artifact:
- Diff summary:
- Risk/rollback:

## Stop conditions

- 合同含糊或依赖未合并；
- 需要真实凭证或放宽安全边界；
- 必须修改未授权路径；
- 改动预计超过 1000 行或超过 2 个工作日。

## Handoff

- Consumer:
- Contract/version:
- Known limitations:
- Open decisions:

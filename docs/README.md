# Zebra Agent Docs Guide

## Active Execution Set

The current effective documents are:

1. `../AGENTS.md`
2. `实施任务拆解与阶段验收.md`
3. `02_Codex-like工程Agent平台_多人协作任务分配与RACI_v1.0.md`
4. `AGENT_TASKS.md`
5. `../PROGRESS.md`
6. `执行收敛与最小Runtime_Task_Memory切片方案_v1.0.md` for the active
   `HAR-CONV-01` implementation and locked `CTX-REHYDRATE-02` follow-up

Use these files for implementation, task claiming, collaboration, and phase progress.

## Document Roles

- `实施任务拆解与阶段验收.md`: historical Phase 0-8 dependency and acceptance baseline
- `02_Codex-like工程Agent平台_多人协作任务分配与RACI_v1.0.md`: collaboration model, ownership, and review rules
- `AGENT_TASKS.md`: current executable task registry
- `DeepSeek_V4_模型适配与专项优化方案_v1.0.md`: implemented `DS-OPT-01`
  provider-profile, protocol-safety, routing, caching, observability, and Eval baseline
- `上下文生命周期与混合压缩架构方案_v1.0.md`: implemented `CTX-LC-01`
  context-window planning, progressive compaction, durable Capsule, provider
  continuation, recovery, and operator-control baseline
- `执行收敛与最小Runtime_Task_Memory切片方案_v1.0.md`: current two-stage
  convergence repair authority; Phase 1 adds progress-aware terminal convergence,
  while Phase 2 remains locked for projection recovery and on-demand rehydration
- `上下文连续性与治理记忆改进方案_v1.1.md`: PR `#198` review baseline for
  exact recent context, recoverable overflow and governed repo-memory recall
- `Zebra Agent Runtime Upgrade Proposal v2.0.md`: long-term target proposal;
  it does not activate full Memory 2.0 or override the executable task registry
- `阶段性Session_Handoff与短线程链架构方案_v1.0.md`: implemented staged
  Session handoff contracts, recovery boundaries, operator surfaces, and rollout
- `生产级Runtime实施方案_v1.0.md`: implemented Linux-first gVisor/OCI runtime
  boundary and explicit production prerequisites
- `主线架构工程完成度审计与收口计划_v1.0.md`: current evidence-backed
  completion assessment and remaining platform boundary
- `operator_runbook.md`: current local operator workflow for CLI, API, and stream replay
- `TASK_CARD_TEMPLATE.md`: template for adding or splitting tasks
- `CODEOWNERS.template`: ownership template for GitHub

## Historical Reference

- `01_Codex-like工程Agent平台_任务拆解与阶段验收标准_v1.0.md` is retained as an older planning package reference.
- `agent架构设计0.1.0.md` is an older design exploration document.

Historical documents must not override the active execution set.

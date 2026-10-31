# Zebra Agent Docs Guide

## Product Plugin admission

[CA-P4-01 public contract and proof boundaries](CA-P4-01_plugin_admission.md) ·
[Machine artifacts](contracts/plugin-admission-v1/README.md). Trusted product publication
and current approval queries are separate from installation and Worker execution.

## Active Execution Set

The current effective documents are:

1. `../AGENTS.md`
2. `实施任务拆解与阶段验收.md`
3. `02_Codex-like工程Agent平台_多人协作任务分配与RACI_v1.0.md`
4. `AGENT_TASKS.md`
5. `../PROGRESS.md`

Use these files for implementation, task claiming, collaboration, and phase progress.

## Document Roles

- `实施任务拆解与阶段验收.md`: historical Phase 0-8 dependency and acceptance baseline
- `02_Codex-like工程Agent平台_多人协作任务分配与RACI_v1.0.md`: collaboration model, ownership, and review rules
- `AGENT_TASKS.md`: current executable task registry
- `ADR-016_Agent_Definition控制面与版本发布边界.md`: accepted Agent Definition
  metadata authority, Task/Attempt snapshot separation, release and migration
  contract; implementation remains task-gated
- `DeepSeek_V4_模型适配与专项优化方案_v1.0.md`: implemented `DS-OPT-01`
  provider-profile, protocol-safety, routing, caching, observability, and Eval baseline
- `上下文生命周期与混合压缩架构方案_v1.0.md`: implemented `CTX-LC-01`
  context-window planning, progressive compaction, durable Capsule, provider
  continuation, recovery, and operator-control baseline
- `阶段性Session_Handoff与短线程链架构方案_v1.0.md`: implemented staged
  Session handoff contracts, recovery boundaries, operator surfaces, and rollout
- `生产级Runtime实施方案_v1.0.md`: implemented Linux-first gVisor/OCI runtime
  boundary and explicit production prerequisites
- `主线架构工程完成度审计与收口计划_v1.0.md`: current evidence-backed
  completion assessment and remaining platform boundary
- `Wigolo_Web_Intelligence原生化架构与实施计划_v1.0.md`: planned, not yet
  implemented provider-neutral `web.*` contracts, wigolo Provider boundary,
  Zebra-owned research/security, durable Watch, task order, and acceptance gates
- `operator_runbook.md`: current local operator workflow for CLI, API, and stream replay
- `TASK_CARD_TEMPLATE.md`: template for adding or splitting tasks
- `CODEOWNERS.template`: ownership template for GitHub

## Historical Reference

- `01_Codex-like工程Agent平台_任务拆解与阶段验收标准_v1.0.md` is retained as an older planning package reference.
- `agent架构设计0.1.0.md` is an older design exploration document.

Historical documents must not override the active execution set.

## Accepted Directions And Non-Executable Proposals

- `Zebra Agent Runtime Upgrade Proposal v2.0.md` is the accepted direction for a
  versioned Agent Definition control plane. Locally accepted ADR-016 is the stable decision
  authority and corrects the proposal wherever they differ. Implementation tasks
  remain `Locked` until ADR-016 is merged and the registry explicitly advances them.

Accepted directions become executable only after their required ADR is approved
and a path-bounded implementation task is explicitly activated in `AGENT_TASKS.md`.

## Cloud Agent 高可用专项（规划，非HA达标证明）

- [正式方案、DDD边界与目标](CLOUD_HIGH_AVAILABILITY_PLAN_v1.md)：复用矩阵、缺口、兼容/unknown保护及证据等级。
- [分阶段任务与验收](CLOUD_HIGH_AVAILABILITY_TASKS_v1.md)：CA-HA-00–10、依赖、候选路径和故障矩阵。
- 00已合入并推送；01文档合同已集成，02–10仍Locked，不恢复暂停的重型验收或Docker环境。

## CA-HA-01 固定基线与设计合同（已集成，未实现/未演练）

- [基线、依赖、开关与逐卡路径](CA-HA-01_baseline_and_scope.md)。
- [DDD不变量、SLO、E1/F1及证据](contracts/cloud-ha-v1/README.md) · [机器可读规划](contracts/cloud-ha-v1/acceptance.json)。
- 00已推送cloud-agent d782039c；01 revision 2设计已集成1dd88bfd，02–10 Locked；强停候选仍独立依赖。

## CA-HA-01 revision 2复核与02前置

- [复核发现与修正记录](evidence/ca-ha-01/review.json)：单人文档复核，不是独立审查或HA实测。
- [CA-HA-02任务与依赖](CA-HA-02_readiness_preflight.md)：01合入后技术前置满足；未获实施授权仍Locked。
- [合同](contracts/cloud-ha-v1/README.md)与JSON同步revision 2；03因共享Worker文件改为依赖02。

## 用户卡顿/卡死与多用户性能（CA-HA-UX-00，仅设计）

- [正式方案用户体验补充](CLOUD_HIGH_AVAILABILITY_PLAN_v1.md#9-用户卡顿卡死与多用户性能保障)。
- [revision 3：UX-01–10计时、分母、E1-C/E1-O与验收](contracts/cloud-ha-v1/README.md#7-用户卡顿卡死与并发性能合同revision-3补充)。
- [任务与验收映射](CLOUD_HIGH_AVAILABILITY_TASKS_v1.md#8-用户体验专项验收索引均未运行) · [机器可读目标](contracts/cloud-ha-v1/acceptance.json)。
- 新增目标全部not_run，待评审；02–10仍Locked，前端mock和暂停重型环境的约束不变。

## CA-HA-02候选实现（未部署）

[API/Worker实际行为、旧模式限制和验证边界](CA-HA-02_readiness_preflight.md#6-ca-ha-02候选实现2026-10-31review) ·
[定向证据](evidence/ca-ha-02/validation.json)。精确GET存活/就绪、公共控制面有界观测、
Worker原进展和私有文件；没有执行权限/Task终态变更。仅02候选Review，03–10仍Locked；
完整测试/真实PG/故障与UX容量未验，不恢复重型测试或Docker，不部署/生产迁移。

CA-HA-02候选复核：[58项定向验证及修复证据](evidence/ca-ha-02/review-validation.json)。
就绪不过真实进展截止、只读普通本机文件、关闭失败仍尝试其余资源；完整门禁/真实PG未验。

[CA-HA-02完整门禁、真实PG及基线阻塞](evidence/ca-ha-02/full-validation.json)：PG5通过，
完整门禁15失败/16尺寸/Ruff4924均已基线复现；未主线合入，03依赖复核见02前置文档第8节。

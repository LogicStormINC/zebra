# 2026-08-08 FinOS Next Runtime Task Board

- 状态：Executable planning baseline
- Zebra integration branch：`codex/finos-runtime-next`
- FinOS integration branch：`vinson1101/FinOS:codex/finos-next`
- 上游：`ADR-015_FinOS_Personal_Investment_OS_Runtime_Integration_Boundary.md`
- 上游：`ADR-016_Portable_User_Skills_and_Host_Capability_Binding.md`
- 配套 FinOS 计划：`docs/dual-repo-next-development-plan-2026-08-08.md`

本文只注册 FinOS 下一阶段真正需要的 **generic Zebra runtime** 工作。它不是新的 FinOS 专用 runtime roadmap，也不替代已有 `docs/AGENT_TASKS.md` 的通用任务历史。

原则：

> Zebra 不需要和 FinOS 同步“保持忙碌”。只有 cross-repo red test 证明 generic primitive 缺失时，才增加 Zebra 实现任务。

稳定分支 `codex/finos-runtime-alignment-integration` 不在本任务板直接开发。

---

## 1. 当前可复用能力

现有 Zebra 已完成的 EXT Skill 基础包括：

- `EXT-SKILL-01`：metadata v2；
- `EXT-SKILL-02`：scope / namespace / digest / no silent override；
- `EXT-SKILL-03`：Task-level `skill_components` snapshot；
- `EXT-SKILL-04`：enable/disable management surface；
- `EXT-SKILL-05`：provenance + eval；
- ADR-014：Available → Installed → Enabled → Granted → Approved；
- ADR-016：Portable Skill Core + Host Capability Binding。

因此下一阶段不重新建设 Skill runtime，不新建 FinOS-specific Skill type，不把 Review 产品流程搬进 Zebra。

---

## 2. Runtime critical path

```text
ADR-016
  |
  v
ZNX-SKILL-00 Portability Red Tests
  |
  +-- existing runtime passes ------------------+
  |                                             |
  +-- gap proven -> ZNX-SKILL-01 minimal fix    |
                                                v
                                             Gate 1
                                                |
                                FinOS Review MVP integration
                                                |
                                             Gate 2
                                                |
                                      ZNX-USKILL-01
                                                |
                                             Gate 3
```

Zebra 在 Gate 1 后可以暂时没有新代码工作；FinOS Review store、Knowledge、UI、Data Confirmation 和登录继续独立推进。

---

## 3. ZNX-SKILL-00 — Portable Skill Contract Red Tests

- Status: `Ready`
- Suggested branch: `codex/znx-skill-portability-tests`
- Suggested role: `TOOLS / CORE / EVAL / QA`
- Depends on: ADR-016
- FinOS dependency: none

### Goal

用 generic fixtures 验证 Zebra 已有 Skill runtime 是否真的满足 portable/user-skill architecture，而不是直接假设需要新 runtime 代码。

### Owned paths

建议限制在：

- `tests/agent_tools/`；
- `tests/agent_runtime/`；
- `tests/integration/`；
- `evals/fixtures/skills/`；
- 必要的 test-only host/tool fixture；
- 本任务记录文档。

如果测试证明 runtime 已满足，不修改生产代码。

### Required tests

#### Test A — system/user parity

同一 Skill 内容、同一 concrete Task grant，仅 source/scope 不同：

- tool/resource visibility 一致；
- Policy 一致；
- no hidden privilege；
- provenance/source 可以不同。

#### Test B — alternate host naming

Skill 的专业正文不依赖固定 tool name。使用两个不同 tool/resource 名称但等价的 test host，runtime 不应因为业务品牌不同产生特权路径。

该测试不要求 Zebra 自动做 semantic ontology；它只证明 runtime 不把某个 host 名称写死。

#### Test C — capability denial

Skill 可见，但一个 concrete tool/resource 未 Granted：

- 不可调用；
- Skill metadata/body 不扩大 authority；
- 不通过 fallback 暗中重新暴露。

#### Test D — attachment-only

Skill 只有用户 attachment，没有 host-private tool：

- Task 可以正常读取 Skill/attachment；
- runtime 不要求某个业务 host API 才能运行 Skill。

#### Test E — persistence isolation

Skill 输出 typed artifact candidate，但没有 host business persistence command：

- Zebra 不产生外部业务写入；
- Task/Artifact 仍可终态；
- Skill 名称不能触发隐藏 adapter。

#### Test F — resume provenance

Task suspend/resume/inspect 后：

- active Skill identity/provenance 不因 catalog 当前状态漂移；
- 至少可以追溯到启动时 component identity 和实际 `skills.read` provenance。

### Acceptance

- 所有 tests 先红/确认现状，再决定生产代码；
- 不新增 finance-specific runtime code；
- 不新增 Review/Thesis/Knowledge domain type；
- existing EXT tests/regressions 不破坏；
- 形成“existing runtime sufficient”或“明确 gap list”二选一结论。

---

## 4. ZNX-SKILL-01 — Exact Skill Grant / Producer Identity

- Status: `Conditional Ready`
- Suggested branch: `codex/znx-skill-grant-identity`
- Suggested role: `CORE / STORAGE / API / RUNTIME`
- Depends on: `ZNX-SKILL-00` 证明 gap
- FinOS dependency: none for implementation；Gate 1 consumer is FinOS

### Goal

让宿主能够可靠回答：

> 这个 Task 实际 Granted/读取的是哪个精确 Skill 组件？

需要的 identity 至少涵盖：

```text
name
version
digest
scope/source or equivalent provenance
```

### First audit

先核对：

- `TaskPreparedPayload.skill_components` 当前仅 name snapshot 的语义；
- LocalSkillCatalog metadata；
- `skills.read` completion metadata；
- workspace/session inspection；
- Artifact/output contract lineage；
- resume/handoff。

### Preferred solution order

按最小改动排序：

1. 如果现有 durable event + execution metadata 已能无歧义重建，增加统一 read projection/helper + tests；
2. 如果不能，增加 backward-compatible optional structured identity snapshot；
3. 保留旧 `skill_components` 兼容；
4. 不重写旧事件，不要求历史 Task retroactive fabrication。

### Hard non-goals

- `finos_review_skill=true`；
- FinOS artifact IDs；
- finance producer enum；
- semantic input role 自动授权；
- Plugin/Marketplace；
- mid-task mutable Skill grant，除非另立任务证明需要。

### Gate 1 acceptance

宿主可以从稳定 API/projection/event lineage 得到 exact identity，用于业务 Artifact provenance；Task resume 后 identity 不漂移。

---

## 5. ZNX-CAP-01 — Host Binding Runtime Audit

- Status: `Audit-only after Gate 1`
- Suggested branch: `codex/znx-host-binding-audit` only if code/doc changes needed
- Depends on: Gate 1

### Goal

确认 FinOS semantic input role binding 是否可以完全在 Host integration 层完成，而无需 Zebra 引入行业 capability ontology。

目标答案优先是：**no runtime change**。

检查：

- Task 已 Granted tool/resource/attachment 的发现方式；
- host 能否把这些 concrete identities 放入 Task context；
- Skill 能否自主选择可见工具；
- Artifact/input lineage 是否能记录最终 concrete refs；
- missing tool/resource 是否结构化失败而不是隐式授权。

只有 red test 证明 generic gap 时才创建 follow-up implementation card。

### Explicit non-goals

- `portfolio_positions` 之类成为 Zebra 全局 ontology；
- Skill requirement 自动寻找 provider；
- 未 Grant tool 的动态 discovery；
- FinOS account scope 进入 Zebra domain model。

---

## 6. Gate 2 — System Review Skill Integration Support

Gate 2 的 Review product code 属于 FinOS。Zebra 只提供 generic runtime。

Zebra 侧 acceptance：

- stable Task；
- exact Skill provenance；
- typed tools/resources；
- portable Artifact/output contract；
- follow-up correction；
- usage/audit；
- no implicit business write。

如果这些均由已有 runtime 满足，Gate 2 不产生新的 Zebra task。

禁止因为 FinOS 要做 Review history 就在 Zebra 增加 Review database。

---

## 7. ZNX-USKILL-01 — User/Private Skill Lifecycle Alignment

- Status: `Planned after Gate 2`
- Suggested branch: `codex/znx-user-skill-lifecycle`
- Suggested role: `TOOLS / STORAGE / API / SECURITY`
- Depends on: ADR-016 + existing EXT-SKILL-01..05 + Gate 2 baseline

### Why after Gate 2

Review MVP 先证明 portable system Skill + host binding + host save 成立；随后再迁移 user Skill source-of-truth。这样避免同时改：

- Review persistence；
- Skill package runtime；
- user Skill migration；
- FinOS UI。

### Goal

让 host/user 提供的 private Skill package 成为正常 Zebra Skill component，而不是宿主私有 runtime registry。

### Minimum target contract

```text
immutable package
  -> version/digest
  -> source/scope/namespace
  -> Installed
  -> Enabled
  -> Task Granted
  -> runtime audit/revoke
```

### Design constraints

- user-provided content is untrusted；
- package source does not grant tools；
- no hidden credential access；
- no cross-namespace visibility；
- running Task uses pinned component identity；
- revocation affects new Task first；active Task behavior follows explicit revocation policy；
- existing local/root Skills remain backward compatible。

### Non-goals

- public Marketplace；
- automatic remote update；
- package execution at install time；
- arbitrary Python/Node Plugin；
- OAuth ownership；
- FinOS business capability grant。

---

## 8. ZNX-USKILL-02 — Host Projection / Reconciliation Contract

- Status: `Planned, only if ZNX-USKILL-01 needs a host-facing read model`
- Depends on: `ZNX-USKILL-01`

### Goal

提供业务宿主读取 Skill Installed/Enabled/provenance/runtime state 的稳定 projection/API，使 FinOS 等 host 可以做自己的产品 UI，而不复制 runtime source-of-truth。

### Acceptance

- host 可以列出 namespace/user scope 下的组件；
- version/digest/source/enablement 可见；
- host business entitlement 不由 Zebra推断；
- reconciliation 有明确 cursor/version；
- FinOS 不需要共享 Zebra database。

如果现有 admin/inspection API 已足够，则本卡以“no new code / contract verified”关闭。

---

## 9. Runtime Memory Track

- Status: `Not on Review MVP critical path`

FinOS Investor Knowledge 与 Zebra Runtime Memory 已明确分层。当前不要为了“Personal Investment OS 会学习”而把业务知识塞进 `memory_records`。

未来独立任务才评估：

- runtime memory capture criteria；
- retrieval；
- namespace isolation；
- delete/export；
- conversation usefulness；
- no business-memory writeback。

该任务不得成为 Gate 2 blocker。

---

## 10. Cross-repo merge protocol

Zebra task 如果是 FinOS integration dependency，执行：

```text
1. branch from codex/finos-runtime-next
2. implement generic runtime task
3. targeted/full/static/eval gates
4. merge into codex/finos-runtime-next
5. publish exact Zebra SHA
6. FinOS integration branch tests against that SHA
7. cross-repo E2E
8. compatible SHA pair recorded in FinOS development-version record
```

不允许：

- FinOS 永久依赖未合入的 Zebra feature branch；
- 把 Zebra feature branch 直接当稳定部署来源；
- 因 FinOS deadline 绕过 Zebra generic tests；
- 直接修改 `codex/finos-runtime-alignment-integration`。

---

## 11. Done definition for Zebra cards

每张激活卡至少：

- one narrow task branch；
- explicit owned paths；
- red test/evidence；
- backward compatibility；
- no FinOS-specific domain leakage；
- targeted tests；
- repository required full/static/eval gates；
- task board/progress evidence；
- merge into `codex/finos-runtime-next`；
- if cross-repo dependency: FinOS compatibility acceptance。

---

## 12. Recommended actual start

现在 Zebra **只建议立即启动一个代码/测试任务**：

```text
ZNX-SKILL-00 Portable Skill Contract Red Tests
```

它完成后再决定：

```text
if exact producer identity insufficient:
    start ZNX-SKILL-01
else:
    close Gate 1 with contract evidence
```

不要同时启动 user Skill upload、runtime memory、Plugin、Marketplace 等多条线。

这保证 Zebra 继续是通用 Agent Runtime，而不是被 FinOS 下一阶段产品计划反向塑造成金融专用运行时。
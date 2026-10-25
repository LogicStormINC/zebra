# CA-P3-02Y — Durable explicit same-Run Surface revision prerequisite
- Status: Review; fresh make test 11075 passed/3052 conditional skips; make check passed; unchanged SDK check/156 tests passed. Candidate Chromium/WebKit React first Worker/UI terminal then explicit same-Run Native revision, lost-reply two-BFF GET-only/current mapping CAS passed. Native production/SDK unchanged; final published-source consumer evidence separate. dependencies audited 2026-10-25: published U8a7e0d5/X7b5f8482; user-authorized stacked continuation, not main integration.
- Human owner Luke Ding; executor Codex; branch codex/ca-p3-02y-explicit-surface-revision.
- Owned paths: docs/CA-P3-02Y_explicit_surface_revision.md; docs/evidence/ca-p3-02y/; docs/{AGENT_TASKS.md,实施任务拆解与阶段验收.md}; PROGRESS.md; WORKLOG.md; task_plan.md.
- Boundary BEFORE code: atomic Task/Surface/RUN at admission revision1 may advance directly to explicit surface_mount of the exact same Runtime/Thread/Task/Run and original encrypted credential. Preserve legacy task/open/mount ancestry. Validate current authority/CAS and known successful original; pending/unknown blocks new UUID or changed input. One authorized new mount dispatch then original GET-only across BFF replicas/restart. No automatic rebind/reclaim, new Run, React revision lifecycle or cancellation claim. This prerequisite fixes a traced BFF ancestry mismatch before broader SDK multi-Run work.
- DDD: BFF owns encrypted originals and mapping CAS; Native owns Surface/Profile/Controller and immutable original results. Reuse atomic-surface/1, public Client Surface metadata and existing Native APIs; no schema/Worker/Python/React/core SDK change or new dependency. Credentials stay BFF.
- Acceptance: deterministic shared-PG ancestry/negative/CAS/unknown tests, actual React first Run -> Worker/approval/UI/terminal followed by explicit same-Run native revision, lost reply/new-operation refusal/two BFF restart/GET-only/current mapping and original receipt preservation. Same-source old core flow, both make test/check, SDK baseline and formal evidence. Preserve mock/history/receipts/Coverage; no deploy/production migration/main merge/npm/production HA claim.

## 依赖复核与实施顺序

U/X已提供显式React初始捕获和原子首RUN，但不承诺多轮或修订。真实调用链为React capture -> BFF Admissions revision1 -> Native Task/Surface/RUN原201 -> BFF mapping -> Worker审批/UI/receipt/terminal。现有Admissions只接受旧task_create -> surface_open -> surface_mount三步；它无法消费原201中嵌套surface.session_credential，因而拒绝初始原子准入之后的显式修订。

选择修复共享Admissions的祖先检查，沿用公开atomic-surface/1；不通过额外surface_open绕过（会创建多余会话/Controller），不放宽Runtime/Thread/Task/Run或凭据匹配，也不把新Run塞入旧原操作。先验证持久BFF修订前置，再分别推进React新快照/接管生命周期及多轮Run；本片不把后两项标为完成。

## DDD与状态转换

| 当前持久头 | 允许的新命令 | 约束 |
| --- | --- | --- |
| revision1，原atomic-task-run-surface/1 task_create成功201 | 显式atomic-surface/1 surface_mount | 同Runtime/Thread/Run，Task等于原task_id，非空凭据精确等于原surface.session_credential |
| revision1，旧Task成功 | 旧surface_open | 保留已有Task匹配/无凭据检查 |
| 后续已完成Surface头 | 旧surface_mount | 保留已有Task/Run/原凭据与CAS检查 |
| 任一pending/unknown | 只观察原operation | 不新建UUID、不改输入、不自动POST或重领Controller |

BFF BC-INTEGRATION拥有加密原请求、版本CAS和产品身份授权。Native拥有当前Profile/Surface、绑定修订/Controller和密封原结果；Go不读Native数据库。先持久claim未知意图，再仅一次Native POST；响应丢失后两个BFF进程/重启只GET该原收据。新显式修订本身可按Native既有合同更新绑定摘要/修订并轮换fence；读取/恢复绝不再次mount或轮换。
原子首RUN的密封结果是历史事实，新UI状态不能覆盖它。后续读取当前有效性仍由Native查询确认；拿旧原201不等于旧Controller仍有效。新映射使用现有Service.Install当前权威观察与独立CAS；收据已知成功但映射CAS失败时保留原收据，不重新派发修订。

## 交互流程

1. 完成已有真实React Hook首RUN、Worker审批、唯一DOM效果、持久receipt和Worker终态；实际卸载首个React owner。
2. 可信产品明确创建同Run的新Surface修订操作；使用原surface凭据、当前业务身份和平台注册绑定，指定更高ui_revision。此时不是自动React重新挂载，也不代表新的Worker任务已执行。
3. BFF校验祖先/CAS并记录加密原请求，公开atomic-surface/1只POST一次。测试故意丢响应，状态保留unknown；新UUID、改输入和新Run均拒绝。
4. 两个BFF实例在重启后GET同原收据，确认同binding、递增修订及新digest/fence。只投影公开metadata给页面；credential/fence始终留BFF。
5. BFF通过原收据的当前权威观察安装映射，旧CAS拒绝；再次重启仍解析同Task/Run/Client和新fence。原Task/RUN与修订收据摘要不变，所有恢复无额外POST。

## 验证与证明边界

新增共享PG回归覆盖八种祖先/目标/凭据拒绝、unknown/new-UUID/改输入拒绝、两个service实例只读恢复、旧原收据不变、下一修订沿用旧路径。公开联合固定Native源码、实际Python导入、SDK包、Go源和二进制摘要；Chromium/WebKit新React首轮加显式BFF修订，再以同发布源运行旧core流程。两仓库make test/check及SDK全量检查/测试另录实际结果。

此处证明的是准入修订与当前映射恢复，不是React已接管新修订、Readable新值已进入新Run、Worker已执行第二轮、后端安全取消或外部副作用不存在。已提交原准入不提供非提交/取消证明；修订的旧atomic-surface终止规则不升级首RUN原v5证明。无新Native接口/Worker/schema、React/core SDK生产改动或依赖；不重写旧合同、不修改前端mock、历史数据、原收据和Coverage。无部署/生产迁移/main合并/npm发布；生产HA/QPS与真实厂商账号仍独立验收。

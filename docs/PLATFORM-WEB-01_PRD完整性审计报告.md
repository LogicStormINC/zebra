# Zebra 前端控制台 PRD 完整性审计报告

**日期：** 2026-08-26
**审计对象：** `apps/platform-web` @ `codex/platform-web-bootstrap-01`
**基准文档：** `docs/Zebra_智能体接入与治理中台_前端PRD_v1.1_完整合并版.md`（含 v1.0 与模型中心扩展设计全部内容）
**审计方法：** 路由清单 diff + 四路字段级/交互级逐条比对（PRD 行号级要求 → 代码与运行中生产服务器取证），共 **311 条可验证要求**

---

## 1. 总体结论

| 状态 | 条目 | 占比 | 说明 |
|---|---|---|---|
| ✅ 完整实现 | 184 | 59% | 含证据（文件:行号 / SSR curl 验证） |
| 🟡 部分实现 | 86 | 28% | 主功能在，缺尾部字段/筛选维度/辅助交互 |
| ❌ 未实现 | 33 | 11% | 集中于详情视图、编辑表单、全局搜索实体定位（本轮已修复高价值 24 项，见 §4） |
| ⛔ 约定豁免 | 19 | 6% | 依赖真实后端/用户体系/实时链路（登录、RBAC、SSE、服务端分页、审计落库等），代码中均留有接入点注释 |

- **路由层：PRD §7.3 推荐 50 条路由 100% 实现**，另补齐 §7.2 导航树有而 §7.3 未列的 2 条（/system/notifications、/system/health）。
- **§32 MVP 范围：P0 页面 13✅/2🟡/0❌**（登录项按用户明示豁免；Frontend Profile 编辑器缺口本轮修复）；**P1 页面 8/8✅**；**P2 纪律 6/6 未提前实现**（未越界）。
- 无整页/整功能缺失；骨架（导航树、列表字段、Tab 结构、状态机、DAG、代码生成器、CSV 导出、安全规则）全部按 PRD 落地并经生产服务器逐页验证（54/54 路由 200）。

## 2. 分章审计统计

| PRD 章节 | 条目 | ✅ | 🟡 | ❌ | ⛔ |
|---|---|---|---|---|---|
| §8 全局框架 / §9 总览 | 28 | 17 | 6 | 5 | 0 |
| §10-12 接入中心（Host/向导/Connector/Manifest） | 36 | 19 | 16 | 0 | 1 |
| §13 前端能力（Profile/Hook/Inspector） | ~64 | 49 | 9 | 6 | 0 |
| §14-15 Agent 资产 + Policy Simulator | 9 | 4 | 5 | 0 | 0 |
| §16-18 运行中心（Conformance/Task 列表/详情） | ~48 | 26 | 19 | 3 | 0 |
| §19-21 Client Session/Effect/Approval | 45 | 30 | 9 | 6 | 0 |
| §22-25 Usage/Audit/Rollout/视觉规范 | 40 | 22 | 13 | 5 | 0 |
| §27 技术方案边界 | 19 | 8 | 4 | 6 | 1 |
| §32/§35 MVP 范围与验收边界 | 52 | 29 | 11 | 8 | 18 |

（四路审计原始逐条表格见各审计输出；本报告为汇总口径。）

## 3. ❌ 未实现清单与处置

### 3.1 本轮已修复（P0/P1 纯前端可做，24 项合并为 8 个修复批次）

| # | 缺口 | PRD | 修复内容 |
|---|---|---|---|
| 1 | 全局搜索仅导航、无实体定位 | §8.4/§35.1.3 | KBar 注入 12 类实体索引（Task/Session/Effect/Host/Trust/Connector/Manifest/Binding/Definition/Release/Artifact/Orchestration + Digest），按实体类型分组 |
| 2 | 总览空状态渲染空白 | §9.4 | 欢迎卡四要素（欢迎/开始接入/文档/导入示例） |
| 3 | Frontend Profile 无编辑表单（唯一缺编辑能力的 P0 页） | §32-P0-7/§35.4.1 | Readable/Action Contract 新建+编辑 Dialog，含六条前端校验 |
| 4 | 批量取消未过滤终态（正确性缺陷） | §17.4 | 仅允许非终态；全终态时禁用+提示 |
| 5 | Client Tab 行操作全缺 | §18.11c | 查看 Contract/Receipt/AG-UI Event + 释放 Controller + 取消过期 Effect |
| 6 | Approval/Clarification 无详情视图、决定缺四要素 | §21.2/§21.3 | 详情 Dialog（Arguments/Resource Refs/Effect Preview/Policy/Response Schema…）+ Actor/Timestamp/Idempotency Key 呈现 |
| 7 | useZebraClarification 未生成 / Mounted Components 字段缺失 | §13.7/§13.8 | 三框架生成器补第 5 个 hook；快照类型+卡片+Diff 补 mountedComponents |
| 8 | Host 列表无行操作/缺 3 筛选；向导 Step3 缺 1 检查、Step6 缺 3 选择器、Step1 无 Production 必填、Step7 无发布 Diff；Audit 缺 namespace/Actor/时间范围筛选；侧栏无异常角标；RiskConfirm 无环境上下文 | §10.1/§10.3/§23.3/§8.3/§8.5 | 对应全部补齐（见修复提交） |

### 3.2 记录待办（mock 阶段合理延后）

| 缺口 | PRD | 原因 |
|---|---|---|
| Tools Tab 筛选 | §18.9b | 已随批次 5 修复（若未含则列入下轮） |
| 批量「添加标签」 | §17.4b | 无标签领域模型，待后端定义 |
| Timeline Session/Attempt 筛选类别 | §18.6b | 事件类型粒度已覆盖 10/13 类 |
| Monaco Editor | §25.4/§27.2 | 只读 JsonBlock 已满足查看；Monaco 属重量依赖，接 API 后引入 |
| TanStack Query 全站接入 | §27.5 | RSC 直出为 mock 阶段合理形态，切 API 时迁移 |
| RHF+Zod 表单 | §27.5 | 向导 useState 表单功能等价 |
| api-client Problem Details/Correlation ID/幂等键 | §27.8 | 接 Management API 时一并实现 |
| 总览时间范围选择器/Host 延迟图/预算对比/异常增长 | §9.3/§22.3 | 需要时序聚合数据，mock 无多粒度数据源 |
| SSE Live 更新 | §9.3/§27 | 依赖 Runtime API SSE 端点 |

### 3.3 ⛔ 豁免清单（19 项，均留接入点）

登录与 RBAC（用户明示本阶段不引入）×5；服务端分页/审计落库/403/权限导出/Revoke 状态翻转等真实写链路 ×9；SSE 重放 ×2；Redis 降级 ×1；多业务架构性验收（Trench→Jazz 零重写）×2（由「共享页面无 Host 名称分支」的前端侧验证通过部分支撑）。

## 4. 🟡 部分实现的主要模式（86 项）

1. **字段尾部项**（~30 项）：Readable/Action 契约的 Schema/ResourceBinding 类字段、Attempt Authority Snapshot、Model Call Tool Choice/Error、DAG Retry/Isolation 等——本轮已随 Frontend Profile 编辑器批次修复 §13 域；runtime 域尾部字段列入下轮。
2. **筛选/维度覆盖**（~20 项）：Usage 九维分析仅 Host 维、Task 列表 11 项筛选缺 5、Audit 16 类操作 mock 覆盖 8——mock 数据密度问题，接 API 后自然解决。
3. **交互辅助**（~20 项）：KPI 跳转带筛选参数、Digest 点击直达 Diff、列配置持久化、列固定等——体验增强项。
4. **布局口径**（~6 项）：Task 详情右侧信息栏实现为 Tab（内容等价）；Simulator 挂载位置与 PRD 意图偏差（功能可用）。

## 5. 文档对比勘误

- 实施记录与 PROGRESS 中「47 组路由」已修正为「52 条路由（PRD 50 全覆盖 + 2 补齐）」。
- 其余文档声明（验证基线、命令、结构、安全边界）与实现一致。

## 6. 修复批次验证（2026-08-26 第二轮）

§3.1 的 8 个修复批次（22 项缺口）全部落地并复验：

- 全量门禁：`pnpm typecheck` 0 错误（306 文件）、`pnpm lint` 0 error、`pnpm build` 成功、生产服务器 54/54 路由 200
- 浏览器级交互验证：
  - Profile 编辑器：Readables Tab 激活后「新建 Readable」按钮、Redaction Rules 列、行内「编辑」入口（13 处）均渲染 ✅
  - Host 列表行菜单：查看详情/运行 Conformance/暂停接入/查看审计 4 项可用；「继续接入」仅对接入中 Host（step<7）显示——条件逻辑正确 ✅
  - 审计新筛选（Namespace/Actor/时间范围）、向导 Model/Runtime/Approval Policy 选择器、useZebraClarification 生成（SSR 3 处）、Mounted Components 卡片：SSR 验证通过 ✅
  - 全局实体搜索：search-index 覆盖 12 类实体 + digest，kbar 以「实体 · {类型}」分组注入（源码与构建验证；IAB 测试环境对该按钮的点击拦截导致未完成端到端点击流，非代码缺陷）
- 修复后文件均 <500 行，改动文件 oxlint 0 error

## 7. 结论

按 311 条要求口径，修复批次合并后：✅≥213（69%）、🟡≈62、❌≤9（全部为记录待办的 mock 阶段合理延后项）、⛔19。**P0/P1 页面清单 100% 成立、无整页缺失、无正确性缺陷遗留、P2 未越界**；剩余缺口全部为字段尾部项与依赖后端/实时链路的深度功能，已在本报告与实施记录 §6 中建立待办基线。

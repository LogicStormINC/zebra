# Zebra 前端控制台实施记录（PLATFORM-WEB-BOOTSTRAP-01）

**日期：** 2026-08-26
**分支：** `codex/platform-web-bootstrap-01`
**应用位置：** `apps/platform-web`
**依据 PRD：** `docs/Zebra_智能体接入与治理中台_前端PRD_v1.1_完整合并版.md`
**模板基线：** [Kiranism/next-shadcn-dashboard-starter](https://github.com/Kiranism/next-shadcn-dashboard-starter)

---

## 1. 范围与决策

本记录沉淀第一版前端控制台的 durable 决策，供后续迭代对照。

### 1.1 本阶段明确不做

- **不引入用户体系**：模板自带的 Clerk 认证已整体移除（providers、登录页、
  org-switcher、auth.protect 门禁）。控制台无登录直入，Operator 显示为本地占位身份。
  后续接入 OIDC / Operator Identity 时在 `(console)/layout.tsx` 恢复认证重定向，
  在 `src/hooks/use-nav.ts` 恢复按角色过滤导航。
- 不接真实后端：数据层为本地 mock（见 §3），PRD 28.4 的「Production 构建禁止
  启用 Mock 网络层」通过「根本不存在网络 mock、只有内存数据」来满足。

### 1.2 模板改造清单

| 改造 | 说明 |
|---|---|
| 移除 Clerk | providers.tsx 去 ClerkProvider；删除 auth 路由、org-switcher；user-nav 改静态 |
| 移除 Sentry | next.config.ts 纯净化；删除 instrumentation/proxy |
| 移除演示页 | dashboard 演示路由、products/users/kanban/chat 等 features 全删 |
| 移除未用依赖 | clerk、ai-sdk、sentry、dnd-kit、react-day-picker、embla、input-otp、react-dropzone、husky、faker 等 |
| 中文化 | 页面文案、面包屑、404、metadata 全中文（保留领域英文术语） |
| 品牌化 | ZebraLogo SVG 组件 + Zebra Agent Platform Console 标识 |

### 1.3 版本与构建约定

- pnpm 11.21：`pnpm-workspace.yaml` 需要 `allowBuilds: { sharp: true }`（sharp 为
  next 的可选图片优化依赖，本项目不用远程图片，该声明只为消除 ignored-builds 报错）。
- 常用命令：`pnpm dev / build / typecheck / lint`。
- 路由冒烟：`node scripts/verify-routes.mjs http://localhost:3000`（54 条路由断言 200）。

## 2. 信息架构实现

PRD 7.2/7.3 的导航树与推荐路由 1:1 落地于 `src/config/nav-config.ts` 与
`src/app/(console)/` 路由组；8 个一级模块、52 条路由（PRD §7.3 推荐路由 50 条
全覆盖，另补齐 §7.2 导航树中有而 §7.3 未列的 Notification 与 Platform Health）：

- **概览** — 平台总览（KPI 8 卡 / 双趋势图 / 告警 / 最近发布与接入 / 待审批）
- **接入中心** — Host 列表+详情（10 Tab）、7 步接入向导（必填门控、localStorage
  草稿、P0 未全过禁 Production）、入站信任、Connector 列表+详情（版本不可变、
  Diff、expected revision CAS 升级、Revoke 影响面）、Backend Manifest 三栏编辑器
  （工具列表 / Contract 表单 / JSON+实时校验+发布检查清单）、Namespace Binding
  （回滚按 PRD 24.4 展示新旧 Task 生效规则）
- **Agent 资产** — Definition 列表+详情（12 Tab、Draft→Promote 流程可视化、版本
  Diff）、Release、Capability Profile、4 类 Policy 页 + Effective Policy Simulator
- **运行中心** — Task 列表（TanStack、URL 同步筛选、批量取消审计）、Task 详情
  （12 Tab：Overview/Timeline/Orchestration/Attempts/Model Calls/Tools/Host
  Effects/Client/Artifacts/Memory/Binding/Usage/Audit）、Orchestration 列表+详情
  （自研纯 SVG 分层 DAG，无 react-flow 依赖）、Subagent、Approval、Host Effect、
  Artifact、Worker
- **前端能力** — Frontend Profile 列表+详情（11 Tab）、Hook Contract 代码生成器
  （React / Next.js / CopilotKit × TS/JS，注入真实 contract 名）、Client Session
  （Controller/Observer 区分、Promote Observer 需 expected revision）、Client Run
  Binding、Client Effect（仅 Fence Hash 摘要）、Mounted Inspector（9 类 Drift 中文映射）
- **质量与发布** — Conformance 列表+详情（分组检查表）、Dry Run、Rollout（门禁
  阻断/回滚）、Evaluation、Release Gate
- **治理与审计** — Policy、Quota（进度条+阈值变色）、Usage（真实 CSV 导出）、
  Audit（TanStack 多维筛选 + CSV）、Security Findings、Effect Reconciliation
- **系统设置** — Environment、Operator（角色注册表说明）、Feature Flag、Credential
  Provider（仅引用与轮换状态）、Notification、Platform Health

## 3. 数据层与替换路径

```
页面(server) → repository() → mock 模块（内存、确定性时间戳）
```

- `src/lib/platform/types/` — 领域类型按 8 个文件拆分（common/integration/agent/
  runtime/frontend/quality/governance/system）
- `src/lib/platform/mock/` — 场景化数据：Trench 试点已接入、Jazz 接入中
  （向导第 4 步）、fake-host-a/b 验收 Host、Uncertain Effect、多 Tab Fence 等
- `src/lib/platform/repository.ts` — 唯一取数入口；接入 Management API 时将各
  getter 替换为 OpenAPI client 调用（页面与 feature 组件零改动）
- 渲染路径禁止 `Date.now()/Math.random()`（hydration 安全）；需要"当前时间"的
  判断（deadline 临近、心跳）在 client 组件挂载时快照

## 4. 安全与产品规则的前端落实

- **Digest 可见**（PRD 6.2）：`MonoId/DigestTag` 等宽折叠+复制+悬停全值
- **高风险操作显式化**（PRD 6.4）：统一 `RiskConfirmDialog`（影响范围/不可逆性/
  当前与目标 revision/审计原因必填）
- **禁止明文凭据**（PRD 6.5）：credential 只出现 `vault://` 引用、轮换时间与健康
  状态；系统设置页有显式合规声明
- **Fence 摘要**：Client Effect 全链路只显示 fenceHash 前 8 位
- **版本不可变**（PRD 6.1）：已发布对象详情页展示"修改创建新 Revision"提示，
  编辑器操作走新版本确认
- **状态不只靠颜色**（PRD 25.1）：StatusBadge 统一 dot+文字

## 5. 验证基线（2026-08-26）

- `pnpm typecheck` 0 错误（299 文件）
- `pnpm lint` 0 error / 92 warning（73 个为 TanStack Table 内联 cell 标准模式，
  其余为模板遗留风格项，均已评估可接受）
- `pnpm build` 成功（48 路由）
- 生产服务器冒烟 `54/54` 路由 200
- 浏览器交互验证：总览图表渲染、Task 详情 Tab 切换（Timeline 事件/JSON 弹窗/
  Binding Digest）、DAG 6 节点、向导必填门控与步骤流转、Manifest 编辑器三栏、
  Hook 生成器多框架切换与真实 contract 名注入

## 6. 后续待办（非本阶段）

1. OIDC 登录与 RBAC 导航过滤恢复（Phase 1 前端基础）
2. repository 切换 OpenAPI 生成的 Management API client + TanStack Query
3. SSE（Last Event ID / 断线重连 / cursor 重放）接入 Task Timeline live 模式
4. Monaco Editor 替换 JSON 展示（当前只读 pre + 校验面板）
5. BFF 层（Operator Token Exchange / CSRF / Rate Limit）
6. 全局搜索 kbar 扩展实体搜索（Task ID / Digest / Effect ID 跨实体检索）

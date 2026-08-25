# Zebra Agent Platform Console（apps/platform-web）

Zebra 智能体接入与治理中台前端 — Agent 接入、能力适配、发布治理、运行观测、前端 Hook 管理与安全审计的一站式平台控制台。

- 依据文档：`docs/Zebra_智能体接入与治理中台_前端PRD_v1.1_完整合并版.md`
- 模板基线：[next-shadcn-dashboard-starter](https://github.com/Kiranism/next-shadcn-dashboard-starter)（已移除 Clerk 用户体系）
- 当前阶段：**不引入用户体系**（无登录门禁，Operator 为本地占位身份），数据层为本地 mock（通过 `src/lib/platform/repository.ts` 统一访问，后续替换为 Management API Client）

## 技术栈

- Next.js 16（App Router）+ React 19 + TypeScript
- Tailwind CSS 4 + shadcn/ui（base-ui 版）
- TanStack Table / Query、nuqs（URL 筛选状态）、recharts、kbar（⌘K 全局搜索）
- 状态：zustand（环境上下文）

## 命令

```bash
pnpm install
pnpm dev          # 开发服务器（http://localhost:3000，自动跳转 /overview）
pnpm build        # 生产构建
pnpm typecheck    # tsc --noEmit
pnpm lint         # oxlint
```

> pnpm 11 提示 sharp 构建脚本被忽略属正常（sharp 为 next 的可选图片优化依赖，本项目不使用远程图片）。

## 结构

```
src/
├── app/
│   ├── (console)/          # 控制台 Shell（侧边导航 + 顶栏 + 环境条）
│   │   ├── overview/       # 平台总览
│   │   ├── integrations/   # 接入中心：Host、向导、Trust、Connector、Manifest、Binding
│   │   ├── agents/         # Agent 资产：Definition、Release、Capability、Policy
│   │   ├── runtime/        # 运行中心：Task、Orchestration、Subagent、Approval、Effect、Worker
│   │   ├── frontend/       # 前端能力：Profile、Hook Code、Client Session/Effect、Inspector
│   │   ├── quality/        # 质量与发布：Conformance、Dry Run、Rollout、Evaluation、Gate
│   │   ├── governance/     # 治理与审计：Policy、Quota、Usage、Audit、Security
│   │   └── system/         # 系统设置：Environment、Operator、Flag、Credential、Health
│   ├── layout.tsx          # 根布局（主题、字体、Provider）
│   └── page.tsx            # 根路径 → /overview
├── features/<domain>/      # 领域 feature 组件（client）
├── components/
│   ├── platform/           # 平台共享组件（PageHeader、StatusBadge、MonoId、RiskConfirmDialog 等）
│   ├── ui/                 # shadcn/ui 组件
│   └── layout/             # Shell 组件（sidebar、header）
├── hooks/                  # use-data-table、use-breadcrumbs 等
└── lib/platform/           # 领域类型 / mock 数据 / repository（数据访问层）/ 状态映射 / 格式化
```

## 数据边界（PRD 27.8 / 28.4）

- 页面禁止手写散落 fetch，统一走 `src/lib/platform/repository.ts`
- 当前 repository 读取本地 mock；接入 Management API 后替换为 OpenAPI 生成的 client，页面组件保持不变
- Production 构建接入真实 API 前不启用任何 mock 网络层

## 安全边界（PRD 6.5 / 34.5）

- 页面只显示 credential_ref / workload_identity_ref / 轮换时间 / 健康状态，任何明文 Secret 不进入页面与日志
- Client Effect 只显示 Fence Hash 摘要，不显示原始 Fence Token
- 高风险操作统一使用 RiskConfirmDialog（影响范围 + 审计原因必填）
- 已发布版本不可变；修改一律创建新 Revision

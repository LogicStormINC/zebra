# Zebra Cloud Agent 与 React 组件库优化实施方案 v1.0

状态：本地实施完成，真实任务与生产发布验收待外部环境
更新日期：2026-09-26

## 1. 目标与边界

交付能可靠完成真实任务的 Zebra Cloud Agent，以及可直接嵌入 React 应用的组件库。
Trench 是首个消费者，但不是 Agent 的产品边界。前端只支持 React；不建设 Vue、
Angular、Web Components 或跨框架渲染层。

保持既有模型和思考强度，不重新引入固定的交互式模型/工具调用次数上限。
PostgreSQL 继续作为 Cloud 执行与受治理记忆的权威存储，Redis 不成为记忆权威源。
不重写 Harness、事件存储、已有 TypeScript SDK 或 Trench 的业务 BFF。

优化同时覆盖：真实任务成功率、结果可信度、异常恢复、响应体验、React 接入成本、
发布可靠性。自动测试通过、浏览器验收通过和生产部署通过是三个独立证据层级。

## 2. 当前基线

- Cloud Runtime 已有 durable events、无状态 Worker、工具/策略/审批、Artifact、恢复和上下文机制。
- 确定性发布 Eval 使用脚本模型和模拟工具，证明协议正确，不代表真实任务完成率。
- `@zebra-agent/react` 已有 Provider/hooks；实施必须扩展现有包，不创建第二套 React SDK。
- `contracts`、`client-core`、`react`、`ui-contracts` 仍以源码为入口，且有跨包源码相对引用。
- Trench 使用 React 19、Next.js 15、Ant Design X、Vitest 和 Tailwind 4。

## 3. 目标架构

```text
React Host
  └─ @zebra-agent/react
       ├─ @zebra-agent/client-core
       ├─ @zebra-agent/contracts
       └─ Host adapter / BFF
             └─ Zebra Cloud API → durable Worker
```

宿主拥有登录、用户/组织、商业权限、导航、业务工具、下载鉴权和品牌配置。
Zebra 拥有任务、事件、策略、审批、恢复、Artifact、记忆治理和使用量证据。
React 包只呈现权威状态和处理交互，不持有 Host Grant、工作负载密钥或模型密钥。

## 4. 实施工作包

### S0 / REACT-PKG-01：包工程基线

1. 固定并验证 TSDX 2.x、Node、Bun 与 pnpm workspace 的组合。
2. 修复四个现有 SDK 包的正式依赖边界和构建产物入口。
3. 生成 ESM、CJS 和声明文件；React 为 peer dependency，不进入 bundle。
4. 用真实 tarball 分别在 Vite React 和 Next.js 消费者中安装验证，不使用源码 alias。
5. 验证包内容不包含密钥、环境文件、测试数据或仓库内部路径。

首个出口：四包独立构建、现有 SDK 测试不退化、打包内容可解析。

### S1 / REACT-UI-01：React 组件库

扩展现有 `@zebra-agent/react`，对外提供一体化 `AgentChat` 和有限的可组合组件：

- `AgentComposer`
- `AgentMessageList`
- `AgentActivityGroup`
- `AgentApproval`
- `AgentClarification`
- `AgentArtifacts`
- `AgentMemorySettings`

会话列表可选；路由和会话列表数据由宿主控制。禁止导出全部内部小组件形成不稳定 API。
样式以显式 CSS 文件和 CSS variables 交付，不要求宿主扫描组件库的 Tailwind 源码，
不注入全局 reset。支持暗色、浅色、窄屏、键盘和减少动画。

### S2 / REACT-UX-01：任务生命周期体验

- 本地提交、服务端接受、排队、执行、等待用户和终态必须区分。
- 新会话到聊天态复用同一 Composer，保留输入、附件和焦点。
- 执行过程使用公开状态，不展示私有思维链；完成后整体折叠并保留展开入口。
- `completed`、`partial`、`blocked`、`failed`、`cancelled` 不得混为一类。
- 重连、继续当前任务和重新执行原请求是三个不同动作。
- 写操作结果未知时先对账，不无条件重放；错误提供诊断 ID，不暴露敏感栈。

### S3 / AGENT-LIVE-EVAL-01：真实任务评测

建立 60 个固定真实任务，覆盖问答、研究、代码修改、文件交付、业务操作、跨会话记忆
与恢复，每类 10 个。先打通 12 个代表性任务，再扩充全集。开发集和留出集分离，
每个真实模型案例至少重复三次。

分别统计首次成功率、最终成功率、人工介入、误报完成、恢复成功、工具重复、引用支持、
首个真实反馈时间、总耗时和单成功任务成本。确定性测试、真实依赖集成和真实模型任务
分开报告；脚本 Eval 不再外推为 Codex 产品效果百分比。

### S4 / AGENT-QUALITY-04：结果级验收

- 关键词任务类型推断只作保底，不把“提到操作”当成“授权操作”。
- answer 验证是否回答目标；research 验证主张被来源支持。
- change 验证预期 diff 与针对问题的检查；create 验证 Artifact 可用和内容合格。
- operate 验证目标系统状态；HTTP 200、工具完成和模型自述不等于操作完成。
- 临时读错误退避；参数错误修正；权限错误请求授权；未知写入先对账。
- 无新证据的重复动作停止并重新规划，不通过统一调用上限截断正常长任务。

### S5 / MEMORY-CONTEXT-02：记忆、上下文和缓存

验证同义召回、偏好反转、临时偏好、跨项目隔离、删除抑制和无关记忆干扰。
自然画像提取先以候选影子模式评估；保持用户确认边界，不把每轮聊天自动转成画像。
压缩后必须保留目标、硬约束、已完成动作、待办、已否定方案、Artifact 和权限边界。

缓存按冷启动、热循环、恢复、压缩和子任务唤醒分别计量。目标是降低单成功任务成本
和完成时间，不追求统一 99% 命中率，不以删除必要上下文换取命中率。

### S6 / CLOUD-RELIABILITY-02：可靠性和发布

覆盖重复/乱序/漏事件、游标过期、登录过期、Worker 重启和多会话并行。
在工具调用前、外部写入后和完成事件落库前注入失败，验证 Effect 对账和幂等边界。
发布冻结 Zebra/Trench commit、组件包版本、镜像 digest、迁移、协议和配置版本。
生产验收包含新旧会话、审批、记忆、Artifact、恢复和回滚；先试运行再扩大并发。

## 5. TSDX 决策

采用 TSDX 2.x，但保持当前 pnpm workspace，不为脚手架便利迁移整个仓库包管理器。
构建所需 Bun 仅作为 SDK 构建工具固定版本。必须验证 React 19、Next.js SSR/RSC、
Vite、ESM、声明文件、CSS 导出和 tree-shaking；React 18 只在矩阵通过后宣称支持。

内部包必须使用正式 workspace 依赖，禁止跨包导入 `../../other-package/src`。
React 和 ReactDOM 使用 peer dependency。交互入口保留 `use client`，模块顶层不得读取
`window` 或 `document`。重型图片导出等依赖延迟加载。

## 6. 验收矩阵

| 类别 | 验收 |
|---|---|
| 包 | clean install、pack、exports、types、CSS、React peer，无源码旁路 |
| React | StrictMode、Next SSR/RSC、Vite、移动端，无重复订阅和 hydration 错误 |
| 交互 | 中文输入、上传、切会话、滚动、折叠、键盘，无内容丢失 |
| 流 | 重连、乱序、重复、cursor 过期后与权威终态一致 |
| 动作 | 审批、暂停、取消、未知写入和重试无隐式越权或重复副作用 |
| 结果 | 编码、研究、文件和业务操作由独立检查确认实际交付 |
| 记忆 | 确认、纠正、删除、隔离和同义召回正确且不泄露 |
| 发布 | 依赖故障、Worker 重启、并发和回滚可诊断、可恢复、版本一致 |

## 7. 排期与依赖

工程日为粗估，不是交付承诺；另预留约 20% 回归缓冲。

| 阶段 | 内容 | 工程日 | 出口 |
|---|---|---:|---|
| S0 | 基线和 TSDX spike | 3–5 | 真实 tarball 可安装 |
| S1 | 包边界与组件迁移 | 6–10 | Trench 和 fixture 消费同一包 |
| S2 | 消息、审批、错误与恢复体验 | 5–8 | UI 状态矩阵通过 |
| S3 | 真实任务集与结果验证 | 8–12 | 固定任务成绩和失败归因 |
| S4 | 记忆、上下文、缓存 | 5–8 | 质量与效率收益证据 |
| S5 | 故障注入和候选发布 | 5–8 | 版本绑定、回滚、稳定性证据 |

S1 与 S3 可在 S0 后并行；S2 依赖稳定组件状态边界；S4 依赖真实评测；正式发布
依赖相应验收。现有 dirty changes 先保留归属，不重置，不混入不相关提交。

## 8. 完成度报告

冻结 100 分权重：包工程 15、React 体验 20、真实任务评测 15、质量闭环 20、
记忆/上下文/效率 10、可靠性发布 20。分别报告本地实施完成率、验收通过率、
生产发布完成率和真实任务成功率，不将其中任一指标称为“达到 Codex 的百分比”。

截至 2026-09-26，本地实施为 `100/100`：Trench 已消费正式 React 包，60 个
固定案例及 180 次防伪评测矩阵已落地，React 18/19 消费矩阵和本地 PostgreSQL
组合验收通过。该数字不代表产品验收：真实模型矩阵仍为 `0/180`，本机无
`runsc`，远端主机不可达，因此 gVisor 执行层、不可变候选、canary 和 rollback
仍无证据；生产发布完成率保持 `0%`。

## 9. 暂不实施

跨框架 UI、通用页面 DSL、插件市场、默认多 Agent、Redis 权威记忆、以更强模型掩盖
Harness 问题、固定 99% 缓存目标，以及未经真实验收的公开 npm 稳定版发布。

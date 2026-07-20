# 扩展体系威胁模型

> 状态：Phase A 契约基线
> 日期：2026-07-20
> 上游 ADR：`ADR-014_扩展体系架构.md`
> 任务：`EXT-0`

本文把扩展体系的主要威胁映射到既有或计划中的控制。它不是重写 Zebra 的总体威胁模
型，而是确认扩展新增面都落在既有安全边界之内。

## 威胁总览

| # | 威胁 | 扩展面 | 控制 | Phase |
|---|---|---|---|---|
| T1 | 不可信 Skill 正文注入指令 | Skill | `[UNTRUSTED]` 标记 + 不赋权 + 每动作走 Policy | A |
| T2 | MCP server 返回恶意/越权输出 | MCP | 不可信输出标记 + Task allowlist + Policy/Approval | A |
| T3 | Plugin 在安装或运行时执行任意代码 | Plugin | v1 声明式、不进程内 import、安装不跑 lifecycle | Locked |
| T4 | MCP Confused Deputy / token passthrough | MCP | audience/resource 校验 + token 不进 Sandbox/event/log | A(HTTP)/B(OAuth) |
| T5 | Elicitation 被用于绕过 Approval | MCP | 映射到 durable ClarificationContext，不绕过 Policy | A |
| T6 | Sampling 导致无限递归 / 预算失控 | MCP | 硬 Non-Goal，Phase A 不实现 | — |
| T7 | Marketplace 分发恶意包 | Marketplace | 签名/SBOM/扫描/撤销/kill switch + 私有云 GA gate | Locked |
| T8 | Hook 绕过 Policy 或补造成功 | Hook | 声明式、content-hash 信任、fail-open/closed 分类 | Locked |
| T9 | 远程 MCP SSRF | MCP | 复用 web egress 预检 + 强制 https + 私网拒绝 | A |
| T10 | 扩展 metadata 静默扩大 authority | 全部 | requested_capabilities 只做预览，五层状态不自动推导 | A |

## 逐项控制

### T1 不可信 Skill 正文

- 现状：`skills.list` / `skills.read` 输出强制 `[UNTRUSTED LOCAL SKILL METADATA]` /
  `[UNTRUSTED LOCAL SKILL GUIDANCE]` 前缀，metadata 设 `untrusted_procedural_guidance:
  True`。
- EXT 增量：`EXT-SKILL-01/02` 增加 digest/scope，但**不改变**不可信立场；`dependencies`
  / `allowed-tools` 只用于预检，绝不赋权。
- 残余风险：模型仍可能遵循恶意指令——但每个具体动作仍受 typed Tool + Policy +
  Approval 约束，Skill 本身无执行能力。

### T2 恶意 MCP 输出

- 现状：MCP tool 描述前缀 `Untrusted external MCP capability.`，输出有 32 KiB 上限，
  Task 级精确 allowlist，`AuthorizedMcpToolCatalog` 渐进披露桥在 Policy 前还原真实
  `mcp.<server>.<tool>`（无伪审批、无重复计费）。
- EXT 增量：`EXT-MCP-01` Streamable HTTP 复用同一披露桥与 Policy；`EXT-MCP-02` 健康
  分类不放松输出边界。

### T3 Plugin 任意代码执行

- Phase A 立场：v1 Plugin 是**声明式分发单元**，不进程内 import Python/Node/共享
  库，安装时不执行 npm/pip/uvx lifecycle，不自动改 PATH/环境/项目文件。
- 残余：若未来需原生扩展，强制走独立 sidecar / OCI / WASM runtime + 版本化 RPC +
  最小 capability；扩展崩溃不得破坏 Worker。

### T4 Confused Deputy / token passthrough

- HTTP（Phase A）：Bearer token 经 env 变量名注入，**不进 manifest / event / log /
  Artifact / 前端存储**；token 撤销后未开始调用 fail closed。
- OAuth（Phase B）：Protected Resource Metadata、Authorization Server Metadata、PKCE、
  audience/resource 校验、禁止 token passthrough——依赖 Credential Broker 云端形态。

### T5 Elicitation 绕过 Approval

- 立场（ADR-014 §7）：server-initiated elicitation 1:1 映射到既有 durable
  `ClarificationContext` + `CLARIFICATION_REQUESTED` + `WAITING_INPUT`，**复用**既有
  HITL 边界，而非新建绕过通道。
- 控制：`ZEBRA_MCP_ELICITATION=off` 全局禁用；typed `response_schema` 限制可接受响
  应；elicitation 不产生副作用，只暂停等待用户输入。
- 不变量：elicitation 绝不让服务器绕过 Policy、Approval 或不可信输出标记。

### T6 Sampling

- 硬 Non-Goal。Phase A 不实现。理由：sampling 让服务器请求 Zebra 代发 LLM 调用，涉
  及模型预算、Prompt 展示与递归限制，需要独立威胁模型与独立任务。

### T7 Marketplace 恶意包

- Locked。依赖私有云 GA gate：namespace / Credential / Egress / Sandbox 隔离 + 签名 +
  SBOM + 扫描 + 撤销 + kill switch + canary + 回滚 + 运维告警。
- 在这些条件完成前，只实现本地 Catalog/Registry 契约，不实现公共分发。

### T8 Hook 绕过

- Locked。首版只支持声明式、确定性 Hook：PreToolUse 只能 deny / require-approval；
  PostToolUse 只能加审计标签 / 提建议，不能修改结果事实；绑定 package digest，变更
  后重新审核。

### T9 远程 MCP SSRF

- 控制（`EXT-MCP-01`）：复用既有 `LocalWebGatewayTransport` 的私网解析拒绝（抽为模块
  级 `reject_non_public_resolution`）；强制 `https://`；`trusted_local` 时走 operator
  HTTPS proxy；header 值来自 Broker，不存 manifest/event。

### T10 metadata 静默扩权

- 控制：五层状态机前一状态不自动推导后一状态；`requested_capabilities` /
  `permissions` / `allowed-tools` / `dependencies` 一律只做安装预览与启动预检；Granted
  必须来自 `TaskPreparedPayload` 精确 identity，Approved 必须来自单次 Approval。

## Phase A 不放宽的边界

- Credential / Token 全链路不可见。
- internal Policy 只能保持或收窄 caller authority。
- 安装不执行包内代码。
- EventType 枚举 Phase A 不新增成员（复用既有事件 + 可选字段）。
- file-size / strict mypy / eval gate 不因扩展新增而放宽。

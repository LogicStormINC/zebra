# Zebra Agent 生产级 Runtime 实施方案 v1.0

## 1. 决策与状态

- 任务：`ARCH-129-RT-01 - Hard-Enforced Local Runtime`
- 分支：`codex/arch-129-hard-runtime`
- 状态：实现与本地/真实 Linux gVisor 验收完成，PR `#142` 已合并
- 目标：交付 Linux-first、硬隔离、可恢复、默认断网、可持续验证的
  Production Runtime v1
- 当前基线：`LocalRuntime` 仅为可信宿主进程执行，不属于硬沙箱
- Phase A A1：`os-sandbox` 已实现，macOS Seatbelt 与 Linux bubblewrap 由真实
  平台 smoke 验收；Windows 与缺失能力保持 fail closed

本任务不会通过重命名、字符串过滤或 Python 路径检查把宿主进程包装成安全
边界。显式请求生产 Runtime 而环境不满足时，必须在任何工具命令开始前失败。

## 2. 技术选型

### 2.1 Runtime Classes

| Runtime class | 后端 | 安全定位 |
|---|---|---|
| `trusted-local` | 现有 `LocalRuntime` | 明确信任的本地开发 |
| `os-sandbox` | Seatbelt / bubblewrap | Desktop/CLI 日常硬隔离 |
| `oci-rootless` | Rootless Podman 或等价 OCI CLI | 开发、兼容、单租户容器隔离 |
| `gvisor` | OCI engine + `runsc` | Linux 生产环境、不可信代码 |

生产默认目标是 `gvisor`。`oci-rootless` 不能被报告为与 gVisor 等价；
`trusted-local` 保持向后兼容，但产品和运维输出必须明确其信任等级。

### 2.2 平台矩阵

| 平台 | 状态 |
|---|---|
| Linux AMD64 + gVisor | Production v1 支持 |
| Linux ARM64 + gVisor | Production v1 支持，独立验收 |
| Linux rootless OCI | 兼容支持，较低安全等级 |
| Ubuntu 22.04 + bubblewrap | 原生 `os-sandbox`，真实 CI smoke |
| Ubuntu 24.04 + 受限 userns | capability probe 失败时 fail closed |
| macOS Seatbelt | 原生 `os-sandbox`，真实 CI smoke |
| macOS 原生 gVisor | 不支持，请求时 fail closed |
| Windows | 不支持，请求时 fail closed |

## 3. 架构边界

```text
Worker / Harness
  -> RuntimePort
       -> LocalRuntime (trusted-local)
       -> OsSandboxRuntime
            -> macOS Seatbelt
            -> Linux bubblewrap namespaces
       -> OciRuntime
            -> rootless OCI
            -> gVisor runsc

Session Event Store <- runtime authority and lifecycle evidence
Workspace Projection <- effective runtime class, engine, image and spec digest
Tool Gateway -> all command, patch, git and test execution
External Gateway/Broker -> Web, MCP, SCM and credentials
```

Session Event Store 仍是 durable authority。Runtime 负责执行隔离，不复制 Policy
状态机。Sandbox 不获得模型、SCM、MCP 或云平台长期凭证。

## 4. Runtime 合同

新增或扩展以下类型：

- `RuntimeClass`
- `RuntimeLimits`
- `SandboxSpec`
- `RuntimeCapabilities`
- `EffectiveRuntimeAuthority`
- 带有效权限摘要的 `RuntimeHandle`
- 带镜像和 spec 摘要的 `RuntimeSnapshot`

`SandboxSpec` 至少固定：

- runtime class 和实际 enforcement engine
- OCI/gVisor 镜像 digest；`os-sandbox` 不声明容器镜像
- workspace root 与读写模式
- CPU、内存、PID、tmpfs、超时和输出上限；Workspace 磁盘配额由部署存储层强制
- 网络 profile
- 容器用户、只读根文件系统和 tmpfs
- session/attempt identity

Runtime provision 后产生不可变 `EffectiveRuntimeAuthority`。恢复时 spec digest
必须相同，或者经过显式的“只收紧不扩大”比较；首版采用完全相同作为安全默认。

### 4.1 原生 OS Sandbox

- macOS 通过系统 `sandbox-exec` 加载 Seatbelt `system.sb` 基线，只开放
  Workspace 读写并显式拒绝网络；
- Linux 通过 bubblewrap 创建 user/mount/PID/network 等私有 namespace，空根
  文件系统只读挂载系统目录，Workspace 是唯一持久读写 bind；
- 执行环境由 Runtime 清空后重建，不继承宿主 API key、代理或用户环境；
- capability probe、engine 缺失、平台不支持或 authority drift 均在命令前失败；
- 整个命令从 sandbox wrapper 启动，后代进程继承同一 Seatbelt 或 namespace 边界。

## 5. OCI 硬化参数

Production Runtime 固定生成参数，不接受调用方自由拼接：

- 非 root 用户
- `read-only` 根文件系统
- workspace 是唯一可写持久挂载
- `/tmp` 为限额 tmpfs
- `cap-drop=ALL`
- `no-new-privileges`
- 禁止 privileged、host namespace、设备和 runtime socket
- PID、CPU、内存、执行时间和输出限制
- Agent phase 默认 `network=none`
- 固定镜像 digest，Agent phase 不隐式 pull
- timeout/cancel/destroy 清理整个容器进程树

OCI 命令通过参数向量调用，不使用 shell 拼接。Engine 错误输出经过边界截断，
不得回显环境和凭证。

## 6. 网络和凭证

Production v1 中，Sandbox 内普通 Agent 命令保持断网。现有 Web、MCP、SCM
能力继续在 Sandbox 外通过 Gateway/Broker 执行并接受 Policy/HITL。

- `none`：支持并由 Runtime 强制
- `mcp-proxy-only`、`git-proxy-only`：Sandbox 仍断网，代理在外部执行
- `domain-allowlist`：外部 Web Gateway 执行，Sandbox 不直连
- `setup-only`：只允许外部 Setup Egress Gateway 对精确 HTTPS URL 执行 GET；
  Sandbox 自身仍为 `network=none`
- `full-trusted-local`：只允许 `trusted-local`

任何不能由当前 Runtime 证明的网络 profile 必须拒绝，不得降级为 host network。

### 6.1 Setup/Agent 两阶段

`setup-only` 不把任意外网直接交给 Sandbox。Worker 按以下顺序执行：

1. 校验 operator 配置的域名、最终 HTTPS URL、文件名和 SHA-256；拒绝 IP、
   userinfo、query、非 443 端口和跨域 redirect；
2. 外部 Gateway 使用可选临时 Bearer Credential 下载内容寻址依赖到
   `.zebra/setup-cache`，命中相同 digest 时复用；
3. Gateway 关闭并清除 Credential 后，才启动无网 Setup Sandbox；
4. Setup command 必须保持声明的 lockfile 不变，随后生成并校验 Snapshot；
5. 销毁 Setup Sandbox，使用相同 immutable authority 启动新的无网 Agent Sandbox；
6. 将来源、hash、lockfile、SPDX 2.3 SBOM、Snapshot 和 authority 摘要写入现有
   Artifact payload store；Artifact 只记录 command hash，不记录命令或 Secret。

启用时必须同时配置：

```text
ZEBRA_SETUP_ENABLED=true
ZEBRA_SETUP_COMMAND_JSON=["/bin/sh","-c","install-from .zebra/setup-cache"]
ZEBRA_SETUP_ALLOWED_DOMAINS=files.example.test
ZEBRA_SETUP_DEPENDENCIES_JSON=[{"url":"https://files.example.test/pkg.whl","sha256":"<64 hex>","file_name":"pkg.whl"}]
ZEBRA_SETUP_LOCKFILES=uv.lock
ZEBRA_SETUP_CREDENTIAL_ENV=TEMP_SETUP_TOKEN
```

配置只保存 Credential 环境变量名；缺值、hash 漂移、lockfile 变化、非硬 Runtime、
Snapshot 不可恢复或 Artifact 持久化失败都会 fail closed。下载是只读 GET 且以
digest 缓存，因此 Worker 重启可复用已验证结果，不重放远程写副作用。

## 7. 生命周期与恢复

生命周期为：

```text
capability preflight -> provisioned -> ready -> executing
  -> suspended -> restored -> ready
  -> destroyed
```

首版不使用 CRIU，不承诺任意指令中间的进程内存恢复。Suspend 在工具边界执行：

1. 阻止新工具执行；
2. 终止或确认当前命令完成；
3. 创建 workspace snapshot；
4. manifest 固定 runtime class、image digest、spec digest 和文件来源；
5. restore 创建全新 Sandbox；
6. durable Session/Event 恢复 Harness；
7. 幂等键阻止已完成副作用重复执行。

## 8. Worker 接线

- Runtime 设置由配置层读取并严格校验；
- Worker 在构造 `LocalToolGateway` 前完成 capability preflight 和 provision；
- `LocalToolGateway` 接受注入的 `RuntimePort`，不再写死 `LocalRuntime`；
- provision 证据先写 durable event，再允许 Harness 工具执行；
- continuation/recovery 比较已有 effective authority，发生漂移则 fail closed；
- attempt 结束、异常、取消时均执行 Runtime cleanup；
- suspend/resume 使用相同 runtime class 和 spec digest。

## 9. 安全验收矩阵

必须覆盖：

- workspace 外读写、绝对路径、`..` 和 symlink 逃逸失败
- Home、SSH、宿主环境、文件描述符和 runtime socket 不可见
- setuid、capability、mount、ptrace、设备和 host namespace 失败
- fork bomb、内存、磁盘、时间和输出超限受到控制
- timeout/cancel 清理全部后代进程
- 默认网络、DNS、私网和元数据地址访问失败
- Engine、runsc、镜像或配置缺失时工具执行前失败
- snapshot 缺失、篡改或 spec 不兼容时拒绝恢复
- Worker 重启和 continuation 不扩大权限
- 日志、事件和 Artifact 不出现凭证

## 10. 实现结果

本方案已经落到 Runtime 合同、OS/OCI/gVisor adapter、Setup Egress、配置、
Worker/Tool Gateway、
暂停恢复、SQLite 投影、API/CLI readback 和 CI。硬模式启动前验证 Engine 与
handler，清理同 session 遗留容器，再创建固定安全参数的 Sandbox。容器写权限
预检失败、镜像未固定、运行时不可用、快照越界/篡改或 authority 漂移都会拒绝
执行。逐命令环境变量被硬模式拒绝，Web/MCP/SCM 仍只走 Sandbox 外 Gateway。
`setup-only` 现在通过外部内容寻址下载、Credential 撤销、无网 Setup、Snapshot
验证、新 Agent handle 和 Setup Artifact 完成两阶段交接，不向 Sandbox 注入代理
Token，也不新增 durable state 模型。

原生隔离由 macOS Seatbelt 与 Linux bubblewrap 的 `os-sandbox-runtime` matrix
验收 Workspace 读写、宿主逃逸、子进程继承和断网。容器隔离继续由 Linux CI
的 `gvisor-runtime` job 验收：校验官方 runsc SHA-512，向
Docker 注册 handler，解析 Alpine 镜像 digest，并验证 Workspace 写入、默认
断网和 Runtime socket 不可见。Seatbelt smoke 不等于原生 gVisor 验收。

首版明确不伪造进程内存 checkpoint。Production Worker 现在要求 Workspace 根
目录本身是独立、容量不超过 `ZEBRA_RUNTIME_WORKSPACE_QUOTA_MB` 的文件系统挂载
点；共享宿主文件系统、超大卷、无法读取 mount 信息或不受支持的平台都会在
Runtime 创建前 fail closed。Linux CI 使用真实 8 MiB tmpfs 写满到 `ENOSPC`，
而不是用应用层字节计数模拟 quota。`No space left on device` 被归一化为
`workspace_quota_exceeded` 并进入 Tool metadata。

本机子进程以独立进程会话启动；超时会向整个进程组发送终止信号并等待回收，
防止直接子进程退出后留下未跟踪后代。可靠性门禁固定 20 次原生 Sandbox
provision/execute/snapshot/inspect/destroy/cleanup 循环，长流门禁固定 64 个增量、
80 个重载恢复增量和取消后 5 秒无迟到完成。quota、soak、gVisor 和长流均在 CI
输出 JUnit 或 JSON 机器可读证据并保留 14 天。

Packaged Desktop 门禁不再以 Vite 浏览器预览替代桌面发行物。Tauri 依赖由
`Cargo.lock` 固定，macOS/Windows/Linux 图标进入源码，CI 在 Ubuntu 22.04
构建 `.deb`，并使用 `tauri-driver`、系统 WebKit WebDriver 与 Xvfb 驱动实际
release 二进制。测试启动真实 API、Worker 和 `os-sandbox`，验证界面公开
Runtime profile 与 `fallback_allowed=false`，并覆盖取消、审批后工具执行、
provider 失败、API 断联以及 API 重启后 durable session 恢复。证据包含 JSON
与失败现场截图并保留 14 天。

API `/health` 现在返回已解析的 Runtime profile、runtime class 和禁止静默降级
标志；Session Inspector 同时显示实际 Workspace Runtime。连接投影以当前请求
错误优先，不能因旧的成功响应把已停止的 API 继续显示为已连接。取消操作采用
有界 optimistic retry：若 live Worker 抢先写入相同 sequence，则重新读取 durable
状态后重试；不会重放模型或工具副作用。

## 11. 验证命令

```text
uv sync --frozen --all-packages --group dev
uv run pytest tests/agent_runtime tests/agent_security tests/worker
make test
make check
```

CI 包含 Linux OCI 合同、真实 Workspace exhaustion、macOS/Linux 原生 Sandbox
soak、长流与真实 gVisor smoke。真实 gVisor 环境不可用时，该 job
不得伪造成功；Production gVisor 能力保持未验收或 fail closed。

本次验收结果：本地 `1345 passed, 1 skipped`，跳过项仅为平台限定的真实
gVisor smoke；文件大小、Ruff、Mypy `361` 源文件和 `8` 个 release eval 通过。
PR `#142` 的 Backend、Desktop 和真实 Linux `runsc` gVisor job 全部通过。

Phase A A4 本地验收结果：`1484 passed, 7 skipped`；文件大小 `888` 文件、
Ruff、Mypy `412` 源文件和 release eval `8/8` 通过；Desktop 检查、Vite build、
Playwright `6` 个真实后端 E2E、Cargo check 以及 macOS release `.app` 构建通过。
Linux `.deb` 和 packaged WebDriver 证据必须由 PR CI 通过后才可计入最终完成状态。

## 12. 完成标准

- Runtime 合同、OCI 后端、Worker 接线和 durable authority 全部落地；
- 所有安全矩阵测试通过；
- Linux gVisor smoke 通过；
- 全仓测试、Ruff、Mypy、eval 和文件大小门禁通过；
- operator runbook、架构、安全状态和 README 与实际能力一致；
- `trusted-local` 与生产模式在错误和状态读回中可明确区分；
- Kubernetes、Kata、Firecracker、warm pool 和多租户调度仍明确为后续范围。

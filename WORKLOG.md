# Progress Log

## 2026-06-28 Phase 19 Closeout And Phase 20 Planning

- 执行 `P19-CLOSE-01 - Phase 19 Closeout And Next Planning`
- 新增 Phase 19 验收记录：
  - `docs/Phase19_Secret_Store_And_Broker_Credentials_验收记录.md`
- 汇总 Phase 19 已完成证据：
  - `SecretStore`
  - `LocalSecretStore`
  - `GitHubAppCredentialBroker`
  - provider-backed `failure_class`
- 将仓库主线状态推进到 Phase 20 ready
- 新增 Phase 20 starter tasks：
  - `P20-SEC-01 - Network Profile Contract`
  - `P20-INT-01 - SCM Transport Egress Guard`
  - `P20-DOC-01 - Egress Control Operator Docs`
  - `P20-CLOSE-01 - Phase 20 Closeout And Next Planning`
- Phase 20 方向依据：
  - 架构文档 `11.6 Egress Control`
  - `network none` 为默认 fail-closed posture
  - 目录规划中的 `policy/network_policy.py` 与 `credentials/egress_proxy.py`

## 2026-06-28 P20-SEC-01 Network Profile Contract

- 执行 `P20-SEC-01 - Network Profile Contract`
- 在 `packages/agent-security/src/agent_security/network_profile.py` 新增确定性网络配置契约：
  - 定义 `none`、`setup-only`、`domain-allowlist`、`mcp-proxy-only`、`git-proxy-only`、`full-trusted-local`
  - 保持 `DEFAULT_NETWORK_PROFILE=none` 的 fail-closed 本地默认值
  - 对无效 profile、空白 profile、歧义 allowlist、非 allowlist profile 附带域名列表等情况做显式拒绝
- 在 `tests/agent_security/test_network_profile.py` 增加定向回归覆盖
- 更新 `README.md`、`PROGRESS.md`、`docs/Credential_Broker_Foundation.md`，将 Phase 20 当前完成状态写回仓库
- 验证：
  - `poetry run pytest tests/agent_security/test_network_profile.py tests/agent_security/test_secret_store.py tests/agent_security/test_policy_profiles.py`
  - `uv run ruff check packages/agent-security/src/agent_security tests/agent_security`
  - `uv run mypy packages/agent-security/src/agent_security tests/agent_security`

## 2026-06-28 P20-INT-01 SCM Transport Egress Guard

- 执行 `P20-INT-01 - SCM Transport Egress Guard`
- 在 `packages/agent-integrations/src/agent_integrations/scm.py` 为 GitHub PR 执行路径增加 egress gate：
  - 从环境读取 `ZEBRA_SCM_NETWORK_PROFILE`
  - 从环境读取 `ZEBRA_SCM_NETWORK_DOMAIN_ALLOWLIST`
  - 在 credential lookup 与 transport side effect 之前先判断是否允许访问目标 GitHub API host
- 当前 direct GitHub transport 仅在以下 profile 下允许：
  - `full-trusted-local`
  - `domain-allowlist` 且 allowlist 命中目标 host
- 默认 `none` 下远程执行会返回 `failure_class=egress_policy`，并记录：
  - `network_profile`
  - `target_host`
- 保持 dry-run 与 local-only 行为不变；credential / transport 失败分类在放行 egress 后继续保留
- 更新 `tests/agent_integrations/test_scm.py` 与 `tests/api/test_session_pull_request.py`：
  - 新增默认 egress block 覆盖
  - 新增 domain allowlist 放行覆盖
  - 保持 broker / env / GitHub App / transport failure 审计语义
- 验证：
  - `poetry run pytest tests/agent_integrations/test_scm.py tests/api/test_session_pull_request.py`
  - `uv run ruff check packages/agent-integrations/src/agent_integrations tests/agent_integrations tests/api/test_session_pull_request.py`

## 2026-06-28 P20-DOC-01 Egress Control Operator Docs

- 执行 `P20-DOC-01 - Egress Control Operator Docs`
- 更新 `docs/operator_runbook.md`：
  - 增加 `ZEBRA_SCM_NETWORK_PROFILE` 与 `ZEBRA_SCM_NETWORK_DOMAIN_ALLOWLIST` 配置说明
  - 明确当前 direct GitHub transport 仅允许 `full-trusted-local` 或命中 API host 的 `domain-allowlist`
  - 增加默认 `network_profile=none` 下的阻断示例
  - 将 `egress_policy` 纳入 delivery audit `failure_class` 说明与 remediation 指引
  - 明确测试后要回退到 `network_profile=none` 的安全默认值
- 更新 `README.md`、`PROGRESS.md`、`docs/AGENT_TASKS.md`，将 Phase 20 文档状态与下一张 closeout 任务写回仓库

## 2026-06-28 P20-CLOSE-01 Phase 20 Closeout And Next Planning

- 执行 `P20-CLOSE-01 - Phase 20 Closeout And Next Planning`
- 新增 Phase 20 验收记录：
  - `docs/Phase20_Egress_Control_Foundations_验收记录.md`
- 汇总 Phase 20 已完成证据：
  - `NetworkProfile`
  - fail-closed `DEFAULT_NETWORK_PROFILE=none`
  - SCM egress gate with `failure_class=egress_policy`
  - operator runbook remediation and rollback guidance
- 将仓库主线状态推进到 Phase 21 ready
- 新增 Phase 21 starter tasks：
  - `P21-INT-01 - SCM Proxy Transport Contract`
  - `P21-INT-02 - GitHub Proxy Pull Request Adapter`
  - `P21-TOOL-01 - MCP Proxy Egress Starter Contract`
  - `P21-DOC-01 - Proxy Egress Operator Docs`
  - `P21-CLOSE-01 - Phase 21 Closeout And Next Planning`
- Phase 21 方向依据：
  - 当前 `git-proxy-only` 与 `mcp-proxy-only` 仍只有策略标签，没有真实 transport
  - 下一阶段应把 remote side effect 从 direct local transport 进一步收敛到 proxy-backed contract

## 2026-06-28 P21-INT-01 SCM Proxy Transport Contract

- 执行 `P21-INT-01 - SCM Proxy Transport Contract`
- 在 `packages/agent-integrations/src/agent_integrations/scm_proxy.py` 新增独立 proxy contract：
  - `ScmProxyRequest`
  - `ScmProxyResponse`
  - `ScmProxyTransport`
  - `build_github_pull_request_proxy_request(...)`
- 约束点：
  - request / response 形状必须是确定性的可序列化 JSON 结构
  - headers 去重、排序并标准化
  - contract 与现有 direct GitHub HTTP transport 分离，不改变当前执行路径
- 在 `tests/agent_integrations/test_scm_proxy.py` 增加定向回归：
  - request / response 标准化
  - 非 JSON 值拒绝
  - duplicate headers 拒绝
  - GitHub proxy request helper 的稳定输出
  - proxy transport Protocol 兼容性
- 更新 `README.md`、`PROGRESS.md`、`docs/AGENT_TASKS.md`，将下一张 adapter 任务和 MCP proxy starter 解锁
- 验证：
  - `poetry run pytest tests/agent_integrations/test_scm_proxy.py tests/agent_integrations/test_scm.py`
  - `uv run ruff check packages/agent-integrations/src/agent_integrations tests/agent_integrations`
  - `uv run mypy packages/agent-integrations/src/agent_integrations/scm_proxy.py tests/agent_integrations/test_scm_proxy.py`

## 2026-06-28 GitHub App Credential Adapter Skeleton

- 执行 `P19-INT-01 - GitHub App Credential Adapter Skeleton`
- 新增 `agent_integrations.github_app`：
  - `GitHubAppCredentialBinding`
  - `GitHubAppInstallationToken`
  - `GitHubAppTokenTransport`
  - `GitHubAppCredentialBroker`
- 适配路径：
  - 通过 `SecretStore` 读取 private key material
  - 通过 `GitHubAppTokenTransport` 交换 installation token
  - 返回标准 `CredentialCapability`
- 新增 provider-backed failure 语义：
  - `CredentialTransportError`
  - SCM audit `failure_class=transport_failure` 可从 GitHub App token exchange 透传
- 保持安全边界：
  - private key 不进入 `repr`
  - private key 不进入 API response
  - private key 不进入 delivery audit metadata
- 新增和更新测试：
  - `tests/agent_integrations/test_github_app.py`
  - `tests/agent_integrations/test_scm.py`
  - `tests/api/test_session_pull_request.py`
- 更新文档：
  - `docs/Credential_Broker_Foundation.md`
  - `docs/operator_runbook.md`
- 本轮验证结果：
  - `poetry run pytest tests/agent_integrations/test_github_app.py tests/agent_integrations/test_scm.py tests/api/test_session_pull_request.py` 通过
  - `uv run ruff check packages/agent-integrations/src/agent_integrations packages/agent-security/src/agent_security tests/agent_integrations tests/api/test_session_pull_request.py` 通过
  - `uv run mypy packages/agent-integrations/src/agent_integrations packages/agent-security/src/agent_security tests/agent_integrations` 通过

## 2026-06-28 Local Secret Store Backend

- 执行 `P19-SEC-02 - Local Secret Store Backend`
- 在 `agent_security.secret_store` 中新增：
  - `LocalSecretStore`
  - `get_secret_value(...)`
- 本地 backend 设计：
  - 以本地目录为 root
  - 按 handle 映射到分层 JSON secret document
  - 返回 `SecretMaterial`
  - 继续沿用 redacted contract，不暴露 raw value
- 当前错误语义：
  - missing secret -> `SecretMissingError`
  - missing/unreadable root or invalid document -> `SecretUnavailableError`
  - traversal or blank handle -> `ValueError`
- 更新文档：
  - `docs/Credential_Broker_Foundation.md`
- 本轮验证结果：
  - `poetry run pytest tests/agent_security/test_secret_store.py tests/agent_security/test_broker.py tests/agent_security/test_capabilities.py tests/agent_security/test_environment_broker.py` 通过
  - `uv run ruff check packages/agent-security/src/agent_security tests/agent_security` 通过
  - `uv run mypy packages/agent-security/src/agent_security tests/agent_security` 通过

## 2026-06-28 Secret Store Port And Redaction Contract

- 执行 `P19-SEC-01 - Secret Store Port And Redaction Contract`
- 新增 `agent_security.secret_store`：
  - `SecretStore`
  - `SecretMaterial`
  - `SecretStoreError`
  - `SecretMissingError`
  - `SecretUnavailableError`
  - `InMemorySecretStore`
- 约束 secret-store contract：
  - raw secret value 不进入 `repr`
  - `redacted()` 统一输出 `<redacted>`
  - missing 与 unavailable 语义分离
- 更新 `agent_security.__init__` 导出和 `docs/Credential_Broker_Foundation.md`
- 新增测试：
  - `tests/agent_security/test_secret_store.py`
- 本轮验证结果：
  - `poetry run pytest tests/agent_security/test_secret_store.py tests/agent_security/test_broker.py tests/agent_security/test_capabilities.py tests/agent_security/test_environment_broker.py` 通过
  - `uv run ruff check packages/agent-security/src/agent_security tests/agent_security` 通过
  - `uv run mypy packages/agent-security/src/agent_security tests/agent_security` 通过

## 2026-06-28 Phase 18 Closeout And Phase 19 Planning

- 执行 `P18-CLOSE-01 - Phase 18 Closeout And Next Planning`
- 新增 Phase 18 验收记录：
  - `docs/Phase18_SCM_Audit_Observability_验收记录.md`
- 汇总 Phase 18 已完成证据：
  - `credential_source`
  - `credential_backend`
  - `failure_class`
  - operator remediation guidance
- 将仓库主线状态推进到 Phase 19 ready
- 新增 Phase 19 starter tasks：
  - `P19-SEC-01 - Secret Store Port And Redaction Contract`
  - `P19-SEC-02 - Local Secret Store Backend`
  - `P19-INT-01 - GitHub App Credential Adapter Skeleton`
- Phase 19 方向依据：
  - 架构文档 `Credential Broker`
  - 架构文档 `Secret: OS Keychain / 本地安全存储`
  - 目录规划中的 `credentials/secret_store.py` 与 `protocols/github_app.py`

## 2026-06-28 Credential Failure Audit Classification

- 执行 `P18-OBS-02 - Credential Failure Audit Classification`
- 为 SCM pull-request 失败审计增加稳定的 `failure_class` 分类：
  - `credential_missing`
  - `credential_denied`
  - `credential_unavailable`
  - `transport_failure`
- 分类从集成层透传到 API delivery audit metadata：
  - broker missing / denied / unavailable 分别保留不同 failure class
  - GitHub transport failure 与 broker unavailable 明确区分
  - transport failure 仍保留 `credential_source` 与 `credential_backend`，便于排障
- 新增和更新测试：
  - `tests/agent_integrations/test_scm.py`
  - `tests/api/test_session_pull_request.py`
  - `tests/api/test_delivery_audit_metadata.py`
  - `tests/api/test_session_delivery_audit.py`
- 更新 `docs/operator_runbook.md`，补充基于 `failure_class` 的 remediation 指引
- 本轮验证结果：
  - `poetry run pytest tests/agent_integrations/test_scm.py tests/api/test_session_pull_request.py tests/api/test_delivery_audit_metadata.py tests/api/test_session_delivery_audit.py` 通过
  - `make check` 通过
  - `make test` 未通过；当前阻塞为与本任务无关的 `tests/worker/test_loop.py::test_worker_loop_skips_already_leased_ready_session`
  - 阻塞原因是该用例使用固定 `acquired_at=2026-06-23T09:00Z` 与真实当前时间比较，lease 已过期后被 worker 正常重新 claim；该问题位于 `tests/worker/`，不属于 `P18-OBS-02` owned paths

## 2026-06-23 SCM Credential Source Audit Metadata

- 执行 `P18-OBS-01 - SCM Credential Source Audit Metadata`
- 为 GitHub pull request 计划与 API delivery audit 增加非敏感凭证来源字段：
  - `credential_source`
  - `credential_backend`
- 打通三类语义路径：
  - broker-backed 成功执行记录 `credential_source=broker`
  - explicit env fallback 成功执行记录 `credential_source=env_fallback`
  - broker missing 失败记录保留来源元数据，便于和普通 transport failure 区分
- 保持安全边界不变：
  - API response 不暴露 token
  - delivery audit 不暴露 token
  - request payload 继续使用 redacted authorization header
- 新增和更新测试：
  - `tests/api/test_delivery_audit_metadata.py`
  - `tests/api/test_session_delivery_audit.py`
  - `tests/api/test_session_pull_request.py`
  - `tests/agent_integrations/test_scm.py`
- 本轮验证结果：
  - `poetry run pytest tests/api/test_delivery_audit_metadata.py tests/api/test_session_delivery_audit.py tests/api/test_session_pull_request.py tests/agent_integrations/test_scm.py` 通过
  - `make check` 通过

## 2026-06-22 CLI Durable Run Execution

- 执行 `P8-CLI-05 - CLI Durable Run Execution`
- 新增 `run --execute`：
  - 复用现有 harness loop 与 single-attempt orchestrator
  - 接入真实 model gateway
  - 接入本地 policy engine、runtime-backed builtin tools、SQLite event/projection persistence
- 默认 `run` 行为保持为仅创建 session，不隐式开始执行
- 新增测试：
  - assistant-only durable execution
  - `files.read` builtin tool durable execution

## 2026-06-22 API Session Create And Execute

- 执行 `P8-API-06 - API Session Create And Execute`
- 把本地 harness 执行 wiring 抽到 `agent-runtime.run_local_harness`
- CLI durable execution 改为复用共享 runtime-side helper
- 新增 API `POST /sessions`：
  - `execute=false` 时仅创建 durable session
  - `execute=true` 时立即运行一轮本地 harness，并持久化完整事件流
- 新增测试：
  - runtime shared harness runner
  - API app create-only / execute paths
  - route adapter `POST /sessions`
  - HTTP JSON request parsing、create、execute 与错误输入

## 2026-06-22 Queued Session Bootstrap Events

- 执行 `P8-QUE-01 - Queued Session Bootstrap Events`
- 在 `agent-core` 新增共享 `SessionBootstrapService`
- create-only CLI/API session 现在都会持久化：
  - `SESSION_CREATED`
  - `USER_MESSAGE_RECEIVED`
  - `TASK_PREPARED`
- create-only session 的 durable 状态从 `created` 前移到 `ready`
- 为后续 worker-owned execution 预埋了可恢复的任务输入与 workspace 信息

## 2026-06-22 Worker Execute Ready Session

- 执行 `P8-WKR-04 - Worker Execute Ready Session`
- `agent-runtime` 暴露可复用 `LocalToolGateway`
- `apps/worker` 新增 `SessionExecutionService`
- worker 现在可以：
  - 从 queued bootstrap events 重建任务输入
  - claim/resume 一个 `ready` session
  - 执行一轮本地 harness attempt
  - 持久化 terminal events、projection、model call index、tool run index
  - 在终态后释放 lease
- 新增测试：
  - assistant-only worker execution
  - builtin `files.read` worker execution 与 tool-run indexing

## 2026-06-22 CLI Resume Execute Trigger

- 执行 `P8-CLI-06 - CLI Resume Execute Trigger`
- `zebra-agent resume` 保持默认只读
- 新增 `zebra-agent resume --execute`：
  - 复用 worker-side `SessionExecutionService`
  - 允许显式传入 `--worker-id`
  - 返回终态 `status`、assistant message 和紧凑 tool trace
- 新增测试：
  - read-only resume 不变
  - assistant-only resume execution
  - `files.read` resume execution trace

## 2026-06-19

- 将会与 `PROGRESS.md` 冲突的旧 `progress.md` 会话日志文件重命名为 `WORKLOG.md`
- 执行 `P2-TOOL-01 Tool Contracts And Execution Results`
- 新增 `agent-tools` 执行层骨架：
  - `contracts.py`
  - `errors.py`
  - `registry.py`
  - `executor.py`
  - `gateway.py`
- 新增测试：
  - `tests/agent_tools/test_executor.py`
- 为 `agent-core` 和 `agent-tools` 增加 `py.typed`，消除 workspace 类型导入噪音
- 本轮验证结果：
  - `uv run pytest tests/agent_tools tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-tools tests/agent_tools tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-tools/src/agent_tools tests/agent_tools` 通过

## 2026-06-19 Governance Alignment

- 恢复真正的 `PROGRESS.md` 项目状态文件
- 把文档中的会话日志引用统一从 `progress.md` 改为 `WORKLOG.md`
- 更新 `README.md`，将仓库状态从 bootstrap 调整为 `Phase 2 - Runtime And Tooling Spine`

## 2026-06-19 Runtime Workspace Baseline

- 执行 `P2-RT-02 - Workspace And Worktree Abstractions`
- 新增 `agent-runtime.workspace` 模块：
  - `errors.py`
  - `models.py`
  - `local.py`
- 新增 `LocalWorkspace` 和 `LocalWorktree`
- 增加 workspace root 绝对路径校验、相对路径归一化、越界路径拒绝、worktree 创建与销毁生命周期
- 新增测试：
  - `tests/agent_runtime/test_workspace.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_runtime/test_workspace.py tests/agent_runtime/test_local_runtime.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-runtime/src/agent_runtime tests/agent_runtime tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-runtime/src/agent_runtime tests/agent_runtime` 通过

## 2026-06-19 Builtin File Read Path

- 执行 `P2-TOOL-02 - Builtin File Read Path`
- 新增 `agent_tools.builtin.files`
- 实现 `files.read`：
  - 通过 `LocalWorkspace` 做相对路径归一化
  - 拒绝越界读取
  - 对大文件返回截断结果和结构化 metadata
- 为 `agent-tools` 增加对 `agent-runtime` 的 workspace 依赖声明
- 新增测试：
  - `tests/agent_tools/test_file_read_tool.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_tools/test_file_read_tool.py tests/agent_tools/test_executor.py tests/agent_runtime/test_workspace.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-tools/src/agent_tools tests/agent_tools packages/agent-runtime/src/agent_runtime tests/agent_runtime tests/smoke/test_workspace_bootstrap.py` 通过
  - `make check` 通过

## 2026-06-19 Builtin Command Execution Path

- 执行 `P2-TOOL-03 - Builtin Command Execution Path`
- 新增 `agent_tools.builtin.command`
- 实现 `command.run`：
  - `command` 必须是 typed argv，不接受自由 shell 字符串
  - 默认在 workspace 根目录执行
  - `cwd` 如果提供，必须仍然位于 workspace 内
  - `timeout_seconds` 透传到 `RuntimePort`
  - 返回结构化执行结果：`stdout` 作为输出，`exit_code`、`stderr`、`timed_out` 写入 metadata
- 新增测试：
  - `tests/agent_tools/test_command_run_tool.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_tools/test_command_run_tool.py tests/agent_tools/test_file_read_tool.py tests/agent_tools/test_executor.py tests/agent_runtime/test_workspace.py tests/agent_runtime/test_local_runtime.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-tools/src/agent_tools tests/agent_tools` 通过
  - `uv run mypy packages/agent-tools/src/agent_tools tests/agent_tools` 通过
  - `make check` 通过

## 2026-06-19 Builtin Patch And Validation Path

- 执行 `P2-TOOL-04 - Builtin Patch Apply Path`
- 新增 `agent_tools.builtin.patch`
- 实现 `patch.apply`：
  - 输入为 unified diff 字符串
  - 先校验 patch 头中的路径，拒绝越界到 workspace 外
  - 通过 typed `patch` 命令映射到 `RuntimePort`
  - 非零退出和 stderr 作为结构化结果返回
- 新增测试：
  - `tests/agent_tools/test_patch_apply_tool.py`

- 执行 `P2-TOOL-05 - Builtin Validation Commands`
- 新增 `agent_tools.builtin.tests`
- 实现 `tests.run`：
  - 使用 preset 映射，不接受任意自由 shell 文本
  - 支持 `cwd` 与 `timeout_seconds`
  - 返回结构化执行结果
- 新增测试：
  - `tests/agent_tools/test_tests_run_tool.py`

- 执行 `P2-IT-01 - Local Toolchain Integration Flow`
- 新增集成测试：
  - `tests/integration/test_local_toolchain_flow.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_tools tests/agent_runtime tests/integration tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-tools/src/agent_tools tests/agent_tools tests/integration` 通过
  - `make check` 通过

## 2026-06-19 Readonly Git Inspection Path

- 执行 `P2-GIT-01 - Readonly Git Inspection Tools`
- 新增 `agent_tools.builtin.git`
- 实现 `git.status`：
  - 只执行 readonly `git status --short --branch`
  - `cwd` 如果提供，必须仍然位于 workspace 内
  - 返回结构化结果，不引入写操作
- 新增测试：
  - `tests/agent_tools/test_git_status_tool.py`
- 补齐 `Phase 2` 最小本地工具闭环：
  - `files.read`
  - `patch.apply`
  - `command.run`
  - `tests.run`
  - `git.status`
  - `tests/integration/test_local_toolchain_flow.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_tools tests/agent_runtime tests/integration tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-tools/src/agent_tools tests/agent_tools tests/integration` 通过
  - `make check` 通过

## 2026-06-19 Harness Loop Skeleton

- 执行 `P3-HAR-01 - Harness Loop Skeleton`
- 新增 `agent_core.harness`
- 实现最小 loop 骨架：
  - `HarnessTask`
  - `HarnessAttempt`
  - `HarnessContext`
  - `HarnessAttemptResult`
  - `HarnessLoop`
- 新增 `HARNESS_ATTEMPT_STARTED` 事件，并接入 session projection
- 当前 loop 只协调一次注入式 `attempt_runner`，不提前耦合真实模型或真实工具执行
- 新增测试：
  - `tests/agent_core/test_harness_loop.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `uv run mypy packages/agent-core/src/agent_core tests/agent_core` 通过

## 2026-06-19 Mock Model Gateway

- 执行 `P3-MOD-01 - Mock Model Gateway`
- 新增 `agent_core.domain.modeling.ModelCompletion`
- 调整 `ModelGatewayPort`，从返回单条消息升级为返回 `ModelCompletion`
- 新增 `agent_core.application.mock_model`：
  - `ScriptedModelGateway`
  - `ScriptedModelResponse`
- 新增 `HarnessModelStep`，用于构造初始用户消息并请求一次模型完成
- 新增测试：
  - `tests/agent_core/test_mock_model_gateway.py`
- 覆盖场景：
  - deterministic mock completion
  - tool call planning path
  - script exhaustion failure
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_mock_model_gateway.py tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-19 Single Attempt Tool Orchestration

- 执行 `P3-HAR-02 - Single Attempt Tool Orchestration`
- 新增 `SingleAttemptOrchestrator`
- 在单次 attempt 中串起：
  - model completion
  - tool call proposal
  - policy evaluation
  - tool execution
  - structured attempt result
- 为 harness 增加 `HarnessEventDraft` 机制，使 attempt 内部步骤能稳定写回事件流
- 新增测试：
  - `tests/agent_core/test_single_attempt_orchestrator.py`
- 覆盖场景：
  - model -> policy -> tool success
  - tool execution failed path
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_mock_model_gateway.py tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-19 Structured Run Output And Retry Skeleton

- 执行 `P3-HAR-03 - Structured Run Output And Retry Skeleton`
- 新增：
  - `HarnessRunResult`
  - `HarnessStopReason`
  - `HarnessStoppingPolicy`
- `HarnessLoopResult` 现在包含结构化 `run_result`
- 当前 loop 仍然只执行单次 attempt，但已经能稳定给出：
  - 最终 outcome
  - stop reason
  - attempts used
  - max attempts
  - can retry
- 新增测试：
  - `tests/agent_core/test_harness_stopping.py`
- 覆盖场景：
  - failed but retryable
  - retry exhausted
  - loop 暴露结构化 run result
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_stopping.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_mock_model_gateway.py tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-19 Multi-Attempt Loop Driver

- 执行 `P3-HAR-04 - Multi-Attempt Loop Driver`
- `HarnessLoop` 从单次 attempt 升级为 bounded multi-attempt driver
- 当前行为：
  - 如果失败且 `can_retry=true`，继续下一次 attempt
  - 成功后立即停止
  - 达到重试预算后终止并返回 `retry_exhausted`
- `HarnessLoopResult` 现在保留 `attempt_results`
- 新增测试：
  - `tests/agent_core/test_harness_multi_attempt.py`
- 覆盖场景：
  - 第一次失败，第二次成功
  - 重试预算耗尽后失败终止
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_multi_attempt.py tests/agent_core/test_harness_stopping.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_mock_model_gateway.py tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-20 Assistant And Tool Trace Projection

- 执行 `P3-HAR-05 - Assistant Message And Tool Trace Projection`
- 新增：
  - `HarnessToolTrace`
  - `HarnessAttemptTrace`
  - `HarnessRunTrace`
  - `HarnessTraceProjector`
- `SingleAttemptOrchestrator` 现在在 emitted events 中显式携带 `attempt_number`
- 当前 projection 可以把 assistant message、tool proposal、policy decision、tool result 投影为紧凑 run-facing trace
- 新增测试：
  - `tests/agent_core/test_harness_trace_projection.py`
- 覆盖场景：
  - successful tool trace
  - failed tool trace
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_trace_projection.py tests/agent_core/test_harness_multi_attempt.py tests/agent_core/test_harness_stopping.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_mock_model_gateway.py tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-20 Attempt Event Timestamp Refinement

- 执行 `P3-HAR-06 - Attempt Event Timestamp Refinement`
- 新增：
  - `SystemClock`
  - `StepClock`
- `HarnessLoop` 现在通过 `ClockPort` 驱动事件时间，不再把整次 run 的所有事件压成同一个 `created_at`
- 当前行为：
  - 初始化事件按时钟顺序推进

## 2026-06-22 Model Call Index

- 执行 `P4-STO-05 - Model Call Index`
- 为核心模型调用补齐 durable 索引闭环：
  - `agent_core.domain.model_calls.ModelCallRecord`
  - `agent_core.ports.model_call_store.ModelCallStorePort`
  - `agent_core.domain.modeling` 中的 `ModelCallMetadata` 与 `ModelUsage`
- `SingleAttemptOrchestrator` 现在会把以下字段写入 `MODEL_RESPONSE_RECEIVED` 事件：
  - `provider`
  - `model_name`
  - `input_tokens`
  - `output_tokens`
  - `total_tokens`
  - `latency_ms`
  - `cache_hit`
  - `cost_usd`
- 新增 `agent_storage.model_calls.SQLiteModelCallStore`
- 新增 `zebra_agent_worker.model_call_index.ModelCallIndexer`
- 新增测试：
  - `tests/agent_storage/test_sqlite_model_calls.py`
  - `tests/worker/test_model_call_index.py`
  - `tests/agent_core/test_single_attempt_orchestrator.py` 中的模型响应元数据断言
- 本轮验证结果：
  - `uv run pytest tests/agent_storage/test_sqlite_model_calls.py tests/worker/test_model_call_index.py tests/agent_core/test_single_attempt_orchestrator.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core packages/agent-storage/src/agent_storage apps/worker/src/zebra_agent_worker tests/agent_core/test_single_attempt_orchestrator.py tests/agent_storage/test_sqlite_model_calls.py tests/worker/test_model_call_index.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core packages/agent-storage/src/agent_storage apps/worker/src/zebra_agent_worker tests/agent_storage/test_sqlite_model_calls.py tests/worker/test_model_call_index.py` 通过
  - `make check` 通过

## 2026-06-22 Context Compiler Bootstrap

- 执行 `P5-CTX-01 - Context Compiler Bootstrap`
- 将 `agent-context` 从占位返回值升级为最小可用的 deterministic compiler：
  - `ContextItemKind`
  - `ContextProvenance`
  - `ContextItem`
  - `ContextBudget`
  - `ContextCompileRequest`
  - `CompiledContext`
- `compile_context` 现在支持：
  - workspace 扫描
  - root/doc 文件优先
  - 基于任务词和路径的基础打分
  - repo map 引导项
  - token budget 裁剪与 `truncated` 标记
- 新增测试：
  - `tests/agent_context/test_compiler.py`
  - `tests/smoke/test_workspace_bootstrap.py` 中的真实编译路径断言
- 本轮验证结果：
  - `uv run pytest tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-context/src/agent_context tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-context/src/agent_context tests/agent_context/test_compiler.py` 通过
  - `make check` 通过

## 2026-06-22 Related Files Recall And Ranking Split

- 执行 `P5-CTX-02 - Related Files Recall And Ranking Split`
- 将 `agent-context` 进一步拆分为更清晰的职责边界：
  - `scanner.py`
  - `ranking.py`
  - `related.py`
  - `compiler.py`
- 新增 `ContextItemKind.RELATED_FILE`
- `compile_context` 现在除了主排序文件外，还会基于本地 Python import 关系补充 related file context items
- 新增测试：
  - `tests/agent_context/test_compiler.py` 中的 related-file recall 场景
- 本轮验证结果：
  - `uv run pytest tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-context/src/agent_context tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-context/src/agent_context tests/agent_context/test_compiler.py` 通过

## 2026-06-22 Conversation And Tool Output Compaction

- 执行 `P5-CTX-03 - Conversation And Tool Output Compaction`
- 新增 `agent_context.compaction`：
  - `ConversationCompactionRequest`
  - `ToolOutputCompactionRequest`
  - `ToolOutputEvidence`
  - `compact_conversation`
  - `compact_tool_outputs`
- 新增 `ContextItemKind`：
  - `CONVERSATION_SUMMARY`
  - `TOOL_OUTPUT_SUMMARY`
- 当前 compaction 行为：
  - 保留用户目标、验收、约束、计划、修改文件、失败尝试、未解决测试、审批、artifact 等关键 section
  - 对工具输出做结构化单行压缩
  - 在 token budget 下做 deterministic truncation
- 新增测试：
  - `tests/agent_context/test_compaction.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-context/src/agent_context tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-context/src/agent_context tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过
  - `make check` 通过

## 2026-06-22 Prompt Layout And Cache Key Rules

- 执行 `P5-CTX-04 - Prompt Layout And Cache Key Rules`
- 新增 `agent_context.prompt_layout`：
  - `PromptSectionKind`
  - `PromptSection`
  - `PromptLayout`
  - `PromptCacheKeyRequest`
  - `build_prompt_layout`
  - `build_prompt_cache_key`
- 当前 prompt-layout 行为：
  - `AGENTS.md` / `README.md` 等稳定项目指导进入 stable section
  - `Repo Map`、代码片段、related files 进入 semi-stable section
  - conversation/tool-output compaction items 进入 dynamic section
- 当前 cache-key 行为会显式纳入：
  - `task_input`
  - `workspace_root`
  - `model_profile`
  - `policy_summary`
  - `tool_manifest`
  - 各 section 的序列化 context items
- 新增测试：
  - `tests/agent_context/test_prompt_layout.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-context/src/agent_context tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-context/src/agent_context tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过
  - `make check` 通过

## 2026-06-22 Trust Marking And Prompt-Injection Baseline

- 执行 `P5-CTX-05 - Trust Marking And Prompt-Injection Baseline`
- 新增 `agent_context.trust`：
  - `trust_level_for_item`
  - `prompt_injection_metadata`
- `ContextItem` 现在补充：
  - `trust_level`
  - `metadata`
- 当前 trust baseline：
  - `Repo Map` 标记为 `system`
  - `AGENTS.md` / `README.md` / `pyproject.toml` / `Makefile` 标记为 `trusted`
  - conversation/tool-output summaries 标记为 `user`
  - 代码文件默认标记为 `untrusted`
- 当前 injection baseline：
  - 仅做 suspicious pattern metadata 标记
  - 不做自动拒绝或策略联动
- 新增测试：
  - `tests/agent_context/test_compiler.py` 中的 suspicious-content 标记断言
- 本轮验证结果：
  - `uv run pytest tests/agent_context/test_compiler.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-context/src/agent_context tests/agent_context/test_compiler.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-context/src/agent_context tests/agent_context/test_compiler.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py` 通过
  - 每次 attempt 有独立 `started_at`
  - emitted events 和 terminal events 继续沿时钟推进
- 新增测试：
  - `tests/agent_core/test_harness_multi_attempt.py` 中的时间顺序断言
- 覆盖场景：
  - 多 attempt 事件时间递增
  - 同一 run 内时间顺序稳定可预测
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_multi_attempt.py tests/agent_core/test_harness_trace_projection.py tests/agent_core/test_harness_stopping.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_mock_model_gateway.py tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-20 Planner And Verifier Hooks

- 执行 `P3-HAR-07 - Planner And Verifier Hooks`
- 新增：
  - `PlannerHook`
  - `VerifierHook`
  - `PlannerResult`
  - `VerifierResult`
  - `NoopPlanner`
  - `NoopVerifier`
- `SingleAttemptOrchestrator` 现在有显式 planner / verifier hook 点：
  - planner 在 tool call proposal 前参与
  - verifier 在 tool result 后参与
- emitted events 里新增：
  - `PLAN_PROPOSED`
  - `TESTS_COMPLETED` 作为最小 verifier 完成事件
- 新增测试：
  - `tests/agent_core/test_harness_hooks.py`
- 覆盖场景：
  - planner 和 verifier 在一次 run 中被调用
  - 结构化 metadata 回写到 attempt result
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_hooks.py tests/agent_core/test_harness_multi_attempt.py tests/agent_core/test_harness_trace_projection.py tests/agent_core/test_harness_stopping.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_mock_model_gateway.py tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-20 Session Event Builder Cleanup

- 执行 `P3-HAR-08 - Session Event Builder Cleanup`
- 新增 `HarnessEventRecorder`
- 统一收拢：
  - `SessionEvent.create`
  - sequence 递增
  - append 到事件流
  - `apply_event` 投影回 session
  - clock 驱动的 `created_at`
- `HarnessLoop` 改为通过 recorder 记录初始化、attempt、draft 和 terminal 事件
- 新增测试：
  - `tests/agent_core/test_harness_recorder.py`
- 覆盖场景：
  - recorder 正常记录事件
  - sequence 递增
  - session projection 行为保持不变
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_recorder.py tests/agent_core/test_harness_hooks.py tests/agent_core/test_harness_multi_attempt.py tests/agent_core/test_harness_trace_projection.py tests/agent_core/test_harness_stopping.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_mock_model_gateway.py tests/agent_core/test_harness_loop.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_session_projection.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-20 Tool Call Selection Strategy

- 执行 `P3-HAR-09 - Tool Call Selection Strategy`
- 新增：
  - `ToolCallSelection`
  - `ToolCallSelectionStrategy`
  - `FirstToolCallSelectionStrategy`
- `SingleAttemptOrchestrator` 现在通过显式 selector 选择 tool call，不再内联硬编码 `completion.tool_calls[0]`
- 当前行为：
  - 默认策略仍然稳定选择第一个 tool call
  - selection summary 和 metadata 会进入 proposal event 与 attempt metadata
- 新增测试：
  - `tests/agent_core/test_single_attempt_orchestrator.py`
- 覆盖场景：
  - 默认选择策略的确定性
  - multi-tool completion 下 orchestrator 只执行选中的 tool call
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_single_attempt_orchestrator.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core` 通过
  - `uv run mypy packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-20 Explicit Harness Budgets

- 执行 `P3-HAR-10 - Explicit Harness Budgets`
- 新增：
  - `HarnessTask.max_model_calls`
  - `HarnessTask.max_tool_calls`
  - `HarnessRunResult` 的 budget usage / limit 字段
  - `MODEL_CALL_BUDGET_EXHAUSTED`
  - `TOOL_CALL_BUDGET_EXHAUSTED`
- `HarnessLoop` 现在会把 task budget 写入 `TASK_PREPARED` event，并累计每次 attempt 的 model/tool usage
- `SingleAttemptOrchestrator` 现在会在 attempt metadata 中显式回传：
  - `model_calls_used`
  - `tool_calls_executed`
- `HarnessStoppingPolicy` 现在会在 retry 判断前先检查 model/tool budget 是否已经耗尽
- 新增测试：
  - `tests/agent_core/test_harness_stopping.py`
  - `tests/smoke/test_mock_harness_loop.py`
- 覆盖场景：
  - tool call budget exhausted
  - model call budget exhausted
  - loop 因 tool budget 耗尽而停止重试
  - mock harness loop 端到端 smoke 闭环
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_stopping.py tests/agent_core/test_single_attempt_orchestrator.py tests/smoke/test_mock_harness_loop.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core tests/smoke` 通过
  - `uv run mypy packages/agent-core/src/agent_core tests/agent_core` 通过
  - `make check` 通过

## 2026-06-20 SQLite Event Store And Session Projection

- 执行 `P4-STO-01 - SQLite Event Store And Session Projection`
- 新增 `agent-storage` workspace package
- 新增：
  - `SQLiteEventStore`
  - `SQLiteProjectionStore`
  - SQLite 连接与 event row 映射辅助模块
- 当前行为：
  - session events 可按 `session_id + sequence` 顺序持久化和读取
  - 同一 session 的重复 sequence 会被 SQLite 唯一约束拒绝
  - 读取出的 event stream 可以直接喂给 `rebuild_session`
- 新增测试：
  - `tests/agent_storage/test_sqlite_event_store.py`
  - `tests/agent_storage/test_sqlite_projection_store.py`
- 覆盖场景：
  - append/list session events
  - duplicate sequence rejection
  - replay into session projection
  - save/get session projection
- 本轮验证结果：
  - `make sync` 通过
  - `uv run pytest tests/agent_storage/test_sqlite_event_store.py tests/agent_storage/test_sqlite_projection_store.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-storage/src/agent_storage tests/agent_storage tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-storage/src/agent_storage tests/agent_storage` 通过
  - `make check` 通过

## 2026-06-20 Event Idempotency Protection

- 执行 `P4-STO-02 - Event Idempotency Protection`
- `SQLiteEventStore` 现在会为 `session_id + idempotency_key` 建立唯一索引
- 当前行为：
  - 同一 session 下，带相同 `idempotency_key` 的重试写入不会产生第二条事件
  - `append()` 在幂等重试时会返回已存在的 durable event
  - 原有 `session_id + sequence` 冲突保护保持不变
- 新增测试：
  - `tests/agent_storage/test_sqlite_event_store.py`
- 覆盖场景：
  - idempotent retry returns existing event
  - duplicate sequence rejection still works
- 本轮验证结果：
  - `uv run pytest tests/agent_storage/test_sqlite_event_store.py tests/agent_storage/test_sqlite_projection_store.py` 通过
  - `uv run ruff check packages/agent-storage/src/agent_storage tests/agent_storage` 通过
  - `uv run mypy packages/agent-storage/src/agent_storage tests/agent_storage` 通过
  - `make check` 通过

## 2026-06-20 Worker Recovery Entry

- 执行 `P4-WKR-01 - Worker Recovery Entry`
- `apps/worker` 新增：
  - `SessionRecoveryService`
  - `RecoveredSession`
  - `SessionRecoveryError`
- 当前行为：
  - worker 可以从 event store 读取一个 session 的完整事件流
  - 通过 `rebuild_session` 重建 durable session 视图
  - recovery 后会把最新 projection 写回 projection store
  - 缺失 session 会以确定性错误失败
- 新增测试：
  - `tests/worker/test_recovery.py`
- 覆盖场景：
  - interrupted running session recovery
  - terminal session recovery
  - missing session failure
- 本轮验证结果：
  - `make sync` 通过
  - `uv run pytest tests/worker/test_recovery.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check apps/worker/src/zebra_agent_worker tests/worker tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy apps/worker/src/zebra_agent_worker tests/worker` 通过
  - `make check` 通过

## 2026-06-21 SQLite Worker Leases

- 执行 `P4-SCH-01 - SQLite Worker Leases`
- `agent-core` 新增：
  - `WorkerLease`
  - `LeaseStorePort`
- `agent-storage` 新增：
  - `SQLiteLeaseStore`
  - `LeaseConflictError`
- 当前行为：
  - worker 可以为某个 session 申请 lease
  - 未过期 lease 不允许被其他 worker 抢占
  - 过期 lease 可以被后续 worker 重新获取
  - 已持有 worker 可以 heartbeat 更新 checkpoint 和 expiry
  - release 后 lease 会被删除
- 新增测试：
  - `tests/agent_storage/test_sqlite_leases.py`
- 覆盖场景：
  - acquire and read active lease
  - reject other worker before expiry
  - allow reacquire after expiry
  - heartbeat owned lease
  - release owned lease
- 本轮验证结果：
  - `uv run pytest tests/agent_storage/test_sqlite_leases.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core packages/agent-storage/src/agent_storage tests/agent_storage tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core packages/agent-storage/src/agent_storage tests/agent_storage` 通过
  - `make check` 通过

## 2026-06-21 Worker Claim And Resume Flow

- 执行 `P4-WKR-02 - Worker Claim And Resume Flow`
- `apps/worker` 新增：
  - `SessionClaimService`
  - `ClaimedSession`
- 当前行为：
  - worker 可以先恢复 session，再申请 lease 完成 claim
  - claim 结果同时包含 recovery state 和 lease state
  - 已 claim session 可以 heartbeat 续租并推进 checkpoint
  - 可以显式 release claim
- 新增测试：
  - `tests/worker/test_claims.py`
- 覆盖场景：
  - claim running session
  - block concurrent claim before expiry
  - allow takeover after expiry
  - heartbeat and release claim
- 本轮验证结果：
  - `uv run pytest tests/worker/test_claims.py tests/worker/test_recovery.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check apps/worker/src/zebra_agent_worker tests/worker tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy apps/worker/src/zebra_agent_worker tests/worker` 通过
  - `make check` 通过

## 2026-06-21 Core Event Schema Drafts

- 执行 `P4-GOV-01 - Core Event Schema Drafts`
- `agent-core` 新增：
  - `agent_core.contracts`
  - `event_payload_schema_for`
  - `validate_event_payload`
  - `EventPayloadValidationError`
- 当前行为：
  - `SessionCreated`、`UserMessageReceived`、`ToolExecutionCompleted` 已有 machine-checkable payload schema
  - covered payload 默认拒绝未知字段
  - 可以直接生成 JSON Schema dict，供后续 API / storage / docs 复用
- 新增测试：
  - `tests/agent_core/test_event_contracts.py`
- 覆盖场景：
  - schema generation
  - valid payload acceptance
  - unknown field rejection
  - unknown event schema lookup failure
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_event_contracts.py tests/agent_core/test_events.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core/contracts tests/agent_core/test_event_contracts.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core/contracts tests/agent_core/test_event_contracts.py` 通过
  - `make check` 通过

## 2026-06-21 Event Schema Enforcement

- 执行 `P4-GOV-02 - Event Schema Enforcement`
- `SessionEvent.create()` 现在会对已覆盖的 event payload 执行 schema 校验
- 当前行为：
  - covered event 在创建时即拒绝非法 payload
  - 未覆盖 event 暂时保持 passthrough，避免阻塞后续 schema 逐步补齐
- 新增测试：
  - `tests/agent_core/test_events.py`
- 覆盖场景：
  - invalid covered-event payload rejection
  - uncovered event payload passthrough
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_events.py tests/agent_core/test_event_contracts.py tests/agent_storage/test_sqlite_event_store.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core/domain/events.py tests/agent_core/test_events.py tests/agent_storage/test_sqlite_event_store.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core/domain/events.py tests/agent_core/test_events.py` 通过
  - `make check` 通过

## 2026-06-22 Incremental Event Replay

- 执行 `P4-STO-03 - Incremental Event Replay`
- `EventStorePort` 新增 `read_since(session_id, sequence)`
- `SQLiteEventStore` 现在支持按 sequence 增量读取 session 事件
- `SessionRecoveryService` 现在会优先读取已有 projection，并只回放其后的增量事件
- 新增测试：
  - `tests/agent_storage/test_sqlite_event_store.py`
  - `tests/worker/test_recovery.py`
- 覆盖场景：
  - event-store delta reads
  - projection-based resume with newer events
- 本轮验证结果：
  - `uv run pytest tests/agent_storage/test_sqlite_event_store.py tests/worker/test_recovery.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core/ports/event_store.py packages/agent-storage/src/agent_storage/sqlite.py apps/worker/src/zebra_agent_worker/recovery.py tests/agent_storage/test_sqlite_event_store.py tests/worker/test_recovery.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core/ports/event_store.py packages/agent-storage/src/agent_storage/sqlite.py apps/worker/src/zebra_agent_worker/recovery.py tests/agent_storage/test_sqlite_event_store.py tests/worker/test_recovery.py` 通过
  - `make check` 通过

## 2026-06-22 Explicit Resume Entry

- 执行 `P4-WKR-03 - Explicit Resume Entry`
- `apps/worker` 新增：
  - `SessionResumeService`
  - `ResumedSession`
  - `SessionResumeError`
- 当前行为：
  - worker 可以通过单个 resume entry 完成 claim + recovery
  - terminal session 会被明确拒绝
  - terminal resume 失败后不会遗留 lease
- 新增测试：
  - `tests/worker/test_resume.py`
- 覆盖场景：
  - resume running session
  - reject terminal session without dangling lease
- 本轮验证结果：
  - `uv run pytest tests/worker/test_resume.py tests/worker/test_claims.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check apps/worker/src/zebra_agent_worker tests/worker tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy apps/worker/src/zebra_agent_worker tests/worker` 通过
  - `make check` 通过

## 2026-06-22 Tool Run Index

- 执行 `P4-STO-04 - Tool Run Index`
- `agent-core` 新增：
  - `ToolRunRecord`
  - `ToolRunStorePort`
- `agent-storage` 新增：
  - `SQLiteToolRunStore`
- `apps/worker` 新增：
  - `ToolRunIndexer`
- 当前行为：
  - tool execution event 可以被映射为 durable tool-run record
  - control plane 可以按 session 查询 tool run 索引，而不是每次直接扫描原始 event payload
- 新增测试：
  - `tests/agent_storage/test_sqlite_tool_runs.py`
  - `tests/worker/test_tool_run_index.py`
- 覆盖场景：
  - tool-run upsert and query
  - event-to-tool-run indexing
- 本轮验证结果：
  - `uv run pytest tests/agent_storage/test_sqlite_tool_runs.py tests/worker/test_tool_run_index.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core/domain/tool_runs.py packages/agent-core/src/agent_core/ports/tool_run_store.py packages/agent-storage/src/agent_storage/tool_runs.py apps/worker/src/zebra_agent_worker/tool_run_index.py tests/agent_storage/test_sqlite_tool_runs.py tests/worker/test_tool_run_index.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core/domain/tool_runs.py packages/agent-core/src/agent_core/ports/tool_run_store.py packages/agent-storage/src/agent_storage/tool_runs.py apps/worker/src/zebra_agent_worker/tool_run_index.py tests/agent_storage/test_sqlite_tool_runs.py tests/worker/test_tool_run_index.py` 通过
  - `make check` 通过

## 2026-06-22 Runtime Evidence Context Injection

- 执行 `P5-CTX-07 - Runtime Evidence Context Injection`
- `ContextCompileRequest` 新增：
  - `runtime_evidence_items`
- 当前行为：
  - 允许把 `CONVERSATION_SUMMARY` 与 `TOOL_OUTPUT_SUMMARY` 作为 runtime evidence 注入编译输入
  - 这些 items 和普通 context items 一样参与统一 token budget
  - prompt layout 会把它们路由到 dynamic section
- 新增测试：
  - `tests/agent_context/test_runtime_evidence.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_context/test_runtime_evidence.py tests/agent_context/test_adapter.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过
  - `uv run ruff check packages/agent-context/src/agent_context tests/agent_context/test_runtime_evidence.py tests/agent_context/test_adapter.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过
  - `uv run mypy packages/agent-context/src/agent_context tests/agent_context/test_runtime_evidence.py tests/agent_context/test_adapter.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过

## 2026-06-22 Attempt Evidence Feedback Loop

- 执行 `P5-CTX-08 - Attempt Evidence Feedback Loop`
- `agent-core` 新增：
  - `RuntimeEvidenceInput`
- `HarnessLoop` 现在支持：
  - 从 prior attempt result 提取 conversation summary evidence
  - 从 prior attempt result 提取 tool-output evidence
  - 在 retry attempt 前把 evidence 填回 `HarnessTask.runtime_evidence`
- `LocalContextCompiler` 现在支持：
  - 接收抽象 runtime-evidence inputs
  - 把它们压缩成 dynamic context items
- 新增测试：
  - `tests/agent_core/test_harness_runtime_evidence.py`
  - `tests/agent_context/test_adapter.py` 中的 runtime-evidence 渲染场景
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_core/test_mock_model_gateway.py tests/agent_context/test_adapter.py tests/agent_context/test_runtime_evidence.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过

## 2026-06-22 Path Risk Rules

- 执行 `P6-POL-03 - Path Risk Rules`
- `LocalPolicyEngine` 现在支持：
  - `files.read` path traversal 预检
  - `git.status` 与 `command.run` cwd traversal/absolute path 预检
  - `patch.apply` patch header path traversal 预检
- 更新测试：
  - `tests/agent_security/test_policy_profiles.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_security/test_policy_profiles.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-security/src/agent_security tests/agent_security/test_policy_profiles.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-security/src/agent_security tests/agent_security/test_policy_profiles.py` 通过
  - `make check` 通过
  - `uv run mypy packages/agent-security/src/agent_security tests/agent_security/test_policy_profiles.py` 通过
  - `make check` 通过
  - `uv run mypy packages/agent-security/src/agent_security tests/agent_security/test_policy_profiles.py` 通过
  - `make check` 通过

## 2026-06-22 Sensitive Output Rules

- 执行 `P6-POL-04 - Sensitive Output Rules`
- `LocalPolicyEngine` 现在支持：
  - sensitive path marker 检测
  - network-capable data transfer command 检测
  - 明显 secret exfiltration 风险进入 approval
- 更新测试：
  - `tests/agent_security/test_policy_profiles.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_security/test_policy_profiles.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-security/src/agent_security tests/agent_security/test_policy_profiles.py tests/smoke/test_workspace_bootstrap.py` 通过

## 2026-06-22 Context-Aware Retry Plan Hint

- 执行 `P5-CTX-10 - Context-Aware Retry Plan Hint`
- `agent-core` 新增：
  - `RetryPlanHint`
  - `build_retry_plan_hint`
- 默认 `NoopPlanner` 现在支持：
  - 在 retry attempt 存在 runtime evidence 时生成 deterministic retry summary
  - 在 planner metadata 中暴露 retry focus、retry blockers、accepted constraints、prior tool outputs
- 当前行为：
  - `planner_summary` 会成为 retry focus
  - failed `verifier_summary` 与 failed `tool_status` 会成为 retry blockers
  - passed `verifier_summary` 会成为 accepted constraints
- 新增测试：
  - `tests/agent_core/test_harness_retry_plan.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_retry_plan.py tests/agent_core/test_harness_hooks.py tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_core/test_harness_multi_attempt.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core/test_harness_retry_plan.py tests/agent_core/test_harness_hooks.py tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_core/test_harness_multi_attempt.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core tests/agent_core/test_harness_retry_plan.py tests/agent_core/test_harness_hooks.py tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_core/test_harness_multi_attempt.py` 通过
  - `make check` 通过

## 2026-06-22 Context Compiler Acceptance Hardening

- 执行 `P5-CTX-11 - Context Compiler Acceptance Hardening`
- `ContextCompileRequest` 现在校验：
  - `workspace_root` 必须存在
  - `workspace_root` 必须是目录
  - runtime evidence 只能使用 conversation/tool-output summary kinds
  - runtime evidence provenance 必须来自 session projection 或 tool trace
- 新增/更新测试：
  - `tests/agent_context/test_compiler.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_context/test_compiler.py tests/agent_context/test_runtime_evidence.py tests/agent_context/test_adapter.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py` 通过
  - `uv run ruff check packages/agent-context/src/agent_context tests/agent_context/test_compiler.py tests/agent_context/test_runtime_evidence.py tests/agent_context/test_adapter.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py` 通过
  - `uv run mypy packages/agent-context/src/agent_context tests/agent_context/test_compiler.py tests/agent_context/test_runtime_evidence.py tests/agent_context/test_adapter.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py` 通过
  - `make check` 通过

## 2026-06-22 Phase 5 Closeout Record

- 执行 `P5-CTX-12 - Phase 5 Closeout Record`
- 新增文档：
  - `docs/Phase5_Context_Compiler_验收记录.md`
- 当前状态：
  - Phase 5 context compiler local MVP scope 已关闭
  - `PROGRESS.md` 已推进到 `Phase 6 - Policy And Approvals Hardening`
  - Git context provider、durable context-compacted events、persistent context cache 明确作为后续项
- 本轮验证结果：
  - `uv run pytest tests/agent_context tests/agent_core/test_harness_model_step.py tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_retry_plan.py` 通过
  - `uv run ruff check packages/agent-context/src/agent_context packages/agent-core/src/agent_core/ports/context_compiler.py packages/agent-core/src/agent_core/harness/model_step.py packages/agent-core/src/agent_core/harness/loop.py packages/agent-core/src/agent_core/harness/retry_plan.py tests/agent_context tests/agent_core/test_harness_model_step.py tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_retry_plan.py` 通过
  - `uv run mypy packages/agent-context/src/agent_context packages/agent-core/src/agent_core/ports/context_compiler.py packages/agent-core/src/agent_core/harness/model_step.py packages/agent-core/src/agent_core/harness/loop.py packages/agent-core/src/agent_core/harness/retry_plan.py tests/agent_context tests/agent_core/test_harness_model_step.py tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_retry_plan.py` 通过
  - `make check` 通过

## 2026-06-22 Local Policy Profiles

- 执行 `P6-POL-01 - Local Policy Profiles`
- `agent-security` 新增：
  - `PolicyProfile`
  - `LocalPolicyEngine`
- 当前行为：
  - `read_only` 允许 `files.read`、`git.status`
  - `workspace_write` 允许 `patch.apply`、`tests.run`，但 `command.run` 进入 approval
  - `full_access` 允许已知本地工具
  - 未知工具在所有 profile 下拒绝
- 新增测试：
  - `tests/agent_security/test_policy_profiles.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_security/test_policy_profiles.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-security/src/agent_security tests/agent_security/test_policy_profiles.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-security/src/agent_security tests/agent_security/test_policy_profiles.py` 通过
  - `make check` 通过

## 2026-06-22 Approval Request Model

- 执行 `P6-POL-05 - Approval Request Model`
- `agent-security` 新增：
  - `ApprovalRisk`
  - `ApprovalRequest`
  - `build_approval_request`
- 当前行为：
  - allow/deny decision 不生成 approval request
  - approval request 携带 tool、profile、reason、risk、scope
  - sensitive transfer approval 标记为 high risk
- 更新测试：
  - `tests/agent_security/test_policy_profiles.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_security/test_policy_profiles.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-security/src/agent_security tests/agent_security/test_policy_profiles.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-security/src/agent_security tests/agent_security/test_policy_profiles.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-security/src/agent_security tests/agent_security/test_policy_profiles.py` 通过
  - `make check` 通过

## 2026-06-22 Approval Event Wiring

- 执行 `P6-POL-06 - Approval Event Wiring`
- `SingleAttemptOrchestrator` 现在支持：
  - `REQUIRE_APPROVAL` policy decision 发出 `APPROVAL_REQUESTED`
  - approval-required tool call 不执行 tool gateway
  - attempt metadata 保留 `policy_decision=require_approval`
- `Session` 状态机现在允许：
  - 当前 local MVP 里的 `waiting_approval -> failed` terminal path
- 更新测试：
  - `tests/agent_core/test_single_attempt_orchestrator.py`
  - `tests/agent_core/test_session_projection.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_session_projection.py tests/agent_core/test_harness_trace_projection.py tests/agent_core/test_harness_hooks.py tests/agent_core/test_domain_models.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_session_projection.py tests/agent_core/test_harness_trace_projection.py tests/agent_core/test_harness_hooks.py tests/agent_core/test_domain_models.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_session_projection.py tests/agent_core/test_harness_trace_projection.py tests/agent_core/test_harness_hooks.py tests/agent_core/test_domain_models.py` 通过
  - `uv run pytest` 通过，144 passed
  - `make check` 通过

## 2026-06-22 Approval Decision Projection

- 执行 `P6-POL-07 - Approval Decision Projection`
- `SessionProjection` 现在支持：
  - `APPROVAL_GRANTED` 将 waiting approval session 恢复为 running
  - `APPROVAL_REJECTED` 将 waiting approval session 投影为 failed
- 更新测试：
  - `tests/agent_core/test_session_projection.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_session_projection.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_event_contracts.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core/application/session_projection.py tests/agent_core/test_session_projection.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_event_contracts.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core/application/session_projection.py tests/agent_core/test_session_projection.py tests/agent_core/test_sessions.py tests/agent_core/test_events.py tests/agent_core/test_event_contracts.py` 通过
  - `uv run pytest` 通过，146 passed
  - `make check` 通过

## 2026-06-22 Approval Service Entry

- 执行 `P6-POL-08 - Approval Service Entry`
- `agent-core.application` 新增：
  - `ApprovalDecisionAction`
  - `ApprovalDecisionCommand`
  - `ApprovalDecisionService`
- 当前行为：
  - grant command 构造 `APPROVAL_GRANTED`
  - reject command 构造 `APPROVAL_REJECTED`
  - approval decision 必须基于 `WAITING_APPROVAL` session
  - approval decision sequence 必须连续
- 新增测试：
  - `tests/agent_core/test_approval_decisions.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_approval_decisions.py tests/agent_core/test_session_projection.py tests/agent_core/test_sessions.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core/application packages/agent-core/src/agent_core/domain/sessions.py tests/agent_core/test_approval_decisions.py tests/agent_core/test_session_projection.py tests/agent_core/test_sessions.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core/application packages/agent-core/src/agent_core/domain/sessions.py tests/agent_core/test_approval_decisions.py tests/agent_core/test_session_projection.py tests/agent_core/test_sessions.py` 通过
  - `uv run pytest` 通过，150 passed
  - `make check` 通过

## 2026-06-22 Phase 6 Closeout Record

- 执行 `P6-POL-09 - Phase 6 Closeout Record`
- 新增文档：
  - `docs/Phase6_Policy_Approvals_验收记录.md`
- 当前状态：
  - Phase 6 policy and approvals local MVP scope 已关闭
  - `PROGRESS.md` 已推进到 `Phase 7 - Eval And Observability`
  - MCP-specific rules、network egress broker、credential broker、approval API adapters 明确作为后续项
- 本轮验证结果：
  - `uv run pytest tests/agent_security tests/agent_core/test_approval_decisions.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_session_projection.py` 通过
  - `uv run ruff check packages/agent-security/src/agent_security packages/agent-core/src/agent_core/application packages/agent-core/src/agent_core/harness/orchestrator.py packages/agent-core/src/agent_core/domain/sessions.py tests/agent_security tests/agent_core/test_approval_decisions.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_session_projection.py` 通过
  - `uv run mypy packages/agent-security/src/agent_security packages/agent-core/src/agent_core/application packages/agent-core/src/agent_core/harness/orchestrator.py packages/agent-core/src/agent_core/domain/sessions.py tests/agent_security tests/agent_core/test_approval_decisions.py tests/agent_core/test_single_attempt_orchestrator.py tests/agent_core/test_session_projection.py` 通过
  - `uv run pytest` 通过，150 passed
  - `make check` 通过

## 2026-06-22 Observability Models Bootstrap

- 执行 `P7-OBS-01 - Observability Models Bootstrap`
- 新增 workspace package：
  - `packages/agent-observability`
- 当前行为：
  - session event stream 可以构造 `TraceRecord`
  - trace 包含 event count、tool result count、audit records、cost summary
  - 空 event stream 和 mixed session stream 会被拒绝
- 新增测试：
  - `tests/agent_observability/test_trace_models.py`
- 本轮验证结果：
  - `uv sync --all-packages --group dev` 通过
  - `uv run pytest tests/agent_observability/test_trace_models.py` 通过
  - `uv run ruff check packages/agent-observability/src/agent_observability tests/agent_observability/test_trace_models.py` 通过
  - `uv run mypy packages/agent-observability/src/agent_observability tests/agent_observability/test_trace_models.py` 通过
  - `uv run pytest` 通过，154 passed
  - `make check` 通过

## 2026-06-22 CLI Model Gateway Smoke

- 执行 `P8-MOD-02 - CLI Model Gateway Smoke`
- 新增：
  - `zebra-agent model "<prompt>"`
  - CLI 到 `agent-integrations.build_model_gateway(...)` 的依赖 wiring
- 当前行为：
  - 发送一条 user prompt 到当前 provider settings 对应的 model gateway
  - 返回 assistant response、provider/model/usage metadata
  - 缺失 API key 时在发请求前确定性失败
  - 不改变现有 `run` / `inspect` / `resume` / `approve` 行为
- 文档更新：
  - `docs/operator_runbook.md` 增加 model smoke 命令
- 本轮验证结果：
  - `uv lock` 通过
  - `make sync` 通过
  - `uv run pytest tests/cli/test_cli_commands.py` 通过，12 passed
  - `uv run ruff check apps/cli/src/zebra_agent_cli tests/cli` 通过
  - `uv run mypy apps/cli tests/cli` 通过
  - `uv run pytest` 通过，216 passed
  - `make check` 通过

## 2026-06-22 OpenAI-Compatible Model Gateway Adapter

- 执行 `P8-MOD-01 - OpenAI-Compatible Model Gateway Adapter`
- 新增：
  - `packages/agent-integrations`
  - `OpenAICompatibleModelGateway`
  - `build_model_gateway(settings, env=...)`
- 当前行为：
  - 使用 OpenAI-compatible `/chat/completions` 接口
  - 将 core `SessionMessage` 序列化为 chat messages
  - 解析 assistant text、usage、tool calls 到 `ModelCompletion`
  - 缺失 API key 时在发请求前确定性失败
- 当前边界：
  - 这是 provider adapter foundation，还没有接到 CLI/API 执行主路径
  - 当前按 DeepSeek 文档使用 `https://api.deepseek.com/chat/completions`
- 本轮验证结果：
  - `uv lock` 通过
  - `make sync` 通过
  - `uv run pytest tests/agent_integrations/test_openai_compatible.py` 通过，4 passed
  - `uv run ruff check packages/agent-integrations/src/agent_integrations tests/agent_integrations` 通过
  - `uv run mypy packages/agent-integrations tests/agent_integrations` 通过
  - `uv run pytest` 通过，213 passed
  - `make check` 通过

## 2026-06-22 Local API Auth Foundation

- 执行 `P8-API-05 - Local API Auth Foundation`
- 新增：
  - `ZEBRA_API_AUTH_TOKEN` settings support
  - optional bearer-token auth guard for non-health API routes
- 当前行为：
  - `/health` 始终公开
  - 未配置 auth token 时，当前本地 API 行为不变
  - 配置 auth token 后，session read 和 stream 路径要求 `Authorization: Bearer ...`
  - 鉴权失败返回确定性的 `401 unauthorized`
- 文档更新：
  - `docs/operator_runbook.md` 增加本地 token 用法
- 本轮验证结果：
  - `uv run pytest tests/config/test_settings.py tests/api/test_http_app.py tests/api/test_api_app.py tests/cli/test_cli_commands.py` 通过，29 passed
  - `uv run ruff check apps/config/src/zebra_agent_config apps/api/src/zebra_agent_api tests/config tests/api tests/cli` 通过
  - `uv run mypy apps/config apps/api tests/config tests/api` 通过
  - `uv run pytest` 通过，209 passed
  - `make check` 通过

## 2026-06-22 Operator Runbook

- 执行 `P8-DOC-01 - Operator Runbook`
- 新增：
  - `docs/operator_runbook.md`
  - `make api-serve`
  - `uvicorn` local operator dependency
- 行为对齐：
  - CLI `run` 现在会写入 `session_created` bootstrap event
  - 刚创建的 session 可以立即被 `/sessions/{id}/stream` replay
- 文档覆盖：
  - local bootstrap
  - CLI `run` / `inspect` / `resume` / `approve`
  - API `health` / `sessions/{id}`
  - SSE `sessions/{id}/stream`
- 手工验证结果：
  - `make api-serve` 可启动本地 API
  - `uv run zebra-agent run ...` 可创建 session
  - `curl /health`、`curl /sessions/{id}`、`curl -N /sessions/{id}/stream` 均验证通过
- 本轮验证结果：
  - `uv lock` 通过
  - `make sync` 通过
  - `uv run python -c "import uvicorn; print(uvicorn.__version__)"` 通过
  - `uv run pytest tests/cli/test_cli_commands.py` 通过，9 passed
  - `uv run ruff check apps/cli/src/zebra_agent_cli tests/cli` 通过
  - `uv run mypy apps/cli tests/cli` 通过
  - `uv run pytest` 通过，204 passed
  - `make check` 通过

## 2026-06-22 Session Stream Foundation

- 执行 `P8-API-04 - Session Stream Foundation`
- 新增：
  - `GET /sessions/{session_id}/stream` 路径
  - API session event listing for one session
  - HTTP `text/event-stream` replay built from persisted session events
- 当前行为：
  - stream 端点按 sequence 顺序回放当前已持久化事件
  - 缺失 session 继续返回确定性的 `not_found`
  - 普通 `GET /sessions/{session_id}` 行为不变
  - 当前是 replay foundation，不是实时增量订阅
- 新增测试：
  - API session stream read path
  - route adapter session stream path handling
  - HTTP SSE replay and missing-session coverage
- 本轮验证结果：
  - `uv run pytest tests/api/test_api_app.py tests/api/test_routes.py tests/api/test_http_app.py` 通过，18 passed
  - `uv run ruff check apps/api/src/zebra_agent_api tests/api` 通过
  - `uv run mypy apps/api tests/api` 通过
  - `uv run pytest` 通过，204 passed
  - `make check` 通过

## 2026-06-22 FastAPI Serving Foundation

- 执行 `P8-API-03 - FastAPI Serving Foundation`
- 新增：
  - `zebra_agent_api.http.create_http_app`
  - FastAPI request/response adapter over existing `RouteAdapter`
  - HTTP tests for health, session lookup, unknown path, and unsupported method
- 当前行为：
  - `GET /health` 复用现有 health payload
  - `GET /sessions/{session_id}` 复用现有 session lookup payload
  - 未支持路径和方法继续返回确定性的 `not_found`
  - FastAPI handler 不直接承载领域逻辑
- 依赖更新：
  - `apps/api` 增加 `fastapi`
  - root dev group 增加 `httpx`
- 本轮验证结果：
  - `uv lock` 通过
  - `make sync` 通过
  - `uv run pytest tests/api/test_api_app.py tests/api/test_routes.py tests/api/test_http_app.py` 通过，12 passed
  - `uv run ruff check apps/api/src/zebra_agent_api tests/api` 通过
  - `uv run mypy apps/api tests/api` 通过
  - `uv run pytest` 通过，198 passed
  - `make check` 通过

## 2026-06-22 Entry Point Settings Wiring

- 执行 `P8-CONFIG-02 - Entry Point Settings Wiring`
- 新增行为：
  - CLI `run`、`resume`、`inspect`、`approve` 在未传 `--database` 时使用 `zebra-agent-config` 的 `database_url`
  - CLI 显式 `--database` 继续覆盖 settings
  - API `create_app()` 在未传 database path 时使用 settings database URL
  - API 显式 database path 继续覆盖 settings
- 更新依赖：
  - `apps/cli` 依赖 `zebra-agent-config`
  - `apps/api` 依赖 `zebra-agent-config`
- 新增测试：
  - CLI settings database default
  - CLI explicit database override
  - API settings database default
  - API explicit database override
- 本轮验证结果：
  - `uv lock` 通过
  - `uv run pytest tests/cli/test_cli_commands.py tests/api/test_api_app.py` 通过，14 passed
  - `uv run ruff check apps/cli/src/zebra_agent_cli apps/api/src/zebra_agent_api tests/cli tests/api` 通过
  - `uv run mypy apps/cli apps/api tests/cli tests/api` 通过
  - `uv run pytest` 通过，194 passed
  - `make check` 通过

## 2026-06-22 Local Settings Loader

- 执行 `P8-CONFIG-01 - Local Settings Loader`
- 新增：
  - `apps/config`
  - `configs/default.env`
  - typed `ZebraAgentSettings`
  - typed `ModelSettings`
- 当前行为：
  - 默认 profile 为 `local`
  - 默认 database 为 `.zebra-agent/sessions.sqlite`
  - 默认 model provider 为 `deepseek`
  - 默认 model 为 `deepseek-v4-flash`
  - env values 可以覆盖 repository defaults
- 新增测试：
  - `tests/config/test_settings.py`
- 本轮验证结果：
  - `make sync` 通过
  - `uv run pytest tests/config/test_settings.py` 通过，2 passed
  - `uv run ruff check apps/config/src/zebra_agent_config tests/config` 通过
  - `uv run mypy apps/config tests/config` 通过
  - `uv run pytest` 通过，190 passed
  - `make check` 通过

## 2026-06-22 API Route Adapter

- 执行 `P8-API-02 - API Route Adapter`
- `apps/api` 新增：
  - `RouteRequest`
  - `RouteAdapter`
- 当前行为：
  - `GET /health` 路由到 health handler
  - `GET /sessions/{session_id}` 路由到 session lookup handler
  - unsupported routes 返回 deterministic 404/not_found
  - route adapter 仍不依赖外部 HTTP framework
- 新增测试：
  - `tests/api/test_routes.py`
- 本轮验证结果：
  - `uv run pytest tests/api/test_routes.py tests/api/test_api_app.py` 通过
  - `uv run ruff check apps/api/src/zebra_agent_api tests/api` 通过
  - `uv run mypy apps/api tests/api` 通过
  - `uv run pytest` 通过，188 passed
  - `make check` 通过，包含 eval release gate

## 2026-06-22 API Health And Session Foundation

- 执行 `P8-API-01 - API Health And Session Foundation`
- `apps/api` 更新：
  - `ZebraAgentApi`
  - `ApiResponse`
  - health handler
  - session lookup handler
- 当前行为：
  - API app 仍是无外部 framework 的 composition object
  - health 返回 service status
  - session lookup 通过 `SQLiteProjectionStore` 读取 projection
  - missing session 返回 404/not_found
- 新增测试：
  - `tests/api/test_api_app.py`
- 更新测试：
  - `tests/smoke/test_workspace_bootstrap.py`
- 本轮验证结果：
  - `uv lock` 通过
  - `uv run pytest tests/api/test_api_app.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check apps/api/src/zebra_agent_api tests/api tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy apps/api tests/api` 通过
  - `uv run pytest` 通过，185 passed
  - `make check` 通过，包含 eval release gate
  - 说明：直接 mypy `tests/smoke/test_workspace_bootstrap.py` 会触发既有未标记 `py.typed` 的包导入问题，默认 `make check` 不检查 tests

## 2026-06-22 CLI Approve Local Decision

- 执行 `P8-CLI-04 - CLI Approve Local Decision`
- `apps/cli` 更新：
  - `approve --database`
  - `approve --operator`
  - `ApprovalDecisionService` 本地组合
  - `SQLiteEventStore` approval event append
  - `SQLiteProjectionStore` session projection update
- 当前行为：
  - waiting approval session 可以通过 CLI 记录 grant/reject
  - non-waiting session 返回 deterministic `invalid_state`
  - missing session 返回 deterministic `not_found`
- 更新测试：
  - `tests/cli/test_cli_commands.py`
- 本轮验证结果：
  - `uv run pytest tests/cli/test_cli_commands.py` 通过
  - `uv run ruff check apps/cli/src/zebra_agent_cli tests/cli` 通过
  - `uv run mypy apps/cli tests/cli` 通过
  - `uv run pytest` 通过，182 passed
  - `make check` 通过，包含 eval release gate

## 2026-06-22 CLI Inspect And Resume Session Read

- 执行 `P8-CLI-03 - CLI Inspect And Resume Session Read`
- `apps/cli` 更新：
  - `inspect --database`
  - `resume --database`
  - `SQLiteProjectionStore` session projection lookup
- 当前行为：
  - `inspect` 和 `resume` 可以读取 session title、status、current_sequence
  - missing session 返回 deterministic `not_found`
  - `resume` 仍不修改 session 状态，也不启动 worker execution
- 更新测试：
  - `tests/cli/test_cli_commands.py`
- 本轮验证结果：
  - `uv run pytest tests/cli/test_cli_commands.py` 通过
  - `uv run ruff check apps/cli/src/zebra_agent_cli tests/cli` 通过
  - `uv run mypy apps/cli tests/cli` 通过
  - `uv run zebra-agent run ...` 后接 `uv run zebra-agent inspect ...` 通过
  - `uv run pytest` 通过，181 passed
  - `make check` 通过，包含 eval release gate

## 2026-06-22 CLI Run Local Session Creation

- 执行 `P8-CLI-02 - CLI Run Local Session Creation`
- `apps/cli` 更新：
  - `run --database`
  - `Session.create` 本地组合
  - `SQLiteProjectionStore` session projection 持久化
- 当前行为：
  - `zebra-agent run` 会创建本地 session id
  - 输出包含 session id、status、prompt、title、workspace、database
  - worker execution 和 model orchestration 仍留给后续任务
- 更新测试：
  - `tests/cli/test_cli_commands.py`
- 本轮验证结果：
  - `uv lock` 通过
  - `uv run pytest tests/cli/test_cli_commands.py` 通过
  - `uv run ruff check apps/cli/src/zebra_agent_cli tests/cli` 通过
  - `uv run mypy apps/cli tests/cli` 通过
  - `uv run zebra-agent run "Fix tests" --title "Fix failing tests" --database /tmp/zebra-agent-cli-session.sqlite` 通过
  - `uv run pytest` 通过，180 passed
  - `make check` 通过，包含 eval release gate

## 2026-06-22 CLI Command Skeleton

- 执行 `P8-CLI-01 - CLI Command Skeleton`
- `apps/cli` 新增：
  - deterministic CLI parser
  - `run` command intent output
  - `resume` command intent output
  - `inspect` command intent output
  - `approve` command intent output
- 当前行为：
  - CLI 命令只输出本地 intent，不提前接 storage、worker 或 API
  - `main.py` 保持入口转发，解析逻辑在 `cli.py`
- 新增测试：
  - `tests/cli/test_cli_commands.py`
- 本轮验证结果：
  - `uv run pytest tests/cli/test_cli_commands.py` 通过
  - `uv run ruff check apps/cli/src/zebra_agent_cli tests/cli` 通过
  - `uv run mypy apps/cli tests/cli` 通过
  - `uv run zebra-agent run "Fix tests" --title "Fix failing tests"` 通过
  - `uv run pytest` 通过，180 passed
  - `make check` 通过，包含 eval release gate

## 2026-06-22 Phase 7 Closeout Record

- 执行 `P7-EVAL-06 - Phase 7 Closeout Record`
- Phase 7 验收证据：
  - trace/audit/cost models 已由 `P7-OBS-01` 覆盖
  - local JSONL trace persistence 已由 `P7-OBS-02` 覆盖
  - local replay runner 已由 `P7-OBS-03` 覆盖
  - eval case/grader/runner 已由 `P7-EVAL-01` 和 `P7-EVAL-02` 覆盖
  - bugfix/refactor/recovery/security/analysis baseline cases 已由 `P7-EVAL-03` 覆盖
  - local release gate 与 `make check` 集成已由 `P7-EVAL-04` 和 `P7-EVAL-05` 覆盖
- Phase 8 ready 状态：
  - 下一阶段从 CLI/API Productization 开始
  - 首批任务应围绕 `run`、`resume`、`inspect`、`approve` CLI 命令和 API health/session foundation 注册
- 本轮验证结果：
  - `make check` 通过，包含 ruff、mypy 和 eval release gate

## 2026-06-22 Eval Release Check Integration

- 执行 `P7-EVAL-05 - Eval Release Check Integration`
- 新增：
  - `scripts/eval_release_check.py`
  - `make eval`
  - `make check` eval release gate step
- 当前行为：
  - release check 加载 `evals/cases/`
  - 基于 case 阈值构造本地 baseline replay summaries
  - 输出 pass rate、average score、case count
  - release gate 失败时脚本返回非 0
- 新增测试：
  - `tests/agent_observability/test_eval_release_check.py`
- 本轮验证结果：
  - `make eval` 通过
  - `uv run pytest tests/agent_observability/test_eval_release_check.py tests/agent_observability/test_release_gate.py tests/agent_observability/test_eval_runner.py tests/agent_observability/test_evals.py` 通过
  - `uv run ruff check scripts/eval_release_check.py tests/agent_observability packages/agent-observability/src/agent_observability` 通过
  - `uv run mypy packages/agent-observability/src/agent_observability tests/agent_observability` 通过
  - `uv run pytest` 通过，175 passed
  - `make check` 通过，包含 eval release gate

## 2026-06-22 Local Release Gate Baseline

- 执行 `P7-EVAL-04 - Local Release Gate Baseline`
- `agent-observability` 新增：
  - `ReleaseGatePolicy`
  - `ReleaseGateResult`
  - `LocalReleaseGate`
- 当前行为：
  - release gate 可以基于 eval pass rate 和 average score 做本地判定
  - empty eval result fail closed
  - invalid gate threshold 被拒绝
- 新增测试：
  - `tests/agent_observability/test_release_gate.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_observability/test_release_gate.py tests/agent_observability/test_eval_runner.py tests/agent_observability/test_evals.py` 通过
  - `uv run ruff check packages/agent-observability/src/agent_observability tests/agent_observability` 通过
  - `uv run mypy packages/agent-observability/src/agent_observability tests/agent_observability` 通过
  - `uv run pytest` 通过，174 passed
  - `make check` 通过

## 2026-06-22 Baseline Eval Case Expansion

- 执行 `P7-EVAL-03 - Baseline Eval Case Expansion`
- `evals/cases/` 新增：
  - `analysis-locate-error`
  - `bugfix-typescript-type-error`
  - `refactor-cross-file`
  - `refactor-control-unrelated-diff`
  - `recovery-dependency-lock-constraint`
- 当前行为：
  - 本地 eval dataset 覆盖 bugfix、refactor、recovery、security、analysis
  - case 数量从 3 扩展到 8
  - 测试锁定 Phase 7 baseline category coverage
- 本轮验证结果：
  - `uv run pytest tests/agent_observability/test_evals.py tests/agent_observability/test_eval_runner.py` 通过
  - `uv run ruff check tests/agent_observability packages/agent-observability/src/agent_observability` 通过
  - `uv run mypy tests/agent_observability packages/agent-observability/src/agent_observability` 通过
  - `uv run pytest` 通过，170 passed
  - `make check` 通过

## 2026-06-22 Local Eval Runner

- 执行 `P7-EVAL-02 - Local Eval Runner`
- `agent-observability` 新增：
  - `EvalRunResult`
  - `LocalEvalRunner`
- 当前行为：
  - eval cases 和 replay summaries 可以按顺序组合评分
  - eval run result 暴露 total count、pass count、all-pass status、average score
  - missing replay result 会成为显式失败
  - empty eval run 被拒绝
- 新增测试：
  - `tests/agent_observability/test_eval_runner.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_observability/test_eval_runner.py tests/agent_observability/test_evals.py tests/agent_observability/test_replay.py` 通过
  - `uv run ruff check packages/agent-observability/src/agent_observability tests/agent_observability` 通过
  - `uv run mypy packages/agent-observability/src/agent_observability tests/agent_observability` 通过
  - `uv run pytest` 通过，169 passed
  - `make check` 通过

## 2026-06-22 Eval Case And Grader Bootstrap

- 执行 `P7-EVAL-01 - Eval Case And Grader Bootstrap`
- `agent-observability` 新增：
  - `EvalCase`
  - `EvalGrade`
  - `LocalEvalGrader`
  - `load_eval_cases`
- `evals/cases/` 新增最小本地数据集：
  - `bugfix-python-test`
  - `security-block-env`
  - `recovery-resume-task`
- 当前行为：
  - eval case 可以从 JSON 文件或目录加载
  - grader 可以基于 replay summary 产出 typed pass/fail result
  - invalid case path、threshold、category 会被拒绝
- 新增测试：
  - `tests/agent_observability/test_evals.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_observability/test_evals.py tests/agent_observability/test_replay.py tests/agent_observability/test_jsonl_trace_store.py tests/agent_observability/test_trace_models.py` 通过
  - `uv run ruff check packages/agent-observability/src/agent_observability tests/agent_observability` 通过
  - `uv run mypy packages/agent-observability/src/agent_observability tests/agent_observability` 通过
  - `uv run pytest` 通过，166 passed
  - `make check` 通过

## 2026-06-22 Local Replay Runner

- 执行 `P7-OBS-03 - Local Replay Runner`
- `agent-observability` 新增：
  - `LocalReplayRunner`
  - `ReplayResult`
- 当前行为：
  - 单个 trace record 可以 replay 成 deterministic summary
  - JSONL trace store 可以按写入顺序 replay
  - missing store file replay 返回空结果
  - zero-event trace 被拒绝
- 新增测试：
  - `tests/agent_observability/test_replay.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_observability/test_replay.py tests/agent_observability/test_jsonl_trace_store.py tests/agent_observability/test_trace_models.py` 通过
  - `uv run ruff check packages/agent-observability/src/agent_observability tests/agent_observability` 通过
  - `uv run mypy packages/agent-observability/src/agent_observability tests/agent_observability` 通过
  - `uv run pytest` 通过，161 passed
  - `make check` 通过

## 2026-06-22 Local Trace JSONL Store

- 执行 `P7-OBS-02 - Local Trace JSONL Store`
- `agent-observability` 新增：
  - `JsonlTraceStore`
- 当前行为：
  - trace records 可以 append 到本地 JSONL 文件
  - trace records 可以按写入顺序读回
  - missing store file 返回空列表
  - directory path 被拒绝
- 新增测试：
  - `tests/agent_observability/test_jsonl_trace_store.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_observability/test_jsonl_trace_store.py tests/agent_observability/test_trace_models.py` 通过
  - `uv run ruff check packages/agent-observability/src/agent_observability tests/agent_observability` 通过
  - `uv run mypy packages/agent-observability/src/agent_observability tests/agent_observability` 通过
  - `make check` 通过

## 2026-06-22 Command Risk Rules

- 执行 `P6-POL-02 - Command Risk Rules`
- `LocalPolicyEngine` 现在支持：
  - `command.run` 参数级风险判断
  - shell interpreter execution 进入 approval
  - shell metacharacter usage 进入 approval
  - malformed command arguments 进入 approval
- 更新测试：
  - `tests/agent_security/test_policy_profiles.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_security/test_policy_profiles.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core packages/agent-context/src/agent_context tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_core/test_mock_model_gateway.py tests/agent_context/test_adapter.py tests/agent_context/test_runtime_evidence.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core packages/agent-context/src/agent_context tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_context/test_adapter.py tests/agent_context/test_runtime_evidence.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过
  - `make check` 通过
  - `uv run ruff check packages/agent-core/src/agent_core packages/agent-context/src/agent_context tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_core/test_mock_model_gateway.py tests/agent_context/test_adapter.py tests/agent_context/test_runtime_evidence.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core packages/agent-context/src/agent_context tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_context/test_adapter.py tests/agent_context/test_runtime_evidence.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过
  - `make check` 通过

## 2026-06-22 Harness Context Input Wiring

- 执行 `P5-CTX-06 - Harness Context Input Wiring`
- `agent-core` 新增：
  - `ContextCompilerPort`
  - `HarnessTask.workspace_root`
  - `HarnessTask.context_token_budget`
- `HarnessModelStep` 现在支持：
  - 通过抽象 `ContextCompilerPort` 生成 system message
  - 在 user message 前注入 compiled context prompt
- `agent-context` 新增：
  - `LocalContextCompiler`
- 新增测试：
  - `tests/agent_core/test_harness_model_step.py`
  - `tests/agent_context/test_adapter.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_model_step.py tests/agent_core/test_mock_model_gateway.py tests/agent_context/test_adapter.py tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run ruff check packages/agent-core/src/agent_core packages/agent-context/src/agent_context tests/agent_core/test_harness_model_step.py tests/agent_core/test_mock_model_gateway.py tests/agent_context/test_adapter.py tests/agent_context/test_compiler.py tests/smoke/test_workspace_bootstrap.py` 通过
  - `uv run mypy packages/agent-core/src/agent_core packages/agent-context/src/agent_context tests/agent_core/test_harness_model_step.py tests/agent_context/test_adapter.py tests/agent_context/test_compiler.py` 通过
  - `make check` 通过

## 2026-06-22 Structured Planner And Verifier Evidence

- 执行 `P5-CTX-09 - Structured Planner And Verifier Evidence`
- `RuntimeEvidenceInput` 新增：
  - `metadata`
- `HarnessLoop` 现在支持：
  - 把 prior attempt 的 planner summary 提取为 `planner_summary`
  - 把 prior attempt 的 verifier result 提取为带 pass/fail metadata 的 `verifier_summary`
  - 把 tool status 与 tool output 分别保留为结构化 evidence
- `LocalContextCompiler` 现在支持：
  - 把 planner summaries 合并进 conversation compaction 的 current plan
  - 把 failed verifier summaries 合并进 unresolved tests
  - 把 passed verifier summaries 合并进 acceptance criteria
- 更新测试：
  - `tests/agent_core/test_harness_runtime_evidence.py`
  - `tests/agent_context/test_adapter.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_harness_runtime_evidence.py tests/agent_core/test_harness_model_step.py tests/agent_core/test_mock_model_gateway.py tests/agent_context/test_adapter.py tests/agent_context/test_runtime_evidence.py tests/agent_context/test_prompt_layout.py tests/agent_context/test_compaction.py tests/agent_context/test_compiler.py` 通过

## 2026-06-23 API Resume Execute Trigger

- 执行 `P8-API-07 - API Resume Execute Trigger`
- `apps/api` 现在支持：
  - `POST /sessions/{session_id}/resume`
  - `worker_id` 与 `lease_ttl_seconds` 请求参数校验
  - 对 missing session、terminal resume、lease conflict、execution error 的确定性响应映射
- 新增模块：
  - `apps/api/src/zebra_agent_api/responses.py`
  - `apps/api/src/zebra_agent_api/session_payloads.py`
  - `apps/api/src/zebra_agent_api/serialization.py`
- 更新测试：
  - `tests/api/test_routes.py`
  - `tests/api/test_http_app.py`
- 本轮验证结果：
  - `uv run pytest tests/api/test_routes.py tests/api/test_http_app.py` 通过

## 2026-06-23 Worker Ready Session Loop

- 执行 `P8-WKR-05 - Worker Ready Session Loop`
- `packages/agent-core` 现在支持：
  - `ProjectionStorePort.list_ready_sessions(limit=...)`
- `packages/agent-storage` 现在支持：
  - `SQLiteProjectionStore.list_ready_sessions()` 按 `updated_at` 顺序扫描 ready session
- `apps/worker` 现在支持：
  - `WorkerLoopService`
  - `zebra-agent-worker` 本地 operator 入口
  - 单次 poll 与多 cycle ready session 执行
- 更新测试：
  - `tests/agent_storage/test_sqlite_projection_store.py`
  - `tests/worker/test_loop.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_storage/test_sqlite_projection_store.py tests/worker/test_loop.py` 通过

## 2026-06-23 Phase 8 Mainline Alignment

- 执行 `P8-INT-01 - Phase 8 Mainline Alignment`
- 主线对齐后同时包含：
  - CLI `resume --execute`
  - API `POST /sessions/{session_id}/resume`
  - `zebra-agent-worker` ready session loop
- 冲突整理：
  - `PROGRESS.md`
  - `README.md`
  - `docs/operator_runbook.md`
  - `docs/AGENT_TASKS.md`
  - `WORKLOG.md`
- 本轮验证结果：
  - `uv run pytest tests/cli/test_cli_commands.py tests/api/test_http_app.py tests/api/test_routes.py tests/agent_storage/test_sqlite_projection_store.py tests/worker/test_loop.py` 通过
  - `make check` 通过

## 2026-06-23 Phase 8 Closeout Record

- 执行 `P8-CLOSE-01 - Phase 8 Closeout Record`
- 新增文档：
  - `docs/Phase8_CLI_API_Productization_验收记录.md`
- 更新规划：
  - `docs/AGENT_TASKS.md` 增加 `P8-CLOSE-01`
  - `docs/AGENT_TASKS.md` 增加 `Phase 9 Task Board`
  - `PROGRESS.md` 切换到 `phase 9 ready`
  - `README.md` 补充 Phase 8 closeout 与 Phase 9 starter lanes
- 本轮验证结果：
  - `make check` 通过

## 2026-06-23 Session Messages Entry

- 执行 `P9-API-01 - Session Messages Entry`
- `agent-core` 现在支持：
  - `SessionMessageAppendService`
- `apps/api` 现在支持：
  - `POST /sessions/{session_id}/messages`
  - non-blank content payload 校验
  - terminal session append rejection
- 更新测试：
  - `tests/agent_core/test_session_messages.py`
  - `tests/api/test_routes.py`
  - `tests/api/test_http_app.py`
- 本轮验证结果：
  - `uv run pytest tests/agent_core/test_session_messages.py tests/api/test_routes.py tests/api/test_http_app.py` 通过

## 2026-06-23 Approval HTTP Entry

- 执行 `P9-API-03 - Approval HTTP Entry`
- `apps/api` 现在支持：
  - `POST /approvals/{approval_id}/approve`
  - `POST /approvals/{approval_id}/reject`
  - approval operator/reason payload 校验与默认值
  - waiting approval session 的 grant/reject durable event 写入
  - invalid approval state 的 deterministic 409 映射
- 本轮新增测试：
  - `tests/api/test_approval_api_app.py`
  - `tests/api/test_approval_routes.py`
  - `tests/api/test_http_approvals.py`
- 文档同步：
  - `docs/operator_runbook.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`

## 2026-06-23 Worker Continuous Loop Behavior

- 执行 `P9-WKR-01 - Worker Continuous Loop Behavior`
- `zebra-agent-worker` loop 现在支持：
  - omitted `--max-cycles` 的连续 daemon-style polling
  - `stop_reason` 机器可读输出
  - idle 多轮 polling 的 deterministic sleep 语义
  - 单轮 `--max-cycles 1 --stop-when-idle` 行为继续可用
- 更新测试：
  - `tests/worker/test_loop.py`
- 文档同步：
  - `docs/operator_runbook.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 本轮验证结果：
  - `uv run pytest tests/worker/test_loop.py tests/worker/test_execution.py tests/worker/test_claims.py tests/worker/test_resume.py` 通过

## 2026-06-23 Phase 9 Closeout And Phase 10 Planning

- 执行 `P9-CLOSE-01 - Phase 9 Closeout And Phase 10 Planning`
- 新增文档：
  - `docs/Phase9_Session_Control_Worker_Hardening_验收记录.md`
- 更新规划：
  - `docs/AGENT_TASKS.md` 增加 `P9-CLOSE-01`
  - `docs/AGENT_TASKS.md` 增加 `Phase 10 Task Board`
  - `PROGRESS.md` 切换到 `phase 10 ready`
  - `README.md` 补充 Phase 10 starter lanes
- Phase 10 首批任务：
  - `P10-API-01 - Session Diff Read API`
  - `P10-API-02 - Session Artifacts Read API`
  - `P10-API-03 - Session Commit API`
  - `P10-API-04 - Session Pull Request API`

## 2026-06-23 Session Diff Read API

- 执行 `P10-API-01 - Session Diff Read API`
- `agent-runtime` 现在支持：
  - `WorkspaceDiffService`
  - clean/dirty Git workspace diff projection
  - non-Git workspace deterministic rejection
- `apps/api` 现在支持：
  - `GET /sessions/{session_id}/diff`
  - missing session 404
  - missing or non-Git workspace `diff_unavailable` conflict
  - bearer auth behavior inherited from existing session routes
- 更新测试：
  - `tests/agent_runtime/test_git_diff.py`
  - `tests/api/test_session_diff.py`
- 文档同步：
  - `docs/operator_runbook.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`

## 2026-06-23 Session Artifacts Read API

- 执行 `P10-API-02 - Session Artifacts Read API`
- `agent-storage` 现在支持：
  - `SQLiteArtifactStore`
  - model call artifact projection
  - tool run artifact projection
  - explicit empty artifact list
- `apps/api` 现在支持：
  - `GET /sessions/{session_id}/artifacts`
  - missing session 404
  - inherited bearer auth behavior for session routes
- 更新测试：
  - `tests/agent_storage/test_artifacts.py`
  - `tests/api/test_session_artifacts.py`
- 文档同步：
  - `docs/operator_runbook.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`

## 2026-06-23 Session Commit API

- 执行 `P10-API-03 - Session Commit API`
- `agent-runtime` 现在支持：
  - `WorkspaceCommitService`
  - dirty Git workspace commit
  - clean or non-Git workspace deterministic rejection
- `agent-security` 现在支持：
  - `CommitPolicy`
  - commit requires `full_access` session policy
- `apps/api` 现在支持：
  - `POST /sessions/{session_id}/commit`
  - commit message and author validation
  - missing session 404
  - policy-blocked conflict
  - inherited bearer auth behavior for session routes
- 更新测试：
  - `tests/agent_runtime/test_git_commit.py`
  - `tests/agent_security/test_delivery_policy.py`
  - `tests/api/test_session_commit.py`
- 文档同步：
  - `docs/operator_runbook.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`

## 2026-06-23 Session Pull Request API

- 执行 `P10-API-04 - Session Pull Request API`
- `agent-integrations` 现在支持：
  - `LocalOnlyPullRequestGateway`
  - PR dry-run plan
  - local-only unavailable response for network execution
- `agent-security` 现在支持：
  - `PullRequestPolicy`
  - PR requires `full_access` session policy
- `apps/api` 现在支持：
  - `POST /sessions/{session_id}/pull-request`
  - PR title/body/base/head/dry_run payload validation
  - missing session 404
  - policy-blocked conflict
  - local-only unavailable conflict when `dry_run=false`
- 更新测试：
  - `tests/agent_integrations/test_scm.py`
  - `tests/agent_security/test_delivery_policy.py`
  - `tests/api/test_session_pull_request.py`
- 文档同步：
  - `docs/operator_runbook.md`
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`

## 2026-06-23 Phase 10 Closeout And Phase 11 Planning

- 执行 `P10-CLOSE-01 - Phase 10 Closeout And Phase 11 Planning`
- 新增文档：
  - `docs/Phase10_Code_Delivery_Surface_验收记录.md`
- 更新规划：
  - `docs/AGENT_TASKS.md` 增加 `P10-CLOSE-01`
  - `docs/AGENT_TASKS.md` 增加 `Phase 11 Task Board`
  - `PROGRESS.md` 切换到 `phase 11 ready`
  - `README.md` 补充 Phase 11 starter lanes
- Phase 11 首批任务：
  - `P11-API-01 - Side Effect Idempotency Keys`
  - `P11-OBS-01 - Delivery Audit Events`
  - `P11-INT-01 - GitHub Pull Request Provider Skeleton`

## 2026-06-23 Phase 11 Side Effect Idempotency Keys

- 执行 `P11-API-01 - Side Effect Idempotency Keys`
- 新增 `SQLiteIdempotencyStore`：
  - 以 `action + idempotency_key` 记录首次请求 hash、状态码和响应体
  - 同 key 同 payload 重放首次响应
  - 同 key 不同 payload 返回确定性冲突
- API 集成：
  - `POST /sessions/{session_id}/commit`
  - `POST /sessions/{session_id}/pull-request`
  - HTTP/Route 层透传 `Idempotency-Key`
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P11-API-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P11-OBS-01` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
  - `docs/operator_runbook.md`
- 验证：
  - `uv run pytest tests/agent_storage/test_idempotency.py tests/api/test_session_commit.py tests/api/test_session_pull_request.py`
  - `make check`
  - `make test`

## 2026-06-23 Phase 11 Delivery Audit Events

- 执行 `P11-OBS-01 - Delivery Audit Events`
- 修正任务边界：
  - `docs/AGENT_TASKS.md` 为 P11-OBS-01 增加 `apps/api/` 和 `tests/api/` owned paths，用于显式 API wiring
- 新增 core/storage 能力：
  - `DeliveryAuditRecord`
  - `DeliveryAuditStorePort`
  - `SQLiteDeliveryAuditStore`
- API 集成：
  - commit 成功、policy blocked、unavailable 会记录 delivery audit
  - pull-request dry-run、policy blocked、unavailable 会记录 delivery audit
  - idempotent replay 不重复写入审计记录
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P11-OBS-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P11-INT-01` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
  - `docs/operator_runbook.md`
- 验证：
  - `uv run pytest tests/agent_storage/test_delivery_audit.py tests/api/test_session_commit.py tests/api/test_session_pull_request.py`
  - `make check`
  - `make test`

## 2026-06-23 Phase 11 GitHub Pull Request Provider Skeleton

- 执行 `P11-INT-01 - GitHub Pull Request Provider Skeleton`
- 新增集成骨架：
  - `GitHubPullRequestConfig`
  - `GitHubPullRequestGateway`
  - `GitHubPullRequestPayload`
- 行为边界：
  - local-only 仍是默认 PR gateway
  - GitHub dry-run 可以生成可审查的 request payload
  - GitHub non-dry-run 缺 token 时在网络调用前失败
  - GitHub non-dry-run 即使有 token 也仍 fail-closed，真实执行尚未实现
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P11-INT-01` 标记为 `Done`
  - `PROGRESS.md`
  - `README.md`
  - `docs/operator_runbook.md`
- 验证：
  - `uv run pytest tests/agent_integrations/test_scm.py`
  - `make check`
  - `make test`

## 2026-06-23 Phase 11 Closeout And Phase 12 Planning

- 执行 `P11-CLOSE-01 - Phase 11 Closeout And Phase 12 Planning`
- 新增文档：
  - `docs/Phase11_Delivery_Hardening_验收记录.md`
- 更新规划：
  - `docs/AGENT_TASKS.md` 增加 `P11-CLOSE-01`
  - `docs/AGENT_TASKS.md` 增加 `Phase 12 Task Board`
  - `PROGRESS.md` 切换到 `phase 12 ready`
  - `README.md` 指向最新 Phase 11 closeout summary
- Phase 12 首批任务：
  - `P12-CONFIG-01 - SCM Provider Settings`
  - `P12-INT-01 - Pull Request Gateway Selection`
  - `P12-API-01 - Delivery Audit Read API`
- 验证：
  - `make check`
  - `make test`

## 2026-06-23 Phase 12 SCM Provider Settings

- 执行 `P12-CONFIG-01 - SCM Provider Settings`
- 配置新增：
  - `ScmSettings`
  - `ZEBRA_SCM_PROVIDER`
  - `ZEBRA_GITHUB_OWNER`
  - `ZEBRA_GITHUB_REPO`
  - `ZEBRA_GITHUB_TOKEN_ENV`
  - `ZEBRA_GITHUB_API_BASE_URL`
  - `ZEBRA_SCM_PULL_REQUEST_DRY_RUN`
- 行为边界：
  - 默认 provider 为 `local-only`
  - GitHub provider 必须显式配置 owner、repo 和 token env name
  - 配置只保存 token 环境变量名，不保存 token 值
  - 现有手动构造 `ZebraAgentSettings` 默认仍得到 local-only SCM settings
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P12-CONFIG-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P12-INT-01` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
  - `docs/operator_runbook.md`
- 验证：
  - `uv run pytest tests/config/test_settings.py`
  - `make check`
  - `make test`

## 2026-06-23 Phase 12 Pull Request Gateway Selection

- 执行 `P12-INT-01 - Pull Request Gateway Selection`
- 新增集成能力：
  - `PullRequestGateway` protocol
  - `build_pull_request_gateway(settings.scm)`
- API 集成：
  - `SessionPullRequestApi` 接收可注入 PR gateway
  - `ZebraAgentApi` 基于 `settings.scm` 选择 local-only 或 GitHub gateway
  - GitHub dry-run 会返回 provider=`github` 和可审查 `request_payload`
  - GitHub non-dry-run 仍 fail-closed
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P12-INT-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P12-API-01` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run pytest tests/agent_integrations/test_scm.py tests/api/test_session_pull_request.py`
  - `make check`
  - `make test`

## 2026-06-23 Phase 12 Delivery Audit Read API

- 执行 `P12-API-01 - Delivery Audit Read API`
- 新增 API：
  - `GET /sessions/{session_id}/delivery-audit`
  - `SessionDeliveryAuditApi`
- 响应字段：
  - `action`
  - `status`
  - `status_code`
  - `policy_profile`
  - `idempotency_key`
  - `result_metadata`
  - `created_at`
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P12-API-01` 标记为 `Done`
  - `PROGRESS.md`
  - `README.md`
  - `docs/operator_runbook.md`
- 验证：
  - `uv run pytest tests/api/test_session_delivery_audit.py tests/api/test_routes.py tests/api/test_http_app.py`
  - `make check`
  - `make test`

## 2026-06-23 Phase 12 Closeout And Phase 13 Planning

- 执行 `P12-CLOSE-01 - Phase 12 Closeout And Phase 13 Planning`
- 新增文档：
  - `docs/Phase12_Remote_SCM_Configuration_验收记录.md`
- 更新规划：
  - `docs/AGENT_TASKS.md` 增加 `P12-CLOSE-01`
  - `docs/AGENT_TASKS.md` 增加 `Phase 13 Task Board`
  - `PROGRESS.md` 切换到 `phase 13 ready`
  - `README.md` 指向最新 Phase 12 closeout summary
- Phase 13 首批任务：
  - `P13-API-01 - API Composition Split`
  - `P13-INT-01 - Guarded GitHub Pull Request Execution`
  - `P13-SEC-01 - SCM Credential Boundary Draft`
- 验证：
  - `make check`
  - `make test`

## 2026-06-23 Phase 13 API Composition Split

- 执行 `P13-API-01 - API Composition Split`
- 新增：
  - `apps/api/src/zebra_agent_api/session_read.py`
- 拆分内容：
  - session lookup
  - session stream
  - session diff
  - session artifacts
  - session delivery audit read delegation
- 结果：
  - `apps/api/src/zebra_agent_api/app.py` 从 489 行降到 384 行
  - endpoint 行为不变
  - `P13-SEC-01` 解锁为下一步，`P13-INT-01` 等待 credential boundary
- 验证：
  - `uv run pytest tests/api/test_api_app.py tests/api/test_routes.py tests/api/test_http_app.py tests/api/test_session_diff.py tests/api/test_session_artifacts.py tests/api/test_session_delivery_audit.py`
  - `make check`
  - `make test`

## 2026-06-23 Phase 13 SCM Credential Boundary Draft

- 执行 `P13-SEC-01 - SCM Credential Boundary Draft`
- 新增：
  - `ScmCredentialCapability`
  - `ScmCredentialBoundary`
  - `REDACTED_SECRET`
- 行为边界：
  - local-only 不产生 token capability
  - GitHub capability 只保留 token env name 和运行时 token value
  - settings snapshot 不包含 token value
  - redacted serialization 输出 `<redacted>`
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P13-SEC-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P13-INT-01` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
  - `docs/operator_runbook.md`
- 验证：
  - `uv run pytest tests/agent_security/test_credentials.py tests/config/test_settings.py`
  - `make check`
  - `make test`

## 2026-06-23 Phase 13 Guarded GitHub Pull Request Execution

- 执行 `P13-INT-01 - Guarded GitHub Pull Request Execution`
- 新增：
  - `GitHubPullRequestTransport`
  - `GitHubHttpPullRequestTransport`
  - settings-driven token lookup in `build_pull_request_gateway`
- 行为边界：
  - local-only 仍为默认 provider
  - GitHub execution 必须显式关闭 `ZEBRA_SCM_PULL_REQUEST_DRY_RUN`
  - 缺 token 时在网络调用前失败
  - 测试使用 fake transport，不依赖 live GitHub
  - 成功执行返回 `status=created` 和 PR URL
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P13-INT-01` 标记为 `Done`
  - `PROGRESS.md`
  - `README.md`
  - `docs/operator_runbook.md`
- 验证：
  - `uv run pytest tests/agent_integrations/test_scm.py tests/api/test_session_pull_request.py`
  - `make check`
  - `make test`

## 2026-06-23 Phase 13 Closeout And Phase 14 Planning

- 执行 `P13-CLOSE-01 - Phase 13 Closeout And Phase 14 Planning`
- 新增文档：
  - `docs/Phase13_API_Composition_And_Guarded_SCM_Execution_验收记录.md`
- 更新规划：
  - `docs/AGENT_TASKS.md` 增加 `P13-CLOSE-01`
  - `docs/AGENT_TASKS.md` 增加 `Phase 14 Task Board`
  - `PROGRESS.md` 切换到 `phase 14 ready`
  - `README.md` 指向最新 Phase 13 closeout summary
- Phase 14 首批任务：
  - `P14-OBS-01 - SCM Execution Audit Hardening`
  - `P14-SEC-01 - SCM Token Redaction Regression Gate`
  - `P14-DOC-01 - Remote SCM Operator Safety Runbook`
- 验证：
  - `make check`
  - `make test`

## 2026-06-23 Phase 14 SCM Execution Audit Hardening

- 执行 `P14-OBS-01 - SCM Execution Audit Hardening`
- 行为更新：
  - pull-request delivery audit 记录规范化 `provider`
  - dry-run 和 created 响应记录 `status`、`commit_sha`、`dry_run`、`url`
  - policy blocked、missing workspace、transport unavailable 等失败路径记录 provider、dry-run flag 和 reason
  - delivery audit read API 返回同一套 result metadata，不引入 token value
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P14-OBS-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P14-SEC-01` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
  - `docs/operator_runbook.md`
- 验证：
  - `uv run pytest tests/api/test_delivery_audit_metadata.py tests/api/test_session_delivery_audit.py tests/api/test_session_pull_request.py tests/agent_storage/test_delivery_audit.py`
  - `make check`
  - `make test`

## 2026-06-23 Phase 14 SCM Token Redaction Regression Gate

- 执行 `P14-SEC-01 - SCM Token Redaction Regression Gate`
- 新增回归覆盖：
  - GitHub PR plan 不暴露真实 token
  - API pull-request created 响应不暴露真实 token
  - delivery audit result metadata 不暴露真实 token
  - credential redacted snapshot 和 settings snapshot 不暴露真实 token value
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P14-SEC-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P14-DOC-01` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
  - `docs/operator_runbook.md`
- 验证：
  - `uv run pytest tests/agent_security/test_credentials.py tests/agent_integrations/test_scm.py tests/api/test_scm_token_redaction.py tests/api/test_session_pull_request.py tests/api/test_delivery_audit_metadata.py`

## 2026-06-23 Phase 14 Remote SCM Operator Safety Runbook

- 执行 `P14-DOC-01 - Remote SCM Operator Safety Runbook`
- 文档更新：
  - `docs/operator_runbook.md` 增加 remote GitHub PR execution checklist
  - checklist 从 local-only dry-run 开始，再切换 GitHub dry-run，最后才允许 live execution
  - live execution 前明确 token env、`full_access` policy、payload review 和 target branch 前置条件
  - live execution 后要求立即读取 delivery audit
  - rollback 和 failure handling 覆盖 accidental PR、`policy_blocked`、`pull_request_unavailable`
- 规划更新：
  - `docs/AGENT_TASKS.md` 将 `P14-DOC-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 增加 `P14-CLOSE-01 - Phase 14 Closeout And Next Planning`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`

## 2026-06-23 Phase 14 Closeout And Phase 15 Planning

- 执行 `P14-CLOSE-01 - Phase 14 Closeout And Next Planning`
- 新增文档：
  - `docs/Phase14_SCM_Execution_Hardening_验收记录.md`
- Phase 14 验收结论：
  - SCM execution audit metadata 完成
  - token redaction regression gate 完成
  - remote SCM operator safety runbook 完成
  - local-only 和 dry-run 默认安全边界保持不变
- Phase 15 首批任务：
  - `P15-SEC-01 - Credential Capability Domain Model`
  - `P15-SEC-02 - Credential Broker Port`
  - `P15-INT-01 - SCM Broker Lookup Adapter`
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`
  - `make test`

## 2026-06-23 Phase 15 Credential Capability Domain Model

- 执行 `P15-SEC-01 - Credential Capability Domain Model`
- 新增：
  - `CredentialCapability`
- 行为边界：
  - capability 包含 provider、audience、scopes、expires_at
  - runtime token value 仅保留为运行时字段，`repr` 不显示
  - `redacted()` 只输出 `<redacted>`，不输出真实 token
  - expiry 使用 timezone-aware datetime 判断
  - 未引入任何具体 secret backend
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P15-SEC-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P15-SEC-02` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run pytest tests/agent_security/test_capabilities.py tests/agent_security/test_credentials.py`
  - `make check`

## 2026-06-23 Phase 15 Credential Broker Port

- 执行 `P15-SEC-02 - Credential Broker Port`
- 新增：
  - `CredentialBroker`
  - `InMemoryCredentialBroker`
  - `CredentialMissingError`
  - `CredentialDeniedError`
  - `CredentialUnavailableError`
  - `docs/Credential_Broker_Foundation.md`
- 行为边界：
  - broker Port 通过 provider、audience、scopes 和 now 请求 SCM credential
  - fake broker 可返回 runtime capability，但 redacted snapshot 不暴露 token
  - missing、denied、unavailable 错误语义分离
  - 未引入 durable token storage 或具体 secret backend
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P15-SEC-02` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P15-INT-01` 解锁为 `Ready`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run pytest tests/agent_security/test_broker.py tests/agent_security/test_capabilities.py`
  - `make check`

## 2026-06-23 Phase 15 SCM Broker Lookup Adapter

- 执行 `P15-INT-01 - SCM Broker Lookup Adapter`
- 行为更新：
  - `build_pull_request_gateway` 支持可选 `credential_broker`
  - GitHub dry-run 不请求 broker credential
  - GitHub non-dry-run 可使用 broker-issued capability
  - broker missing/denied/unavailable 错误在网络执行前转为 `ScmUnavailableError`
  - 没有传入 broker 时保留现有 env-token fallback，以兼容当前 API composition path
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P15-INT-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 增加 `P15-CLOSE-01 - Phase 15 Closeout And Next Planning`
  - `docs/Credential_Broker_Foundation.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run pytest tests/agent_integrations/test_scm.py tests/agent_security/test_broker.py`

## 2026-06-23 Phase 15 Closeout And Phase 16 Planning

- 执行 `P15-CLOSE-01 - Phase 15 Closeout And Next Planning`
- 新增文档：
  - `docs/Phase15_Credential_Broker_Foundation_验收记录.md`
- Phase 15 验收结论：
  - credential capability domain model 完成
  - credential broker Port 完成
  - SCM broker lookup adapter 完成
  - env-token fallback 仍保留为兼容边界
- Phase 16 首批任务：
  - `P16-SEC-01 - Local Environment Credential Broker`
  - `P16-APP-01 - API Credential Broker Composition`
  - `P16-CLOSE-01 - Phase 16 Closeout And Next Planning`
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`
  - `make test`

## 2026-06-23 Phase 16 Local Environment Credential Broker

- 执行 `P16-SEC-01 - Local Environment Credential Broker`
- 新增：
  - `EnvironmentCredentialBinding`
  - `EnvironmentCredentialBroker`
- 行为边界：
  - provider、audience、scopes、token env name 和 expiry 通过 binding 显式配置
  - broker 从配置的 env var name 读取 runtime token value
  - missing env value 映射为 `CredentialMissingError`
  - unsupported provider 或 scope 映射为 `CredentialDeniedError`
  - raw token 不出现在 capability repr、redacted snapshot 或 broker repr
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P16-SEC-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P16-APP-01` 解锁为 `Ready`
  - `docs/Credential_Broker_Foundation.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run pytest tests/agent_security/test_environment_broker.py tests/agent_security/test_broker.py tests/agent_security/test_capabilities.py`

## 2026-06-23 Phase 16 API Credential Broker Composition

- 执行 `P16-APP-01 - API Credential Broker Composition`
- 行为更新：
  - `ZebraAgentApi` 支持注入 `credential_broker`
  - `ZebraAgentApi` 支持注入 GitHub transport 以便 API 层 fake execution 测试
  - `create_app` 与 `create_http_app` 保持默认行为不变，同时支持 dependency injection
  - GitHub non-dry-run API 路径可使用 broker-issued capability
  - broker missing credential 在网络执行前失败并记录 delivery audit metadata
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P16-APP-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P16-CLOSE-01` 解锁为 `Ready`
  - `docs/Credential_Broker_Foundation.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run pytest tests/api/test_session_pull_request.py tests/agent_integrations/test_scm.py tests/agent_security/test_environment_broker.py`

## 2026-06-23 Phase 16 Closeout And Phase 17 Planning

- 执行 `P16-CLOSE-01 - Phase 16 Closeout And Next Planning`
- 新增文档：
  - `docs/Phase16_Local_Credential_Backend_And_API_Wiring_验收记录.md`
- Phase 16 验收结论：
  - local environment credential broker 完成
  - API credential broker composition 完成
  - missing credential audit metadata 覆盖完成
  - direct env fallback 仍保留为兼容边界
- Phase 17 首批任务：
  - `P17-APP-01 - API Default Environment Broker Factory`
  - `P17-INT-01 - SCM Env Fallback Boundary`
  - `P17-DOC-01 - Broker-Backed SCM Operator Docs`
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`
  - `make test`

## 2026-06-23 Phase 17 API Default Environment Broker Factory

- 执行 `P17-APP-01 - API Default Environment Broker Factory`
- 新增：
  - `zebra_agent_api.credential_broker.build_default_credential_broker`
- 行为更新：
  - local-only API 不构造 credential broker
  - GitHub API composition 在未显式注入 broker 时从 SCM settings 构造 `EnvironmentCredentialBroker`
  - GitHub non-dry-run API 路径可通过默认 environment broker 使用 fake transport 测试
  - missing default broker env value 在网络执行前失败并记录 delivery audit metadata
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P17-APP-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P17-INT-01` 解锁为 `Ready`
  - `docs/Credential_Broker_Foundation.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run pytest tests/api/test_credential_broker.py tests/api/test_session_pull_request.py tests/agent_security/test_environment_broker.py`

## 2026-06-23 Phase 17 SCM Env Fallback Boundary

- 执行 `P17-INT-01 - SCM Env Fallback Boundary`
- 行为更新：
  - `build_pull_request_gateway` 默认不再读取 direct env token fallback
  - retained fallback 必须显式传入 `allow_env_token_fallback=True`
  - broker-backed path 保持优先
  - local-only 和 GitHub dry-run 行为不变
- 文档更新：
  - `docs/AGENT_TASKS.md` 将 `P17-INT-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 将 `P17-DOC-01` 解锁为 `Ready`
  - `docs/Credential_Broker_Foundation.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `uv run pytest tests/agent_integrations/test_scm.py tests/api/test_session_pull_request.py tests/api/test_credential_broker.py`

## 2026-06-23 Phase 17 Broker-Backed SCM Operator Docs

- 执行 `P17-DOC-01 - Broker-Backed SCM Operator Docs`
- 文档更新：
  - `docs/operator_runbook.md` 改为 broker-backed GitHub PR execution 说明
  - 明确 API composition 默认从 SCM settings 构造 environment broker
  - 明确 `ZEBRA_GITHUB_TOKEN_ENV` 只存 env var name，token value 只存在 API process env
  - 明确 direct SCM adapter env fallback 默认关闭，只保留 integration compatibility flag
  - delivery audit checklist 增加 missing broker env value 的 reason
- 规划更新：
  - `docs/AGENT_TASKS.md` 将 `P17-DOC-01` 标记为 `Done`
  - `docs/AGENT_TASKS.md` 增加 `P17-CLOSE-01 - Phase 17 Closeout And Next Planning`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`

## 2026-06-23 Phase 17 Closeout And Phase 18 Planning

- 执行 `P17-CLOSE-01 - Phase 17 Closeout And Next Planning`
- 新增文档：
  - `docs/Phase17_Credential_Backend_Hardening_验收记录.md`
- Phase 17 验收结论：
  - API default environment broker factory 完成
  - direct SCM env fallback 默认关闭，显式 compatibility flag 保留
  - broker-backed SCM operator docs 完成
- Phase 18 首批任务：
  - `P18-OBS-01 - SCM Credential Source Audit Metadata`
  - `P18-OBS-02 - Credential Failure Audit Classification`
  - `P18-CLOSE-01 - Phase 18 Closeout And Next Planning`
- 文档更新：
  - `docs/AGENT_TASKS.md`
  - `PROGRESS.md`
  - `README.md`
- 验证：
  - `make check`
  - `make test`

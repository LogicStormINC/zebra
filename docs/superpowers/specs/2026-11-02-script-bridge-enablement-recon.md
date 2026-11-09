# 脚本桥启用路径评估（CA-P7-01B）——2026-11-02

任务来源：CA-P7-01A 首域决策时的拆卡（"脚本桥启用路径评估，Blocked：排在 01A 后"）。
01A/02 全链已完，本评估回答"启用脚本桥还差什么"。勘察基线：cloud-agent a260e87e。

## 1. 核心发现：脚本桥已建约 95%，只有两处硬锁

### 已就绪（六层全部存在，测试覆盖）

| 层 | 现状 |
|---|---|
| 域 | `NativeScript`/`NativeScriptManifest`、`ScriptRunnerProfile`（production 模式强制 gvisor）、`ScriptBinding`、`NativeScriptPlan`（精确闭包）、`ScriptBundle`（base_bundle+scripts）、`ScriptRuntimeAssembly`（extends RuntimeAssembly+native_scripts）、`parse_runtime_assembly` 判别器 |
| catalog | `ScriptExecutionCatalog`（schema /cloud-agent.execution-catalog/2，extends /1 加 script_plans+scripts 含私有 source）；`resolve_scripts(bundle)→ScriptRuntimeAssembly`（计划批准闭包+逐脚本批准校验）；`script_for(digest)` |
| API | `script-validation`、`script-bundle-validation`、`script-publication` 三组端点在 `host_registry_management` 链注册（与 bundle-validation 同一装配链），**已可调用** |
| worker 执行 | `prepare_native_scripts`（execution_tool_gateway 内接线，script_recorder 非 None 时走）+ `ScopedNativeScriptRunner`（native_script_runtime）；`script_evaluation.py` CLI（initialize/evaluate/read 三模式含 eval suite） |
| 合同 | overdoze 侧 6 套合同目录全在：`native-script`、`script-validation`、`script-publication`、`script-bundle-validation`、`script-config`、`script-worker`（各含 check.cjs + native-source pin） |
| 配置 | `ZEBRA_SCRIPT_VALIDATION_CONFIG`（私有批准文件：scope/audience/trust_revision/credential_sha256/actions=script.contract.read+script.validate）——与 bundle 批准同模式 |

### 仅有的两处硬锁

| # | 位置 | 内容 | 影响 |
|---|---|---|---|
| 1 | zebra `runtime_management.py:175` | 描述符硬编码 `"nativeScriptAbi": "unsupported"` | 目标描述符不声明脚本能力 |
| 2 | overdoze `runtime.go:190` | 身份检查 `d.Capabilities.Script != "unsupported"` → verify 拒 | 即便 zebra 翻转，overdoze 目标验证也拒 |

**关键事实**：脚本端点本身无能力门——它们与 bundle 端点同一装配链注册，直接调用（带
script-validation 批准文件的凭证）今天就能工作。"unsupported" 是**目标描述符的声明面**，
不是端点的开关。启用 = 让 overdoze 的 delivery/verify 域识别脚本能力的 runtime。

## 2. 启用路径（协调翻转，镜像 o1 合同 digest 同窗模式）

### 2.1 zebra 侧（CA-P7-01B-z1）
- 描述符 `"nativeScriptAbi": "unsupported"` → 真实 ABI 版本（从域代码取
  `NativeScriptPlan` 的 schema 版本，即 `"cloud-agent.native-script/1"` 或其 ABI 标识）。
- 描述符合同 `runtime-management/1` 的合同文档/artifact 若 pin 了此值则同窗重导出。
- 测试：描述符两态（翻转值/旧值）的 Go 兼容断言在 overdoze 侧做。

### 2.2 overdoze 侧（OD-P7-01B-o1）
- `runtime.go:190` 检查放宽：接受 `"unsupported"` 或 `"cloud-agent.native-script/1"`
  （向后兼容——旧 runtime 仍验通）。
- Go 测试：两态描述符（旧=unsupported 通过/新=script ABI 通过/未知值拒）。
- 若 overdoze 有 runtime-gate/deployment-gate 合同 pin 该字段值则同窗更新。

### 2.3 不需要做的
- 端点启用：已注册可调用，无能力门。
- 域/catalog/worker 代码：全部就绪。
- 描述符 capabilities.Bundle 同为 "unsupported" 但 bundle 链一直在工作——
  证明该字段是声明面非执行开关，同样的翻转逻辑适用。

## 3. 拆卡建议

| 卡 | 内容 | 规模 | 状态 |
|---|---|---|---|
| CA-P7-01B-z1 | zebra 描述符翻转到真实 ABI 值（含合同 artifact 同窗） | 小 | Ready |
| OD-P7-01B-o1 | overdoze 身份检查放宽两态兼容（含 Go 测试） | 小 | Ready（依赖 z1 定值） |
| 验证 | zebra+overdoze 联调：真实 script-validation 调用经目标验证通过 | 中 | 依赖前两卡 |

**两卡可同窗交付（值先约定再各自实施）——比 o1 的 digest 重导出简单得多：
无向量/工件连锁，只有一处常量+一处检查。**

## 4. 风险

- 描述符值是 `runtime-management/1` 合同的一部分——若 pin 了 capabilities 块，
  翻转即换合同 digest（需确认 pin 范围；本勘察未发现 pin 此字段的独立合同）。
- 生产模式脚本强制 gvisor（ScriptRunnerProfile.production_isolation）——
  启用后生产部署须有 gVisor 沙箱（ERPNext 满血栈已验证过 gVisor eval）。
- `script_abi: Literal["unsupported"]` 在 bundle envelope（runtime_bundle_types:55）
  **保持不动**——ScriptBundle 层叠在 base bundle 之上，base 声明不支持脚本是诚实的
  （脚本面在 ScriptBundle 层），翻转描述符不触碰 envelope。

# 原生脚本 ABI 与只读 Runner — CA-P3-01A

Owner Luke Ding；2026-10-21。生产者为 Python Runtime，ABI `cloud-agent.native-script/1`。
这是 P3 的第一片执行前置；[任务登记](AGENT_TASKS.md)和[制品](contracts/native-script-v1/contract.json)
说明本轮实际交付。公开物化/发布/业务准入沿用 [P2D](PUBLICATION_MANAGEMENT.md)。

## 依赖核对与分片

P2 A/B/C/D 已提供完整声明、不可变快照、纯校验、公开物化/发布和独立消费授权。
Overdoze OD-P2-01A/B/C 已提供意图和成对 Worker/公开 HTTPS 验收；这些交付仍在功能分支。
用户本轮继续授权基于已发布依赖开发新分支，没有授权整合 main/cloud-agent 或部署。

| 顺序 | 工作 | 当前出口 |
| --- | --- | --- |
| CA-P3-01A | 生产者 ABI、纯变换 Runner、沙箱/超时/输出合同 | 本片；显式调用，无自动准入 |
| CA-P3-01B | Worker Tool/Context/Verifier 接入 | [B 实现与证据](NATIVE_SCRIPT_WORKER.md)：显式新闭包/快照、当前权限、取消与持久恢复；A 制品不变 |
| OD-P3-02A | 可信原生资产最小上传/编辑/固定版本 | 后续：BC-ASSET，仅所属产品开发环境；依赖本 ABI 及 B 实际绑定合同 |
| OD-P3-01A | 前端登记/bootstrap/Hook 与当前用户绑定 | 后续：BC-ACCESS，先核对既有 TS SDK/公开原生 Profile/Controller 接口 |
| 后续 P3/P4/P5 | 真实业务写入/unknown、分发/撤销、交付 | 不以本片成功关闭这些依赖 |

Bundle v1 的 `engine.script_abi`、组件允许集和目标描述继续为 `unsupported`。
本片没有将脚本塞进旧 Bundle、自动注册 Tool、扩大 publisher/Host 权限或提前解锁配置域。
P0 `overdoze.native-capability/1` 和 `overdoze.script/1` 是历史设计名称；不能直接执行或当成本 ABI 的别名。

## 领域与协议

原生执行上下文拥有不可变 NativeScriptManifest、源字节与 ScriptInvocation。
`agent-core/domain` 只校验值、不做 I/O；`agent-runtime` 适配既有 RuntimePort/SandboxSpec。
不建立新任务聚合、存储/通用 Operation 或 Go 执行模型，不新增依赖。

Manifest 严格拒绝未知字段；声明精确 ABI、name、语义 version、kind、源码摘要、Python 3.12、
stdlib-only、固定 `execute` 入口、`effects=none`、input/output shape、超时与输出上限。
源码只是一份 UTF-8 文件，入口为 `def execute(arguments): return {...}`。
stdlib-only 表示没有安装/依赖解析或 SDK/Secret 注入，不是 Python 语言级能力沙箱。
禁止将不受信上传直接送入本入口；摘要证明内容相同，不证明发布者可信或用户有权执行。

Shape 是最多 32 个唯一字段的封闭记录，每项仅 string/integer/boolean，所有项必填。
string 至多 4096 UTF-8 字节，integer 沿用原生有界 64 位整数 JSON；bool 不可充当 integer。
不支持嵌套、数组、可选字段、浮点数、任意 JSON Schema 或外部 `$ref`，未知类型必须拒绝。
Context 输出至少有 string `text`，Verifier 输出至少有 boolean `passed`。
Tool/Context/Verifier 在这里是协议种类，尚未进入各自 Worker 执行点。

| 身份 | 精确算法 |
| --- | --- |
| source_digest | `sha256:` + 原始源码字节 SHA256 |
| manifest_digest | 原生整数/ASCII canonical JSON 的 Manifest 摘要；不包含源码全文 |
| input_digest | 原始 invocation 字节 SHA256；空白变化也改变输入身份 |
| output_digest | 验证后的 output 对象 canonical JSON 摘要，不是 stdout/frame 摘要 |

Invocation 必须包含 ABI、规范 UUID invocation_id、精确 manifest_digest、合规 arguments；
不接受脚本覆盖解释器、shell、环境变量、网络、文件挂载或权限。
Runner 将 Bootstrap、源码、Invocation 分别作为 argv 项传入固定解释器 `-I -S -B -c`；不经过 shell。
子进程只允许输出一份 JSON Response，必须回显相同 ABI/invocation_id/manifest_digest 并通过输出 Shape。
重复键、BOM、浮点/NaN、隐藏后缀、额外 stdout、错误/超量输出均拒绝；原始 stderr 不进入结果。

Manifest/Invocation/Response/Observation JSON schemas 是结构合同；Pydantic 领域校验、
Shape 语义、字节预算和摘要校验同样必需，单独通过 JSON Schema 不表示可以执行。
[正例](contracts/native-script-v1/positive-vectors.json)有三种种类及固定摘要；
[负例](contracts/native-script-v1/negative-vectors.json)由实际生产者解析器执行拒绝。

## 隔离、资源与失败

Runner 只接受只读工作区、network=none、可用且匹配的 OS sandbox/rootless OCI/gVisor。
provision 后核对真实 Handle 的 runtime class、spec digest、只读与网络执行权威，再调用现有 execute。
缺引擎、能力不匹配、TrustedLocal、可写工作区/网络放宽都不能回退到宿主执行。
专用 RuntimePort 的活动 Handle 不与另一 Runner 共享；每 Runner 一次调用，忙时立即拒绝，无队列/重试。
本实例信号量只保护活动句柄，不是跨 Worker 调度权威；B 应复用现有 Task lease/fence 和预算。

输入/源码各 16KiB，输出最多 32KiB，超时最多 30 秒；Manifest 不能超过受信 SandboxSpec 限额。
POSIX 共享进程执行器现在对父进程退出和后代继承管道使用同一个 deadline，超时 KILL 原进程组、回收父进程、关闭管道。
Windows 原有实现保持兼容；本片不声称覆盖其管道期限或任意逃离原进程组的后代回收。
OS sandbox 是可信开发脚本验证方式，保留系统 profile 的必需系统资源规则；
没有证明 CPU/内存/PID 强限制、恶意代码隔离或生产 gVisor 运行。
生产集成须固定镜像/解释器/依赖闭包并实际验证 gVisor/资源限制，不能用开发沙箱替代。

`ScriptObservation` 由父进程产生，绑定调用、Manifest、原始输入、Runtime spec 和成功输出摘要。
失败只返回固定 reason：timeout/process_failed/output_limit/invalid_response，不暴露子进程数据。
结果没有持久化、当前产品授权、Worker 租约或签名，不是 ToolReceipt、发布 EvalEvidence 或 Coverage certificate。
Verifier 的 `passed=true` 仍是脚本数据；不能晋升成覆盖证明或直接通过发布门禁。
本片不做业务写入、Secret/工具 SDK 回调、活跃取消、崩溃重入、unknown 对账或自动重试。
这些必须由 B 接入原有 Policy/Effect/事件收据/恢复边界后逐项验收。

## 开发者入口

纯校验（不执行）：

```sh
uv run python scripts/native_script.py \
  --manifest docs/contracts/native-script-v1/example-manifest.json \
  --source docs/contracts/native-script-v1/example.py
```

显式开发沙箱：

```sh
uv run python scripts/native_script.py \
  --manifest docs/contracts/native-script-v1/example-manifest.json \
  --source docs/contracts/native-script-v1/example.py \
  --invocation docs/contracts/native-script-v1/example-invocation.json \
  --run-os-sandbox
```

默认解释器取当前 Python 的真实绝对路径，只有该安装根作为只读工作区（无业务目录挂载）。
macOS 需可重定位的 Python 3.12 安装，例如当前 uv 工具链；普通 Framework Python 的绝对动态库路径
未必在沙箱允许根内，失败时不补全盘读权限。Linux 需可用 bubblewrap 与可执行的 3.12 安装。
未来 OCI/gVisor 应使用镜像内解释器路径；本片 CLI 不创建容器或部署服务。
argv 包含专有源码和业务输入，可能被宿主进程检查读取；本片仅供可信开发脚本/非秘密测试输入，
不注入凭据、不写入服务日志/指标/审计。后续业务集成须设计私有IPC/受控引用，不直接复用argv传秘密。
CLI 输出仅用于受控本地检查。

## 验证与兼容

专项运行：

```sh
uv run pytest -q tests/agent_core/test_native_script.py \
  tests/agent_runtime/test_native_script_runner.py tests/test_native_script_contract.py \
  tests/agent_runtime/test_process_pipe_deadline.py tests/agent_runtime/test_process_execution.py
```

实际 macOS Seatbelt 正例与文件/联网拒绝、超时、输出污染测试；其他平台的对应用例明确跳过，
Linux/gVisor 需后续单独真实验收，不能把模拟 RuntimePort 负例当成生产隔离证明。
共享执行器回归先在旧实现复现无超时失败，再修复通过；既有 process/OS/OCI 行为专项复验。
完整 make test/check、源码冻结和历史保持证据见 `docs/evidence/ca-p3-01a/validation.json`。
没有数据库 schema/迁移、历史 Task/Bundle/Definition 字节或 Coverage 算法变更；前端仍 mock。

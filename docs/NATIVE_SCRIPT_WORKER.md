# CA-P3-01B — Worker 脚本绑定、取消与持久恢复

2026-10-21；Luke Ding；状态 Review；实现、专项和最终全量门禁通过，Git 交付以最终回执为准。
基于已发布 d6729de3（A）及其 P2 依赖，用户明确启动 B，功能分支叠加开发。
[任务登记](AGENT_TASKS.md) · [A ABI](NATIVE_SCRIPT_ABI.md)。不整合主线、不部署、不做生产迁移。

## DDD 与版本边界

- 原生执行上下文拥有不可变 ScriptBinding/ScriptPlan、脚本 Bundle 扩展、Definition3/Task snapshot3。
- 新扩展封装原 Bundle1（基础20域）和精确脚本闭包，不改变原 Bundle1、Definition1/2 和 Snapshot1/2 的字节/摘要。
- ScriptAssembly 使用明确新 discriminator；老 reader 不会静默忽略执行字段。Registry 继续用现有 JSON sidecar，不重写历史。
- Manifest、源码各自固定摘要；包源不内联执行快照。私有 execution-catalog/2 显式批准完整 scope、profile 与精确脚本集合，复用现有配置路径与基线 HMAC。
- 平台原 P2/脚本 A 合同保留原制品；Go 仍无 Python 执行路径。可执行上传/资产分发、写入/Secret SDK 不在 B。

## 准入与授权

API 的 Runtime Bundle 解析显式区分旧 Bundle 和新脚本封装；物化要求 publisher 同时获精确基础 Bundle 与脚本封装引用，不能由基础允许集推导脚本权利。
消费 Host、产品环境/目标、当前 Task snapshot 与完整作用域沿用既有边界。
Worker 先核对新 reader、原模型/基线/镜像、完整脚本闭包、受信 profile 与当前 Host scopes；缺失/漂移拒绝，不退回无脚本执行。
每次执行、收据重放、结果提交都重新检查当前 Task/Host/STOP/lease 与精确当前脚本批准；冻结配置不扩大当前权限。
开发 OS sandbox 与生产 gVisor 明确区分；生产模式必须 gVisor/固定镜像，缺真实隔离证据不宣称上线通过。

## 三执行点

- Tool：沿既有 ToolContract/ModelToolDefinition/Policy/FencedEffectToolGateway，独立 native.* 名称、只读且不并行；输入与输出仍是 A 的封闭 scalar record。
- Context：输入固定 user_input，输出 text 作为有来源、低信任的运行证据进入原 ContextCompiler，不能成为 system policy 或扩权声明；每 Task/输入固定身份。
- Verifier：在完整候选的 ANSWER_COMMITTED 写入之前执行，只可拒绝既有成功候选；passed=true 不生成 verification freshness、EvalEvidence 或 Coverage certificate。
- 严格 Coverage 路径不接受新脚本配置混入；现有 Coverage 与旧快照恢复路径保留。

## 原生调用状态与恢复

使用现有受租约保护的 Session Event Store，不复制 Task 聚合或另起无关收据数据库。
Native invocation 应用服务拥有状态转换；Journal Port 将受限查询与追加映射到现有 fenced Recorder。
UUID5 调用身份固定 Task、snapshot digest、binding、逻辑调用标识及完整输入摘要。
事件固定 schema、调用身份、owner fence、执行尝试、binding/Manifest/输入身份（binding 摘要覆盖源码引用）；终态包含父进程观察与验证后输出摘要/内容。

- append started 成功后才执行。数据库未知结果不伪造未执行，不自动补成功。
- 已完成且匹配的收据在重新授权后重放，不再次分派脚本。
- started 无终态属于未决；同 fence 不重复执行。只有新有效 fence 可对 effects=none 的纯读变换重新计算，最大3次，保留原身份及各次记录。
- 晚到旧 Worker 不能提交新收据；依赖现有 epoch/fence 原子 Worker event transaction，而不是进程内锁。
- 终态或答案持久事务异常直接传播；不信任外层 COMMIT 前已推进的 Recorder 缓存，恢复先重新读取持久事实。业务写入仍不支持，不能借纯读恢复语义盲重试写入。
- Journal 读取必须有事件/字节/期限上限，超过预算拒绝，不能把未完整搜索当成没有收据。首版有界流扫描的成本需明确，后续索引优化另立任务。

## IPC 与取消

源码/调用通过有界私有 stdin pipe 输入，不作为 argv；不向脚本传管理/Host凭据。
复用 RuntimeExecutionRequest 与共享进程执行器，保持默认调用行为；为只读脚本增加有界 stdin 与取消回调。
执行期间持续检查当前控制/所有权，STOP、撤权或 lease loss 原样中断；杀原进程组，OCI 同时销毁对应受权容器，不伪造成功/回滚。
正常超时仍是失败观察；取消/租约异常不降级为可接受 ToolResult。
provision 前后也检查权限，启动/清理预算继承既有 runtime lifecycle；局部信号量不替代分布式租约。

## 验收出口（未完成不打勾）

- [x] 新格式/闭包/私有批准、当前权限、旧 canonical 金样、旧 reader 拒绝。
- [x] 实际私有 stdin、STOP/lease/撤权取消、进程树与容器清理，失败不泄露输入/源码。
- [x] 实际 Worker 三执行点、模型可见工具/Context 数据、Verifier 拒绝不能变成功。
- [x] 真实持久存储、跨进程/新 fence 重启重放、未决/COMMIT未知与旧 Worker 晚到拒绝。
- [x] 当前授权/撤销与重放/最后提交竞争；不兼容 Worker 拒绝与匹配 Worker 恢复。
- [x] 旧任务/历史数据与 Coverage 保持专项；冻结源码 make test/check 全通过并记录跳过界限。
- [x] 正式文档/任务与验证证据同步，准备已验证的分支提交；按授权推送并在最终交付回执核对远端 SHA。无部署/生产迁移。

## 交付与配置入口

[机器合同与显式新 reader](contracts/native-script-worker-v1/README.md) 导出 ScriptBundle、Plan、Assembly、Definition3、Snapshot3 和调用事件 schema。
旧 A/P2 合同目录保留原字节。既有通用 `POST /agent-definitions/{definition_id}/versions` 的
`runtime_bundle` 可传新 wrapper；仍要求现有 Host publisher 认证/原生评估门禁，且额外授予：

```text
runtime-bundle/<base_bundle_digest without sha256:>@1
script-bundle/<outer_bundle_digest without sha256:>@1
```

发布服务再次核对脚本引用。消费入口还核对当前批准的 consumer Host、全 scope、两项精确引用和每个 binding scope。
原 P2 `bundle-validation/1` 和 `/management/v1/runtime-publication` 继续只接受 Bundle1；
此片不暗改已被 Go 固定的合同。平台上传、脚本验证 HTTP 合同与资产分发仍由后续 OD-P3 承接。

API/Worker 继续使用 `ZEBRA_RUNTIME_BUNDLE_CONFIG` 挂载私有文件。catalog/2 保留 catalog/1
的 scope/image/baseline_key/baseline_config/providers/output_schema/build_evidence，并增加：

| 字段 | 内容与限制 |
| --- | --- |
| schema_version | `cloud-agent.execution-catalog/2`；无默认升级 |
| script_plans | 1–8 个完整 NativeScriptPlan，精确批准，不读取 latest |
| scripts | 1–16 个 A Manifest 加 `source` UTF-8 文本；源码仅留在此私有批准中 |
| Plan.runner | development/os-sandbox 或 production/gvisor；Python 绝对路径 |
| Plan.bindings/lock | 1–8 个 native.* 绑定、非空 scopes，以及按 kind/id/version 排序的精确 Manifest/Source pins |

Context 输入固定 user_input，Verifier 输入固定 tool_status/tool_output；其他输入输出遵循 A 封闭 scalar record。
每字段字符串最多4096 UTF-8字节，整个规范化调用最多16KiB；大候选不绕过约束，拒绝提交。
生产 gVisor 的实际配置镜像摘要必须等于 base Bundle 的 image pin，且资源上限可容纳绑定。
原配置基线 HMAC 不因配置路径/私有 catalog 升级而改变；实际 Worker 的其他基线配置仍需精确匹配。
缺旧版本批准或旧源码时明确拒绝恢复，不能借新版本源码“修复”旧任务。

## 取消、授权与保证边界

- 运行时 stdin 与取消回调支持有界 POSIX 捕获；Windows 旧调用行为保留，新脚本 Worker 不在该子集。
- 执行中的进程每至多50ms调度一次授权检查；实际取消还受数据库检查期限与系统调度影响，不承诺50ms端到端 SLA。
- 取消在 provision 前后检查；provision/清理沿用现有 OCI 管理期限与受租约保护的实例生命周期。此片不宣称启动中的容器可瞬时取消。
- 最后答案持久写入在短 Host FOR SHARE 事务中复用原 Worker CAS；并发 registry disable 与该写入串行化。
  脚本执行在事务之外。Verifier false 没有 ANSWER_COMMITTED，既有已提交答案恢复规则不作削弱。
- 当前 Host 检查包含 active、issuer、namespace、policy_version、origin、原授权 expiry；冻结 scopes 只是上限。
  未实现的外部业务逐用户 ACL 主动撤销不能由此推定存在；需要业务新授权/过期或原生 Host 撤销边界。
- 私有脚本 catalog 是每个部署实例的明确批准，不是跨副本在线撤销服务；新旧副本需运维一致配置。
  最后写前重读批准不能把本地文件更换与数据库 COMMIT 变成分布式原子事务。
- Journal 逐页读取固定 highwater，最多8192事件/8MiB，共享2秒数据库预算；超限拒绝。
  尚无调用索引，长会话应在后续专门任务增加持久索引，不能临时扩大到无界扫描。
- 纯读未决调用可在新有效 fence 下重算，最多3次；仅已提交的终态保证相同输出重放。
  Python 标准库不保证函数语义确定性，源码摘要也不证明业务正确。
- 真实开发验收使用独享 PostgreSQL 与 macOS Seatbelt；生产 gVisor 只有适配/配置/拒绝路径检查，
  未执行生产镜像、真实 gVisor 集群、吞吐/故障域 HA 验收。未部署或执行生产迁移。

## 当前验证记录

专项64passed/零跳过：含实际 Worker 三执行点、拒绝前置、Host最后提交竞争、STOP/lease/Host实时取消、
真实持久收据、新进程重放、未知 COMMIT 不结束 Task。独享临时 PostgreSQL 保持专项74passed/零跳过。
最终 make test10822passed/3008既有依赖跳过，1100.23秒、exit0；make check通过，mypy1381源文件、eval30/30。
冻结2899项源码/合同，全量期间零漂移；旧入口回归124pass，策略构造入口13pass。
[验证记录](evidence/ca-p3-01b/validation.json) 区分受控失败复现、被中断/未通过轮次和最终通过结果；
不以这些开发证据关闭后续线上资产授权、分发与 gVisor/HA 接入验收。

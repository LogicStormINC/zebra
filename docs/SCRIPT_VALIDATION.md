# CA-P3-01C — 公开原生脚本校验前置

2026-10-21；Owner Luke Ding；基于已发布 CA-P3-01B60893da8。
[任务](AGENT_TASKS.md) · [A ABI](NATIVE_SCRIPT_ABI.md) · [B Worker](NATIVE_SCRIPT_WORKER.md) ·
[机器合同](contracts/script-validation-v1/README.md)。功能分支继续开发，不整合/部署或生产迁移。

## 依赖与 DDD 边界

OD-P3-02A 的资产上传/编辑/不可变版本需要消费真实原生校验合同。
B 已有 ScriptBundle、Definition3 和实际 Worker 三执行点，但旧 P2 scoped HTTP 仍只接 Bundle1；
不能绕用通用 Host publisher、复制 Go 编译规则，或把草稿保存当成可执行批准。
本片先提供无副作用的包校验入口，资产管理在消费固定合同后另片实施。

原有 NativeScriptManifest / parse_native_script 仍拥有 ABI、严格字段、类型、摘要、源码语法规则。
HTTP 模块只做认证/当前批准复核、传输翻译和返回原生观察；无新业务聚合、执行状态或存储。
复用原 Bundle 校验的有界流/线程 transport；旧 URL、凭据、错误、期限、槽位和合同原字节保持。
不改旧 Schema/Task/Version 数据，不修改 Coverage 证明算法或事件，不新增数据库 DDL。

## 开发者接口

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| GET | /management/v1/script-contract | 当前 scope 下发现 script-validation/1、schema、限制和合同摘要 |
| POST | /management/v1/script-validation | 固定合同下纯包校验；不保存或执行源码 |

必须同时传 Authorization: Bearer rtsv_<43个base64url字符>、
X-Runtime-Deployment、X-Runtime-Audience、X-Runtime-Product、X-Runtime-Environment、X-Runtime-Trust-Revision。
POST 额外传 Content-Type: application/json 和 X-Runtime-Script-Contract（发现的精确 contractDigest）。
生产传输由调用者/入口提供经过受信配置验证的 HTTPS；本轮 socket 验证使用自有 loopback HTTP。
不得把源码/令牌放 URL、Cookie、日志、指标或错误正文。

请求严格只有 schema_version=cloud-agent.script-validation-request/1、scope、manifest_base64、source_base64。
scope 六字段为 authority_issuer、namespace_id、product_id、environment、target_id、deployment_id，
必须完整等于私有批准；并与当前部署 namespace 和请求头绑定。
源码和 Manifest 使用标准且规范的 Base64（含必要 padding；拒绝空白、额外 padding 和非零 padding bits），
解码后各最多16KiB且非空。Manifest 保留原始字节；通过已有严格 integer JSON 解析。
完整请求体最多64KiB，duplicate keys、未知字段、BOM、浮点、NaN、畸形/过深 JSON 均拒绝。

POST 返回 contractVersion/contractDigest、scope/trustRevision/observedAt、
inputDigest（完整原始请求字节 SHA256）、manifestDigest（原生规范 Manifest）、sourceDigest（原始源码）、
name/version/kind/sourceBytes、三个 passed 检查及明确能力限制。没有源码、凭据或编译异常详情。
允许以同一固定请求重做纯校验；观察时间可变化，不产生跨服务写入或 exactly-once 声明。

## 独立授权与配置

显式挂载 ZEBRA_SCRIPT_VALIDATION_CONFIG 指向绝对路径的私有普通 JSON 文件（0400或0600，最多16KiB）。
不接现有 rtmg/rthm/rtbv/rtpub/Host/Agent Token；令牌只在此接口有权限。
只保存服务令牌 SHA256；部署系统单独向平台提供原令牌，示例使用占位符，不附真实凭据。
批准严格字段：

```json
{
  "schema_version": "cloud-agent.script-validation-approval/1",
  "scope": {
    "authority_issuer": "https://authority.example",
    "namespace_id": "namespace-a",
    "product_id": "product-a",
    "environment": "dev",
    "target_id": "target-a",
    "deployment_id": "runtime-a"
  },
  "audience": "overdoze-script-validator",
  "trust_revision": 1,
  "credential_sha256": "<64 lowercase hex characters>",
  "expires_at": "2099-01-01T00:00:00Z",
  "actions": ["script.contract.read", "script.validate"]
}
```

操作批准在读取/编译之前和返回观察之前完整重读：令牌、action、UTC期限、trust revision、
全部 scope、其余批准内容任何变化均拒绝本次成功。配置缺失/不可读/畸形/namespace未知返回503。
缩权可只保留一个 action；原子替换挂载文件用于轮换，当前节点读新配置后生效。
这是单次请求观察点，不能把它用作未来调用权限。每副本文件批准仍需部署一致性，
没有分布式资产撤销或原子“配置替换+任务提交”的保证。
新设置为 keyword-only；API-only 路径从既有基线 HMAC 排除，旧固定摘要不变。

## 有界资源、失败和保证边界

每实例两条新路由共享8个槽（旧 Bundle 路由另有8槽）；无等待队列，满时429+Retry-After:1。
槽位先覆盖收流：最多0.2秒、64KiB。原生线程回应最多等待1秒；
超时返回503，取消/超时后仍保留实际线程槽，直到工作结束才释放并收取消费晚到异常。
客户端输入导致的语法/摘要拒绝为422 SCRIPT_REJECTED；合同不匹配409，
凭据401、scope/action/expiry403，畸形传输400、错误方法405，统一 no-store且固定脱敏错误。
总容量需乘副本数，并计入共享线程池、其他管理路由、内存和 CPU；无生产 QPS/HA 证明。

源码只传给已有 compile 检查，绝不 import/exec。通过不证明 execute 函数存在、外部依赖可用、
代码安全、业务语义正确或终将执行成功。stdlib-only/effects=none 是 ABI 声明；
实际隔离、输入/输出/权限及当前 Worker 批准仍由 A/B 执行边界强制。
本回执不是持久构建证明、资产信任批准、EvalEvidence、可发布 Bundle 或 Coverage certificate。
Go 后续 BC-ASSET 保存原始草稿/校验意图与不可变版本；再通过显式脚本 Bundle 的独立准入流程。
旧 P2 /management/v1/runtime-publication 和 bundle-validation/1 仍不接脚本封装，
公开脚本 Bundle 的 scoped 装配/发布扩展、资产分发/撤销、Secret/业务写入 SDK 仍为后续工作。

## 验收

[本轮证据](evidence/ca-p3-01c/validation.json)记录专项、全量与冻结源码；
实际 socket 子进程验证合同、正负例、当前授权轮换和数据库行数保持。
上传代码不执行、最终批准竞争、请求取消/超时/背压、旧 Bundle transport 回归均有确定性检查。
老 A/B/P2合同目录逐字节固定，旧任务/PG历史/Coverage机制由保持回归和全量门禁验证。
不以本片证明生产 TLS、真实 gVisor、集群故障恢复/HA或 Overdoze 上传业务已完成。


### 既有PG测试夹具修复

额外独享PG保持专项暴露4个既有夹具失败，已在未修改的B60893da8同样复现：
证书读取测试仍拦截旧bounded方法，而当前走VerifiedArtifactPayloadReaderPort；
3个伪造事件测试被后来已存在的数据库不可变事件触发器提前挡住。
本片只更新该测试的实际Port观察点；伪造用例先断言正常UPDATE被生产保护拒绝，
再在独享临时schema事务内SET LOCAL session_replication_role=replica模拟磁盘/特权损坏，
继续验证原有证明读取拒绝和行数保持。没有修改生产触发器/算法/DDL或历史事件。
首次全量因这一夹具修正主动中断，保留原日志/冻结清单；最终门禁使用修正后重新冻结的源码。


### 最终门禁（2026-10-22）

make test：10856passed/3008既有依赖跳过，1109.12秒，exit0；make check：通过，mypy1385源文件/eval30/30。
专项50passed零跳过；独享PG历史/证明保持106passed零跳过；3613项源/配置/合同冻结零漂移。
默认门禁的环境跳过与显式PG保持专项分开记录，不声称外部S3/gVisor或生产HA已验证。
提交/推送依授权执行，实际远端SHA以最终交付回执为准。

# Cloud Agent 第二批去耦实施设计

日期：2026-10-20；分支：cloud-agent；负责人：Luke Ding；执行：Codex。
开工条件：先修复 CLOUD-EVAL-BASELINE-01，make test 与 make check 均退出0。
条件满足前仅审计/设计，不修改第二批运行路径。保留第一批和用户既有工作。

## 1. 范围

本批实现通用身份授权交换、显式资源绑定和通用计划续权。
保留 Trench 的现有能力，通过可信配置选择兼容适配，不按 host 名或工具名
在通用逻辑中选择业务权限。无需新依赖或历史摘要/事件改写。连接器策略采用新增可空列的追加迁移；
旧记录保持 NULL 与原 digest，不执行现有数据库迁移或历史数据回填。
不实现 overdoze Go 后端、access/refresh token 发行服务、Coverage 协议或业务消息迁移。

## 2. 身份与业务授权

通用 Broker 只认识不透明稳定身份、workspace、scope、resourceRefs、有效期。
identity key 不是凭证；Bearer/Cookie 必须由受信的外部业务/身份服务验证。
工作负载 HMAC 只认证调度器，不能把 principal 中的源列表或 scope 当作当前权益。
通用交换必须调用显式配置的 HTTPS authority endpoint 重新确认当前权限；
未配置、不可用、过期、权限撤销或主体漂移都拒绝签发，不降级到历史声明。

保留现有 /exchange 与 JWKS，以及 HostSessionGrant 签名/隔离/限额/消费契约。
通用 authority 请求转发原始交换载荷及选定凭据：交互凭据或已验证工作负载
签名，不能由调用者指定上游 URL。转发签名时须保留原始规范化请求对象及原始
HMAC headers；经过默认填充/类型转换的对象不得冒充原签名载荷。另一选择是
由 Broker 以明确的新凭据签署规范化请求。业务服务独立验证凭据并计算当前权益。
响应至少明确身份、workspace、Host/namespace、scope、resourceRefs 与有效期；
响应必须匹配配置中的 Host/namespace，及已验证 workload 的预期主体/workspace；
空 scope/资源集合表示没有对应权益。请求业务资源不得使用保留的 thread/run/principal，
由 Broker 自行生成且每种恰好一条。请求权限必须被当前权益覆盖，签发只保留请求范围；
过期时间取配置 TTL 截止与 authority 截止两者较早值，后者必须有时区且尚未过期。
Cookie、Bearer、工作负载签名和服务密钥不进入持久化记录或错误详情。
身份 key 成为 Grant subject/principal 的稳定不透明标识，不建立业务用户表。

旧 Trench Cookie 校验、订阅源/历史权限、旧 scope 回退隔离在显式兼容模块。
旧 workload 的签名声明信任行为保留于兼容模式，不宣称它已重新验证当前订阅；
未升级业务 workload authority 前不能把旧模式当作通用的实时撤权证明。

## 3. 通用计划续权

排除 thread/run/principal 后，其余原资源类型均作为不透明业务引用传递。
通用请求不生成 activeSourceIds；该字段仅在显式旧兼容协议中保留。
新签名授权必须匹配 Host、namespace、workspace、issuer、origin、policy、subject，
并且 thread/run 必须分别严格匹配本次 schedule_id/fire_id，principal 匹配 owner。
要求当前授权覆盖所有请求 scope/资源，丢弃新授权多出的资源和权限，并收紧限额。
不改现有 Schedule 记录、触发 ID、幂等键、持久化/恢复语义。

## 4. 显式 Manifest 与历史恢复

复用现有 HostToolManifest 丰富工具契约和 ResourceBindingRule，不新增第二套工具
协议。新通用实时发现要求每个工具显式声明 resourceBindings；空列表表示无需
资源绑定，不能触发 Trench 推断。严格校验 required/matchMode，不作布尔强制转换。

兼容选择来自受信 connector profile 或部署设置；不能由 Host response、工具名、
Host ID 或历史 supported_protocol_versions 文本决定。小型 profile policy 字段
仅在显式设置时进入 profile_digest；旧 JSON 缺省时维持原 digest/兼容语义。
策略变更必须发布新的不可变 profile revision 和对应冻结，不能重用旧修订缓存
冒充显式声明。新声明模式在冻结载荷中持久保存并参与 manifest 摘要，恢复时
不可丢失空声明。
历史 unversioned 冻结载荷保持原解析/摘要；不重写旧 profile、Manifest、Task。
已冻结新声明不能在恢复时降级到旧推断；所有恢复仍验证原绑定摘要。

本批不宣称 HostCapabilityManifestV1 的完整语义 ceiling 已接入生产 admission。
该类型的 ResourceBindingRule 可复用，但当前实际执行契约仍是 HostToolManifest；
本批继续通过 scope、resource binding 和现有 Policy 强制授权，不改变 Task ceiling。

## 5. 实施清单

- [x] 前置检查：eval30/30；make check 与 make test 均退出0并留存日志。
- [x] Broker：固定通用/兼容两种适配，业务规则外移；新 authority 正反例覆盖。
- [x] 计划续权：不透明资源、当前权益确认、严格触发绑定、不扩大范围；旧模式回归。
- [x] Manifest：可信 profile policy、严格实时发现、新冻结声明、历史 digest 金样。
- [x] 配置接入：API/Worker factories 与部署兼容配置传递正确策略；默认通用中立。
- [x] 非 Trench 认证/工具调用/前端契约/续权及恢复验证；明确模拟与真实证据边界。
- [x] 安全回归：有效 HMAC 但权益撤销、保留/重复资源引用、错误 fire thread/run、
  新显式空绑定冻结恢复、历史 digest 金样均覆盖。
- [x] 全量 make check/make test，独立规格与质量审查；更新任务/进度/交接日志。

## 6. 数据与验收保护

不修改/清理旧事件、绑定、Manifest、任务或业务数据库；不更换生产凭据或镜像。
旧产品重新部署需要显式兼容配置；未升级产品 authority 时旧业务行为仍可运行。
本地集成仅使用独立临时资源。不得通过减小 scope 检查、跳过失败门禁或更改
评分阈值制造通过。源码检查、模拟 authority、真实存储/HTTP 以及生产业务验收
分别记录。具体 Owned paths 在 AGENT_TASKS 开工前冻结，扩展前先登记。

## 7. 最小实现约定（开工后遵循）

- connector 新增可空 `manifest_binding_policy`：`declared` / `legacy`。
  缺省仅解释历史 profile 的旧兼容；None 不进入 profile_digest，不改旧 JSON。
- 持久化审计发现 registry 逐列存储 profile；必须新增独立可空 policy 列，
  不能借用 supported_protocol_versions JSONB 或协议文本。追加迁移仅在独立
  临时数据库验证，不修改现有服务数据库；部署须先按正常流程应用该迁移。
  新通用连接器明确选择 declared，现有 supported_protocol_versions 不作策略开关。
- 实时 HostToolGateway 默认 declared；API/Worker 工厂从可信 profile 传入策略。
  环境 fallback 使用显式部署设置，旧 compatibility overlay 选 legacy。
- 新冻结 wire payload 保存 `bindingPolicy: declared` 并参与摘要，包含显式空
  resourceBindings。历史 decoder 继续读取旧无 marker 的冻结字节；实时 strict
  路径由可信策略强制，不能由响应中的 marker 降级。
- API 读取冻结缓存也核对声明策略；同修订旧缓存不能冒充新 declared profile。
- 历史金样（开工前保存）：现有 tests/worker/test_resource_binding_resolution.py
  的 legacy fixture 冻结摘要为
  `5082cc40e9ff8e5ac317789449a800fd7a54ad5f3b61fb20952746abdcdcf2a6`。
- Scheduler 通用协议不含 activeSourceIds；旧协议的转换隔离在兼容模块，
  由配置选择，不能按 owner.host_app_id 猜测。Worker 代码不引入产品名称分支。

## 8. 开发者接入契约与升级步骤

通用 Broker 通过以下环境变量配置，不能由交换请求选择 URL 或业务模式：
`ZEBRA_GRANT_BROKER_AUTHORITY_MODE=generic`（进程默认）、`AUTHORITY_URL`、
`HOST_APP_ID`、`NAMESPACE_ID`、`ISSUER`、`ORIGIN`、签名私钥与允许 scope。
以上名称均带 `ZEBRA_GRANT_BROKER_` 前缀；authority URL 必须使用 HTTPS。
`/exchange` 接收 audience、threadId、runId、scopes、resourceRefs；交互请求带
Bearer/Cookie，调度请求携带原有四个 X-Zebra-Workload 签名头与 principal。
配置的 authority 以 POST 接收原始 JSON 和选定凭据，必须独立验证凭据、签名
及当前业务权限，响应如下（principalId 就是不透明 identity key）：

```json
{
  "principalId": "opaque-user-key",
  "workspaceId": "workspace-1",
  "hostAppId": "catalog",
  "namespaceId": "catalog-tenant",
  "scopes": ["agent.run", "record.read"],
  "resourceRefs": [{"type": "catalog.record", "id": "record-1"}],
  "expiresAt": "2030-01-01T00:00:00Z"
}
```

示例过期时间只说明格式；实际必须是当前仍有效的授权截止时间。
Broker 签发仅保留请求子集，授权截止与 Broker TTL 取较早值。
Token pair 发行/刷新接口仍由外部身份平台实现，本批没有新增用户库或冒充该服务。

1. 正常部署流程先应用追加的 v106 nullable policy 列迁移；历史行不回填，
   历史 profile JSON、摘要及事件保持原样。此轮仅在新建临时 PostgreSQL 验证。
2. 新业务发布新 connector revision，明确 `manifest_binding_policy=declared`，
   每个工具声明 resourceBindings，包含无需资源的空列表。切换绑定沿用现有 CAS。
3. 部署 fallback 使用 `ZEBRA_HOST_MANIFEST_BINDING_POLICY=declared`；Scheduler
   使用 `ZEBRA_SCHEDULER_GRANT_EXCHANGE_PROTOCOL=generic`，由 authority 查询当前权益。
4. 现有 Trench 使用明确 compatibility overlay；Broker 模式 `trench_legacy`，
   Scheduler 协议 `legacy`，fallback binding policy `legacy`。该模式保留原行为，
   不提供新的当前权益复核保证。历史 pinned profile 缺省策略继续兼容，不改旧任务。
5. 新 Host 注册用 `scripts/register_host.py`（所有 Host/namespace/issuer 参数必填）；
   原 `register_trench_host.py` 为兼容入口。发布前端 profile 必须明确 `--profile`、
   `--host-app-id` 和 `--namespace-id`；`--check-only` 只验证文件且不连接后端。

回滚需要恢复旧镜像及原 connector binding/revision；新 policy 列可保留，不能删除
历史冻结记录、改旧 digest 或把 declared 冻结当作 legacy 重新推断。没有生产切换。

## 9. 本轮验证记录（2026-10-20）

前置 eval 修复在第二批任何运行代码变更前完成：真实 Harness 回放中先变更实际
revision，再由后续只读工具验证；不是把所有工具标作 mutation，也没有移除验证门禁。
前置 make test10075pass/2931skip；make check exit0（eval30/30）。

| 证据 | 结果及边界 |
|---|---|
| 第二批认证/签名续权/前端 Harness 链 | 94pass；真实 RS256，HTTPS authority/浏览器回执模拟 |
| PostgreSQL Manifest/Profile/Worker 集成 | 88pass/2skip；独立真实 PG，Host HTTP 模拟；2skip 需要完整 S3 |
| 前端回执数据库恢复回归 | 12pass；真实临时 PG |
| CLI 与初始部署中立检查 | 9pass；不连接真实业务 |
| 最终产品兼容配置及 fixture 回归 | 50pass；RabbitMQ fallback 明确 legacy，未启动产品服务 |
| 独立规格审查 | GO；补齐默认通用配置与 catalog-web wait/receipt/resume 证据 |
| 独立质量/安全审查 | APPROVE；独立134pass，最终配置刷新3pass |
| 最终 make check | exit0；文件限制/Ruff/mypy1323/eval30/30/进度检查全部通过 |
| 五个本地镜像构建 | API、Worker engine、迁移、Broker、Scheduler 全部成功；未推送 |
| 无业务服务独立启动 | PASS；真实 PG/Redis/S3、gVisor mTLS 预检、401、API 重启后对象/注册保留 |
| 第二批首轮完整 make test | 10160pass/2934skip/1fail：旧目录断言止于105，遗漏新增106；保留失败日志 |
| 最终 make test | exit0；10162pass/2934skip，1127.97秒；完整复跑包含目录断言及兼容配置补充 |

独立启动首次使用了基础 worker target，缺少 Docker CLI，健康检查失败。该操作
错误日志与失败结果保留；改用 Compose 原已指定的 worker-engine target 重新构建后
复验 PASS，没有修改源码/健康检查，也没有降低 gVisor 要求。

所有日志位于 `.artifacts/cloud-decouple-02/`。`independent-boot/` 保存失败，
`independent-boot-engine/` 保存纠正后的实际启动结果，`images.json` 保存镜像 ID，
`reviews.json` 保存审查结论，`preservation-final.json` 核对原有32容器ID、
用户文件与临时资源清理。新增 v106 只应用到临时 PG；旧服务/数据库未操作。
首轮全量运行期间仅补充显式产品兼容 YAML 与对应定向回归，生产 Python 源码保持冻结；
该补充单独通过50项检查，随后完整 make check 再次退出0。目录断言修复后再次
完整复跑 make test 与 make check，均退出0；最终59个源码/测试/配置文件哈希
与冻结快照一致，详见 validation-summary.json。

以上是源码、真实存储、隔离进程启动与模拟 Host/浏览器组件的证据组合，不能称为
生产业务联调或完整部署产品 E2E。Coverage 通用化与产品消息/兼容退休留给03/04，
本轮没有宣称全部 Trench 耦合已清除，也没有自动切换生产、新旧任务或业务认证服务。

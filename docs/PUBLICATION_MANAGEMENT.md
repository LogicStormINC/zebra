# Runtime 原生发布与消费授权（CA-P2-01D）

2026-10-21。依赖 A/B/C 的 Bundle、不可变快照和纯校验合同。本片新增
`runtime-publication/1`，不修改旧 v1/v2 字节、历史数据或 Coverage 证明算法。
[公开合同](contracts/runtime-publication-v1/openapi.json)。

## 权威与接入

- Go 管理草稿、校验/发布意图及管理授权；不编译 Runtime，不写 Runtime 数据库。
- 原生私有配置批准专用 `rtpub_` 服务凭据摘要、唯一 scope/Definition、发布者 actor、
  精确引用、Definition 模板、消费 Host、评估者允许集与 policy_version。
- `ZEBRA_PUBLICATION_MANAGEMENT_CONFIG` 指向绝对、私有0400/0600普通文件，最多32768字节。
  结构为 `cloud-agent.publication-approval/1`；字段见 `publication_config.py`。
  actions 为 materialize/publish/read；引用不允许通配；consumer_hosts 不获得发布权限。
- 显式原生迁移 v111 后，运行 `python -m zebra_agent_api.publication_admin
  --deployment-namespace <namespace> --expected-revision <current>` 批准该配置。
  数据库 URL 从已有原生配置读取。此命令不迁移、不启动或部署。
- 使用现有 shared approval 表与锁机制，actor 是独立发布服务身份，不授予 Host 管理动作。
  每请求重新读私有文件且核对共享批准的完整指纹、修订、scope、期限。
  旧副本持有旧 Secret/配置时不能绕过共享审批轮换。删除文件/过期配置失败关闭。
- HTTP 工厂新增显式 Registry/PublisherGrantPort 注入；云端已有 PG stores 也装配 Registry。
  默认旧发布者允许集仍为空，旧凭据不会自动获得发布权限。

## 公开流程

所有请求带专用 Bearer 和 X-Runtime-Deployment/Audience/Product/Environment/Trust-Revision。
无 Cookie、query、重复敏感头、压缩或任意 URL/凭据输入；POST 精确 application/json。

1. Go 已有 Bundle 校验 accepted/current，只证明输入与本地 Target/trust 绑定。
2. POST `/management/v1/runtime-publication`，action=materialize，指定 operationId、
   expectedRevision、versionId、version、bundle。模板与允许引用来自受信原生配置。
   原生 parser/catalog、Draft CAS/validation、精确 Bundle grant 和 Version 服务全部复用。
3. 评估系统/受信原生操作员为该不可变 Version 写入 `AgentDefinitionEvalEvidence`。
   本 HTTP 合同没有写评估证据的权限；不接受 passed 或调用者自报 gate。
4. POST 同一路径，action=publish，operationId、expectedRevision、versionId、evidenceId。
   必须引用最新的原生评估记录，passed=true、Version 摘要、允许的 evaluator_actor 和
   case_summary.policy_version 全匹配。原生现有发布服务创建有效 Release。
5. GET 同一路径，X-Runtime-Operation 为原操作 UUID，查询已提交的精确操作收据。
   404 只表示此刻未见收据；不能当作永远没有提交的证明。网络/5xx结果为 unknown。

返回 contractVersion、完整 scope、trustRevision 和 result。inputDigest 是 **原始 POST 字节**
的 SHA256（带 sha256:），不是 Go 实现的原生语义摘要；重放必须保持原始字节。
Version/Bundle/assembly 摘要由原生服务产生。收据是历史事实，不代表 Release 仍为当前有效版本。
expectedRevision 是专用发布渠道的每 Definition 序列，materialize/publish 每成功操作加一；
它不是旧 Registry Release revision。旧受信操作员发布入口仍保留，Task 使用原生实际有效 Release。

## Task 准入与独立消费权限

`/tasks` 等已有业务 HTTP 仍要求原生 HostGrant 验签、当前 Host Registry、jti 防重放和
principal/thread/run 归属。rtpub、rtbv、rtmg、管理 access token 不能替代业务 Grant。
配置发布渠道时，消费入口要求显式 consumer_hosts、相同签名 issuer/namespace、固定 Definition
和环境以及当前共享审批。返回快照还必须是v2，完整Bundle scope和精确引用匹配当前批准；
即便旧受信操作员将同一Definition切到其他产品，也不得借此跨产品创建Task。生产快照解析不再借用业务 Host 的发布者 ceiling；不开放候选 Eval。
未配置新渠道时保留旧绑定行为。普通及计划 Task 模板使用相同绑定函数。
新渠道当前一个配置批准一个 Definition/产品环境；多 Definition 动态路由另立任务。

## 并发、失败与历史

当前批准锁 → Definition 锁 → 原生 Registry/操作收据，全在短 PostgreSQL 事务内；
嵌套 Registry 适配借用同一连接。Version/sidecar/Release/head/receipt 原子提交或全部回滚。
评估证据追加共享 Definition 锁，发布不能与评估替换交错。原生旧发布入口兼容保留。
审批/配置变化、精确引用缺失、失败评估、CAS 冲突均不能留下部分发布结果。
收据主键包含 deployment namespace、actor、operation UUID，重放不同输入409。

每进程4个 body/thread 槽，body读取0.5秒、HTTP等待6秒，实际线程完成前不释放槽；
原生存储继承5秒 Task I/O/COMMIT预算。总请求最多262144字节、深度24/节点8192
（包含包装结构），无自动重试。读失败/等待超时不证明写回滚；显式查询恢复。
多副本仍需预算乘以副本数；当前 metadata 锁/存储不构成生产吞吐或 HA 证据。
共享 work_unit 只额外识别原生 TaskIoConnection 的严格超时后缀，保留 DSN/schema 检查。
API-only 配置不进入 B 的 baseline HMAC；固定旧摘要回归必须通过。

## 验证与限制

本片检查 HTTP/PG 授权、精确 Bundle、原生评估门禁、原子回滚、重放、CAS、消费隔离和
共享审批。Go 成对验收单独记录。正式最终计数见 PROGRESS 和 docs/evidence/ca-p2-01d/。
评估记录的产生仍由受信原生评估流程负责；测试的显式评估记录不证明商业模型质量。
不扩展 Bundle 支持子集，不升级 v2 strict Coverage，不改变 v1 Coverage 的证明与恢复。
无部署、生产迁移或主线整合。

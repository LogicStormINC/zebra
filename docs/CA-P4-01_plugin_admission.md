# CA-P4-01 — 产品级 Plugin 受信准入公开合同

状态：Review，生产者实现及最终完整门禁通过；公开源由消费者另行固定。
基线 cloud-agent dd94e248，功能分支 codex/ca-p4-01-plugin-admission。

## 范围、依赖和 DDD 边界

复用 PluginPackageManifest/BundleScope、Native package_integrity、现有受信目录
PluginPackagePublicationService、不可变 Artifact 对象和 v111 原操作收据表。
复用共享 HostManagementStore 的严格产品发布者批准和短事务，不创建新 schema，
不触碰 Definition publication heads，不伪造业务 HostGrant/ExtensionScope。
API adapter 只翻译公开 DTO、授权和组织现有用例；包语义仍由 integrations 的原生
完整性/Skill 校验负责，元数据事务在 storage adapter。没有新的执行状态机。

Overdoze A/B 已有结构封存/组织可见性与独立源码权限；它们不是 Native 受信审批。
本前置解锁 C 的原生校验与受信发布消费。D 的产品到用户安装映射、分发/引用及
产品撤销在安装/Turn/Worker 的强制执行仍须独立实施和验收，不能把当前查询 API
或产品发布收据误称为 Worker 已停止。本合同 capabilities 明确 workerRevocation=false。
原有用户安装禁用、Turn admission、Worker 当前安装检查保持原状。

## 公开合同和交互

机器合同及请求/批准 schema 位于 [plugin-admission-v1](contracts/plugin-admission-v1/README.md)。

1. 管理平台以独立 rtpa_ Bearer、准确 deployment/audience/product/environment/
   trustRevision 请求 GET /management/v1/plugin-admission/contract，固定合同摘要。
2. 平台已封存的 ZIP 在消费端拆出排序文件，以 path/content_base64 请求 POST
   /management/v1/plugin-admission，action=validate、scope=完整 BundleScope。
   原生限制64文件、1MiB总字节、每文件64KiB、manifest16KiB；HTTP JSON1.5MB。
   复用真实 package/Skill 规则，不导入/执行源码，不写安装/执行数据。
3. 返回 inputDigest、Native packageDigest/manifestDigest/manifest。平台 ZIP digest、
   结构库存 digest 与 Native packageDigest 是不同事实，禁止替换。
4. 受信发布仍由 operator 装载只读目录，并将准确 Native digest 列入本产品批准。
   新上传的包不会凭结构校验自动变成受信包。平台保存发布意图后显式 POST
   action=publish、scope、operation_id 和 package_digest。
5. Native 先核对共享当前批准，调用已有 publisher 检查受信目录并 put-if-absent、
   固定对象版本，之后短事务保存完整原收据。响应丢失/超时保留 unknown。
6. GET 同一 admission 路径，X-Runtime-Operation=原 UUID，仅恢复原结果；或
   X-Runtime-Plugin-Digest=Native digest 查询当前批准。两 selector 互斥。
   无 selector 的 GET 返回合同。GET 不携带 body；查询参数/Cookie 拒绝。
   非合同调用都要求 X-Runtime-Plugin-Contract=固定摘要，包括 GET。
7. 原收据与当前批准分开：撤销后原 Result/Pin 不变，currentApproval.approved=false。
   404 不证明未提交，不自动重发、换 key、新意图或重领 Controller。

401 凭据错误；403 scope/动作/当前共享批准不匹配或包未批准；409 合同/原操作
冲突；422 包输入拒绝；429 有界并发拒绝；503 配置/存储/对象依赖不可用。
响应 no-store，错误不携带源码、路径、凭据或底层异常。

## 操作配置、CAS 和撤销

默认关闭；ZEBRA_PLUGIN_ADMISSION_CONFIG 指向绝对路径、私有挂载 JSON，形状见
approval.schema.json。共享 actor 由完整 scope 的 SHA256 确定性派生为 plugin-<digest>，不可通过配置覆盖；
同产品目标的凭据轮换/副本不能另起一份批准目录，也不得与其他管理通道共用。scope 包含 issuer、namespace、
product、environment、target、deployment，批准 fingerprint 包含全部配置事实。

显式批准命令（仅隔离验证执行；本轮不操作真实环境）：

    uv run python -m zebra_agent_api.plugin_admission_admin \
      --deployment-namespace <namespace> --expected-revision <old>

沿用现有 PostgreSQL schema，必须事先由运维完成既有正式迁移；HTTP/startup 不迁移。
批准 CAS 只能从旧 revision 到旧+1；当前共享记录必须与私有配置 fingerprint、scope、
期限完全一致。撤销单包：新配置去除准确 digest、trust_revision+1，经上述显式 CAS
登记，再分发新私有配置。旧副本被共享记录拒绝；尚未更新的新副本失败关闭。
仅编辑某副本文件不是全局撤销；全部撤销可移除所有 digest，仍允许当前授权方读旧收据。
如撤销整个发布者则旧凭据无权再读；由新批准凭据在原 actor/scope 下恢复。

每次合同/校验/GET/发布均检查共享当前批准，结束前重读配置及共享批准。撤销线性化
在共享批准事务提交；发布收据提交先胜则保留原收据，撤销先胜则收据提交拒绝。
不声称响应发送瞬间仍未撤销，也不声称撤销能撤回已经派发的外部业务写入。

## 持久性、并发和恢复

复用 (deployment_namespace,actor,operation_id) 主键/同批准 advisory lock，
相同原 UUID 的不同请求字节409，结果不可覆盖。两个副本可重复准备同一不可变对象，
最终只保存同一原收据；不同输入最终冲突。GET 始终用当前凭据授权。
对象网络/目录读取在 metadata 事务之外；撤销/提交失败可留无引用不可变对象，
不代表安装或执行；没有自动 GC 或删除历史对象。精确对象可由原 Pin 恢复，目录
后续变化不会重写已保存收据。已提交操作不因当前批准收窄而丢失历史事实。

HTTP每实例8槽；body500ms、response6秒。取消/超时保留线程及槽至真实完成，不能
因 HTTP 超时提前释放并发预算或当作未提交。跨副本总预算为实例数×8。
共享批准锁按 actor/namespace 串行短元数据事务；5秒/凭据期限限制沿用现有存储。
这是有界正确性基线，不是吞吐/SLO/生产HA证明。未来测量后细化读取并发，不移除
当前性栅栏。没有数据库长事务包裹对象 IO。

## 兼容性和验证

新增根 README.md 仅在原生0.2声明中作为被哈希元数据；未声明源码仍拒绝。
旧0.1规则/摘要保持；旧 Pin、Task、原收据、历史和 Coverage 没有重写或迁移。
新增管理配置排除在 Runtime baseline HMAC 外，避免管理批准改变旧任务装配身份。
前端 mock、BFF凭据、SDK、Controller 和 Worker 生产路径不变。
首次全量发现可选管理入口关闭时仍取对象存储，已修复默认关闭装配。旧 Coverage 测试
夹具的模块导入时钟可在长门禁中失效；共享 wire 改用调用方时钟生成描述符，保留
冻结默认时钟和真实过期拒绝。新增回归模拟两天 collection 延迟及真正过期；
Runtime 的过期规则未放宽。显式 JSON 解析容量只对 Plugin 上传使用1.5MB，
原 Bundle 默认256KB/整数/深度/节点限制保持，大于256KB的合法Skill包已实际验收。

定向检查包括真实隔离 PostgreSQL 的共享批准、旧副本拒绝、单包撤销、原GET恢复、
并发同操作及精确输入冲突；复用 publisher 的受信目录/不可变对象检查。对象端为
确定性进程内 Port 实现，不宣称真实 S3/生产业务/Worker 产品撤销或生产HA验收。
完整门禁与交付源见后续验证记录，不将条件跳过记成通过。

## 最终验收记录

- 最终 make test：11174 passed，3067 条件跳过，0 failed；未把跳过计为通过。
- 最终 make check：边界/文件规范/Ruff/1420源文件Mypy/30Eval和恢复风险检查全部通过。
- 88项最终定向检查；157项装配/Coverage修复检查（21条件跳过）；123项共享
  Coverage调用方检查通过。首次24失败已定位修复，未修改生产过期规则。
- 独立子进程真实PG共享批准更新/旧配置拒绝及公共 create_http_app 的真实PG
  校验入口检查通过，0对象写入；发布对象端为确定性Port测试，不冒充真实S3验收。
- 冷启动子进程10秒超时定向和最终全量复验均通过；未放宽该测试的截止时间。
- 源码、schema和合同产物由 Overdoze 固定最终发布 commit/字节摘要，C实现另验。
- 没有部署、生产迁移、主线合并或历史数据/原收据/Coverage重写。

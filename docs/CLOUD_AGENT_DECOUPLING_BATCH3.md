# Cloud Agent 第三批 Coverage 去耦

日期：2026-10-20；分支 cloud-agent；负责人 Luke Ding；执行 Codex。
用户批准承接第二批（完整 make test/check 已绿），在现有分支实施。

## 契约与边界

v1 Contract、Scope、admission、快照与历史 JSON/digest 保持原有语义。旧业务
适配字段隔离在显式兼容路径。新增 v2 exhaustive Contract，明确 dataset 与修订、
不可变 source 声明和 opaque selection_ref/selection_digest。业务服务负责选择器、
数据权限与授权修订；Core 不解释订阅周期或 visible_at。仅支持 canonical_body，
同样的已发布语义检查与 certified_report_only，不宣称任意内容/任意工具 ABI 已支持。

v2 source 声明包含 protocol=coverage-source/2、resource_type、read_scope、
create_scope；admission 带完整 source_ref(type/id)，与 source 声明匹配。
这些配置参与 contract/admission 摘要并进入原有 TASK_PREPARED/RunBinding；
后续创建、读取、恢复、报告下载从冻结契约派生，不能读 live 配置降级。
新空字段不进入 v1 JSON，旧 history_ref 保持原样；不改写历史事件/快照/摘要。

v2 固定 dataset.snapshot.create/get/page/read ABI，资源参数 source_ref 为字符串 ID；
admission 与 provenance 使用完整 type/id，Manifest 以 /source_ref 绑定冻结资源类型；
不是任意工具名映射框架。每个操作都必须匹配已冻结签名 Host manifest 的
scope/资源规则/风险/幂等要求，以及当前 Host 资源与有效期。调用者声明
较弱的 scope 不会代替工具契约和实际权限检查；未支持的声明必须拒绝。

v2 descriptor wire 外层版本2，provenance 明确 dataset、资源 type/id、workspace、
authority_revision，scope 与冻结 selection、contract digest 严格匹配。
纯通用 Descriptor/Record/Part/页/字节证明格式仍沿用现有格式。
get/prepare/read 恢复也必须校验冻结契约，不能仅在 create 时核对数据集。

## 必须保留的证明与权限

保留封存快照、逐条 ordinal/ID/version/part 验证、完整页哈希、循环游标拒绝、
精确清单/结果集合证明、Artifact 可读性、预算、截止/撤权、Lease fence、
Effect 幂等/未知写恢复和 certified publication。所有最终/流式/回放/文件/下载/
业务输出继续失败关闭；不通过总数相等或模型回答声称覆盖完成。
报告下载需当前相同主体/Host/namespace/workspace/issuer、源资源读 scope、
artifact.read 和未撤销的固定连接器；写权限不能作为下载必要条件。

## 实施与验收清单

- [x] 审计全链路，先登记 Ready/owner/Owned paths，留存旧金样和工作区状态。
- [x] v2 Contract/Scope/source 声明；v1 完整兼容与金样。
- [x] 版本化 source invocation/wire/provenance，读取与重放固定契约。
- [x] Worker admission/Effect/bootstrap/native/recovery 与 API report 资源通用化。
- [x] 非 Trench 完整、缺页/缺项、过期、撤权、错数据集/资源及中断恢复验证。
- [x] 真实临时存储验证及原证明/输出安全回归；区分模拟与生产证据。
- [x] 独立规格/质量审查；报告权限回调与截止时间测试复核通过。
- [x] 完整 make test/check 均退出0。
- [x] 更新正式方案、任务状态、进度及交接；原有数据/运行服务保持不变。

不接真实产品数据源，不修改生产服务/数据，不提交、推送或上线。
第四批消息归属与旧兼容退休仍不在本轮范围。

## 开发者接入与兼容

新产品明确使用 contract.schema_version=2。下列为新增字段片段；checks、预算与
model_profile 仍必须匹配 Runtime 实际发布的定义，不能以自行填入摘要来获得执行能力。

```json
{
  "schema_version": 2,
  "dataset": "archive.documents",
  "dataset_revision": "revision-7",
  "source": {
    "protocol": "coverage-source/2",
    "resource_type": "archive.collection",
    "read_scope": "collection.read",
    "create_scope": "collection.snapshot.create"
  },
  "scope": {
    "selection_ref": "opaque-selection",
    "selection_digest": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  }
}
```

admission.source_ref 的规范序列化为
`{"resource_type":"archive.collection","resource_id":"collection"}`，不能再携带
history_ref；工具实际 arguments.source_ref 为字符串 `collection`。四个工具的
Manifest 必须恰好声明一条 required/exact 的 `/source_ref` 资源规则，类型为
archive.collection，读取工具风险 read，create 风险 write 且必须幂等。
调用者声明的 source scope 必须由冻结 Manifest 与当前签名授权同时覆盖。

v2 创建请求携带 opaque scope、contract_digest、content_requirements 与 source_ref；
业务源按自己已配置的资源/选择器到 dataset/revision 映射创建快照，响应中的
dataset/revision 必须匹配冻结契约。本 ABI 不新增任意数据集路由参数；不能
要求未配置映射的业务端凭 contract_digest 推导数据集。读取使用同一冻结契约。返回 outer wire
schema_version=2，snapshot Descriptor 仍使用通用 schema_version=1。provenance
明确 dataset/dataset_revision、resource_ref（完整资源 type/id）、workspace_ref、
authority_revision；后者等于封存 Descriptor 的授权修订。page/read 的原有
完整页哈希、逐记录版本与字节摘要格式继续使用，不放宽数据枚举与证明要求。

业务端负责按 opaque selector 和当前权益生成有界不可变快照、签名游标、当前
授权状态与规范正文。业务端不支持、快照过期/撤权、缺项、错版本或错误数据集时，
必须拒绝并让 Runtime 保持不可认证状态；不能返回空快照来掩盖失败。
Runtime 证明的是授权有界快照的处理覆盖，不证明上游抓取完整性或零语义漏判。

v1 仍按原版本解码/调用 history_ref，不推断为 v2、不批量替换产品字符串。
新产品选择 v2；历史 Task 恢复继续读取原 contract/admission/manifest。
本批不新增数据库迁移；仍遵守第二批 v106 的常规部署前置要求，本轮未对现有库操作。

## 报告读取与回调权限

报告 GET/HEAD 的入口和 Grant 消费前置只要求当前签名身份、artifact.read 与相同
冻结 owner。随后完整读取器检查冻结源资源的读 scope、精确 type/id、当前 Host
注册/issuer/连接器修订及最终 Descriptor/证书证明。两阶段均不借用 agent.run、
thread/run 或旧执行 Grant 的存活状态来代替报告读权限。POST、非精确报告路径和
其他 Task 接口仍使用原执行授权检查；HEAD/Range/缓存也不能绕开完整报告证明。

联调发现原报告 HTTP 通用租户检查缺失 verified wrapper，且消费回调另要求执行
权限；修复只涉及精确报告 GET/HEAD，真实数据库测试实际执行 before_consume。
报告原有 no-store、错误脱敏、相同主体/工作区/namespace、撤权和最终证明均保留。

## 验证记录与证据边界

- 设计审查、源码规格/权限审查、质量/安全审查均通过。
- Core/source/历史身份定向1320pass；legacy JSON、contract/admission digest、
  Manifest digest 和创建调用 ID 与 pre-batch/HEAD 提取的字面金样一致。
- 真实临时 PostgreSQL 报告链路51pass，含 v1/v2、真实消费前置回调、GET/HEAD、
  规范报告字节与最终撤权复核；API/preflight 定向91pass/2环境跳过。
- make check 退出0：文件限制、Ruff、mypy1324、eval30/30、进度检查全部通过。
- 合并真实 PG Effect/集合证明/预算/恢复回归217pass，530.63秒；无跳过。
- 包含消费前置回调的最终 PG 报告51pass，42.37秒；API/preflight91pass/2跳过。
- 首次完成的完整 make test：10220pass/2974skip/2fail，失败均为截止时间测试
  替换了已移除的通用租户检查。测试改为验证真实 owner 预检、源读取与 HTTP
  外层共用截止时间；保留超时不读源、不交付及 CPU 超预算拒绝断言。独立复核
  通过，定向3pass；全部 Coverage API147pass/18skip。
- 最终完整 make test 退出0：10222pass/2974skip，1118.77秒；
  final-make-test.log。make check 同一源码快照退出0，包含 mypy1324/eval30/30；
  final-complete-make-check.log。跳过项不当作已执行；另列真实 PG 无跳过证据。
- 原有32容器ID与用户 AGENTS.md/.DS_Store 哈希保持不变，临时数据库已清理；
  最终98个源码/测试/配置文件哈希与门禁快照一致。

真实存储验证使用独立新建 PostgreSQL；对象存储、Host HTTP 和模型响应/metadata
为测试 fixture。不能称为真实生产数据源、真实模型或完整部署产品验收。
测试显式固定模型环境别名，避免本机 .env 把 reviewer 变成其他 profile；仅在
刻意损坏的临时 fixture 事务中暂时关闭复制触发约束来验证拒绝，不改变生产触发器。
原始失败/中止日志与最终日志均保留于 `.artifacts/cloud-decouple-03/`。

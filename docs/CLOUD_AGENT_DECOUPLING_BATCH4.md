# Cloud Agent 第四批：消息归属、兼容退出与产品验收

日期：2026-10-20；分支 cloud-agent；负责人 Luke Ding；执行 Codex。
用户明确承接第二/三批本地验收，在当前分支继续；不提交、推送、部署或改写数据。

## 1. 消息归属

Runtime 仅定义和消费 zebra.session.command.ready，携带已接受事件引用，消息不是
执行权限。解析、数据库 handoff、去重、Lease fence、覆盖恢复证明与持久拒绝仍为
原有安全边界。Broker ACK 不表示任务完成，未经确认的发布不能重试成已成功。

Trench Turn/source 属于产品集成：移入 agent_integrations.trench_compat，使用显式
产品解析器/拓扑入口。原 v1 联合 JSON schema/examples 保留为兼容金样，Runtime
另有仅命令 schema。跨仓库产品自己的 trench_models 不在本轮修改范围；不得
给 Core 引入 agent-integrations 反向依赖或用泛型消息放行未知业务类型。

RabbitMQ 默认只初始化 Runtime namespace/ACL；显式兼容模式才创建旧联合拓扑。
旧 vhost、队列、routing、shadow、DLQ、诊断 ACL 和既有私有凭据保留，不删除/轮换。
本轮只做代码/临时 fixture 验证，不操作已运行的消息代理。

## 2. 旧兼容退出

新接入默认 declared Manifest、generic authority/续权和 Coverage v2。旧身份、
历史 Event/Task、冻结 Manifest、Coverage v1 JSON/digest/CallID 不能批量改写。
消息兼容和联合部署必须显式启用；历史解码路径保留，不能因新产品迁移完成就删除。

新增离线退出检查：每个欲退出的兼容项必须附命名空间绑定的、近期只读盘点文件
及其摘要，明确活动/待恢复任务是否排空。仍有任务时必须固定不可变旧 Runtime
镜像与回滚材料；不能把总数为零的空文件或未核实的声明当作生产数据库事实。
检查产物仅代表所提供材料内部一致，不授予线上删除、切流或迁移权限；本轮
没有生产盘点证据，因此默认退出示例必须阻塞。历史解码器继续保留。

## 3. 产品接入验收

复用现有 shared Host/client conformance、通用 authority/续权与 Coverage v2
用例，统一入口覆盖不同业务词汇、显式资源绑定、普通调用、前端 Effect/回执/恢复、
撤权/越权、定时续权与覆盖证明/报告下载。每层证据独立标明环境：进程内 fixture、
真实临时 PostgreSQL、真实 Broker/浏览器/模型/业务源；不能将组合测试称为跨产品
生产 E2E。外部依赖缺失产生 skip 时必须可见，不把缺失门禁计作 PASS。

新增默认源码/配置依赖检查，防止重新导入产品 ORM/消息或默认部署产品依赖。
保留兼容适配与历史契约中的必要常量，精确列明允许位置，不放开任意例外。
旧 Trench 联合验收入口仍保留且手动运行；新增中立接入 CI/Make 入口，产品
验收凭据由对应集成环境持有。不得删除安全/恢复/覆盖发布门禁来获得独立性。

## 4. 实施清单

- [x] 审计/登记 Owned paths；留存先前120个 dirty 文件与32个容器身份。
- [x] 消息归属与显式兼容、Runtime schema、wire 金样及拓扑回归。
- [x] 离线兼容退出检查、默认边界检查与拒绝回归。
- [x] 中立产品接入验收入口/CI；注明各层执行与跳过。
- [x] 独立规格审查，再质量审查，修复全部阻断项。
- [x] 完整 make test 与 make check 均退出0；最终日志保留。
- [x] 正式方案、README、PROGRESS、WORKLOG、任务表及最终保护检查。

## 5. 验证记录

本地实施与验证完成，状态 Review，尚未提交/推送/部署。
.artifacts/cloud-decouple-04/ 保留日志与摘要。
本批不改 Coverage 算法、模型资格、数据库迁移或发布证明。保留现有能力是指
显式旧产品组合仍可使用原协议，历史任务继续按冻结版本恢复；不代表默认 Runtime
继续自动激活所有产品适配，也不代表已在生产退出兼容。


## 6. 开发者与操作者入口

Runtime：`agent_core.contracts.broker_envelope.parse_broker_envelope`；schema 为
`docs/contracts/broker-runtime-v1.schema.json`。历史产品消息显式使用
`agent_integrations.trench_compat.broker_envelope.parse_broker_envelope`，例如传入
`RabbitMQTransport(..., envelope_parser=parse_broker_envelope)`。未知消息仍拒绝。
原联合 schema/examples 文件不改写，旧产品仓库可继续使用自己的相同协议实现。

默认 `uv run python scripts/provision_rabbitmq.py prepare --env-file <private-file>`
和 `apply` 只处理 Runtime。旧联合操作显式追加 `--trench-compat`；source 还需
原 `--source-delivery`。apply 不创建/轮换凭据，prepare 不覆盖已有文件；默认模式
读取既有联合凭据时不要求删除产品密钥。此处是操作说明，本轮未向真实 Broker apply。

`make check` 包含默认依赖边界检查。它检查 production 源码中的产品包导入、
Core 的业务字面值、默认部署配置；历史 v1 常量只有精确文件/值例外。它是静态
回归检查，不是对动态 Python 导入或任意插件的安全隔离替代。

`uv run python scripts/validate_compatibility_retirement.py <plan.json>`：
从 `configs/compatibility_retirement.example.json` 开始，默认缺材料必拒绝。
plan 明确 deployment_namespace、compatibility、historical_decoder=retain、
strategy=drain/pin。inventory/rollback 各为 `{path, sha256}` 引用，路径相对 plan。
inventory 包含同一 deployment_namespace、完全一致的 compatibility 列表、
24小时内且不在未来的时区时间 observed_at、provenance、精确 pending_task_ids。
drain 必须没有待恢复/活动任务；pin 必须给 pinned_runtime.image_digest（sha256）
与完全一致 task_ids。rollback 包含相同 namespace、不可变 image_digest、
restore_procedure。文件摘要、时间、任务集合或兼容项不匹配均拒绝。

成功只输出 MATERIALS_CONSISTENT，live_retirement_authorized/provenance_verified
始终为 false。操作者仍需核实盘点来自完整只读快照、镜像可拉取、恢复步骤可执行、
旧任务对应的冻结协议/覆盖证明可恢复；本工具不验证生产事实，不执行退出。
本轮保留所有历史解码、证书与恢复路径，不进行生产兼容删除。

## 7. 专项验收命令与证据

- `make test-product-conformance EVIDENCE_ROOT=<directory>`：145pass/0skip，
  真实协议/执行路径配合进程内 fixtures，覆盖两个业务 Host/前端词汇、通用当前权益、
  签名授权、续权拒绝、前端 Effect 挂起/回执/恢复、v2 Source 和报告校验。
- `ZEBRA_TEST_POSTGRES_DSN=<scratch-only-dsn> make test-product-conformance-postgres`：
  87pass/0skip，152秒；真实 PostgreSQL 上的 handoff/历史来源/恢复/认证报告。
  各用例使用独立 schema，验证完成后本轮临时数据库已移除。
- 专项 runner 写入 JUnit 和 conformance-result.json，空跑、skip、xfail、failure/error 或 pytest
  非零都不能 PASS。无 PG DSN 时 storage gate 明确 FAIL，不静默跳过。
- `.github/workflows/product-conformance.yml` 分开 contract/临时 PG 两个 job，
  不依赖产品 Cookie/业务库；Trench 联合工作流保留为产品集成手动验收桥接。
  CI 文件已准备，本轮本地命令通过不等于远端 GitHub job 已运行。
- 规格审查：233项消息/拓扑回归，29项退出/边界/runner 回归；显式兼容产生的
  94项模拟 HTTP 拓扑/权限请求与 HEAD 完全一致。质量审查161pass，无阻断。
- 本地定向消息 aggregate268pass/9skip，跳过的是显式 live Broker 验收；本轮
  没有操作真实消息代理，不能声称实际 Broker、真实产品/浏览器/模型 E2E 通过。

- 当前源码 API/worker-engine/migrate 三个 linux/amd64 镜像构建通过；本地镜像
  ID 见 images.json。无 Trench endpoint/Cookie/业务 CA/业务数据库的独立环境
  启动通过；复用引擎基础设施 mTLS，只读 gVisor 预检 ready，无 fallback；
  匿名任务访问401；API 重启后对象与 Host registry 保留。没有创建业务 Task。
- 32个原有容器身份与用户 AGENTS.md/.DS_Store 不变，123个源码/测试/配置文件
  与门禁快照一致；临时存储/网络/进程资源已清理。未操作既有服务或数据。
- 完整 make check 已退出0（mypy1326/eval30/30）；
  完整 make test 退出0：10342pass/2974skip，1139.10秒。
  日志 final-make-test.log、final-make-check.log；文档更新后再次运行 make check。


## 8. 交接与剩余运营动作

实施任务已完成本地验证；正式任务表标为 Review，不伪装已合并或上线。
现有服务、队列、凭据与历史数据未修改。没有新数据库迁移，也没有移动或清理
历史 Coverage 证书。新产品走通用接入；旧任务仍按冻结契约或固定旧 Runtime 恢复。

真实业务源、真实模型、真实 Broker 及浏览器联合验收尚未在本轮执行。产品负责方
需在自己的验收环境运行手动联合门禁、核实当前权限和完整数据盘点，再决定生产
排空/固定镜像与退出窗口。保留兼容模块与历史 decoder 是明确的保留策略；
本地代码去耦完成不代表生产兼容已经退役。


后续整体复核修正了专项筛选/中断和证据命名缺口，详见
[CLOUD_AGENT_DECOUPLING_AUDIT.md](CLOUD_AGENT_DECOUPLING_AUDIT.md)。历史本批
145/87计数是当时快照；最新修复与最终验收以整体复核记录为准。

# Cloud Agent 四批去耦整体复核

日期：2026-10-20；分支 cloud-agent；负责人 Luke Ding；执行 Codex。
本轮承接四批本地 Review 状态，保留全部既有工作，不提交/推送/上线。

## 审计方法与范围

按默认 Compose/镜像/本机启动脚本、通用与兼容认证、Manifest 固定、定时续权、
Worker 路由、Coverage admission/Effect/快照/恢复/报告、消息与拓扑、独立/联合
发布、产品专项验收逐层追踪实际调用与数据契约。全文搜索用于定位，不将所有
Trench 字符串都认定为依赖：历史字段、显式适配、手动联合验收、前端 mock 示例
属于保留项；新产品默认路径不能查询 Trench 或要求它的 Cookie/业务库/服务。

开始前对145个既有 dirty 文件、HEAD 和32个容器身份留存摘要。已有业务库、
消息代理、服务与原始用户文件不作改写；新迁移只在独立临时库验证。

## 确认问题与修复

| 问题 | 原因及影响 | 修复与兼容策略 |
|---|---|---|
| 专项验收少量测试假通过 | 继承 PYTEST_ADDOPTS 筛选后6pass/139deselected也判 PASS | 清除隐式筛选，逐个核对必需模块，空跑/缺模块/跳过/失败均拒绝 |
| 中断遗留旧 PASS | 启动或 XML 解析失败前未清除上轮 verdict | 子进程启动前持久化 FAIL，异常保留拒绝状态 |
| 辅助证据污染发布收集 | conformance 的 result.json 被 release-evidence 当发布门禁读取 | 独立 conformance-result.json；识别旧辅助文件并归档，不忽略损坏的真实发布门禁 |
| 默认开发密钥仍带产品名称 | generator 的默认 kid 与 generic broker 默认不一致 | 默认 host-grant-v1；旧部署继续显式给出旧 kid；拒绝覆盖/部分覆盖已有密钥与路径逃逸 |
| 联合候选遗漏 Runtime 门禁 | v1 只检查 Trench gate，不能保证核心/恢复门禁 | 与独立候选复用相同 mandatory inventory/digest/member 校验，保留额外 Trench gate |
| Connector 自定义路径被忽略 | API/Worker 未将冻结路径传入 Gateway，其他 Host 无法接入 | 显式新 profile 使用配置路径；nullable 历史 profile 保留原 /manifest 与按工具 invoke URL |
| 新 revision 共用 digest 未冻结及跨代写入不一致 | 旧表 digest 唯一，冲突 DO NOTHING 后没有 revision 关联 | v107 追加 Host/connector/revision 关联，两代写入共用事务锁；冲突拒绝，原表/历史摘要不变 |

前五项包括四批集成后暴露的开发/验收/发布缺口；路径与冻结存储两项已存在于
四批之前的 HEAD，不描述成新引入的回归。未发现认证绕过或 Coverage v1 摘要
破坏；修复不修改证明算法、模型资格、授权阈值或发布失败关闭规则。

## Manifest 与历史兼容

不能直接把旧 profile 中过去被忽略的路径变成生效配置。manifest_binding_policy
为 None 的历史 profile 保留旧 URL 行为；显式 declared/legacy 的新 profile revision
才使用冻结 manifest_path/invoke_path_template。当前 path 模型只允许静态路径，
不新增占位符展开。新产品需要发布显式 profile，旧 JSON/hash 无任何新增字段。
API admission、Worker 和报告源读取三处统一使用 profile_gateway_options，防止
后续只修执行而遗漏下载。真实 PG 报告回归同时断言 v2 /execute 与 v1 历史 URL。

原 host_manifest_freezes 表和历史 digest 的 Worker 读取继续保留。新关联需包含
Host 身份，避免不同 Host 使用相同 connector_id/revision 时借用对方缓存。
对历史不含 Host 的记录，只在注册信息可唯一确定所属 Host 时回退；不猜测歧义
归属。v107 必须先于更新后的 API/Worker 启动；新版摘要读取同时查询两张表，不能
让新版二进制直接运行于 pre-v107 数据库。原表保留让旧 Runtime 读取原历史任务，
不意味着旧 Runtime 能读取只写入新表的 Task：在放行新版 admission 前，必须
协调 API/Worker 升级、排空或隔离旧消费者，防止旧 Worker 接到新版冻结记录。
不承诺本改动可无协调滚动上线；本轮未升级或停启现有服务。回滚不能把仅新表
冻结的 Task 分派给旧 Worker，应保留兼容新版读取器或完成这些 Task 后再回退。

更新后的有 Host/无 Host 两种写入都按 namespace/connector/revision 使用相同
事务锁。旧无 Host 入口遇到多 Host 关联必须拒绝，遇到单一关联仅允许同摘要幂等。
若历史表只有不带 Host 的记录，而同 connector/revision 已注册多个 Host，新
admission 不能自动猜归属：操作者应发布可唯一归属的新 connector/revision，
或明确迁移/固定旧版本后再启用。原 Task 按既有 digest 恢复的内容不改写。
生产候选的数据库兼容字段必须填写真实迁移版本及回滚边界，示例/fixture 不作为
可发布证据；不得将本地临时库迁移结果冒充生产迁移完成。

## 验收与证据边界

- [x] 协议/调用链与部署/发布两条独立只读审计。
- [x] 先登记任务与 Owned paths，再实施具体修复。
- [x] 定向配置路径、冻结/并发/历史回归；实际临时 PG 验证 v107。
- [x] 原筛选参数复现现在执行161项，0skip、无缺失模块，不再6项假通过。
- [x] 独立规格/安全和质量复审放行，补齐混合写入与报告调用路径。
- [x] 最终完整 make test/check 均退出0，并记录准确跳过数。
- [x] 更新正式方案/清单/进度与工作区/服务保护记录。

证据目录 `.artifacts/cloud-decouple-audit/`。真实临时 PostgreSQL 证据与 Host/S3/
模型 fixture 分开记录；生产数据源、真实模型、线上兼容退出和实际 GitHub CI
运行不在本轮执行范围。历史覆盖证明只证明授权有界快照的处理覆盖，不扩大为
上游抓取完整性或零语义遗漏保证。


## 当前验证记录

- Root 定向123pass：中立密钥、专项 runner、独立/联合候选、依赖边界。
- 接入路径及历史参数60pass；最终跨代冻结13pass（真实临时 PostgreSQL，0skip）。
- 规格复审45pass、质量复审59pass，均无剩余阻断项。
- 较早广覆盖 PG78pass/2S3skip 在跨代事务锁补充之前执行，保留为早期回归证据；
  最终完整门禁和新存储专项另记，不用早期计数代表最终源码。
- 保留三类过程失败：新增关联测试的陈旧断言、严格模块检查识别到 fixture-only
  文件、共享 helper 替换中重复 kwargs。均通过修复后回归；不削弱证明或门禁。
- 最终报告路由及 API 凭据8pass（52.75秒），真实 PG 中 v1/v2 下载与消费前置
  回调、撤权和自定义 /execute 同时通过；三处配置源共用 helper 的定向38pass。
- 最终产品 PG87pass/0skip（155.31秒），契约专项161pass/0skip（13.41秒），
  后者确实携带原筛选环境变量，但所有必需模块执行，missing_modules=[]。
- 最终 make check 退出0，含边界、Ruff、mypy1328与 eval30/30；完整 make test
  退出0：10376pass/2987skip，1162.17秒。三份当前镜像内部的源码/配置摘要与
  最终冻结清单一致；独立 cloud/gVisor 无回退启动、只读引擎预检、匿名401和
  API重启后对象/Host registry 保留通过。没有调用模型或创建业务 Task。


## 最终结论与交接

默认配置、构建、启动、通用认证/续权、声明能力、Coverage v2、Runtime 消息与
独立发布路径，没有发现必须依赖 Trench 服务/业务库/Cookie 的剩余项。发现的
7类缺口已修复并通过定向、真实临时存储与完整门禁。显式旧适配与历史 v1 字段
继续保留，不将“目录中存在 Trench 字符串”当作默认依赖，也不声称所有产品已
完成真实联合验收。前端 mock 样例未改成真实后端。

最终 make test10376通过/2987跳过，make check退出0（含 mypy1328/eval30/30）。
跳过项不能当作执行证据；最终临时 PG专项87、跨代冻结13、报告路由及凭据8均
实际执行。三镜像与启动只证明本轮本地构建/启动，不作为生产发布证据。

129个源码/测试/配置摘要与最终门禁一致，32原有容器身份和用户原文件未变化，
本轮自建 PG/Redis/S3/网络/进程均已清理。无现有 DB迁移/队列变更/服务重启、
历史记录改写、提交、推送或部署。任务为本地 Review；v107实际部署与消费者
版本协调按上节执行。证据汇总：.artifacts/cloud-decouple-audit/validation-summary.json。

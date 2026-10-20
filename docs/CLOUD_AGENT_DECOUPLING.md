# Cloud Agent 业务去耦设计

- 日期：2026-10-20；审计基线：cloud-agent@8f67261f。
- 负责人：Luke Ding；实施执行：Codex。
- 当前范围：第一、二批本地验收完成；第三批 Coverage 本地验收完成；第四批消息与兼容边界本地验收完成，生产退出未执行。

## 1. 目标与边界

cloud-agent 是独立执行 Runtime；Trench 是通过公开契约接入的业务产品。
overdoze 独立管理产品、配置、能力包、身份交换与发布意图；Runtime 保有
授权强制执行、Policy、Event、Effect、Lease、Artifact、执行及恢复事实。
不共享业务 ORM、业务数据库或内部领域类；管理后台不进入逐次模型/工具调用路径。
本阶段不改 cloud-agent 的 Python 技术栈，不重写 Harness。

完成去耦的标准不是 Git 历史没有 Trench 字符串，而是通用源码、默认配置、构建、
运行、测试和发布不依赖特定产品。历史文档/事件/资源标识保留原始内容。

## 2. 已核实的耦合与处理

| 范围 | 当前证据 | 目标 |
|---|---|---|
| 身份与业务授权 | host_grant_broker/app.py、grant_minting.py 读取 Trench 会话/源并判断资源权限 | 业务身份与权限归接入端；Runtime 只验证执行授权 |
| 工具绑定 | host_tools/legacy_bindings.py 按 events 工具名推断 trench 资源 | 使用现有 ResourceBindingRule 显式声明；不按名称猜权限 |
| 定时续权 | schedule_grant_exchange.py 过滤 trench.* 并输出 activeSourceIds | 通用资源授权引用，重新确认权限且不可扩大原授权 |
| 覆盖处理 | coverage_contracts.py 固定数据集，coverage_admission.py 固定 history 资源 | 保留通用快照/逐项证明/失败关闭；业务 provenance 外移 |
| 消息 | broker_envelope.py 包含 Trench Turn/source 消息 | Runtime 命令与业务消息分别归属各自系统 |
| 部署 | 基础 Compose 挂载 Trench CA，legacy API 固定 namespace | 中立基础部署；既有产品兼容集中在显式 overlay |
| 发布 | v1 candidate 强制 Trench 镜像/提交/数据库修订 | v2 独立候选，v1 联合契约保持严格验证 |
| SDK/验收 | 通用用量组件写入产品名称；联合验收包含产品凭据 | 中立组件与独立 Runtime 门禁；产品联合验收独立保留 |

## 3. 身份与能力契约

开发者接入使用 access_token、refresh_token 与稳定 identity_key。
identity_key 只标识身份，不独立授予访问权限；映射由可信服务完成。
业务 Cookie、用户订阅与资源权益由产品接入端验证。Runtime 继续验证签名、
issuer/audience、namespace、subject、scope、资源绑定、有效期和撤权。
既有 Host 注册和签名执行授权可复用，无需第一批重写验证器。

原生能力与附加插件都走受控工具网关。Manifest 显式冻结 Schema、scope、
resourceBindings、风险与幂等规则，缺失所需绑定应拒绝；明确无资源工具仍可用。
脚本不能绕过授权、沙箱与 Effect；不得导入产品数据库或隐式读取业务 Cookie。

## 4. 覆盖与续权

保留不可变快照、清单摘要、记录证明、预算、恢复和未完成阻止认证发布机制。
通过现有 CoverageSnapshotPort 接入数据源，将业务数据集/权限/provenance
转换为通用契约。不能仅将 Literal 改为任意字符串来声称任意数据集支持。
续权传递主体、原授权、资源、scope、计划和触发 ID；业务端确认现有权益，
Runtime 验证身份不漂移、范围不扩大。业务断开不使整个 Runtime 无法启动。

## 5. 批次与验收

| 批次/任务 | 交付 | 依赖与完成标准 |
|---|---|---|
| CLOUD-DECOUPLE-01 | 基础部署、独立发布、SDK 文案 | 无 Trench 配置真实构建/启动；独立发布 CLI 可运行且缺证据失败 |
| CLOUD-DECOUPLE-02 | 身份适配、显式 Manifest、通用续权 | 第一批完成；第二测试产品普通/前端/定时/恢复闭环 |
| CLOUD-DECOUPLE-03 | 业务快照适配与 Core 契约 | 第二批边界稳定；覆盖证明不降级，核心无业务数据集假设 |
| CLOUD-DECOUPLE-04 | 消息归属、旧兼容退出、产品验收迁移 | 旧任务迁移决策完成；构建/运行/发布/测试依赖检查通过 |

各批次开始前必须在 AGENT_TASKS 中声明具体 Owned paths；不提前扩大当前批次。

## 6. 第一批设计

基础 Compose 保留 API、Worker、迁移及可选 Scheduler；不强制配置 Host 服务。
独立 Scheduler 仍需明确可信签发方及工作负载凭据，不使用空值绕过安全检查。
证书和 legacy API 放入显式 Trench compatibility overlay，旧部署保留相同 namespace、
挂载和能力。中立自定义 CA 路径由操作者显式提供，不偷偷回退到产品目录。

独立候选 v2 只包含 Runtime 的提交/镜像、SDK 版本、数据库兼容、协议、配置摘要、
证据与回滚；拒绝混入联合发布字段。v1 继续完整校验 Trench 镜像和修订。
基础发布将 Trench gate 明确标为未启用；启用联合产品时必须运行对应门禁，
不删除云端一致性、安全和恢复门禁，不伪造 PASS 证据。

## 7. 数据与迁移保护

不更改历史事件、冻结 Manifest、digest、数据库 namespace、任务身份或生产数据。
不批量替换历史 trench.*。先升级业务接入，再退出 Runtime 兼容。
旧任务排空或固定旧 Runtime 完成，不在恢复时静默切换授权或能力包。
本批只运行独立命名的临时验证资源；不重启或迁移现有服务，不执行生产发布。

## 8. 证据边界

构建、启动、发布契约、完整生产发布和跨业务 E2E 是不同验收。
配置渲染不是启动证明；health 不是任务 E2E；合成 gate fixture 不是生产 release。
最终验证记录写入实施计划、PROGRESS 和 WORKLOG，清楚标明跳过与未完成项。

## 9. 第一批本地实施证据（2026-10-20）

源码已实施，未提交或发布。基础部署与显式兼容配置的回归通过；原有产品仍需
在重新创建容器时显式追加 compatibility overlay，不能仅使用新的基础文件。
既有运行服务未被重启，不存在“自动迁移现有部署”的行为。

API、worker-engine、migrate 的 linux/amd64 镜像真实构建通过；在独立临时网络
使用全新 PostgreSQL/Redis/MinIO 完成迁移及 API/Worker 健康检查。
预检连接真实 gVisor mTLS 引擎，未创建沙箱或模型任务；仅复用引擎基础设施凭据，
复制到私有临时路径，不加载 Trench 业务 CA、Cookie、endpoint 或数据库。
匿名任务访问返回401，API 重启后对象存储探针和 Host 注册记录保持不变。
原有32个运行容器身份不变，临时资源清理完毕。

独立候选及演练 CLI 的合成契约用例通过；缺真实门禁证据的发布清单仍拒绝发布。
不把这些 fixture 计作生产发布证据。旧联合 v1 必须有 Trench 门禁 PASS，
独立 v2 不允许启用 Trench，并要求核心/恢复/安全门禁及对应摘要。

SDK 构建/typecheck 通过；make check 的文件大小、Ruff、mypy1319通过，
随后确定性 eval 得分0.80而失败。将 HEAD 中 packages/apps/evals/scripts 归档至
独立目录再运行，同样0.80；对应 baseline 单测也在该归档中失败。该基线问题保留，未放松发布门禁或改动 Harness。
最终定向105通过；全量快照10067通过/2931跳过/1继承 eval 失败。末次 v2
守卫在全量启动后加入，由最终定向验证覆盖。规格与质量审查通过。
完整命令、计数和审查结论见实施计划；原始日志在本地私有
.artifacts/cloud-decouple-01/。本地构建/启动不等于全任务执行或生产发布验收。


## 10. 第二批本地验收（2026-10-20）

第二批通用认证/声明 Manifest/续权已实现，详见
[CLOUD_AGENT_DECOUPLING_BATCH2.md](CLOUD_AGENT_DECOUPLING_BATCH2.md)。
先完成 eval 修复与双全量门禁，再开始第二批；最终重新运行 make test 为
10162pass/2934skip，make check/eval30均通过。独立规格/质量审查通过；
真实存储、模拟 Host/浏览器和实际隔离启动分别留证。五镜像在本地构建，
无 Trench 服务启动/预检及重启保留通过。v106 仅在临时库验证，没有操作现有
数据库或服务，没有提交/推送/上线。此为第二批验收时状态，第三批进展见下节；第四批仍未实施，不能声称已完全去除业务耦合。


## 11. 第三批 Coverage（2026-10-20）

详细方案与开发者接入见
[CLOUD_AGENT_DECOUPLING_BATCH3.md](CLOUD_AGENT_DECOUPLING_BATCH3.md)。
v2 Contract 明确冻结数据集修订、源资源类型/权限和 opaque selector；Worker、
Effect、恢复、存储与报告读取使用同一冻结契约。通用调用采用固定
dataset.snapshot.create/get/page/read ABI，资源参数为 source_ref 字符串 ID。
业务选择、权益与数据集映射由业务源负责；不宣称任意工具协议或任意正文格式已支持。

v1 JSON、摘要、资源参数、Manifest 与创建调用 ID 保持字面金样一致；历史数据
不重写，无新增数据库迁移。封存快照、逐项/逐页/字节证明、精确结果集合、
预算、截止/撤权、Effect 幂等与未知写恢复、最终认证及全部输出守卫保留。
报告 GET/HEAD 的消费前置检查当前相同 owner 与 artifact.read，再按冻结契约
检查源读权限与证明；其他 Task 路由保留执行授权，不要求下载者具备写权限。

真实临时 PostgreSQL 证明/恢复回归217通过，报告链路51通过，含实际消费前置
回调、v1/v2、GET/HEAD 与最终撤权。Host、对象存储及模型仍为 fixture；不作为
真实产品数据源、真实模型或生产验收证据。最终完整 make test 为10222通过/
2974跳过（1118.77秒），make check 全部通过，含 mypy1324/eval30/30。
设计、规格/权限、质量审查通过；首次完整测试的两项陈旧测试替换点已修正，
未放宽断言，完整双门禁重跑通过。任务状态为本地 Review，未提交/推送/部署。


## 12. 第四批消息与兼容边界（2026-10-20）

详见 [第四批设计与验收](CLOUD_AGENT_DECOUPLING_BATCH4.md)。Core/default transport
只接受 Runtime command，Trench Turn/source 移入显式集成模块；历史联合 schema/
examples 保留原字节。默认 RabbitMQ 拓扑只包含 Runtime，联合/source/shadow
显式启用，94项模拟拓扑与权限请求和原实现一致；不删除队列或轮换凭据。

旧兼容从默认路径退出，历史解码继续保留。离线退役工具校验盘点的 namespace、
compatibility、时间、摘要及精确待恢复任务集合，要求排空或不可变旧镜像固定和
回滚材料；只声称材料一致，不验证生产事实、不授予线上切流/删除权限。
本轮没有生产排空/退出，不改写历史数据、Coverage 证书或恢复记录。

产品契约专项145pass/0skip，真实临时 PG 专项87pass/0skip，明确 Host/S3/model
为 fixture；新增中立 CI/Make 入口，拒绝空跑/skip。Trench 联合 CI 继续作为手动
产品集成桥接。当前源码三个镜像与无业务 Host 独立启动/重启保留验证通过；
现有32容器保持身份不变。规格/质量审查通过；最终 make test 为10342通过/
2974跳过（1139.10秒），make check 全部通过，含依赖边界、mypy1326/eval30/30。
状态 Review，未提交/推送/上线。真实 Broker/模型/产品/浏览器验收与生产兼容
退役尚未执行；历史 decoder/适配和回滚策略继续保留。


## 13. 四批整体复核（2026-10-20）

[正式审计与修复记录](CLOUD_AGENT_DECOUPLING_AUDIT.md)逐层复核默认配置/部署、
认证/续权、Connector/Manifest、Coverage/下载、消息及发布/验收。确认并补齐7类
问题，包含专项筛选/中断/辅助证据、默认密钥生命周期、联合候选 Runtime 门禁、
配置路径及按 Host/revision 冻结；报告下载采用同一配置函数，防止 sibling 遗漏。

当前默认 Runtime 不要求 Trench 服务、Cookie、业务库或业务证书。保留的产品
字符串来自显式旧协议、兼容部署/手动联合验收、历史 v1 Contract 和前端 mock
数据；不批量改写或将存在字符串误判为默认网络依赖。

v107 新增 Host-scoped revision freeze 表，原表/历史 JSON/digest 保留。更新后的
API/Worker 必须先迁移后启动，并协调新 admission 与 Worker 切换；旧 Worker
不能处理仅新表冻结的 Task。歧义旧归属必须由操作者唯一化配置后再接入，不能
猜测归属或静默复用缓存。具体部署/回滚限制以正式审计记录为准。

最终专项契约161pass/0skip，真实临时 PG87pass/0skip，跨代冻结13pass，报告路由
及凭据8pass；规格/质量复审放行。当前源码三镜像构建、隔离启动和重启保留通过，
与冻结源码摘要一致。完整 make test10376通过/2987跳过（1162.17秒）退出0；
make check全部通过（mypy1328/eval30/30），任务状态本地 Review。
现有数据库、队列及运行服务未改动，未提交/推送/上线。

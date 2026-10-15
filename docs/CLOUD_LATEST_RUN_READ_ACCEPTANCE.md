# LATEST-RUN-READ-01 本地验收

2026-10-15；基线6bd170ce，分支codex/latest-run-read-01。
仅优化Cloud PostgreSQL共享最新Run读取；保留现有Client3→2、高思考/v2和此前收益。

## 定位与最小改动

上一轮B2点击→首次模型HTTP2958ms，分为621ms前端/Host准备、1016msCloud准入、
242mscommand→Worker、1080msWorker准备。Worker启动412SQL、65连接，Context约298ms。
两次Context输入刷新隔着不同canonical提交，未把这些新鲜校验当重复缓存删除。

发现postgres/task_replay_headers.py的read_latest_run_header每次先查询最新可执行Run
ID，再调用read_run_header读取metadata。调用者包括Worker progress和StreamProofSnapshot
（后者供Worker临时流及API权限使用）。修复在共享函数，不修改各个消费者。

用一个语句快照选出最新Run并复用RUN_HEADER_BODY、run_header_from_row。保留原canonical
可执行命令筛选、Task高水位/位置准备、anchor/stop、coverage、source locator及歧义拒绝。
缺失/非法Run仍拒绝。没有Run缓存、新Port、迁移、连接池、依赖或SQLite变更。
控制状态、HostGrant、完整lease fence及每次新鲜proof快照边界保持原样。

## 原生确定性验证

新增一个105行检查文件。先在真实隔离PostgreSQL跑出预期失败：实际execute为2、要求1；
其余9项原语义通过。改动后10项均通过。矩阵包括：

- 一条实际SQL返回与显式read_run_header完全相同的dataclass。
- 新run/message替换旧Run，cancel只推进高水位，不成为最新可执行Run。
- 同一已打开RR快照一致；新调用立即观察到替换，证明没有缓存旧Run。
- 空/缺失/空白/超长Run、错误namespace、未就绪位置保持拒绝。

另集中验证PostgreSQL progress、Worker supersession/fence、临时流以及真实API proof：
59 passed，49.32s，无跳过。包含issue/resolve之间epoch/token/owner/expiry/index/coverage
变化的新鲜校验。未修改任何旧fixture或放宽权限。

固定同一canonical Task和Run、每次新连接，在AB/BA交替40对无模型测量中：

| 单次最新Run读取 | 原版 | 候选 |
| --- | ---: | ---: |
| SQL execute | 2 | 1 |
| 中位耗时（含SQL/传输/计划，不含连接建立） | 8.611ms | 7.783ms |

单次减少0.828ms、约9.6%；仅是此函数的结果，不是整轮SQL/首字收益。

## 一组新真实公开搜索配对

同一PG18/Redis8发布日期/特性/官方来源问题；DeepSeek Flash、thinking enabled/high、
transient_v2。两场均completed、无模型重试、无工具失败、0OCI实例、网络峰值2。
每场新Task/Run，无历史Run重放，没有为了更好数据重跑模型。

| 指标 | A1原版 | B1候选 |
| --- | ---: | ---: |
| Worker启动SQL | 412 | 404 |
| Worker启动连接 | 65 | 65 |
| 启动最新Run函数调用 | 8 | 8 |
| Worker→模型HTTP | 1311.64ms | 1115.10ms |
| 点击→模型HTTP | 4009.11ms | 3002.86ms |
| 首段可见正文/过程正文 | 4951.30ms | 3859.30ms |
| 同时含两站官方链接正文 | 23682.90ms | 16899.80ms |
| canonical完成 | 24668ms | 18427ms |
| 模型轮数/工具次数 | 4 / 5 | 3 / 4 |
| 整轮Worker SQL | 2732 | 2128 |

可以直接归因的是启动8次同类读取各少1条SQL，412→404（1.94%），连接65保持。
候选整轮76次最新Run读取各少1条SQL：与候选相同工作量的旧实现相比少76条。
原版和候选整轮函数调用分别96/76次；不同模型/工具工作量使整轮差604条不能全归因。

首段正文观测少1092ms、约22%，但单函数40对仅快0.828ms，8次约6.6ms量级，
足以说明不能把这1秒差值都归因于此改动。Worker准备、Cloud准入/调度和模型行为
均有波动。最终完成少6.24秒也包含少一轮模型/少一次抓取，不宣称稳定端到端收益。

A1：[基线页面](http://localhost:3000/dashboard/strategy/conv_1792068171943_8b3e23)，
Runa9cd5c46-15ff-473c-8cd5-b043323d33d3。
B1：[候选页面](http://localhost:3000/dashboard/strategy/conv_1792068300121_767f87)，
Run623b51ae-eb2d-481a-84d7-61ee6938c1d8。

## 完成边界

单个生产函数净增10行，新原生检查文件105行；最小源码Ruff、mypy1283、file-size3086
以及deterministic eval30通过。完整make test未跑，源码Ruff明确排除未跟踪私有.artifacts；
不把此前make check的私有脚本lint阻断宣称为全量门通过。

正常API/Worker仅覆盖本轮共享SQL文件，原6个Compose/入口/命令保留。56项源码身份
（包含此前Client/Worker收益）以及原搜索镜像/代理/设置核对；临时trace/页面观察器撤除。
页面正常刷新恢复同一已完成Run，无再次模型调用。本地集成目标cloud-agent-trench，
保留无关脏改动，不push/npm发布/远端部署。隔离PG/Redis仅供本轮验证，结束后移除。

本轮验收是减少查询，不是完成首字优化。以后不应把数毫秒SQL微调作为缩短数秒等待的
主线；更大优化必须先找到可并行/可提前完成且不依赖当前授权的准备工作，再决定改动。
原始计时/回执/hash与全部失败保存在私有.artifacts/latest-run-read-20261015。

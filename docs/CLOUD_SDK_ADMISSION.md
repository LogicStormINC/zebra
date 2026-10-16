# Cloud / SDK 准入请求合并

任务：CLOUD-SDK-ADMISSION-01，基线 cdb3bf25，2026-10-17。

## 已定位的边界

上一轮实际页面四次 click → 首次 Provider 请求为 2.337–3.259 秒；
Worker scope → Provider 为 0.374–0.573 秒。建任务后的 command 接受至
harness attempt 开始约 0.1–0.2 秒，未发现秒级队列或沙箱创建。
这不是把“首正文前所有等待”都归给 Worker 的依据。

实际新会话前置顺序：技能目录 → 兼容性探测 → 建任务 → 开 client session
→ 挂载和绑定 → command → 绑定续约 → 观察。挂载和绑定已合并，不能重复计算收益。
目录涉及本轮授权和技能选择；任务创建必须等兼容性成功；command 必须等绑定。
本切片只合并“开会话＋挂载＋绑定”，不跳过目录、不缓存授权、不提前提交 command。

当前页面启动由 Host 的 Python 传输适配器驱动，不是 TypeScript SDK。
因此通用 Cloud 接口和 SDK 一起落地，并在 Host 仅作能力协商/调用接线。
Trench 的技能选择、任务归属、业务权限、prompt、恢复和展示逻辑不改。

## 通用协议与实现

- `/capabilities/runtime` 增加 `client_surface_open_contract_version`。
  仅 cloud 且 client session/profile/controller stores 完整时为精确整数 1；否则 0。
  已有 `client_surface_contract_version` 仍为原语义。
- 在原 `POST /v1/tasks/{task}/runs/{run}/client-surface` 上增加显式开会话请求：
  `grant` 为原 ClientSessionGrant，`mount` 为原挂载报告但不得含 client_session_id，
  `task_capability_scope`、`controller` 保持原契约。ID 必须由服务端产生。
- Host HTTP 验签、目标校验、单次 nonce 消费保持原入口。
  路由在任何写入前重新检查本次 verified Host、有效期、issuer、Task/Run/租户。
- 复用现有 open_client_session、session authorizer、mount_client_session、bind_client_run。
  校验当前 profile 的 Host binding、发布状态、credential、挂载子集和 controller fence。
  两种入口共用内部挂载/绑定续段，避免同一请求重复读取目标授权。
- 所有数据库操作共享最多 2 秒预算，并受新鲜 Host grant 剩余有效期约束。
  此处无跨请求授权缓存，无新依赖、迁移或后台进程。
- 成功返回开会话响应及原挂载/绑定响应；凭据仅返回，不保存响应供重放。
  失败不返回凭据。原部分提交语义保留；丢失响应不得自动重开或改用旧接口，
  遗留会话/控制租约受原 TTL 约束；本接口不宣称事务原子或幂等重放。

SDK 的 `openClientSurface` 为 Host/BFF helper，transport 为每次请求提供新鲜 Host grant。
精确版本 1 使用一次请求；未支持时，在发起写入前选择原开会话/挂载/绑定路径。
能力宣告后若超时、拒绝或响应不完整，直接报错，不回退、不重试。
浏览器直连授权仍未开放，SDK 不持久化返回凭据。

## 验证边界

确定性验证覆盖新旧路径、显式整数协商、缺失/过期/错位授权、失效 profile、
服务端 ID、丢响应不重开以及返回 credential/fence 校验。
一次在未修改干净 HEAD 上重现的既有失败为
`test_http_host_preflight::test_early_extension_read_inherits_remaining_io_budget`：
目录 Host 授权预算 5 秒、后续读取预算 2 秒，但旧断言要求两者完全相等。
不修改该测试或原目录期限实现；报告时单独列出。

页面固定最多四轮 A/B/B/A，各轮新会话、相同公开搜索题，保留失败样本，
保留高思考、DeepSeek Flash、transient_v2，工具调用由 agent 自行决定。
A = 当前已验收 API；B = 仅以上三个 API 文件；Worker/Search 相同。
Host 的同一份协商接线通过 API 能力决定新旧协议，不在样本之间改代码。

计量口径：click → 首次 Provider 请求为启动；实际最终正文前 16 个规范化字符首次
在 DOM 出现为首正文（含显式临时草稿，排除进度）；整轮至 Host terminal 状态。
SQL 为 Worker attempt＋该窗口开始的 API 请求的 Driver execute，空探针另计。
不包含只读取证查询，不宣称全数据库业务 SQL。工具/模型工作量不等时，不将整轮
耗时和 SQL 原始变化全部归因于本次准入优化。

## 当前状态

实现、四次实际页面 Run、本地正常服务恢复均完成；未推送或远端部署。

| 样本 | click→Provider 秒 | 首正文秒 | Host 整轮秒 | 模型轮 | 工具数 | Worker＋API 非空 SQL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A1 | 3.661 | 22.085 | 25.977 | 3 | 5 | 3592 |
| B1 | 2.600 | 17.430 | 22.044 | 4 | 5 | 4023 |
| B2 | 2.450 | 21.731 | 28.495 | 4 | 6 | 4273 |
| A2 | 2.514 | 20.550 | 23.704 | 4 | 5 | 4067 |

- 可重复确认的局部结果：开会话/挂载/绑定段 2 → 1 个请求、36 → 30 条非空 SQL
  （下降 16.7%）；该段墙钟 A1/A2 为 234.94/230.31ms，B1/B2 为 192.10/168.21ms，
  均值 232.62 → 180.16ms，约省 52.47ms（22.6%）。不含共同的首个 Grant 交换。
- 包含绑定续约的阻塞前置 Cloud 请求 7 → 6（下降 14.3%），SQL 189 → 183
  （下降 3.2%，这里无空探针）。Worker 首次 Provider 前仍为 448 execute，其中 33 空探针，
  5 次 TaskIo open，四轮完全一致。相加的启动非空 SQL 为 604 → 598，下降约 1.0%。
- 整体启动均值 3.088 → 2.525 秒是这四个样本的原始差值；A2 已是 2.514 秒，
  因而不能据此认定稳定节省 0.563 秒。首个 Cloud 请求前为 1.350/.817/.605/.582 秒，
  A1 的额外等待发生于 Cloud 调用前，不能归给本次通用接口改动。
- 首正文均值 21.317 → 19.581 秒，整轮 24.841 → 25.270 秒，非空 SQL
  3829.5 → 4148；优化组平均模型 4 轮、工具 5.5 次，对照 3.5 轮、5 次。
  整轮 SQL 没有下降，整轮耗时也没有提升；工作量和网络耗时不等，
  不能把首正文 8.1% 的原始差值宣称为本次合并的稳定收益。
- 四轮均 completed/transient_v2，所有 15 次模型响应为 high/Flash/thinking enabled/retry0；
  21 次工具调用全部成功。每轮仅一次 candidate、一次质量验收并通过，无质量重写。
  工具由模型决定，未固定搜索/抓取数量、未回放历史 Run。

## 剩余启动等待与下一边界

实际前置耗时（ms，A1/B1/B2/A2）：

| 环节 | A1 | B1 | B2 | A2 |
| --- | ---: | ---: | ---: | ---: |
| click 到首个 Cloud 请求 | 1350 | 817 | 605 | 582 |
| 所有阻塞前置 Cloud 请求内累计 | 1138 | 967 | 948 | 1115 |
| Worker scope 到首次 Provider | 440 | 480 | 474 | 423 |

后两项应结合时间线看，不将并行区间机械相加。目录/兼容性仍各自进行当前轮授权读取，
建任务一条请求固定 94 execute，是单个 Cloud 前置请求中最多的 SQL。
Host 初始等待与各次请求间隙包含身份交换、持久化和适配器准备，当前 API 观测不能进一步
分清这几项，不能把间隙全部叫网络耗时、DNS 或身份校验。
下一次若继续，应在同一新会话边界量出通用 transport 初始化和建任务内部阶段，优先复用
现有 transport/连接，再考虑新的批量协议；不直接改 Trench 的业务准备逻辑。
本轮到此收敛，不增加模型样本、不追修无关目录期限测试。

## 验证与交付记录

- API 定向集：83 passed / 1 native PostgreSQL fixture skipped / 1 已确认基线失败 deselected。
  最后仅加强新测试中真实 opaque thread 错位用例后，新开会话文件 13 passed。
  实际四轮使用正常 PostgreSQL/Redis，补充了真实数据库与页面验收。
- SDK：16 项 client-surface 测试通过；pnpm check（工作区构建与 tsc）通过。
- Host 适配：53 passed / 2 skipped；提交 bca9952，仅五个协议接线/验证文件，原脏文件保留。
- 干净跟踪源码默认 make check 通过；ruff/mypy 与 diff 检查通过。
- 正常 API sha256:556fe8e37a4edf486d549d32f3f8b3c3df05f0f7af2c389d4d834354254ba8d2；
  Worker 保留 sha256:1a2270dfbf0bb4986e526cb309e73fc0a339822d34139a7084f700c4e9abc22d；
  Search 保留 sha256:245b675ff61b01a0ddace63abc095420c55393a55761a32b15274e25cfcdd1d5。
- 原六份 Compose、env 摘要、entrypoint/command、healthy/0 restart 和 103 个源文件指纹复核通过；
  移除诊断启动器，搜索服务未做本轮重启、预热或缓存清洗。TypeScript SDK 尚未发布 npm。
- 私有测量：`.artifacts/cloud-sdk-admission-20261017/{summary,startup,breakdown}.safe.json`；
  正常配置与源文件指纹分别为 normal-services.safe.json / final-source-checks.safe.json。
  B2 会话 conv_1792172823056_dabb26，正常服务恢复后只读取原结果，不重调模型。


本地集成：代码提交 2eb15eba 已 fast-forward 到 cloud-agent-trench，27 项原有脏状态
逐字节核对保留；Host 接线 bca9952 在其独立任务分支，原有三个非本任务条目保留。
任务状态 Review（本地交付验收完成，未推送/合入 main）。诊断接收器已关闭，正常服务
恢复后 B2 原正文/高思考 UI 可见，未产生第五次模型 Run。截图保留 page-B2.jpg。

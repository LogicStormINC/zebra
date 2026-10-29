# 部署验收记录

日期：2026-10-23，目标 ubuntu@192.168.110.42。

## 已通过

- 本地业务字段、子表归属、参数、权限、审批摘要及重复确认检查。
- Redis 会话提交锁覆盖 grant commit；同请求重试、丢失执行 ACK 和丢失 Stop ACK 使用稳定正文。
- 首次 Task 创建成功、页面会话 ACK 丢失后重试，不追加重复首条消息。
- 页面会话同 run 复用、未知 credential ACK 等待、过期 lease 清理、空 GET body、receipt 幂等键与 HTTP status 传递检查。
- SSE 分片、重复事件、草稿表单限制、页面过期检查；2000+ 事件及前置 keepalive 的历史恢复检查。
- 真实 Cloud 模型调用 ERPNext discover/read，查询上海天辰商贸有限公司及 CNY，刷新可恢复公开答复。
- 真实浏览器：页面动作打开 ToDo，浏览器确认 succeeded，Cloud 收到 200 receipt，后续答复与实际路由一致。
- 真实浏览器：标准草稿 form.fill 成功、Cloud receipt 200、模型完整中文答复；页面 priority=Low 且 dirty，独立读取数据库仍为 Medium，确认没有自动保存。
- 真实浏览器：模型提出创建测试 ToDo，确认前查询结果为空，页面确认后出现精确标记记录。没有把提案当作已执行业务。
- 真实 HTTP：ToDo 创建/读取/修改、单据版本、重复确认重放、私有附件上传/授权下载/删除、测试数据清理。
- 真实 HTTP：非库存 Item + Material Request 的创建、提交、取消、修订及删除。未产生库存移动。
- 普通 Employee 实际登录：管理员会话、页面代理、审批、私有 ToDo 及选定公司之外的 Company 目标均拒绝；被拒审批未写入。

## 修复并复测的实际故障

中文公司名不能用作 HTTP header 的 workspace ref；改为稳定的不透明标识。新 Cloud namespace 缺少 epoch；使用原生引导初始化。工作目录权限及宿主绝对路径不一致；改独立限额挂载。ERPNext image 入口覆盖 assets symlink；把插件资源链接烘焙进镜像。历史接口实际为 SSE；改原生有限恢复。Frappe 将缺失 GET body 编码为空字符串；按协议归一。多轮客户端控制租约未交接；服务端释放旧轮次后再打开。页面 receipt 的 HTTP 幂等键未转发；按 SDK effect UUID 派生同一键。Frappe value-field 枚举排除 Table；共享授权逻辑按原生 permlevel 补子表。授权导航触发自身页面版本变化而误报 stale；区分目标导航并在 SDK 检查后推进版本。快速本地填写回执与 Worker 等待事件竞争；首次回执等待原生 waiting_client_effect 状态，重复回执按原生状态幂等重放。

## 覆盖边界

通用框架与上述真实路径通过，不代表所有 ERPNext 模块和自定义动作逐项验收。工作流、全部 14 个业务转换、所有财务报表及未提供标准 cur_frm 的页面不作完整业务链已通过的声明。保留原生校验，未发布动作明确不可用。

模型提出待确认操作后，Cloud 可能把当次答复标为 unverified/suspended；面板中的真实审批结果才表示写入成功。新的人类指令通过原生取消/续接保留此前记录，不自动重做业务。

## 2026-10-23 UI 更新

默认面板加宽至 600px，新增整个视口的全屏模式、键盘焦点限制与 Esc 恢复；复用 Frappe whitelist-sanitized Markdown，未增加依赖。

`tests/browser_ui_acceptance.js` 在已登录隔离浏览器中通过：1200×762 桌面与 390×844 移动视口；标题、粗体、列表、表格、代码、引用；危险 HTML、事件属性与 JavaScript URL 被过滤；全屏尺寸、焦点、Esc、切换模式保留消息。测试只在浏览器暂时替换快照回复，没有创建业务数据或调用模型。另读取真实历史会话，确认公司/CNY 表格已生成实际 table 元素。静态资源版本更新为 `20261023-2`。

## 2026-10-23 Trench 会话侧栏适配

参照并适配 Trench `toc-frontend/src/components/product/strategy-session-sidebar.tsx` 的布局、时间分组、选中行和管理交互；品牌保留 Zebra。未引入其 Ant Design、Tailwind、Radix UI 依赖，弹窗复用已安装的 Frappe 原生组件。

全屏左侧 352px（1440px 桌面视口）显示会话列表，右侧为聊天区；支持新建、切换、重命名、删除及侧栏收起。390px 移动视口下会话栏是 300px 抽屉，收起后聊天区宽度为 390px。

- `tests/browser_sessions_acceptance.js`：已登录浏览器实际点击新建两条空会话、重命名保存、切换、确认删除；RPC 复查名称持久化、删除后列表隐藏、快照返回 403。测试结束移除自身会话，不调用模型或修改业务单据。冷刷新后原有五条会话保持可见，测试会话不再出现。
- `tests/test_permissions_frappe.py`：普通 Employee 真实登录验证跨用户重命名、删除、读取与代理均返回 403；原有业务权限边界通过。原生数据库检查删除后会话隐藏、归属访问拒绝、待确认提案到期。UUID 测试用户、公司、单据及审批已清理。
- `tests/test_chat_checks.py`：名称边界、与提交共享锁、执行中的会话禁止删除、失效待确认操作和回收 Grant；原有提交/停止丢失响应的幂等检查仍通过。
- Markdown、全屏、焦点及 Esc 浏览器回归通过；原有 Python 业务、客户端回执和历史恢复检查均通过。

删除采用现有 `status=deleted`，不新增表结构：从列表移除并拒绝后续会话读取/提交/客户端代理，失效待确认操作及映射 Grant，保留 Cloud 审计与业务单据。执行中需先停止；Cloud 状态无法确认时拒绝删除。源码和静态资源已构建部署，版本 `20261023-3`。本次不重复调用模型执行 ERP 业务验收。

## 2026-10-23 Trench 输入框与模型配置

直接复用 Trench `strategy-chat-input.tsx` 所使用、ERP 插件已安装的 Zebra `AgentComposer`，沿用原生样式、900px 最大宽度、Enter 发送、Shift+Enter 换行、IME 输入保护和停止按钮。输入框底部显示 DeepSeek Flash / DeepSeek V4 Pro，以及关闭 / 低 / 高 / 最大四档思考强度。默认仍为 Flash + 高，配置用于下一条发送，当前执行不受下拉框变化影响。

服务端白名单验证配置，将首次任务创建及后续消息的配置传入 Cloud 原生 `/tasks` 和 `/tasks/{id}/messages`。新增内部 `request_options` 字段，在发出请求前持久化；同一个请求 ID 更改配置会拒绝，未知结果重试保留原配置和命令。迁移前已完成原生站点数据库备份。

实际接入发现 ERP 前端 readable 只发布 `erpnext.ui.context`，把模型设置放入 AG-UI state 会返回 `client_admission_rejected`。已移除该错误映射，模型设置只经原生任务通道传入；增加有、无客户端 surface 的回归检查，保留页面状态白名单。

验证结果：

- 浏览器实际选择 Pro + 最大并发送，收到“配置验收通过”。Cloud 原生 MODEL_RESPONSE_RECEIVED 记录 profile=`deepseek-v4-pro-executor-v1`、resolved_model=`deepseek-v4-pro`、thinking_mode=`enabled`、reasoning_effort=`max`。
- 同一会话切换 Flash + 关闭，通过 Enter 发送续聊，收到“续聊配置通过”。原生调用记录 profile=`deepseek-v4-flash-executor-v1`、resolved_model=`deepseek-flash`、thinking_mode=`disabled`、reasoning_effort=null。共两次模型调用，无业务写入。
- Shift+Enter 和 IME 回车未误发送；390×844 视口下模型、强度与发送控件均在输入框和视口范围内；桌面全屏输入框最大宽度为 900px。
- 默认值、四档白名单、首次/后续消息传递、请求 ID 配置绑定、丢失响应重试、前端 readable 白名单均有可运行回归。业务权限、历史恢复及客户端代理已有检查通过。

验收 Task `67a7c93a-f1f6-4f28-a1c2-5e674aa05b5d` 保留原生审计；Host 验收会话 `bgeccbm9hg` 与此前准入拒绝的空验收会话 `a6rk32f04j` 已从列表移除，未删除原有五条会话。Cloud 聚合 usage 在最新调用关闭思考时可能回溯上一条非空 reasoning_effort，本次以逐调用事件为证；ERP 输入控件不使用该聚合值。静态资源版本为 `20261023-4`。

## 2026-10-23 每会话配置持久化

新增内部 `preferences_json` 保存各会话模型和思考强度；与用于未知结果重试的不可变 `request_options` 分开。选择控件修改后立即调用带当前用户及 Company 权限校验的保存 RPC，无需先发送消息；保存与提交共享 admission lock，并在释放锁前提交配置。保存失败显示错误并恢复原选择。读取配置失败时禁用发送，重新连接后恢复，避免使用其他会话的旧值。

新会话采用站点默认模型＋高；旧会话无偏好时继承最后一次已提交的模型/强度。页面切换先读取对应会话设置，不受历史加载速度影响。当前标签页在 sessionStorage 中仅保存按用户区分的所选会话 ID，刷新时恢复；配置本身保存在 ERPNext 服务端，不依赖浏览器存储。

`tests/browser_preferences_acceptance.js` 三阶段实际浏览器验收：

- 空会话 A 设置 Pro＋低，空会话 B 设置 Flash＋最大，均未发送消息，服务端读回值正确。
- 刷新 B 后自动恢复 B 和 Flash＋最大；反复切换 A/B，分别保持自己的设置。
- 再刷新 A 后自动恢复 A 和 Pro＋低，两个测试会话均已移除；无模型调用或业务写入。

`tests/test_permissions_frappe.py` 真实普通 Employee 登录验证读取、保存他人会话设置均为 403。测试清理中 Frappe 异步 create_contact 与 User.on_trash 可触发数据库 1020；仅对 UUID 测试用户的清理事务作回滚后有界重试，复测完整退出成功。原有业务权限边界仍通过。

`tests/test_chat_checks.py` 覆盖会话配置隔离、旧配置继承、保存不改变重试坐标、提交互斥及释放锁前提交。原有业务、客户端与历史恢复检查通过。站点迁移前完成原生数据库备份，静态资源版本 `20261023-5`。

## 2026-10-23 Agent GSAP 动效

新增精确锁定的 GSAP 3.15.0，本地打包，无外部 CDN。`frontend/motion.ts` 对 Agent 根节点及明确标记的 Agent 原生弹窗统一处理：

- 面板 260ms 入场、160ms 退场；全屏和聊天区布局使用 Flip 的 transform 缩放/平移，300ms 后清除临时样式。
- 会话侧栏、条目、新建入口、聊天消息、欢迎页、提示/错误、待确认卡片、执行活动及输入框短距离淡入。详情和会话菜单展开动效；按钮悬停/按压、输入聚焦及选项修改反馈；重命名和删除弹窗入场。
- MutationObserver 仅观察节点、class 与 open，不观察字符数据；WeakSet 保证同一消息 DOM 入场一次。仅动画可见新增节点，每批最多 12 项，入场间隔最多 100ms，避免大量历史内容堆叠动画。
- 关闭后移除面板；节点移除时回收 tween。快速切换完成 Flip 后恢复原布局；减少动态效果开启时完成尚未结束的退出/布局回调并清除临时样式。触摸不触发悬停动画。
- 系统 reduced-motion 同时关闭 GSAP 位移和 Agent 自带 CSS 动效。仅作用于 Agent，未给 ERPNext 业务区域增加动画。

`tests/browser_motion_acceptance.js` 在部署页面通过普通与 reduced-motion 两种模式：面板进退、全屏尺寸、侧栏收放、消息入场、30 次流式文字追加无样式动画重播、按钮反馈、重命名弹窗和快速切换。另验证关闭途中启用 reduced-motion 不留下隐藏面板。390×844 实际移动视口的全屏尺寸正确、抽屉 300px，动画结束后 transform=none。

已有 Markdown/XSS、焦点/Tab/Esc 浏览器检查通过。双会话 Pro＋低 / Flash＋最大配置的三阶段浏览器回归通过，空测试会话已移除。Python 业务、提交幂等、客户端及历史恢复检查通过。本次没有调用模型或写入业务数据；动效探针仅是可移除的浏览器本地 DOM，并非真实消息或审批。

构建产物约 357.9 KiB JS / 45.0 KiB CSS（压缩前），比上一版 JS 增加约 99 KiB。静态资源版本 `20261023-6`。已验证功能与样式清理，未宣称在所有硬件上完成 60 FPS 性能基准。


## 2026-10-23 Trench 内容与功能适配（已部署，资源版本 9）

复用与 Trench 字节完全相同的四个 Zebra npm 包及 `@zebra-agent/react-charts@0.1.0`，正文导图使用同版本 `html-to-image@1.11.13`。共享 Chat、Composer、ContentRenderer、AssetPreview 和 VegaLiteRenderer；ERP 自己承担用户、公司、会话授权及报告存储。

新增页面快捷建议、继续追问、回答操作（复制、Markdown、正文 PNG、私人报告、评价、引用摘要、显式文字重新处理），公开图片/视频/图表/来源/文件卡片，以及当前任务分段文件区。建议由当前页面坐标与公开轮次确定，不额外调用推荐模型；点击提交一次，保留未发送草稿和附件。内部模型/工具记录不再显示成不可用文件。新区域沿用现有 GSAP 和 reduced-motion。

报告和反馈从服务端重新核对完整公开回答的 ID 和摘要；被截断的富文本不能当作完整报告保存。Frappe 新 File 插入会覆盖显式 owner，因此插入后在同一事务提交前通过原生 db_set 固定为 Administrator。报告正文、复制和导图统一隐藏内部 artifact URI。会话管理改用锁内当前读、字段级更新和锁内提交，保护报告与反馈；MariaDB 旧 RR 快照冲突安全拒绝，失败事务回滚后由新请求处理。

真实验收：

- 部署镜像 `sha256:64ca9d8f8cf1ac011468e40dc97ea61149feb2794664fb6a00da0974d399b6bf`，JS SHA256 `68cbe5899596090464e749682f8a83a91330e5c9737aaae7fe3919d44bb15bd5`；浏览器实际加载 `v=20261023-9`，与本地构建一致。
- 实际 Frappe/HTTP：报告重复保存只产生一份服务所有者私有 File；反馈持久化、固定下载 RPC、原生 File API 与私有直链拒绝、公司撤权后下载拒绝均通过。普通 Employee 测试账号有独立 UUID Employee 映射，实际保留角色后验证全部跨用户 RPC/下载拒绝及无越权写入。
- 实际 MariaDB 双连接：旧 RR 读视图冲突回滚保留新报告元数据，新事务重命名成功；当前 pending 状态拒绝删除。报告、用户、员工、公司、会话及临时业务记录仅使用自建 UUID，并完成清理。
- 已登录浏览器的隔离 RPC fixture：桌面 1440×900 和移动 390×844（reduced-motion）通过推荐精确一次、草稿/附件保留、富文本不重复、文件噪声过滤、预览、下载跨输入/反馈不被中断、图表不重取/重置、报告防双击、反馈、PNG 解码且非空、独立文件/图表不进入正文图、显式重新处理、旧会话延迟 ACK 隔离、已知拒绝可纠正及未知请求保持固定。此项是 UI 集成检查，不代表真实 Cloud 附件执行已验收。
- 实际原有会话只读恢复：2 张 Markdown 表格、回答操作与追问可见，内部工具文件噪声消失；管理员原 6 条会话和其他用户会话保留。Markdown/XSS、全屏/焦点/Esc、GSAP 普通与 reduced-motion 回归通过。
- npm 与十组 Python 检查通过，SPEC 与 QUALITY 独立审查通过。本次未启动模型任务或重跑业务；Trench、认证与 ERP Cloud API/Worker 的镜像和启动时间未改变。

仍未开放：私人上传（原生隔离/准入门槛未完成）、历史分段文件、完整 P0–P5 原生能力。当前文件区明确标注 active segment，上传入口遵守实际服务端开关；不把本次页面适配称为全部 Agent 能力已上线。


## 2026-10-28 — approved workbench A deployed

Implemented the approved left searchable session sidebar, compact chat header, sticky Trench composer and on-demand approval/resources drawer. Session CRUD uses existing native APIs; model/reasoning remain server-persisted per conversation. Unsaved drafts stay in memory. Shared guards prevent late approval success/failure from entering a different conversation, preserve newly typed drafts during reconnect/create, treat native ready/created/dispatching as busy and retain the exact uncertain-request identity. RPC uses existing same-origin cookies/CSRF with a bounded inline error. Approval review shows permission-scoped current values, removed/reordered child rows, unknown unreadable fields and exact parameters; native confirmation payload stays unchanged. No dependency was added.

SPEC and QUALITY review passed after the concrete stale-reader/draft fixes. `npm test`, `npm run build` and `git diff --check` passed. The actual built bundle passed isolated browser checks for delayed confirmations and failures across session switches, IME/Shift+Enter, ready/Stop double-click, reconnect/drafts, unknown-response explicit idempotent retry, Markdown/code/safe HTML and reduced-motion mobile layout. These mocked approval/mutation tests are not new live business-write acceptance.

Static-only image `sha256:1f77094c2396921ef1f6f124b94695bfc85e88b9d11e7cea16e45c2bb3487bd7` extends the verified live Host334476 image with only JS/CSS and two asset-version hook strings. Recreated backend/frontend only; clear-cache, no migration. Agent API/chat worker and compose.json remain unchanged; general worker remains stopped. Rollback metadata is private at `/opt/erpnext/zebra-agent/ui-a-20261028-1/backup`. Browser-served version `20261028-workbench-a1` hashes match JS949cc5355d34b9604158876ab2abec295360b83a87129d516d666042d0451e73 and CSSab894177679000ef7dfbe313d77015bf060eb936f753e49a3be9963d67c7f0b5.

Authenticated real-browser acceptance used new conversation `f1p4qpa1me`, titled `[UI A验收] 排产查询`, Run `9172fa90-a6f8-4907-a768-f2e6d97bcbd9`: real model/discover/read completed to awaiting_turn, queried11 production plans/46 work orders/4 workstations, and rendered4 native Markdown tables. Reload restored history and Flash/low; a separate disposable session retained Pro/max independently, then was explicitly deleted through the UI. Native create/switch/rename/delete, desktop1440x900 and mobile390x844 passed; no page horizontal overflow, mobile composer bottom831.844 within844, sidebar258 and drawer390, reduced-motion enabled.

Capacity remains bounded: Production Capacity report and Workstation Working Hour reads returned403, so the reply disclosed unavailable detailed capacity and gave qualified suggestions. This UI release does not claim complete capacity scheduling. No business writes were made. Full-row checks preserved20 business tables (including prior approved plan00011), plus original8 Tasks/10 segments/591 events/22 bindings. Full Agent capabilities beyond the recovered runtime remain incomplete. Public evidence: sibling `zebra-erpnext-evidence/workbench-a-20261028.json`.


## 2026-10-28 — overdoze 品牌替换

用户要求停止使用 Zebra 品牌。侧栏使用小写 overdoze 字标与 o 标记；入口、无障碍名称、助手署名、输入提示、引用摘要、导出文件名/标题、报告、新会话身份提示、应用元数据与用户可见服务错误文案已替换。内部 SDK/API/DocType/会话存储标识保留，未迁移历史数据。历史用户/模型内容不做批量改写。没有现成官方图标文件，本次使用文字字标。

本地 npm test、npm run build、Python AST syntax、git diff --check 通过。线上以当时运行的 A 版镜像为基底，只复制构建资源及对现有五个 Python 模块做字面品牌/version 替换；AST 去字符串常量后相等，逻辑保持。镜像 sha256:7c6b26efc7874154e0a43662a4689a55b251615d1648e5f7cef56a47cac1a8fc，仅重建 backend/frontend 与 clear-cache。Agent API/chat-worker 镜像和 API Python 哈希未变。私有回滚目录 /opt/erpnext/zebra-agent/overdoze-ui-20261028-1/backup。

真实已登录浏览器冷刷新验证：资源版本20261028-overdoze-1；JS9a8427f15315826544a6d4c864d76ddb2338b3a0d521eaac644d144e37631d98、CSSbd4ffb0f629f976dc763631ba94d8fcb711c85d53ebb7ffdef2c5f6c0cd11e52 与构建一致。侧栏 overdoze、提示与无障碍名称无 Zebra，现有真实排产查询4张表格正常恢复，无横向溢出。未重新发起模型/业务写入。


## 2026-10-28 — interrupted user conversation recovered

The reported Failed turn was caused by the brand deployment overlapping live user work, not a logo/rendering error. Backend container creation was10:01:50.988584Z; task dfb645a8-8ee9-4ac1-b43e-29b7d650d37e Fresh probe failed at10:01:51.299385Z with probe_http_unavailable. Its next public-output boundary correctly refused prior_revocation and retained turn_failed/session_failed. Gunicorn started at10:02:07Z. No authority guard was weakened, revoked Run retried, or historical failure overwritten. Repeated HostGrantExpiredError scan messages were not the direct cause of this turn.

After service restoration, a single explicitly labelled NEW read-only request was submitted through the normal Host API with the conversation owner's native ERP permissions (server-side acceptance, not an authenticated owner-browser claim). Same conversation j16fsmoccf and same Task continued natively into segment9c25d91f-6cf2-460b-a4f0-03ea8ae2ac30, Run2454ca6c-c862-4736-9068-b348cb049615. Native turn_completed/session_completed and the owner's public snapshot confirmed46 Work Orders and existing Production Plan MFG-PP-2026-00011. Previous question/failure remains in history. No business writes or further service restart occurred. User can reconnect the original UI to observe the completed new turn.

Added deploy/check_idle.py as a conservative read-only restart gate. Its --self-check rejects ready/created/dispatching/running/queued/waiting_client_effect and unknown states. The actual server invocation correctly REFUSED exit1 because one other retained Task is still ready; it was not cancelled or changed to permit deployment. Before any subsequent backend/frontend replacement: pause new admissions using the existing native maintenance control, let in-flight submissions settle, run this gate, and abort on nonzero. Keep admissions paused through deployment verification; restore the prior setting afterwards. An idle check alone does not lock admission. Never infer task idleness from container health.


## 2026-10-28 — only committed answers get action footers

Root cause: Answer treated every TEXT_MESSAGE_END as a final answer, rendering copy/download/more plus an unverified-answer warning under each progress commentary. Shared Answer now also requires the existing server-issued digest, which history.messages attaches to committed answers, not commentary or clarification. Streaming final output gets its footer after canonical snapshot reconciliation. No message text/history was removed.

Actual built-bundle browser reproduction: two completed progress snippets plus one committed final answer produced3 footers before,1 after; both progress snippets retained text with no footer/warning. Existing npm test/build and diff check passed. Real authenticated history cold reload retained1 answer/1 footer/4 Markdown tables, no reconnect warning. Served JS SHA263742e665e7be2d8fe9a7e4963dde6b74f99136ae15f759b7cb360f547b6bc7.

Deployment did NOT restart any process: atomic JS replacement in backend/frontend static paths, with exact original file owner/group retained and protected rollback at /opt/erpnext/zebra-agent/answer-actions-20261028-1/backup. Four backend/frontend/API/chat-worker container IDs, StartedAt and RestartCount compared byte-for-byte unchanged. Existing hooks/cache URL stays20261028-overdoze-1, so already-open clients need hard refresh. Built immutable future image b0148f6d0d69b25b55276bf10a98d926436c25fa334f51ce985317832a2cf18f and pinned backend/frontend override for the next safe restart; running containers remain the prior7c6b image with this explicit static hot patch. No schema, API, Worker, original Run/model replay or business write. Existing idle gate still refused a retained ready Task, so no compose recreation was attempted.


## 2026-10-28 — recurring execution failures, bounded stability repair

See `cloud-patches/projection-stability/REVIEW.md` for full root-cause evidence, failed activation attempts retained, source/isolated-DB tests, final image and actual acceptance. Final worker812202... removes healthy-route repair polling and fixes oldest-expired-ready starvation. Five sequential real query Turns plus a new read-only verification in the original affected owner's conversation completed. Zero new native execution failures and PG lock timeouts since final Worker start during acceptance. All original20 business-table fingerprints and8 Tasks/10 segments/591 events/22 bindings preserved; no business writes or migration. The separate historical invalid-provider-response root cause remains unverified; no production SLA/long-soak claim.

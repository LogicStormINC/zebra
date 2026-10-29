# Zebra ERPNext 集成

部署入口：**https://192.168.110.42:18443/desk**。登录 ERPNext 后，点击右下角 **Zebra ✦**。面板右上角支持 **全屏 / 退出全屏**；Esc 先退出全屏，再次按下关闭面板。助手回复使用 Frappe 自带安全 Markdown 渲染，支持表格、代码块、列表和链接。

独立 Frappe App，复用 Trench 使用的 Zebra React UI、Client SDK 与现有 Cloud 镜像。业务由 ERPNext 原生控制器执行，对话与执行由 Zebra Cloud 保存。ERPNext 专用 Cloud API/Worker 使用 `erpnext` 命名空间、独立 Host 签名及工具凭证；没有修改 Trench 源码或替换其容器。

## 使用

- 查询：“查询当前公司的库存物料”“查看本月销售情况”。模型先发现当前账号可用的 DocType、字段和报表，再调用原生查询。
- 写入：“准备创建一张采购订单……”。面板显示操作及准确参数，点击“确认执行此操作”后才写入。
- 页面：“打开客户……的单据”。通过已发布的浏览器动作执行；表单填写只影响当前草稿，不自动保存。
- 刷新后选择原会话恢复；连接中断时点击“重新连接”。停止按钮使用固定正文及幂等键，不重复执行业务。

公司范围固定在每条会话；变更公司时新建会话。金额和时间沿用已配置的 CNY、简体中文与 Asia/Shanghai。

## 能力范围

| 能力 | 实现方式与边界 |
|---|---|
| 安装模块、DocType、字段及子表发现 | 动态读取原生元数据、角色和字段权限；分页发现 |
| 查询、读取、创建和修改 | 通用 DocType 适配，包括订单明细等子表；保留原生校验 |
| 提交、取消、删除、修订 | 通过原生 Document 生命周期，逐次确认，校验单据版本 |
| 工作流 | 发现可用 transitions，原生 apply_workflow；没有安装工作流时不虚构动作 |
| 报表 | 用户有权运行的 Query/Script/Custom Report，强制选定公司；原生报表校验仍有效 |
| 打印 | 返回受权限控制的原生打印页面 |
| 附件 | 原生单据权限下的私有附件上传、关联、下载及删除；上传上限 512 KiB、允许类型受限；面板不接收文件，文件选择使用原生单据界面 |
| 单据转换 | 显式发布 14 个常见销售、采购、退货及付款转换；生成草稿与保存分别确认 |
| 设置 | 仅开放 System Settings 的语言、时区、日期及数字格式等发布字段；账号、权限、脚本等管理功能使用原生界面 |
| 页面动作 | 打开单据；精确匹配当前 route/DocType/name 的标准草稿表单填写；不自动保存 |

这是通用业务接入，并不等于 ERPNext 所有按钮、自定义插件、每种报表和每条业务链已逐项认证。未发布的控制器动作通过安装 App 的 `zebra_business_actions` 显式注册；不会开放任意 RPC、SQL、JavaScript 或 Python 路径。新前端不提供 `cur_frm` 的页面会拒绝安全填写。导航后需要在新一轮请求中填写，避免继续使用旧页面版本。

## 权限与恢复

所有业务按登录用户和会话公司执行。Cloud 凭证留在服务端，浏览器只持有自身当前轮次的有限页面会话凭证。工具只能提出写入，不能替用户调用确认；确认必须来自原生登录 Cookie 和 CSRF，且绑定用户、公司、参数摘要和单据版本。重复确认返回同一结果。

提交与停止共用 Redis 会话锁；首条消息、命令及停止正文均持久化。页面会话结果未知时等待 7 分钟，覆盖原生控制租约和传输余量，期间不盲目重开。过期 Host grants 每小时清理。

历史通过原生 SSE 的有限恢复前缀读取，只投影用户内容及公开答复，展示最近 100 条消息。恢复读取上限 4 MiB，超过时明确报错；不把早期片段冒充最新历史。

## 服务与部署

服务器目录 `/opt/erpnext/zebra-agent/`：

- `source/`：本项目；`compose.json`：ERPNext 专用 Cloud API/Worker。
- `erpnext-override.json`：ERPNext 自定义镜像覆盖，已加入原 Compose 配置。
- `secrets/`：签名私钥、Host 配置和 CA，受限权限；源码不包含凭证。
- `workspace.ext4`：独立 1 GiB 限额文件系统，挂载 `/var/lib/zebra/erpnext-workspaces`，已持久化到 fstab。
- Caddy 原配置备份 `Caddyfile.before`，原 ERPNext 环境备份 `erpnext.env.before`；原数据库/文件备份保留在 ERPNext 备份目录。

Cloud 内部地址 `erpnext-agent.zebra.local` 与 Host 地址 `erpnext.zebra.local` 由容器静态解析到服务器并走 Caddy TLS，不要求外部公共 DNS。HTTPS 使用现有 Caddy 内部 CA，浏览器需信任该 CA。HTTP 18090 仍可访问。

复用 native single-root workspace layout 与串行 Worker，Runtime 维持 gVisor、read_only 和无外网 profile；业务数据通过 Host 工具读取。若要启用可写代码工作负载或并行文件工作区，需先升级为每任务独立限额挂载，不能直接扩大当前配置。

运维脚本 `deploy/prepare_remote.py`、`deploy/workspace.sh`、`deploy/seed_cloud.py` 依赖这台机器现有 Zebra 基础设施；不是面向任意服务器的一键安装器。更新先构建前端，再构建镜像、更新 ERPNext Compose 并执行原生 `bench --site 192.168.110.42 migrate`。

## 验证

```sh
npm ci
npm run build
npm test
python3 tests/test_business_checks.py
python3 tests/test_chat_checks.py
python3 tests/test_client_checks.py
python3 tests/test_history_checks.py
```

实际服务器验收另见 [验收记录](docs/acceptance.md)。认证 HTTP 脚本需要受保护环境变量中的管理员密码；只有明确传入 `--allow-disposable-writes` 才创建 UUID 标记测试数据，结束时清理。

全屏会话侧栏沿用 Trench 信息会话的布局和交互，支持新建、切换、重命名、删除以及移动端抽屉。行尾 `•••` 提供管理操作；执行中的会话需先停止才能删除。删除不影响 ERP 业务单据，Cloud 审计记录保留。

输入框与 Trench 共用 Zebra `AgentComposer`：底部可选 DeepSeek Flash / V4 Pro 及关闭、低、高、最大思考强度；默认 Flash + 高。Enter 发送，Shift+Enter 换行，中文输入法确认不触发发送。配置适用于下一次消息，重试未知结果时保留原请求配置。

模型和思考强度按会话保存到服务端，修改后立即保存，无需发送消息。切换会话会恢复各自配置；同一浏览器标签页刷新后恢复所选会话。新会话使用默认配置，旧会话优先沿用上次提交的选择。

Agent 界面动效使用本地打包的 GSAP：面板开合、全屏/侧栏布局过渡、消息与提示入场、执行详情展开、按钮反馈、输入焦点、选择反馈及重命名/删除弹窗。遵循系统“减少动态效果”；流式文字不会逐字重播入场动画，ERPNext 业务页面不参与动效。

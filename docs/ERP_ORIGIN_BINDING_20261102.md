# ERP Origin 绑定修复（2026-11-02）

状态：迁址认证整体复核与后端镜像固化已验证；源修复、部署源码线与受检导出线分别整合同步。

## 根因和证明边界

服务器迁至 `192.168.101.7` 后，ERP 配置与签名 Grant 使用新 Origin，
两个 Runtime 的 Host registry 却仍仅允许 `https://192.168.110.42:18443`。
实际 Cloud 日志显示 capabilities/runtime、原 Task header/usage/artifacts 被
HostGrantBindingError 拒绝。原会话 `5vdk10lcmu` 的真实 BFF 请求复现 403。

仅向 registry 追加新 Origin 可解除签名绑定的 403，但原任务读取仍返回 404。
只读盘点确认 erpnext-full 的 48 条和 erpnext 的 76 条 Task binding 都固定旧 Origin。
原生 require_task_host_context 严格比较 origin，不能重写历史绑定或放宽隔离。
进程内单变量恢复签名 Origin 后，原故障会话四个真实接口均返回 200。

## 最小修复

- 两个 registry 保留旧 Origin，额外允许新精确 Origin；无通配符。
  复用 PostgresHostAuthorityStore/upsert_registry，只替换 allowed_origins。
- ERP base 和 cloud114 配置均恢复 `origin=https://192.168.110.42:18443`，
  保持历史及后续 Task 的授权身份稳定；新增
  `browser_origin=https://192.168.101.7:18443` 表示当前页面实际地址。
- client.open_surface 只在浏览器来源检查处读取 browser_origin；未配置时回退 origin。
  签名 Host Grant、Client Session grant 继续使用 origin，与原 Task 严格一致。
  陌生或缺失浏览器 Origin 不触发 Client Session/Controller 创建。
- issuer、namespace、jwks_uri、公私钥、scopes、用户与公司校验均不变。
  不修改 Task/Run/Controller、原收据、unknown 或 Coverage，不回放任何原操作。

## 线上应用和回退

备份目录：`/home/ubuntu/releases/20261102-erp-origin-binding/`（仅服务端持有配置原件）。
仅在正常 ERP backend 加入精确 client.py 只读 Compose 挂载，并重建该服务。
镜像仍固定 `37649d4cad281e59c13c670abd1c5e259d662eb5211ed8c7a237823a5352f687`。
当前源文件 SHA256 为
`0a043a2f238ae96439d71e1a8a5ca00608715ec18a140d74e15c0eae5c6bae49`。
未构建镜像、创建临时容器、卷或网络；Native、Worker、搜索、MCP 及其他 ERP 服务不重建。

**后续 ERP 镜像必须包含本修复，并移除本次 client.py 挂载，避免旧覆盖遮蔽新镜像代码。**
整合源码时保留正在开发的原生能力工作；不得用本分支旧整包覆盖并行修改。

回退须先核对配置没有后续修改：按备份恢复 ERP origin/browser_origin 与 Compose，
仅重建 backend（`--no-deps --pull never`）。两个 registry 仅在其余字段仍完全等于
本次 after 证据时恢复 before 的 allowed_origins；不得回退审计或 replay ledger。
回退会重新引入本次迁址故障，优先修正前向配置。

首次 Compose 操作因默认 pull 将 sha256 ID 当作仓库引用而遭镜像站 403；
没有重建服务。改用既有缓存镜像与 `--pull never` 后正常重建 backend。
部署配置的其他字段保持原样。backend 环境数组哈希在重建前后不同，旧记录仅含有序数组
摘要，不能证明值变化或仅重排；Compose 环境配置及镜像未修改，不声称字节级环境一致。
原 erpnext-full-scheduler-1 在操作前已处于 Restarting，其后启动时间继续变化，
容器身份/镜像/环境未改动；不将其计作本次重启或声称修好该独立故障。

## 验证

- 回归先红后绿：python3 tests/test_client_checks.py。
  原无 browser_origin 配置兼容；新地址允许且签名 origin 不漂移；
  旧页面地址、陌生地址、缺失 Origin 均不申请 Controller；原 unknown/维护门禁保留。
- python3 tests/test_admin_mode_checks.py 和 tests/test_force_stop_checks.py 通过。
- 修改生产模块 Ruff F 检查、git diff --check 通过；未运行重型全量门禁。
- 正常 backend 的真实 BFF：原故障 Task 的 capabilities/runtime、header、usage、artifacts
  全部 HTTP 200；另一 native105 原 Task header HTTP 200，原映射及 Client Session 数据不变。
- 真实签名 HTTP 矩阵：cloud114 新/旧 Origin 能力查询均 200，陌生 Origin 403。
  native105 的陌生 Origin 403；其 /capabilities 路由本身不存在，可信 Origin 的 404
  不计作成功路由验收，以原 Task header 200 作为实际读取证据。
- 实际 api.snapshot 加载原会话三条历史消息，features.catalog 显示 runtime available。
  原执行状态仍为 failed，保留原失败事实，没有自动恢复业务执行。
- 仅 backend 的容器身份变化；其他既有容器身份、镜像、环境摘要均未变。
  本次没有新增容器、网络、卷、模型/搜索请求、任务派发或 Controller 领取。

证据见 [验收目录](evidence/erp-origin-binding-20261102/)。无原始 Token、密码或配置私钥。
未做新模型端到端或浏览器交互验收，不将读取恢复等同于旧失败 Run 已成功完成。


## 整体复核与源码固化

进一步修复三处遗漏：bootstrap 返回的页面链接改用 browser_origin；旧会话 Manifest
导入缺失 AGGREGATE_METRICS 导致 500，恢复不可变五指标集合并由原聚合校验复用；
初始 prepare_remote 不再写死旧地址到 extra_hosts，改从配置的浏览器 HTTPS IP 获取传输地址。
prepare_remote 仅初始配置使用，本次从未在生产执行该初始化脚本。
保存的私有 host-settings.json 同步 browser_origin，签名 Origin、密钥及其他字段保持原样。

发布检查入口 `python3 deploy/check_auth_release.py` 包含五项无服务检查，支持
`--override` 检查精确文件及上级目录挂载是否遮蔽 api.py、client.py 或 business.py。
通过正常生产源码分支构建小型离线后端镜像，保留其已有管理员/控制器/回执等全部实现：
`sha256:0afdf46442e188caf17bce1c533c0b4503cb1cf7881b79c64f5468d5b120138d`。
**已移除上文记录的 client.py 临时覆盖，修复现在在镜像内，后续发布不得恢复旧覆盖。**
构建限 1 CPU/256 MiB，验证容器限 1 CPU/128 MiB、无网络、无站点数据；容器、匿名卷及
临时构建目录用后回收。旧基础/回退镜像及作为当前镜像父层的镜像保留，不执行 prune。

实际 Cloud 签名 HTTP 12 项矩阵通过：原 Task/新精确 Origin 200；外部 Origin、issuer、
namespace、缺权限、过期和重复 jti 403；跨用户/工作区/thread 404。原生隔离及防重放均未放宽。
正常后端 snapshot 读取原三条消息，原 Run failed 状态不伪改。完整及旧 Runtime 的实际
受信 Host Manifest 分别返回 200（5/3 工具），错误工作负载 HMAC 均 403。
旧 Manifest 检查特意在原 Legacy Worker 容器做独立 GET，而非启动 Worker loop。
从 ERP 后端探测 Legacy 内部 issuer 时不能解析该 Worker 专属地址，不计作产品链路失败；
实际 Worker 侧 DNS/TLS/签名路径已复验通过。

冷启动重新获取两个 Runtime JWKS 均 TLS/HTTP 200、公钥集合摘要一致；Connector/Profile
引用与 ERP namespace、frontend revision/digest 对齐。Frappe host_name 已是新页面地址，
未启用 ignore_csrf 或跨域通配。BFF RPC 仍走原 Frappe Session/CSRF，JWT 不返回浏览器；
SDK 的 Origin、用户/Task/Run/Profile/fence 与 unknown 不重领逻辑由原代码及隔离回归核对。
没有在真实页面新建 Session/Controller 来制造验收。

Legacy 实际 /etc/hosts 与持久化 Compose 都为新地址；Docker 创建时 ExtraHosts 元数据仍
记旧地址。本次不重启这组 Worker/API；后续重建必须使用已更新 Compose，不能从旧模板恢复。
旧站点目录、issuer、Task Origin、归档和历史部署记录中的旧 IP 均是身份或历史事实，保留。

Scheduler 的 persisted env 已改回签名 Origin；复核期间另一维护线将其从 v115 对齐到
正确 v117，已保留其源码/记录。随后确认运行进程仍加载旧的浏览器 Origin 配置，使用该线
既有 idle/snapshot 守卫，仅同镜像重建 Scheduler 刷新 Origin。前后均无 active schedule、
pending/materializing firing、运行会话或有效租约；model_calls=188、sessions=51、firings=0
及迁移账本摘要完全一致，其他服务在该操作期间不变，准入状态精确恢复。
这证明配置与空闲准入边界，不冒称执行过真实定时任务。

124 条 Task binding、27 条 client_run_binding、8 条 Client Effect receipt、17 条原控制操作、
4791 条 Session event 的内容摘要前后一致；ERP 60 条会话、35 条业务审批/执行回执及
1 条计划内容摘要前后一致，Unknown 保持。覆盖证明表及命令收据表同样按内容摘要核对。
认证验收仅新增正常授权映射/防重放审计与诊断 Error Log，不重写原执行或回执。

认证补丁独立保留，不依赖未发布的管理员功能；源仓库 main 整合正常生产源码及全部修复，
保留已验证的原生能力与 Scheduler 对齐源码；Cloud 的受检导出线保留 Gate02 模块拆分/完整 Ruff
规则，通过 git archive 固定发布提交。三条源码线都运行实际认证回归，禁止用旧整包覆盖。
Cloud 导出线 22 个无服务 Python 检查串行通过、完整 Ruff 零违规；生产源码线认证及
admin/document/force-stop 检查通过。未重跑全量 Runtime make test，也未新增业务/模型/搜索。

维护检查原夹具缺少 textRef 并断言旧重连源码，已直接复用先前 Gate02 验证的夹具，保留维护
拒绝、原错误及真实异步重连断言。没有降低任何生产校验、尺寸或 Ruff 门禁。

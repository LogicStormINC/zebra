# 线上会话持续 loading：工作区启动失败修复

任务 CLOUD-WORKSPACE-LOADING-20261022，负责人 Luke Ding / Codex。
目标地址为 `http://192.168.110.42:18080/dashboard/strategy/conv_1792648502376_eee0f2`。
SSH 使用旧地址的已知 host key 校验，确认仍是原服务器。本轮没有修改 IP。

## 根因

会话在 2026-10-22 13:55 左右提交，问题为“你现在能做什么”。

- Trench Turn：743f1490-75f3-4410-8e87-ab6e714c59f7。
- 原 Run：5602158d-f216-4e10-9696-df1b7d817942。
- Zebra Session：d8654a8d-cf8b-4cbb-85b5-000d00b29c77。
- Workspace：d65585d7-bf82-4628-af19-1f09af1ae7dc。

Trench 数据库的会话 key 带用户／工作区命名空间，不能直接以 URL 裸 key 查询。
纠正该查询后，确认不是会话不存在，而是原 Run 已接收但未开始模型执行。

根因链：

1. 宿主 `/var/lib/zebra/workspaces` 是空的 root:root、0755 目录。
2. Worker 以 UID/GID65532 运行，挂载可写但没有目录写权限。
3. HOST_REFERENCE 工作区准备需要写 `.zebra-host-reference`，发生 PermissionError。
4. Provisioner 只捕获 WorkspaceMaterializationError，未转换工作区 provisioning 状态。
   Worker 输入恢复只捕获 FileNotFoundError/ValueError，遗漏 PermissionError 等 OSError。
5. 异常逃出 Worker、进程重启；执行租约虽释放，但 Run 未写入失败终态。
   Trench 已显示 running，于是持续观察无正文、无终态的原 Run。

因此这次不是模型慢，也不是 IP 改变后前端连不上：实际 snapshot 请求持续200，
模型请求事件0。容器重启后 `/health` 正常，不能据此判断会话正常。

## 最小修复

源码只改两处共享边界：

- workspace_provisioner.py：准备／恢复／uncertain 对账同时处理 OSError，
  复用既有 uncertain/fail 转移；把准备时的目录 reset 放入同一个错误边界。
- execution_recovery.py：输入恢复捕获 OSError，沿既有 WorkerExecutionError
  和带租约围栏的 setup-failure 收尾，不再让文件系统异常退出整个 Worker。

不增加重试、模型补调用、关键词规则或新抽象，不修改 Trench 产品逻辑。

运维修复只针对确认为空的上述 bind 根目录，将属主改为65532:65532，权限仍0755。
没有递归 chmod/chown，没有改其他目录。原 hardened Worker cap-dropALL、只读根
文件系统和运行用户保留。属主修复由短暂、断网、只读可信镜像，仅授予 CHOWN、
只挂这一个应用目录完成，不挂宿主根目录、不传生产凭据，完成即删除。

## 无模型验证

- 既有实际 recovery 解析矩阵增加 PermissionError/OSError：定向测试51通过。
- `uv run python scripts/check_workspace_setup_io.py`：4条故障检查通过，涵盖
  reset、materialize、snapshot restore、uncertain reconcile；未误标成功。
- Ruff通过；文件大小门禁3258检查、0违规。
- 从现有生产镜像构建的 API／Worker 各自断网执行同4条检查，通过。
- 最终实际 Worker UID65532 对根目录可写，marker 由65532拥有；精确 Workspace
  通过既有状态转移和有界对账恢复 ready。

未执行全仓门禁或用新模型调用替代故障恢复证明。

## 原 Run 的同步结果

没有重新执行原 Run。只在精确 Session／Run、原4条事件、无新输入／模型事件
校验后取得新鲜 fenced lease，复用既有 finalize_worker_setup_failure 和索引重建。
写入真实的 TURN_FAILED、SESSION_FAILED，未伪造 completed 或 partial。
该操作没有调用执行入口或准备执行输入。

随后正常 Trench observer 自行同步：

| 字段 | 结果 |
| --- | --- |
| Run | 原5602158d-f216-4e10-9696-df1b7d817942 |
| Trench 状态 | failed |
| error_code | zebra_run_failed |
| detail | Worker execution could not start. |
| 原生 owned snapshot | active_turn=null，latest_turn.status=failed，2条消息 |
| 模型调用／新 Run／搜索 | 均0 |

Trench reclaim 的 attempt_count 从1到5属于观察重连，不代表5轮模型执行。
该轮没有生成答案；保留原问题与真实失败状态。修复后可由用户主动提交新 Turn，
本次没有自动重试。浏览器控制连接不稳定，未声称完成实际视觉／点击验收；
验收依据为真实数据库、正常 observer 同步和相同页面读取逻辑的原生 snapshot。

## 部署与保存性

基于现有 accepted6bca5053 镜像，API只覆盖 runtime文件，Worker覆盖上述两文件。
两个修复文件的生产哈希与本地修复源码完全相同：

- runtime：08e47acc09698e10124e9b3447a4d325ab229bba05bce5f038db0d912a99cb49。
- recovery：fb68f0c7425cc0afbebeafd6c887391548595479f64156c87f2861ae9b2ba6d7。

镜像 zebra-api:workspace-io-20261022（ID2156443e...）、
zebra-worker:workspace-io-20261022（ID33b93abc...），均 healthy。
没有部署通用 Runtime 的其他改造；schema仍105，插件允许列表／挂载／开关、
高思考、stream v2、授权、租约、取消、安全设置、环境变量值和命令保持原样。

空闲检查要求有效租约0、待处理命令0，Trench只允许本次确认卡住的精确 Turn。
停止 API 后再次检查 Worker，再成对切换；没有中断其他活动 Run。
四个原受保护 Session 的事件哈希、数量、模型请求计数不变，原 partial 不变。
Search/TLS/Yahoo/Broker/Trench 稳定进程身份与配置保留，Exa control字节相同，
没有重启搜索或 MCP、清冷却、改全局代理或 IP。

已存在的 trench-caddy、pgAdmin 自动重启单独记录：基线已有46／185次重启。
其容器 ID、镜像与配置没有变；不能声称全栈所有进程健康或启动时间均未变化。
本次不修复这两个独立问题。

## 切换检查中的纠正与回滚

初次构建因非 root 无法覆盖 pycache 失败；仅构建阶段用 root 编译，再恢复
原运行用户，最终镜像 Config 相同。第一次应用因原 Worker 不具备 CHOWN
回滚；随后两次分别因环境列表顺序、既有不稳定容器重启计数触发保护回滚。
确认环境值相同后采用按键／挂载目标比较，并将已知不稳定进程单列。
失败记录保留；最终检查通过后才做原 Run 的围栏收尾，模型调用始终0。

发布目录 `/home/ubuntu/releases/20261022-workspace-loading/`，权限0700。
原始环境、日志和快照仅放私有目录，不提交 Git。
当前 Compose 文件序列为此前20261019base、20261020runtime-repair、
20261020version-sync、20261021plugin-production，再叠本轮 workspace-override.json。
后续运维必须保留最新层；不要只运行早期 base。

回滚前仍需空闲检查，成对恢复前四层 API／Worker 配置。保持已修复的目录属主，
不回滚原失败事件、不降 schema、不重跑 Run、不动 Search/MCP 或其他数据。
本地证据 `.artifacts/cloud-workspace-loading-20261022/`。本轮仅本地集成，不推送 GitHub。

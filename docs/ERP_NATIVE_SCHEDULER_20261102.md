# ERP Cloud Scheduler v117 运行时对齐

状态：2026-11-02 已完成无模型隔离验收并更新线上。
范围仅 Native Cloud Scheduler；不是 ERP RQ scheduler，也不是全部定时业务场景认证。

## 根因与最小修复

旧 Scheduler 镜像 `sha256:9a09d2d50d5ae7f9fd0cb3167427fa25101b055f2e2c315d6ffe642d875526f2`
只认识 v115，而已上线 API、Worker 与真实 PostgreSQL 使用 v117。
启动时的完整迁移集合检查按设计拒绝旧程序，导致 Scheduler 持续重启；本轮前重启计数为 164。

已有 API 固定镜像包含 scheduler workspace，原 Compose 已显式声明
`python -m zebra_agent_scheduler.main`。因此无需改运行时代码、装依赖或维护新派生镜像；
仅把 `/opt/erpnext/zebra-agent/full-runtime-20261029-1/compose.json` 的
`services.scheduler.image` 改为 API 同一不可变镜像：

`sha256:e4faff1bfaf7d9d38bd7a60befcb534fedcc1f4faf753eb335cad288a98bf968`

仅 `up --no-deps --no-build --pull never scheduler`。保留原入口、env_file、网络、挂载、
权限配置和重启策略。业务 `ZEBRA_*` 环境逐项一致；Python 版本/校验和/PYTHONPATH 元数据
随已验收 API 镜像对齐，不把凭据展开写入 Compose。

## 启动前核对

- 真实数据库只有一个 deleted 计划，没有 active 计划，包括未来计划均为 0。
- firing 总数 0；无 materializing/待恢复触发；运行会话和有效租约均为 0。
- 模型调用计数 188，会话计数 51。
- API 迁移版本、名称和校验和集合与真实数据库完全一致，版本上限 117。
- 保存旧 Compose、完整服务 inventory、原镜像和私有前置快照；不更改业务计划或原 Run。

## 无模型验收

复用现有 PostgreSQL 镜像创建自有 internal Docker 网络及 tmpfs 数据库。
仅从生产读取 schema-only dump 和未编辑的迁移账本快照，恢复到隔离数据库；没有业务数据、
待执行计划、Cloud Worker 或外网连接。生产数据库和账本始终未迁移、未修改。

1. 原 v115 程序对同一 v117 克隆明确报 schema mismatch；校验没有被关闭或放宽。
2. 最终候选使用线上将获得的有效环境、原只读配置挂载，仅替换隔离 DSN。
   `--once` 返回 `status=stopped, cycles=1`。
3. 连续空闲轮询完成 4 个周期；安装实际 SIGTERM handler 后停止，退出码 0。
4. 首次早停探针在冷初始化完成前发 SIGTERM，Docker 10 秒后以 137 终止；该失败记录保留。
   这是探针未等待信号就绪的边界，未更改原生信号逻辑。最终验证等候 `/proc/1/status` 的
   SIGTERM 捕获位后再测试运行态退出；不把早期失败覆盖成成功或声称任意冷启动阶段均可优雅退出。
5. 本地 Scheduler 配置/准入及 materializer 回归 10 项通过；部署脚本编译、Ruff F 与 diff 检查通过。

## 线上证明

- Scheduler 独立重建，使用 API 相同镜像，实际进程持续运行，观察窗口重启计数 0。
- 在不读业务表、不新增请求的统计观察窗口内，PostgreSQL 实际扫描计数推进：
  `task_schedule_firings` 782600 → 782612，`task_schedules` 391315 → 391321。
  结合空闲隔离周期和启动信号就绪证明，确认不只是容器显示 running。
- 模型调用数 188 → 188，会话 51 → 51，firing 0 → 0，未产生模型、搜索或新 Run。
- 迁移账本指纹前后一致：`73168d2872f8551e6ae4493c6f995cd642a94b373613ff5bbb98c5851ca9059e`。
- 除目标 Scheduler 外，所有原 ERP/Native/搜索/出口容器 ID、镜像、环境哈希、启动时间和重启数
  与发布前完全一致。没有重跑原 Run，未重启搜索或原 MCP 进程。
- 私有证据在 `.artifacts/erp-native-scheduler-20261102/` 和服务器同名 release 目录；
  生产 env、数据库 schema/dump 和配置备份均不进入 Git。
- 验收后按 owner 精确清理 2 个隔离容器、1 个网络、未部署的临时派生镜像；未创建持久卷，
  生产镜像及旧 v115 回滚镜像保留，没有全局 prune。

## 后续发布约束与验收边界

后续 API/Worker 升级必须把 Scheduler 纳入同一冻结运行时/迁移集合的发布检查；
不能只升级 API/Worker 后留下旧 Scheduler，也不能通过更改账本或关闭启动校验掩盖错配。
`deploy/native_scheduler_align.py` 保留可运行的前置空闲检查、旧失败/新通过、真实轮询统计、
环境和非目标服务对照以及原数据/模型计数检查；不自动重试已执行业务。

本次证明匹配 v117 后能正常启动和空闲轮询；未创建计划，未触发带模型或业务写入的真实定时任务。
不是生产 HA/故障切换或长周期 SLO 认证。

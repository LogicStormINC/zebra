# 线上版本补齐与部署凭据 — 2026-10-20

任务：CLOUD-VERSION-SYNC-20261020。负责人：Luke Ding / Codex。
目标服务器：192.168.110.30。用户授权核对最新版，并部署缺失的已提交内容。

## 结论与实际版本

线上原先不是完整最新版。此前故障修复和 Yahoo 出口已部署，但底层镜像仍有
较早源码：Zebra API/Worker/Broker、Trench 插件协议／管理页面存在遗漏，
生产数据库仍为 v104。本轮已补齐所有上述应用角色，并迁移到 v105。

交付源码：Zebra cloud-agent `6bca505358dfe970182d805077b323a7c3d6b6e0`，
Trench main `8feacbfe1c334aa461ba7aef7743dcd873da3cdc`。
后续本任务提交只增加治理／验收文档，不改变运行源码。

| 镜像角色 | 新镜像 | 不可变镜像 ID 前缀 |
| --- | --- | --- |
| zebra-api | `zebra-api:version-sync-20261020-6bca5053` | `5ef2426feab3` |
| zebra-worker | `zebra-worker:version-sync-20261020-6bca5053` | `23abf89753a0` |
| zebra-broker | `zebra-broker:version-sync-20261020-6bca5053` | `460a22f46234` |
| trench-backend | `trench-backend:version-sync-20261020-8feacbf` | `255053542e13` |
| trench-frontend | `trench-frontend:version-sync-20261020-8feacbf-http` | `6e758143eb45` |

更新角色包括 Zebra API、Worker、授权 Broker；Trench API、scraper/RSS/
normalize/archive/market-data/state-derive 六个 Worker 及前端。
只更新应用角色，不按镜像日期升级 PostgreSQL、Redis、MinIO、Caddy 或 RSSHub。
原 Search、Search TLS、Yahoo 独立出口及 MCP 搜索进程保留。

## 如何判定原先遗漏

检查运行中容器里的文件字节，不用 Git 目录或镜像标签代替事实：

| 角色 | 核对范围 | 更新前不一致 | 更新后不一致 |
| --- | --- | ---: | ---: |
| Zebra API | 1,322 个 Python／依赖文件 | 66 | 0 |
| Zebra Worker | 同上 | 64 | 0 |
| Zebra Broker | 同上 | 74 | 0 |
| Trench API | 537 个 Python／依赖文件 | 7 | 0 |
| Trench 六个 Worker | 各 537 个文件 | 各 8 | 0 |
| Trench 前端 | 222 个部署文件，含保留的兼容层 | 原提交清单 221 个中有 10 处差异 | 0 |

Zebra uv.lock/pyproject、Trench Python pdm.lock/pyproject 与已安装依赖一致。
复用现有不可变镜像依赖，复制 Git 归档里的已提交源码并生成 checked-hash
字节码；构建步骤断网，无依赖升级、安装脚本或模型／搜索调用。

前端原有 HTTP 校验兼容层不在 Trench Git 提交中。本轮不覆盖该已有修复：
从固定旧镜像 `sha256:62974fa604d1...` 保留以下五个文件及对应已安装依赖，
单独记录来源与哈希，不能称作全部来自 Git：

- package.json、pnpm-lock.yaml：原已安装的 @noble/hashes 2.4.0。
- src/lib/browser-sha256.ts。
- src/lib/strategy-coverage-report.ts、src/lib/strategy-ordered-items.ts。

其他前端文件均来自最新提交，生产构建断网通过；沿用同源 API 代理目标。
没有添加新的兼容逻辑或产品依赖。未来从纯 Git 全量构建前，仍需单独完成
该既有兼容层的源码收敛，避免 HTTP 环境正文校验回归。

## 迁移、切换与保护

先检查有效执行租约、待处理命令和 Trench queued/dispatching/running Turn。
准备期间曾发现一轮正常业务执行，未中断；自然结束后重新确认三项均为 0。
冻结应用入口后再次检查空闲，随后停应用、执行迁移并启动新版。

- 对照版本、名称和 checksum 集合核对已有迁移，仅补 v105。
  迁移编号存在空缺，不以 migration 表行数当作版本。
- v105 只扩展两个已有 extension kind CHECK 约束，使其接受 plugin。
  扩展记录的 kind 数量在迁移前后相同；未清数据、重写原 Run 或变更 epoch。
- Compose 配置比较只允许应用 image 变化；API、Worker、Broker 的运行环境、
  命令和挂载哈希／集合前后相同。Trench 后台镜像环境与原镜像相同。
- 保留高思考与 stream v2；web_pipeline_v2 仍沿用原 false。
- 生产 Plugin 开关仍为原来的 false。只更新能力代码／页面和 schema，
  没有复制本地试点包、凭据、允许列表或自动扩大生产权限。
- 四个受保护原 Session 的事件数量、内容哈希和模型请求计数相同；未改 partial。
- Search、TLS、Yahoo 出口和数据服务身份未变；Exa control/settings 字节相同。
  全局代理文件及实际配置哈希相同，未清冷却、重建 MCP 或发检索探针。

临时迁移环境文件仅存在服务器私有发布目录，完成后已删除。
发布目录权限 0700；凭据、原始环境、日志及私有快照不提交 Git。

## 验证结果与边界

- Zebra 插件、权限／快照、目录、恢复、MCP 计时等定向回归：111 passed、1 skipped。
- Trench 插件绑定、Skill、调度与交付协议回归：68 passed。
- 插件管理、设置入口、正文／覆盖报告校验等前端回归：91 passed。
  正确使用测试 NODE_ENV 与仓库 PYTHONPATH；未改既有测试或生产代码。
- 五个新镜像全部离线核对源码；正常部署后再次逐角色核对，差异为 0。
- 新 Worker 断网检查确认 web.search 注册、无授权时过滤、空路径可纠正、
  越界仍拒绝、真实来源媒体证据保留；模型／网络请求均为 0。
- 新登录页及 `/api/health/ready` 实际返回 200；本机通过真实 LAN 入口
  `http://192.168.110.30:18080/login` 也收到 200。Redis/PostgreSQL 检查通过。
  该接口的 Zebra 结果是 local_configuration_only，不等同真实鉴权 Run E2E。
- 实际 HTTP 读取新 dashboard 静态资源，包含 plugin-packages 和
  plugin-installations 代码；不是只看镜像里的源码或拦截响应。
- 六个后台 Worker 运行中、Redis ARQ 心跳存在。API/Worker/Broker/前端没有
  启动 traceback，相关健康检查通过。
- RSS Worker 的真实采集记录中仍有 DNS、HTTP 和超时失败／traceback。
  进程和心跳正常，不能把它算作全部业务健康；本轮未扩大到 RSS 上游修复。

本轮未主动新建 Run、发起模型／搜索验收、安装页面插件或重放原 Run。
未重跑全仓门禁或声称完整业务／模型 E2E；当前工作是版本同步与部署验收。

## 发布路径与回滚

私有发布目录：`/home/ubuntu/releases/20261020-version-sync/`。
`deployment-plan.private.json` 记录每个项目的完整 Compose 文件序列。
新应用 override 必须叠在原 20261019 发布文件和 20261020-runtime-repair
文件之后；不要只用早期 base 覆盖回去。

Yahoo 独立配置仍使用 `20261020-yahoo-egress/search-override.pending.json`
及独立出口 Compose；本轮未包含 Search 项目。

迁移到 v105 后不能直接重启裸 v104 应用镜像。已预先生成并断网验证
`zebra-api/zebra-worker/zebra-broker:rollback-v105-20261020`：保留原应用
行为，仅加入已提交的 v105 migration/catalog，使其能够读取当前 schema。
每个项目的 `*-rollback-v105.json` 及旧 Trench 镜像均保留。
回滚前仍需相同空闲检查；只恢复应用镜像，不删迁移行、不降 schema、不动 Search。
本轮切换成功，没有实际执行回滚。

本地证据：`.artifacts/cloud-version-sync-20261020/`，含已提交与部署清单、
前后字节指纹、定向回归、镜像、迁移、页面资源和保存性凭据。
GitHub 远端没有更新于本地的待合入提交；本轮未推送，冻结归档引用不变。

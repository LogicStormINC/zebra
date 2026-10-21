# 线上 Plugin 配置修复与验收 — 2026-10-21

任务 CLOUD-PLUGIN-PROD-20261021，Luke Ding / Codex。
目标为线上 `http://192.168.110.30:18080/` 设置中的独立插件页面。

## 根因与修复

上次版本同步已部署 Plugin 代码、页面和 schema105，但生产 Plugin 开关仍关闭，
管理写入未启用，批准包目录和 digest 允许列表也未配置。因此市场上游实际返回404，
前端显示“插件服务未开放，或该插件当前不可访问”。本轮先用真实签名请求复现404。
既有授权 Broker 已支持 extensions.read/manage，不需要扩大权限或修改 Trench。

复用既有安装、组件归属、授权、快照和撤销流程，只补运行配置：

| 角色 | 本轮配置 |
| --- | --- |
| API | PLUGINS_ENABLED、EXTENSIONS_MANAGE_ENABLED、EXTENSION_TURN_ADMISSION_ENABLED、SKILLS_PUBLISH_ENABLED、SKILL_WORKER_ENABLED 为 true；EXTENSIONS_READ_ENABLED 保持 true |
| API | PLUGIN_BUNDLE_ROOT=/run/zebra/plugins；PLUGIN_ALLOWED_DIGESTS 精确限定下述单包 |
| API | 仅增加批准包目录的只读挂载 |
| Worker | PLUGINS_ENABLED、EXTENSION_WORKER_ENABLED、SKILL_WORKER_ENABLED 为 true |

表中变量都带 `ZEBRA_CLOUD_` 前缀。其他环境、命令、安全配置和挂载保持原值。
没有关闭包完整性校验、允许任意包、复制密钥或扩大 Task/租户授权。

仅接入此前本地已验收的只读试点包：

- cloud-plugin-local-pilot@1.0.0，Local operator pilot。
- digest `sha256:da4f262772d038851935a7304339ee9c9e2bca11cf228e7f1770fa26cce1f5fa`。
- local-guide / skill-bundle，SKILL.md216字节，引用 marker28字节。
- 用途是验证 Plugin → Skill 读取接线；不是通用业务插件市场的完整内容。
- 未推广其他测试包、账户数据或 MCP 凭据。生产 MCP Worker 仍未启用，
  不能据本次 Skill 试点验收声称生产 MCP 插件已可用。

## 切换与版本边界

生产维持已验收 Zebra6bca5053、Trench8feacbf 和 schema105。
API 镜像 ID 前缀5ef2426feab3、Worker23abf89753a0，与修复前完全一致。
本地任务从703c3c03建立文档分支，不代表通用 Runtime 改造已部署。
本轮没有构建镜像、修改产品代码、迁移数据库或更新 Trench。

先确认有效租约0、待处理命令0、Trench活动 Turn0；停止 API 入口后再次检查
Worker 空闲，再成对更新 API/Worker 配置。二者恢复 healthy，只有显式 flags
及上述只读挂载发生变化。Broker、Trench、Search、TLS、Yahoo 出口不重建。

## 无模型验收

1. 当前实际 API/Worker 镜像的离线配置检查通过；包允许列表仅一项，未批准
   digest 被拒绝，Worker 缺少 Cloud authority 仍拒绝，MCP 保持关闭。
2. 新鲜签名的实际市场请求从404恢复200，只返回批准试点包。
3. 隔离 operator principal/workspace 中，用仅含 package_digest 的安装请求成功，
   系统创建 managed Skill 绑定；启用、重新读取、停用、重新读取均保留正确状态。
4. 不同 principal、workspace 均404，缺少 extensions scope403，缺少认证401。
5. 只 bootstrap 一个不执行的隔离 Task，返回 executed=false；实际 Worker
   组件加载真实 Task ceiling、新鲜执行授权和 pinned snapshot，读取完整 Skill
   与精确 marker。空选择不获得插件，停用后旧冻结快照被拒绝。
6. 该隔离 Task 随后取消；数据库确认0模型请求、0工具执行起始、0待处理命令。
   未向 Worker 提交执行 Run/message/resume，未调用搜索或远端 MCP。

隔离 operator 权限证明不代替真实 Trench 会话授权证明，两者分开验收。
试点安装最终停用留作审计；没有替正常用户安装、启用或停用插件。

## 真实页面验收

用户在受控 Chrome 登录后，通过实际线上菜单打开设置 → 插件。
真实页面显示试点名称、版本、Skill 和安装按钮；“已安装”列表为空，与正常账户
未安装任何插件一致。切回市场可重复读取，未出现原错误。

实际浏览器记录：

| 路径 | 结果 |
| --- | --- |
| /api/trench-ai/extensions/plugin-packages?limit=50 | 200，两次实际读取 |
| /api/trench-ai/extensions/plugin-installations?limit=50 | 200，正常用户0项 |

没有拦截/伪造响应，没有从页面发送消息或调用模型。安装/启停写入证明来自隔离
签名原生 API，未声称完成正常用户页面点击安装或实际模型自主调用验收。

## 保存性与限制

前后核对：四个原 Session 事件数量、内容哈希、模型请求数完全相同；原 partial
不变。Worker 源码、模型/运行设置、高思考和 stream v2 保留。原 web_pipeline_v2
值也未改变；它与 stream v2 不是同一个开关。

Search 与 Search TLS、Broker、Trench API 的容器身份、启动时间、环境/命令、
挂载完全相同；Searchsettings和持久 Exa control 字节相同。独立 Yahoo 出口
健康且重启0，全局代理文件和实际配置哈希不变；没有新增 Exa 帧或限流事件。
API/Worker 使用同镜像，仅必要配置变化。临时预检查环境文件已删除。

本轮不是全仓回归、真实模型或所有插件供应商的端到端验收；也未扩展 RSS 上游修复。

## 发布配置与回滚

服务器私有目录 `/home/ubuntu/releases/20261021-plugin-production/`，权限0700。
批准包存于该目录 approved-bundles，仅 API 只读挂载；原始环境/日志不提交 Git。
后续更新应保留本轮 override，避免旧发布配置再次关闭插件。

当前 zebra-application Compose 顺序：

1. 20261019-zebra-trench/config/zebra-release.json。
2. 20261020-runtime-repair/zebra-override.json。
3. 20261020-version-sync/zebra-override.json。
4. 20261021-plugin-production/plugin-override.json。

以上路径均位于 `/home/ubuntu/releases/`。完整参数在私有 plan.private.json；
不要只运行早期 base。回滚配置时先做相同空闲检查，成对恢复前三层配置的
API/Worker；不降 schema、不改镜像、不清插件记录、Search/MCP 或原 Run。
不从 shell 打印原始 Compose/env，因为其中可能包含凭据。

证据位于任务私有 `.artifacts/cloud-plugin-prod-20261021/` 和服务器同名发布目录，
包括 offline/activation/lifecycle/preservation/egress/no-execution 凭据与真实页面
DOM/网络状态。只记录本地治理提交，不推送 GitHub；冻结归档引用保持不变。

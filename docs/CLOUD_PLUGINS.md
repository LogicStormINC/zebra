# Cloud Plugin 使用与运维

2026-10-19。首期交付可信内部包的 Skill/MCP 组合；源码默认关闭。
源码、隔离原生验收、正常服务激活、真实模型验收是四个独立状态。
本地正常服务已完成 Skill-only 隔离试点激活，见第7节；未做真实模型验收。

## 1. 能力边界

Plugin 复用已有 Skill Publication、McpConnection、ExtensionSnapshot 和工具网关。
它记录包内容与组件来源，不产生新的执行权限。安装、启用、Task 授权、单次审批分别判断。

- 支持 Skill-only、HTTP MCP-only、Skill+MCP；一个包最多32个组件。
- 仅绑定当前 scope 中已经 ready 且显式启用的组件，不代为启停底层组件。
- MCP 首期只接受已就绪的 none/bearer 连接与固定非空 catalog。
- 不执行包内代码；不支持安装脚本、任意 stdio/hook、依赖安装或自动更新。
- 不开放 Marketplace、任意远程包 URL、publisher 自声明信任或外部签名信任链。
- researcher 暂不继承父任务的 Plugin/Skill/MCP。其现有只读、深度1与按父授权
  缩小的 web.search 不变；描述性上下文不是子任务的执行授权。
- 不改变模型档位、思考设置、v2、Yahoo 默认、Exa fast 或搜索回退。

## 2. 准备可信包与已有组件

目录示例：

```text
candidate/
  plugin.json
  skills/research/SKILL.md
  skills/research/references/guide.md
```

```json
{
  "manifest_version": "0.2",
  "id": "internal-research",
  "version": "1.0.0",
  "publisher": "internal-team",
  "components": [
    {"id": "guide", "kind": "skill-bundle", "skill_root": "skills/research"},
    {"id": "docs", "kind": "mcp-http", "connection_slot": "docs"}
  ]
}
```

用现有 Skill Publication 流程发布 `skills/research` 的精确文件，准备相应
SkillInstallation；用现有 MCP 管理流程准备连接、凭据及固定 catalog。
Plugin 槽位不包含租户 connection ID、endpoint 或密钥；安装时才在 scope 内绑定。
Skill 的相对路径、长度、完整 SHA-256 文件清单必须与包中该组件一致。

在仓库依赖环境内计算实际包摘要：

```sh
uv run python -c 'from pathlib import Path; from agent_integrations.plugins.package_integrity import load_plugin_package; print(load_plugin_package(Path("candidate")).package_digest)'
```

将经运维审核的目录放在可信根目录下的 `<64位摘要>/`，配置完整
`sha256:<64位摘要>` 允许列表。包目录只读挂载；不要把上传目录或沙箱目录作为可信根。
计算哈希不等于批准来源，管理员仍须审核实际内容及来源。

包摘要覆盖规范化 Manifest 和排序的全部文件路径、长度、SHA-256。
Manifest 摘要与包摘要用途不同。Worker 只读发布时固定的对象版本与校验收据，
不依赖这个目录，不下载同版本的替代包。旧 v0.1 单组件可规范化读取，
但旧 stdio/hook 描述可解析不代表 Cloud 可启用。

## 3. 配置与迁移

前置条件是现有 Cloud PostgreSQL/S3、Host Grant、Task/Worker 权限与扩展组件接线。
对象存储须支持实际不可变版本读；保留 expectation、receipt 和对象版本。

| 设置 | API | Worker |
|---|---|---|
| `ZEBRA_CLOUD_PLUGINS_ENABLED` | `true` | `true` |
| `ZEBRA_CLOUD_PLUGIN_BUNDLE_ROOT` | 可信只读包目录 | 不需要 |
| `ZEBRA_CLOUD_PLUGIN_ALLOWED_DIGESTS` | 逗号分隔的完整摘要 | 不需要 |
| `ZEBRA_CLOUD_EXTENSIONS_READ_ENABLED` | `true` | 沿用现有配置 |
| `ZEBRA_CLOUD_EXTENSIONS_MANAGE_ENABLED` | `true` | 不授予 Worker 管理权 |
| `ZEBRA_CLOUD_EXTENSION_TURN_ADMISSION_ENABLED` | `true` | 沿用现有配置 |
| `ZEBRA_CLOUD_EXTENSION_WORKER_ENABLED` | 沿用现有配置 | `true` |
| `ZEBRA_CLOUD_SKILL_WORKER_ENABLED` | 沿用现有配置 | 有 Skill 时 `true` |
| `ZEBRA_CLOUD_MCP_WORKER_ENABLED` | 有 MCP 时 `true` | 有 MCP 时 `true` |

Skill 发布另用现有 `ZEBRA_CLOUD_SKILLS_PUBLISH_ENABLED`。MCP Worker 仍需要现有
`ZEBRA_MCP_SECRET_ROOT/KEY_HANDLE/KEY_VERSION` 只读密钥挂载；Plugin 不导入凭据。
自动凭据管理、catalog refresh 是已有独立开关，不由 Plugin 隐式打开。
Skill-only 包不需要 MCP 密钥。API/Worker 使用同一 deployment namespace 和对象存储。

`docker/compose.application.yml` 使用显式 environment 映射。
仅在 `.env` 增加新变量不会自动传入容器，部署时须显式映射到对应服务。
例如在既有部署上添加独立 overlay，而不是修改全局代理或业务产品：

```yaml
services:
  zebra-api:
    environment:
      ZEBRA_CLOUD_PLUGINS_ENABLED: "true"
      ZEBRA_CLOUD_PLUGIN_BUNDLE_ROOT: /run/zebra/plugins
      ZEBRA_CLOUD_PLUGIN_ALLOWED_DIGESTS: ${ZEBRA_CLOUD_PLUGIN_ALLOWED_DIGESTS:?set approved digests}
      ZEBRA_CLOUD_EXTENSIONS_READ_ENABLED: "true"
      ZEBRA_CLOUD_EXTENSIONS_MANAGE_ENABLED: "true"
      ZEBRA_CLOUD_EXTENSION_TURN_ADMISSION_ENABLED: "true"
    volumes:
      - ${ZEBRA_PLUGIN_OPERATOR_ROOT:?set trusted absolute directory}:/run/zebra/plugins:ro
  zebra-worker:
    environment:
      ZEBRA_CLOUD_PLUGINS_ENABLED: "true"
      ZEBRA_CLOUD_EXTENSION_WORKER_ENABLED: "true"
```

上例仅补 Plugin 必需设置。按实际组件补齐上表 Skill/MCP 既有开关和只读密钥挂载；
不要为未选组件扩大权限。先用 `docker compose ... config` 验证最终配置，不输出含密钥配置。
此文档没有对正常服务执行 overlay。

迁移105仅扩展两张 extension 配置表的 kind 约束，不改历史迁移51。
正常激活前，用包含105的同一源码版本执行现有 `zebra-migrate`，再配对发布 API/Worker。
同时核对共库且执行精确 schema 校验的所有进程均兼容105，包括部署中的 legacy API；
旧进程仍在运行不代表迁移后能用旧镜像重启。
共享 Worker 有活动 Run 时不要替换；保持 Search/MCP 原进程及冷却状态。

**回滚约束：** 当前启动校验要求精确 migration 集，旧 v104 镜像不认识105，
不能在迁移后直接回退旧镜像。先关闭新 Plugin 选择，保留105兼容镜像、记录和对象；
对已有 Plugin Turn 明确等待或暂停。不要删除 migration 行、降级 schema 或删除包对象。

## 4. 管理 API

沿用已注册 Host 的新鲜签名 Grant、Origin/请求绑定及现有 HTTP 鉴权。
读需要 `extensions.read`，写需要 `extensions.manage`；API 从 Grant 获取完整
issuer/namespace/principal/workspace scope，部署 namespace 再做存储隔离。
客户端不能指定可信 scope、服务器路径、包元数据或凭据。

| 方法 | 路径 | 约束 |
|---|---|---|
| GET | `/v1/extensions/plugin-installations` | 有界 `limit/cursor` |
| GET | `/v1/extensions/plugin-installations/{id}` | 精确 scope |
| POST | `/v1/extensions/plugin-installations` | 唯一 `Idempotency-Key` |
| PATCH | `/v1/extensions/plugin-installations/{id}` | `If-Match: "<revision>"` |

安装请求示例：

```json
{
  "package_digest": "sha256:<完整审核摘要>",
  "bindings": [
    {"component_id": "guide", "kind": "skill-bundle", "installation_id": "existing-skill-installation"},
    {"component_id": "docs", "kind": "mcp-http", "connection_id": "existing-connection"}
  ]
}
```

POST 首次201、同键同意图重放200，返回默认 disabled 的 installation ID、revision 和 ETag。
同键不同意图409；重绑后旧创建请求重放仍核对原始意图并返回当前记录。
PATCH `{"enabled":true}` 显式启用；所有绑定在最终事务内再次校验。
禁用用 `{"enabled":false}`，不连带禁用共享底层组件。

重绑/升级须完整提交 `package_digest` 和全部 `bindings`，产生新 revision 且默认 disabled；
不能与 enabled 合并为一次 PATCH。每次使用最新 ETag；CAS 冲突409，不盲重试。
同值 enabled 不生成空 revision。缺 If-Match 为428、非法请求422、超预算413、
不可见/关闭能力404、权限拒绝403、后端不可用503。对外不暴露对象收据或密钥。

## 5. 执行选择与恢复

在已有 command 的 `payload` 中添加：

```json
{
  "extension_selection": {
    "plugins": [{"installation_id": "<安装返回的installation_id>", "revision": 2}],
    "skills": [],
    "mcp": []
  }
}
```

`skills` 是直接 Skill installation ID，`mcp` 是直接 connection ID。
省略 selection 保留原先直接组件选择行为；显式 `{}` 表示不选任何扩展。
Plugin 只能缩小已有 Task ceiling：Skill 须在 `skill_components` 内且工具 profile
允许 `skills.read`；MCP 须满足执行能力、工具/网络上限及现有审批。
安装启用本身不能让一个 Task 获得原本没有的能力。

accepted command、固定 Turn snapshot 和 revision 复核在同一事务提交。
同一 Turn 继续/恢复始终使用原 snapshot；改变选择须新 Turn，不能恢复时找 latest。
快照仅保存有界引用与来源，不放正文、密钥或完整工具大包；旧空字段不改变旧 digest。

每次组件使用仍做原生新鲜授权、租约/取消及 Plugin 有效来源检查。
Plugin 禁用或重绑后，单独依赖它的后续调用暂停；若这个 Turn 已独立准入相同底层
组件的直接来源，该来源仍按原权限生效。不得临时寻找其他未准入来源。
底层组件本身失效时独立来源也不能绕过原生授权。

必要来源缺包、对象校验不符、没有有效来源时保留结果并暂停，不换版本、不自动重调模型。
Plugin 关闭时已接受的 Plugin snapshot 不退回普通执行。
STOP/取消/租约失效优先；已发出的上游调用沿用现有取消与不确定副作用规则。
1MiB 输入限制、历史预算、验证范围与去重、Client Effect/continuation 边界保留。

## 6. 验收与交付状态

Tasks1–3 已完成包完整性、持久安装/管理、原子准入与 Worker 来源守卫。
独立规格/质量审查通过；具体检查与提交见实施方案及 WORKLOG。
Task4 源码 `9b6eca55` 的隔离原生验收通过，独立规格审查通过：

- 真实 PostgreSQL、版本化 MinIO；混合包含2个非空 Skill 文件。
- 删除可信目录后，独立 Python 进程只凭持久 Task 坐标恢复固定包及组件。
- 4组相同工作量，顺序为直接/Plugin、Plugin/直接，每组执行4次工具调用。
- MCP 审批前0请求；持久批准并恢复精确 continuation 后发出3个协议帧。
- scope、关闭开关、禁用、重绑、固定对象版本丢失且存在坏 latest 均被拒绝。
- 真实 PG 子任务创建/重放保持独立身份，Plugin/Skill/MCP 继承关闭；
  父任务允许/不允许搜索两种情况均检查只读、深度和搜索上限。
- 计数器自检观测到2次真实打开、2条SQL；无模型、provider、搜索或上游请求。

固定脚本样本的驱动计数与本机耗时如下（每格耗时为2个样本范围）：

| 阶段 | 直接路径 SQL/建连 | Plugin SQL/建连 | 直接耗时ms | Plugin耗时ms |
|---|---|---|---|---|
| 准入 | 20 / 9 | 29 / 12 | 120.4–127.0 | 232.8–259.8 |
| 恢复与 catalog | 10 / 6 | 17 / 8 | 71.1–88.9 | 213.8–284.7 |
| 4次工具与持久 HITL | 99 / 74 | 153 / 83 | 2134.3–3646.6 | 1947.8–1981.9 |

新增计数来自包来源和当前状态校验，按准入/组件使用发生，不按流文本帧发生。
工具段包含测试脚本的事件读写、原生授权和持久审批；连接统计反映该脚本的调用边界。
第一组直接路径是独立进程首组，后续组为同进程后续操作，不能把冷暖差异当成收益。
本次仅证明功能与有界成本，耗时波动不足以作提速结论。真实页面首正文、
生产连接复用和模型选择仍须在独立激活/模型门槛通过后测量。

专项检查78通过、2个可选PG测试未启用；真实PG子任务路径已由原生脚本执行。
全库文件大小、Ruff、1315个源码文件 Mypy 及两项 progress 检查通过。
完整 `make test`：9885通过、2951跳过、1项已有 eval 失败；外部集成开关未启用，
真实PG/MinIO证明由独立原生脚本完成。全库命令各运行一次，没有为基线失败扩大修复。
`make check` 的确定性 eval 为24/30：与实施前 `1d160735` 的30例逐例终态及指标
完全一致，保留这项已有门禁失败，未扩大到无关修复。

原生脚本只应指向显式准备的隔离 PostgreSQL/版本化 MinIO。
私有配置文件只在本机保存、权限0600，不记录凭据或响应密文。
配置字段为 `postgres_dsn`、`s3_endpoint`、`s3_access_key`、`s3_secret_key`、
`s3_bucket` 和 `owned_containers`；凭据不放命令行。已有依赖环境中运行：

```sh
export PYTHONPATH="$PWD:$(printf '%s:' "$PWD"/packages/*/src "$PWD"/apps/*/src)"
.venv/bin/python scripts/check_cloud_plugins.py --config /private/cloud-plugin-infra.json
```

脚本只创建/清理随机命名的测试 schema；报告写入
配置文件同目录的 `native-evidence.json`。不要将正常服务数据库作为验收库。
本次入口核验容器 `zebra-cloud-plugin-check-20261019`、
`zebra-cloud-plugin-objects-20261019` 的 `zebra.task=cloud-plugin` 标签；
复现前须准备这组隔离基础设施及对应配置，入口不创建或修改正常服务。
控制面/Worker 跨进程、实际 Skill 字节、真实对象版本读与受控 MCP 协议替身分别说明。
驱动 SQL 次数不冒充服务端触发器内部语句；短样本不冒充 P95。
相同工具脚本的耗时不代表真实高思考模型的首正文时间或质量提升。

以上源码交付阶段未迁移、重启或启用正常服务；第7节记录随后获授权的本地激活。
真实模型/页面验收须另获授权，
且应由模型自主选工具；不得为验收强制委派、选择 Exa 或制造限流。
首期包对象不接入普通 Session payload GC，自动回收另立任务。

最终独立质量与集成审查通过。仅本地集成 cloud-agent-trench，不推送或部署。
仅本任务两个隔离容器及其匿名卷已清理；正常API/Worker/Search的进程与环境哈希保持。
安全汇总归档于 `.artifacts/cloud-plugin/`，不含凭据；运行用的私有 `infra.json`
不纳入交付归档。

## 7. 本地正常服务试点（CLOUD-PLUGIN-LIVE-01）

2026-10-19 20:20 CST 已按用户授权应用 v105，并更新正常 API、legacy API、Worker。
操作前与关闭入口后均确认有效租约0、Worker所在 `zebra` namespace待执行命令0。
3个历史 `running` 投影最后变化在8月，无有效租约；未修改这些旧记录。
Cloud Worker仍不扫描ready投影，未改变namespace或唤醒其他部署的历史命令。

| 服务 | 当前镜像 | 验收 |
|---|---|---|
| API | `zebra-api:cloud-plugin-live-01` | healthy、真实授权管理接口通过 |
| legacy API | `zebra-api:cloud-plugin-legacy-live-01` | running、内部health通过 |
| Worker | `zebra-worker:cloud-plugin-live-01` | healthy、原生组件验收通过 |

三镜像均核对1315个Python源码文件与已验收的 `b1d082b3` 相同；复用原镜像依赖，
未安装新依赖。v105迁移校验全部历史checksum且仅增加plugin类型约束，迁移后精确
schema检查通过。原模型配置、v2、授权、资源、安全选项、网络、端口与挂载均实测
对比；仅允许的Plugin/Skill开关、三镜像和API一个只读可信包挂载发生变化。
共享内存显式保留8409579520字节；legacy空命令的null/空数组按等价形式比较。

试点包 `cloud-plugin-local-pilot@1.0.0` 仅有只读Skill，摘要为
`sha256:da4f262772d038851935a7304339ee9c9e2bca11cf228e7f1770fa26cce1f5fa`。
仅这个摘要获准发布；隔离principal `cloud-plugin-local-pilot-20261019` 与workspace
`workspace-cloud-plugin-local-pilot-20261019` 内有1个启用Plugin、1个启用Skill。
未向正常业务身份安装、默认选择或授予Plugin。共享服务开关全局启用，不是按身份的
feature gate；未来已授权Skill恢复仍受原Task ceiling、scope和固定快照约束。
启用前已有9个Skill/1个MCP配置、119个扩展快照，全部旧配置head/revision/hash保留。
Cloud MCP Worker、凭据自动管理与refresh继续关闭，不初始化任何新MCP连接。

真实无拦截验收：

- 正常API经现有broker密钥在原容器内签发新鲜RS256测试Grant；每请求使用新jti。
  测试身份和权限由操作者显式指定，未模拟Trench用户登录或修改其业务权限。
- Skill发布、安装、启用，Plugin安装、启用、GET均成功；跨principal/workspace返回
  404、缺权限403、无Grant401。旧组件未被重绑或启停。
- 只bootstrap一个 `executed:false` Task，不提交Run/message/resume/coverage命令。
  在正常Worker容器内使用生产composition与PG/S3，校验新鲜Task授权、显式selection、
  snapshot固定读写、Skill列表、216字节正文及非空引用标记；空选择不获得组件。
- 禁用Plugin后原固定snapshot恢复被拒绝；显式启用新revision后以新合成snapshot
  再次验证读取。末尾走现有Task直接取消，试点Task现为cancelled。
- 无model、tool执行事件增量；试点自身没有accepted执行命令。合成snapshot用于
  原生组件证明，不冒称accepted Turn、队列消费、页面或模型端到端验收。
- 原搜索容器 `320c9f820419` 的完整ID、StartedAt、进程PID、镜像、环境及冷却文件
  hash一致；未重启Search/TLS，未调用搜索、Exa或模型。Yahoo默认、fast及MCP内存
  会话所属原进程保留；本次不声称完成自然限流恢复验收。
- 两个原partial Turn的status、answer/request/metadata hash一致；末次有效租约及
  Worker待执行命令均为0。未改变原Run或Trench产品代码。

可选启动overlay为 `docker/compose.cloud-plugins.local.yml`，基础Compose仍默认关闭。
本机可信包、`pilot.env`、精确运行配置和证据位于主工作区
`.artifacts/cloud-plugin-live-01/`；勿删除该目录或替换readonly可信包。
`services-preserve.yml` 仅保留环境占位符，`configure.py`从0600的本机快照在内存中
填入实际值，并逐项检查原配置。基础四层为application、local-gvisor、
coverage-pro-test、web-search，随后是Plugin overlay和精确preserve overlay。
运行 `python .artifacts/cloud-plugin-live-01/configure.py` 只预检，不更新服务。
后续更新须再次核对空闲并复用该组合；不要单独用基础Compose覆盖现有配置。
一次性 `rollout.py` 和 `operator_probe.py` 保留取证，不应为验收再次运行。

安全报告为 `live-proof.safe.json`、`protection-proof.safe.json`、
`migration-live.safe.json`、`runtime-after.safe.json`、`pilot-events.safe.json`。
私有inspect、日志与resolved配置权限0600，不提交或发送。需撤回试点时先确认空闲，
使用同一105兼容镜像关闭新增开关；不要回退schema或启动104旧镜像。
本轮仅本地集成，无远程推送、远程部署或真实模型/页面验收。

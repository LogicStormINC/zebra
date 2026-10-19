# Cloud Plugin 使用与运维

2026-10-19。首期交付可信内部包的 Skill/MCP 组合；源码默认关闭。
源码、隔离原生验收、正常服务激活、真实模型验收是四个独立状态。
本地试点、真实模型与管理页面验收分别见第7至11节；普通 Run 接线见第12节。

## 1. 能力边界

Plugin 复用已有 Skill Publication、McpConnection、ExtensionSnapshot 和工具网关。
它记录包内容与组件来源，不产生新的执行权限。安装、启用、Task 授权、单次审批分别判断。

- 支持 Skill-only、HTTP MCP-only、Skill+MCP；一个包最多32个组件。
- Skill可从批准包一键发布安装；MCP只绑定当前scope已有、就绪且显式启用的连接。
  Plugin启停不扩大权限，也不反转独立共享组件的启停。
- MCP 首期只接受已就绪的 none/bearer 连接与固定非空 catalog。
- 不执行包内代码；不支持安装脚本、任意 stdio/hook、依赖安装或自动更新。
- 市场只列服务已批准包，不开放任意远程注册表、包URL或publisher自声明信任。
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

## 8. 历史失败样本（CLOUD-PLUGIN-E2E-01，原样保留）

用户随后授权一次真实Run，保留high与v2、自主工具选择，不新增搜索或重启服务。
2026-10-19首个样本 `e94e48bf-0c64-45ec-bc38-96803450a9e5` 已真实准入，
Run为 `plugin-e2e-c082f003-fbe9-4bd5-9590-2f40a4846e44`。当前状态failed，
不能算Plugin模型端到端通过：

- 固定Plugin revision4真实snapshot与accepted command的turn/digest一致；
  仅Plugin来源、无direct Skill或MCP，high和transient_v2实际准入通过。
- Worker在tool_gateway初始化时遇到只读根目录 `/workspaces`，抛出Errno30。
  这是验收脚本填写了与正常Worker挂载不符的路径，不是模型或Skill读取失败。
- 模型0次、工具0次；v2客户端2.4576秒收到RUN_ERROR，原失败Run保留。
- 已核对实际可写挂载，并在其隔离子目录
  `/tmp/zebra-trench-live-workspaces/cloud-plugin-e2e-01-isolated` 成功构造/关闭
  原生LocalToolGateway，未调用模型或搜索，未变更服务配置或源码。
- 原搜索容器/进程/冷却、旧安装与两个原partial Turn及模型/工具计数均未变。

用户随后明确允许新建一个替代Run；使用独立幂等键提交样本
`7eb86092-1110-4019-bff2-46a5b73e4529`，Run为
`plugin-e2e-5285de5e-c449-423a-bf10-8e70a5352c2e`。此样本也failed，未读到Skill正文：

| 记录 | 实测 |
|---|---|
| 模型 | DeepSeek Flash，1轮，high，thinking enabled，tool_choice auto |
| 模型事件往返 | 1.365307秒；provider latency1258ms，retry/repair均0 |
| 自主工具 | skills.list、files.list；2次started，0次completed |
| v2客户端 | 3.0009秒出现临时说明，4.3769秒收到RUN_ERROR |
| 最终结果 | 无answer_committed，无RUN_FINISHED，无最终答案耗时 |

原生只读quota检查定位为隔离子目录不是独立挂载点。现有10GiB配额保持开启：
原挂载 `/tmp/zebra-trench-live-workspaces` 的virtiofs容量10527662080字节，检查通过；
子目录返回 `workspace quota requires the workspace root to be a dedicated mount point`。
可写目录/网关构造检查不足以证明Cloud工具执行前置准备合规；首轮参数修正的预检
没有覆盖这一步，不应再用它宣称已准备好第三个模型样本。

源码还确认 `LocalToolGateway.execute` 仅对原生Web和artifacts.read跳过延迟runtime；
skills.list/read同样先调用ensure_ready，故控制面Skill目录读取也被沙箱quota阻断。
后续最小方案应区分无需沙箱的原生Skill读取与真实workspace工具：审计两项Skill
handler不依赖runtime后复用现有跳过机制，保留PG/S3/Plugin新鲜授权；files.list等
仍须使用合规隔离挂载，不能关闭quota、伪造完成或强制模型只选Skill来规避。
该失败阶段未更改生产源码、配置或挂载；后续实施和成功验收见第9节。

搜索工具/上游请求均0；Search完整身份、PID/环境/冷却、旧扩展head及两个原partial
Turn均未变，末次Worker有效租约/待执行命令0。该阶段两个失败Run均保留，没有第三个Run
或恢复命令。证据与单次锁位于 `.artifacts/cloud-plugin-e2e-01/`；替代样本在
`replacement/`，两份 `run_once.py` 均已消费，不可重跑。该阶段完整端到端门槛未通过，后续成功样本见第9节。

### 管理页面边界

当时没有Plugin管理页面；后续按用户授权新增的页面见第10节。后端 `/v1/extensions/plugin-installations` 已提供列表、
详情、安装、CAS启停/重绑；首期计划5.1明确先用HTTP/SDK，不先做Trench管理页面。
只读核对Trench的DashboardExtensionSettings仅接受mcp/skill，Zebra桌面与SDK也没有
Plugin页面/入口。本次未新增前端或修改Trench产品逻辑。

## 9. Skill 延迟沙箱与合规工作区（CLOUD-SKILL-RUNTIME-01，已验收）

2026-10-19按用户授权修复并接入本地正常Worker。`LocalToolGateway.execute`
复用现有Artifact跳过机制，仅增加精确的 `skills.list`、`skills.read`，不提前准备
OCI沙箱；这两项原生handler只依赖有界catalog。原PG/S3固定版本、Plugin授权、路径
校验和调用前后取消边界保留。`files.list`等工作区工具仍正常准备沙箱及检查配额。
新回归曾在旧代码上复现提前准备失败；78项定向测试、Ruff、Mypy1315个源文件和
文件大小检查通过。没有扩大到旧fixture或基线eval修复。

隔离目录 `/tmp/zebra-trench-live-workspaces/cloud-skill-runtime-01` 是原有受限
文件系统上的任务子目录，作为同路径嵌套bind挂入Worker，使其自身成为独立挂载点。
原生检查容量10527662080字节，低于10240MiB上限10737418240字节；
`require_workspace_quota=true`保持开启。容量上限由父文件系统共享，不是给子目录
独占预留10GiB。无模型阶段用真实PG/S3 Plugin和原生工具完成3次Skill调用、0次
沙箱准备，非法路径被拒绝；`files.list`准备1次真实gVisor，Worker和沙箱双向
文件标记检查通过。该组件检查不冒称canonical Run或页面验收。

在有效租约和待执行命令均为0后，仅更新正常Worker：

- 镜像 `zebra-worker:cloud-skill-runtime-01`，ID `sha256:b72e1210d7384952ff4e3a5dc74d00be4382db52e33f8535189ffdfe158e7a91`，仅覆盖已审核的harness文件。
- Worker完整ID `a43ec29a64b97970cb95b1f1574b5e08c911ad656bcd34ef8e5efd83b568932d`，healthy；环境变量值、命令、安全限制、资源、网络与原挂载逐项一致，仅增加上述子目录挂载。
- API、legacy API和Search的完整ID、启动时间、重启计数、环境一致；Search PID和冷却文件hash一致，原MCP会话所属进程保留。未重启Search/TLS。

一次真实Run使用正常签名HTTP准入、真实Worker/模型/Skill及v2 SSE，未拦截响应。
Task `eb4e2171-e798-46f8-80e0-e9d86aab8a5e`，Run
`plugin-e2e-c5713c15-7af8-44a1-a68f-7c54c8d397d8`。固定Plugin revision4的
snapshot与accepted command身份和digest一致，无direct Skill或MCP选择。

| 验收项 | 实测 |
|---|---|
| Run与结果 | 仅1个accepted Run；answer committed、Turn与Session completed、RUN_FINISHED success |
| 模型 | DeepSeek Flash，4轮，均high、thinking enabled、tool_choice auto；retry/repair均0 |
| 自主工具 | skills.list、files.list、skills.read正文、skills.read引用，共4次，均executed |
| 标记 | 实际读得 `CLOUD-PLUGIN-LOCAL-PILOT-V1`，引用路径 `references/marker.txt` |
| 临时说明首字 | 提交Run起3.1580秒；这是过程说明，不是最终答案正文 |
| 最终答案草稿首字 | 13.5771秒；实时v2临时草稿，尚未经最终提交 |
| 整轮至终态 | 17.3511秒；含bootstrap至终态18.3922秒 |
| 冷恢复 | 新鲜Grant、独立HTTP连接读取同Run，最终答案逐字一致，RUN_FINISHED success |

本轮模型自主选择了工作区枚举，因此canonical事件中有1次合法runtime_provisioned；
不能据此声称整轮无需沙箱，也不能把首批并发工具的3.2秒事件区间当成Skill独占耗时。
两次Skill正文读取的事件区间分别约318ms和301ms。成功样本与旧失败样本不能组成
性能提速对照。本轮证明功能修复、权限/配额保持和完整收尾，不声称已有配对降幅。

更新前后无模型事件增量；真实阶段总增量恰为4个模型请求/响应和4个工具start/complete，
与本Run事件逐项匹配，冷恢复没有再调用模型。搜索请求0，无新增MCP调用；旧12个
扩展head/revision/hash、两个原partial Turn的状态与正文/请求/元数据hash不变，
末次租约/待执行命令0。两个历史失败Run原样保留，没有retry/resume或状态修补。
未改Trench/Desktop产品逻辑。本次是真实Cloud Run验收，不是Trench页面验收。

本机后续重启/更新以主工作区 `.artifacts/cloud-skill-runtime-01/compose_local.py`
生成的最终 `services-preserve.yml` 为准，保留原完整配置及新增挂载；原第7节的
旧helper生成的是旧Worker配置，不能单独覆盖当前服务。运行
`python .artifacts/cloud-skill-runtime-01/compose_local.py` 只做预检。
`update_worker.py`已执行，仅作记录；`real-run/run_once.py`已消费单次锁，禁止重跑。
安全证据为 `native-proof.safe.json`、`worker-update.safe.json`、
`update-protection.safe.json`、`acceptance-proof.safe.json` 和
`real-run/canonical-proof.safe.json`。私有inspect、resolved配置和流日志权限0600。
本轮源修复和验收记录仅本地提交并集成cloud-agent-trench，没有远程推送或部署。

## 10. Trench 设置插件与批准包市场（CLOUD-PLUGIN-UI-01）

2026-10-19本地完成。最终入口是设置左侧“工具与连接”**下方的独立“插件”标签**，
其中有“插件市场”和“已安装”。原工具与连接页保持原有行为；临时账户菜单入口、
独立 `/dashboard/plugins` 路由和工具页内的插件标签已移除。沿用现有主题与登录。

市场通过Trench当前用户代理读取 `/v1/extensions/plugin-packages`。Zebra继续校验
新鲜 `extensions.read` 授权，每页最多10个已批准指纹对应的完整包，固定摘要游标。
复用发布器的hash校验，只返回指纹、插件ID、版本、发布者及组件ID/类型；不返回内部
路径、凭据或绑定，不发布S3对象。错误显示不可用，不以空列表掩盖失败。
这是当前服务批准包目录，不是任意外部注册表。没有新增迁移。

配置安装预填所选包与组件，仍需显式选择当前作用域已有、启用且匹配的Skill/MCP
绑定并提交。安装默认停用；启停保留revision CAS，写入保留幂等键，不自动重试。
候选类型独立加载；账号切换丢弃旧响应；初始列表结算后才显示预填表单，避免旧列表
覆盖新安装。页面不自动发布组件、创建权限或为Run选择插件。

实际登录页面读到 `cloud-plugin-local-pilot`（Local operator pilot，1.0.0，
Skill组件local-guide）；“配置安装”中的指纹与组件正确，当前用户已有Skill候选可读。
本用户已安装列表实际为0，没有为演示创建记录或提交安装/启停。页面未拦截响应；
实际变更操作的保护由定向回归及此前Plugin原生验收覆盖，不冒称本轮已做真人安装。

Zebra19项定向回归、Ruff、Mypy1315源文件通过；Trench20项代理回归、前端22项集中
回归及后续16项受影响回归（含新增竞态用例）、生产构建通过。有限审查问题已修复。
API和legacy API仅覆盖3个已验收源文件，环境、命令、挂载、安全/资源/网络保持一致：

- 正常API镜像 `zebra-api:cloud-plugin-market-01`，ID前缀 `cff0acd9f27d`。
- legacy镜像 `zebra-api:cloud-plugin-market-legacy-01`，ID前缀 `3399d7ddc46e`。
- Worker、Search、TLS完整身份/启动时间/重启数/环境不变；Search PID和冷却hash不变。

最终只读capture与任务初始完全相同：schema105、有效租约/待执行命令0，模型/工具
事件无增量，旧12个扩展head和两个原partial Turn状态及正文/请求/元数据hash不变。
没有模型、搜索或新增MCP调用，没有重启原搜索进程或改变其会话。

当前本机重启以主工作区 `.artifacts/cloud-plugin-ui-01/compose_market.py` 生成的
`services-preserve.yml` 为准。此helper复用第9节的Worker挂载并保留本节API镜像；
第7/9节旧helper不能单独覆盖当前服务。运行helper本身只做预检；
`update_market_api.py`已执行，仅作记录，不可重跑。真实页面截图为
`plugin-market-in-settings.png`，结果见 `page-proof.safe.json`、
`final-protection.safe.json`、`services-final.safe.json`，均位于同一任务artifact。
旧两版导航截图只作历史记录。私有inspect/resolved配置保持0600。
源代码和记录仅本地集成；未推送或远程部署。

## 11. 一键安装、逐行列表与真实启停（CLOUD-PLUGIN-UI-02）

2026-10-19按用户后续要求，市场和已安装均改为整行列表，左侧名称/发布者/版本、
右侧安装或启停，行间分隔。包指纹、安装编号、绑定ID及内部revision不在用户界面
展示。删除手动指纹和组件绑定表单。指纹仍在协议内部用于不可变校验。

市场安装只提交digest，复用既有POST和当前用户 `extensions.manage`。省略bindings
时由Cloud组合的组件安装器准备；原显式bindings API保持兼容。核心服务先检查原
创建记录，成功重放不会重复准备组件、反转启停或扩大请求意图。前端幂等键由所选
包确定，刷新和未确认响应后保持一致；单次写入有并发保护，不自动重试。

Skill来自已固定包对象的完整原始文件，通过确定性ZIP复用现有发布/安装/CAS启用；
复用已启用且版本精确匹配的安装，明确停用的既有配置不会被重新启用。自动安装
继续受Skill发布开关约束。包内MCP只描述逻辑connection_slot，不提供可猜测的默认
端点：本期槽位复用管理员在**相同作用域**预置连接的创建幂等键，经共享标识函数
定位并核对现有启用状态、授权就绪、配置revision和非空目录。缺失/撤销时失败关闭，
在写入Skill前报错，不要求用户手动绑ID、不猜选其他连接、不填凭据或访问远端。
需要第三方账号的连接仍须按既有授权流程先就绪；本期没有新增OAuth流程或自动授权。
最终所有组件仍经过原核心绑定校验和存储端原子检查，Plugin安装本身默认停用。

隔离普通产品账号/工作区通过实际登录页面验收，无响应拦截。一次市场点击得到一条
Plugin r1/disabled；点击启用得到r2/enabled；停用得到r3/disabled。每阶段冷刷新以及
清理测试市场入口后的刷新均保留相同安装与状态。真实PG核对Skill已发布ready，文件
清单逐项等于包内组件；MCP绑定精确等于隔离连接r2及其目录摘要，未绑到其他作用域。
MCP目录是明确标注的合成操作员测试数据，本轮不声称验证远端发现或工具执行。
隔离账号通过127.0.0.1独立Cookie登录，不退出或修改localhost的人类账号。

22项Python定向回归、Ruff、Mypy1316源文件、文件上限通过；前端14项定向及后续
9项受影响回归、类型/ESLint、最终生产构建通过。没有扩大无关测试修复。
API/legacy仅覆盖5个验收源文件，运行中hash逐项一致；Worker/Search/TLS不更新。
临时增加一个批准测试包供验收，完成后仅正常API恢复原批准目录并重建；legacy不再
重建，测试包不向正常用户展示。原批准试点包保留，新一键安装实现保留，隔离安装
最终停用r3，3条隔离配置保留用于追溯。最终环境变量值恢复原值，资源/安全/挂载/
网络保持，Worker/Search完整身份和Search PID/冷却hash未变。

保护capture证明模型/工具事件和snapshot无增量，原12个head及两个原partial Turn
的状态和正文/请求/元数据hash不变，仅新增隔离Skill/MCP/Plugin三个head，租约和
待执行命令0。无模型、搜索、远端MCP请求，也未重启原搜索/MCP进程。

当前重启helper为主工作区 `.artifacts/cloud-plugin-ui-02/compose_oneclick.py`，
默认保留原批准目录与新镜像 `zebra-api:cloud-plugin-oneclick-02` /
`zebra-api:cloud-plugin-oneclick-legacy-02`。执行helper只预检；此前章节helper会
覆盖为旧API镜像，不能单独更新当前服务。更新与清理脚本已消费，只作操作记录。
同目录 `installed.safe.json`、`enabled.safe.json`、`disabled-refreshed.safe.json`
核对精确绑定；`protection.safe.json`、`api-final.safe.json`、
`source-hashes.safe.json`证明保护和部署源；`plugin-market-final.png`是正常账号的
最终列表，`installed-disabled-final.png`是隔离账号收尾。私有凭据/inspect均0600。
仅本地提交集成，无推送或远程部署。


## 12. 普通 Run 插件接线与受保护运行时（CLOUD-PLUGIN-NORMAL-01）

普通 Host 在新 Turn 建任务前读取当前作用域的真实扩展目录。已启用且就绪的插件
作为可用能力提供给模型，插件 Skill 名称合入原有冻结 Task 上限；不依赖问题关键词。
独立 Skill 保留既有选择行为。外层 AG-UI `extensionSelection` 传递插件精确安装版本、
独立 Skill 安装ID与可用独立 MCP；API映射到核心 `extension_selection`，不塞入
官方 RunAgentInput。目录、分页、组件和工具总量均有界，失败不伪装为空目录。
每个目录GET（含分页）独立取得一次性Host Grant，复用HTTP连接而不复用已消费授权。

Plugin GET补齐Skill名称、版本、managed及ready/reason；Skill GET以同一归属校验
标记managed；MCP GET仅依据已缓存、校验过的目录返回selectable/tool_count，
不发现远端工具。Plugin目录404才兼容旧服务；其他错误失败关闭。显式空选择仍为
空，已接受的回执与恢复Turn继续使用原快照，不采纳后来目录或新增权限。

自动创建Skill记录不可清除的包来源；复用已有独立Skill仍为共享来源。旧一键安装
通过精确确定性创建ID和不可变r1记录识别，重绑后仍保留约束。新字段为空时不参与
序列化，旧快照摘要不变。归属在版本更新、重放、准入与Worker中保持；停用插件的
托管Skill不能绕入独立选择。关闭插件执行时仍保留只读归属检查，但不能恢复插件
执行。未知旧来源失败关闭；独立共享来源保留。不改旧Event、快照、原Run状态。

Skill/MCP就绪分别核对配置的Worker能力与当前组件版本、发布或固定目录。启用前
再次检查；不可用不宣称ready，不退化为半个插件。MCP总工具数按唯一连接计数，
与运行时相同。运行时继续执行每次新鲜授权、租约、取消、DNS/SSRF与凭据释放检查。
API配置表达部署意图，不冒充Worker心跳；本机激活另用实际Worker接线取证。

源码：Zebra367df88a；Trench eeb8e1f。239项Zebra定向回归、完整Mypy1317文件、
Ruff通过；Trench相邻回归106通过/13项既有PG环境用例跳过。保存的真实high/v2
快照摘要一致；不得将离线测试或目录加载当成新Run、模型决策或远端MCP执行验收。

本地激活与只读原生验收已通过。API42f5b9f793c4、legacy e6e1765a2714、
Worker909761e60366运行正常、重启数0；逐项核对运行中源文件hash与验收镜像一致。
实际认证HTTP读取证明普通Host在无关键词问题上仍选择就绪插件，停用托管Skill
被排除；真实API纯序列化保留选择，未提交命令。实际Worker解析旧快照摘要一致、
读取原Skill标记，并从保存的操作员MCP目录装配1个工具定义；未发远端帧。
关闭执行的只读guard仍阻断旧托管来源/插件恢复，保留独立Skill。操作证据位于主工作区
`.artifacts/cloud-plugin-normal-01/`。只允许更新API/legacy API/Worker，原Search、
TLS、Exa进程与MCP会话保持。初始与最终capture完全一致：15个扩展head、
两个原partial Turn状态/正文/请求/元数据hash、模型/工具计数、125个snapshot、
Search PID/冷却hash均未变，有效租约/待执行命令0。未新增Run、模型、搜索或
远端MCP请求；MCP目录装配不冒充真实远端业务执行验收。

当前准备的重启helper为该目录`compose_runtime.py`，执行只做配置预检。显式保留
原完整环境、命令、资源、安全、网络、日志轮转与挂载，增加只读MCP密钥卷；
API设置Skill/MCP Worker能力及现有凭据管理开关，Worker仅打开现有MCP能力，
保留refresh关闭。主密钥不进入仓库、环境值或日志，卷`zebra-mcp-plugin-normal-01`
持久保存；不能丢弃后生成替代密钥来读取已有密文。无现存密文时才首次生成。
`update_services.py`已消费，只作单次操作记录，禁止重跑；旧章节helper会回退镜像
与能力配置，不能单独覆盖当前版本。仅本地集成，不推送或远程部署。

## 13. 普通页面真实 Run 验收（CLOUD-PLUGIN-PAGE-01，2026-10-20）

仅普通页面发送一次，新会话`conv_1792425312607_dec09a`，Run
`b6fd3788-9a1f-4ec7-9123-6ba1025b353b`。账号原无插件，临时批准既有UI-02
测试包，同账号安装Skill并显式绑定其既有真实MCP fetch连接；页面启用后ready。
普通Host命令`skills=[]`、plugins revision2，经AG-UI和冻结快照固定1Plugin/
1Skill/1MCP，组件目标一致。实际Provider五轮均high、tool_choice=auto、retry0；
请求上下文有Skill及MCP工具计量，存储目录可装配fetch哈希别名，无远端帧。
Skill确实被模型读取；MCP未被调用，不能据此声称远端执行或会话恢复已验收。
主Run五轮模型、七次工具（skills.list1/read2、extensions.list2、files.list2）；
六成功、一项旧未挂载Skill的skill_not_found。页面发送至Host完成28.392秒，
Turn记录创建至完成28.034秒，Provider总等待14.423秒；状态completed，完整正文
1506字符同步，冷刷新保留。被动SSE正文不可读，不报告精确页面首正文；刷新网络
缓冲截断，不据此宣称零HTTP请求，刷新前后持久模型/工具/快照计数确实相同。
Host正常自动生成一次追问建议，单独计数，不混入五轮主Run。搜索和远端MCP调用0。
发现管理工具_record对MCP硬编码catalog_verified=false/刷新提示，agent因此误称
目录未经验证；另可列出未选入当前快照的旧Skill。均属清单表达边界，本轮不扩修。
验收后仅停用新Skill/Plugin并恢复API原白名单/镜像/全部环境。Worker/Search/TLS/
原MCP均未重启；原15heads、两个原partial Turn全部hash、Search PID/冷却不变，
仅新增2测试head/1快照，租约/待执行0。脚本和脱敏证据位于主工作区
`.artifacts/cloud-plugin-page-01/`，analyze.py可重跑只读核对；prepare/fixture是
已消费的操作记录，禁止重跑安装或发送。无生产源码变更、推送或远程部署。

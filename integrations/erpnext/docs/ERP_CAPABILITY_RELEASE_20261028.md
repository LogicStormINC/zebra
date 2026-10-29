> 当前状态（2026-10-29）：七类接线与无模型隔离验收完成，最终镜像已固定；
> 尚未切换生产。下文保留早期前置验收记录，末节为最新交付边界。

# ERP 全能力接入与通用 Cloud 运行时升级

目标是把资源面板的七项能力真正接入。以 cloud-agent 的固定提交为执行基础，
ERP 仅负责当前用户/公司授权、业务工具、同源 BFF 与页面；不再延长 Native105
独立补丁运行时。2026-10-28 用户批准先做备份、隔离迁移和兼容验收，线上暂不切换。

## 当前阶段结果

固定源 `8b4da99f85d656531575eca1980d5a0bfb9197d2`，来自已推送 cloud-agent。
全部104条现有迁移名称/校验和与主线至105相同。备份原库后，在完全隔离的
PostgreSQL17.5 克隆库应用106–114；目标151张表。138张原表按原列逐行哈希
一致，原迁移账本仅核对≤105的既有行；另验证目标完整账本与再次迁移幂等。

原有22个Task、全部Session与3791条事件通过新版本类型及每页≤1MiB读取。
对实际绑定检查132项身份/工作区/命名空间/过期拒绝；观察前后全库哈希一致。
API、Worker、Scheduler、MCP模块可在冻结的依赖镜像中导入；没有启动Worker。

真实回环HTTP/RS256/原生PostgreSQL检查共11项：拥有者header/usage/artifacts
以及Skill/MCP/定时任务列表均200；未签名401、跨工作区404、过期403、无扩展
权限403。使用临时QA签名密钥和文档定义的公钥解析Port，不使用线上私钥，
不替换或拦截API响应。此检查不等于线上JWKS/TLS/BFF/浏览器验收。

HTTP检查暴露历史用量投影缺口。仅在隔离库调用现有
`PostgresAgentTaskStore.backfill_read_summary`，每页256事件/1MiB，补齐22个Task。
仅task_read_summary_heads/frontiers变化，原Run/事件/租约等执行事实不变。
实际修复前409与全部失败日志均保留，未把409当作可用，未在GET中隐式修复。
维护脚本最初写错派生表名称，原结果及失败断言保留；依Native SQL核对后独立
闭合记录，未通过重复维护来制造通过。HTTP鉴权在隔离库仅修改重放/审计两表。

生产配置引用的沙箱镜像digest33735…在服务器上不存在。隔离候选使用已有真实
RepoDigest固定的Python3.12.12镜像，以gVisor冷启动435.6ms，通过UID65532、
零effective capabilities、只读根、none网络及临时scratch检查；容器已清理。
这不证明私人工作区硬配额、完整Native runtime或分析依赖已验收。

## 七项能力的完成条件

| 能力 | 必须补齐的实际接线 | 验收条件 |
|---|---|---|
| ERPNext业务 | 复用discover/read/propose和原生文档权限；将当前仅Production Plan的运行时边界明确迁至新版配置 | 只读与真实业务操作权限均生效；写操作仅准备独立用户审批；原收据去重与模块覆盖台账保留 |
| 文件与图片 | 原生附件/S3策略、私人workspace生命周期、真实配额及提取/多模态消息 | 用户/公司隔离；原字节与提取来源完整；拒绝超限/越权；不绕过quota，不把图片元数据当视觉输入 |
| 成果与用量 | 复用原生有界summary；公共Task成员范围内增加历史分段成果定位和下载 | 刷新/跨分段后原文件可读，逐次授权、大小/MIME校验、拒绝外Task Artifact；不开放任意Session代理 |
| 联网与分析 | 服务端固定profiles与当前授权；受控出口、DNS/SSRF/取消；隔离沙箱与分析依赖 | 用户只能选择已发布profile；旧Task不可扩大冻结权限；真实工具验收另行授权，不把endpoint存在当检索通过 |
| Skill与MCP | scoped管理RPC、发布/安装、revision CAS、显式extensionSelection、Root Task ceiling及Worker当前检查 | 同用户/公司授权；停用/撤销下一边界拒绝；凭据经原生Vault、目录与SSRF校验；写入仍需审批 |
| 知识资料与记忆 | 授权资料的真实读取/检索与出处；修复原生memory管理、手工创建和公司scope边界，开关同时约束注入和提取 | 跨用户/公司不能查到或注入；刷新编辑删除持久；不把普通文件名搜索宣传成语义RAG |
| 定时任务 | Native scheduler、原生schedule版本与firing去重、独立工作负载exchange、每次当前ERP权限复核和会话映射 | 普通Frappe scheduler不能代替；停止/撤权后不执行；lost ACK只查原收据；不自动批准业务写入 |

## 后续实施顺序

1. 先完成新运行时的S3/私人工作区配额与Fresh Host授权组合；固定镜像和依赖，
   不引入ERP专用状态机。现有ExecutionAuthority Ports与Host绑定是复用入口。
2. 复用当前公开Native API增加ERP固定RPC与选择器。Browser不能提交任意URL、
   用户/公司/工作区、tool/network/policy参数或服务端snapshot字段。
3. 配置冻结在Task上；新能力不能扩大旧Task ceiling。旧Run继续原身份观察，
   禁止在刷新、接入升级、统计修复时重建任务或调用模型。
4. 单独接入历史成果/知识memory/调度，各自完成授权、预算、去重和故障回归；
   未实现或未验收项如实显示，不把硬编码pending改成available来完成页面。
5. 用候选完整API/Worker/SDK/BFF做无模型验收，覆盖高思考/v2参数传递、长会话、
   审批、暂停/取消/晚到回执、字节预算与跨业务隔离。真实模型/搜索验收单独安排。
6. 服务切换前再冻结原库/镜像/配置与回滚点，复查原ready任务。不得启动通用扫描
   去消费历史工作，也不得为过部署门禁取消或重跑那条原Task。

## 操作与证据

受保护服务器目录：`/opt/erpnext/zebra-agent/capability-upgrade-20261028-1/`。
包含native105.dump、native114-isolated.dump、candidate.json、migration.json、
compatibility.json、http.json、sandbox.json、summary.json与失败尝试原记录。
数据库备份和身份/业务内容不入Git。内容脱敏摘要在本地ignored
`work/capability-upgrade-20261028/summary.json`。

脚本：deploy/prepare_capability_upgrade.py、check_capability_upgrade.py、
check_capability_compatibility.py、repair_capability_summaries.py、
check_capability_http.py与check_capability_sandbox.py。只允许固定回环克隆库名；
脚本拒绝覆盖旧证据，不继承生产env、密钥或挂载，不启动Worker/Scheduler。

线上数据库仍105；原API/Worker/ERP前后端/Search容器ID、image、StartedAt和
RestartCount未变。模型/搜索请求为0。临时QA容器清理后可从保存的QA114备份
恢复继续下一阶段。当前只完成存储/核心HTTP兼容前置，不是七项能力全部交付，
也不宣称生产HA/SLO、S3/配额或真实业务端到端已经通过。

## 2026-10-29 七项接线候选与真实验收

所有七类的服务端固定RPC、选择器和运行时接线已实现。通用改动已合入本地
cloud-agent89e4afed，包含并行AG-UI更新和v115；ERP适配独立保留，未切生产。

- ERP：新运行时发布通用discover/read/propose及现有原生动作。旧105会话保留
  原只读/Production Plan边界。真实克隆HTTP的ToDo/私有文件与Material Request
  create/submit/cancel/amend、审批去重和清理通过；不代表每个模块专用流程已验收。
- 输入：Cloud原先误用本地payload写接口，现为S3不可变对象+Task/message事务内
  原子元数据。真实PG/S3批次回滚、原字节读取、异会话拒绝和stale-CAS通过。
- 资源：历史分段索引与精确Task成员校验已接入；原22Task/3791事件有界读取通过。
- 联网/分析：固定business/research/analysis组合，不接受浏览器任意权限。独立
  256MiB ext4配额、Fresh Host proof、gVisor非root/caps0/断网CSV和ENOSPC通过。
  只证明Python标准库，不声称pandas/npm已安装。原搜索TLS叶证书Oct26过期；
  保留原进程，隔离TLS入口复用同一受控后端且证书验证通过。未发检索请求。
- Skill/MCP：真实zip发布、版本化S3、安装/启用/选择、AG-UI快照及Worker读取
  SKILL.md通过。MCP真实加密凭据/创建幂等通过；未调用example.invalid，真实
  外部MCP工具依赖用户配置的有效服务；网络/撤销/调用配对由无模型回归覆盖。
- 资料/记忆：私有File归服务身份，用户/公司作用域单独校验；选择快照共用附件
  预算，手工Native Memory按授权workspace管理。没有宣传语义RAG或自动记忆开关。
- 计划：Native持久计划创建/暂停/刷新、签名exchange两次同fire只一会话、错误
  签名和暂停拒绝通过；真实调度器只跑一次无到期周期，没有启动业务执行。

页面真实响应验收已确认Skill/资料选择和计划启用状态刷新保留，MCP未就绪项
不可选择；没有拦截响应。新Task保留Flash/high及v2，未调用模型/搜索。
候选最终镜像、v115后兼容与原会话BFF读取继续记录在同QA目录；生产激活仍需
用户对已完成隔离验收候选的最终许可。不能将这些门禁等同真实模型/检索SLA。

## 最终固定候选与切换边界

- Native源89e4afed；镜像sha256:9a09d2d50d5ae7f9fd0cb3167427fa25101b055f2e2c315d6ffe642d875526f2。
- ERP应用源91f1b19；镜像sha256:2d16a18f2af4ba76c5d3698db8c2330265b12eac8deffbffa5284e43aed53588。
- 新隔离库实际115；API/Worker/独立proof均固定候选镜像。后续提交仅补充
  验收脚本与记录，不改变上述镜像的应用字节。
- 原会话f1p4qpa1me通过实际BFF与页面恢复2消息/4表；保留原issuer、origin、
  Task绑定和独立旧版API路由。新模式明确固定自己的issuer/origin，不互相继承。
- 新会话73okscoa80已实际保存一条QA记忆，刷新后原文保留且页面无错误。
  未运行Worker导致Session观察版本落后时，隐私门会正确409；本次仅用原生
  投影服务及真实租约内恢复/释放该QA Session，未执行Run、未修改安全门。
- 原API、chat Worker、ERP backend、Search、Yahoo出口的ID/镜像/启动时间/
  重启计数均与before一致；SQL核对新命名空间模型/工具执行事件为0。

切换前当前生产Native105、ERP事务备份和服务/配置回滚清单独立保存在
`/opt/erpnext/zebra-agent/full-capability-release-ready-20261029-1/`。不得将
QA数据库、桶或测试用户/任务搬到生产。获准切换后，从当前生产备份另建目标
库迁移115，准备独立full namespace/API/Worker/配额/S3/调度与有效TLS搜索入口，
最后开放新会话；旧运行时和原Run继续原路径。不消费那条旧ready任务来做验收。

无模型门禁不证明真实Provider/搜索耗时、任意第三方MCP或全部ERP专用流程
已经通过端到端验收，也不代表HA/SLO已获得长期运行证据。当前MCP示例地址
故意未就绪，必须由用户配置真实服务后才能选择，不会伪装成可调用。


## 2026-10-29 已授权生产激活

用户明确批准切换后，从**当时生产备份**另建持久库并实际迁移115，未使用QA
数据库、桶、凭据或用户。新会话入口已开放；旧native105会话继续原绑定和路径。

- 独立服务：erpnext-full API、Worker、Scheduler、PostgreSQL、Redis AOF、版本化
  MinIO及内部TLS，数据位于/data/erpnext-agent-full。原Native API/chat Worker、
  Search/Yahoo/MCP的容器ID、镜像、StartedAt、重启计数与部署前一致。
- Native API仍固定9a09d2d50d5a；真实Worker需要Docker CLI，采用仓库已有Worker
  依赖分层，从原固定工具镜像复制CLI，派生a8f0e494c3aa。应用字节仍89e4afed。
  ERP backend/frontend固定2d16a18f2af4；实际HTTP提供的JS SHA256仍72ccc80a…09dbb。
- 生产专用root配额服务持久systemd启用；新运行时另有启动编排，等待私有挂载/
  socket就绪再核对Compose，避免Docker先自动启动Worker造成挂载竞态（未重启服务器）。
  每工作区256MiB独立ext4，逐次Host
  身份、原生事实和文件系统校验保留。proof请求的16KiB上限保留，校验只传
  当前内部TLS叶证书；API/Worker仍使用完整系统信任根，不关闭TLS验证。
- 实际生产新建标记canary：固定analysis/Flash/high，真实私有知识File、S3输入、
  Skill/MCP目录、Native计划创建/暂停、v2命令准入均通过。Worker内复用实际
  编排、当前Host proof、真实租约与持久授权，gVisor内非root/断网/硬配额执行
  得到sum=6，随后销毁沙箱。未启动Agent模型执行。
- Native记忆保存后重新读取、附件列表、历史分段索引、原会话f1p4qpa1me恢复
  两条消息均通过。canary在常驻Worker启动前通过已准入STOP的真实控制路径
  取消；确认full无ready/running、无active计划后才启动Worker/Scheduler。
- 最后打开acceptance_passed。普通chat.create确实选择cloud114、high且没有Task；
  当期SQL核对full命名空间model_/tool_执行事件为0。八项新服务运行、重启0。
  生产实际配置中Host/Agent/Search三路TLS1.3均校验通过，没有发送搜索查询。
- 测试记忆撤回、知识条目墓碑化、未来暂停计划删除，两个标记会话隐藏；保留
  Native审计和原始附件，不将canary变成用户偏好。没有修改原Run或业务记录。

部署问题保留原失败证据：Compose误尝试拉取本地image ID，现固定--pull never；
重放原部署须带/opt/erpnext/.env，否则前端误用8080端口。恢复原18090绑定后
成功启动，配置检查纳入操作记录。首次沙箱probe遗漏持久Attempt授权，被原生
安全门拒绝；补齐真实Worker持久授权和新鲜Host检查后成功，未放宽任何安全门。

受保护生产证据/配置/新鲜备份目录：
/opt/erpnext/zebra-agent/full-runtime-20261029-1；脚本在同级
activation-tools-20261029-1。数据库、密钥及业务内容不入Git。
回退先关闭新会话acceptance_passed，保留已有full会话的API/Worker和数据库；
不能把它们的Task绑定改回105。原镜像、site配置、override和事务备份均保留。

可控生产浏览器仍在登录页，**本轮未完成登录后的生产页面点击验收**；已完成
实际BFF、数据库、S3、运行时和静态资源HTTP检查。零模型/搜索门禁不等于
真实模型/检索SLA、任意外部MCP或全部ERP模块专用流程验收；没有声称生产HA
已通过长期故障演练。当前以单机持久化、租约/权限隔离和自动进程恢复提供基础。

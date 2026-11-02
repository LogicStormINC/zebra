# 首次回复根因：ERP 与 Trench 对照及通用 Cloud 方案

日期：2026-11-03（上海时区）。本轮只读调查，没有新增模型/搜索请求、原 Run 重跑、配置/数据库/服务变更。
代码基线：cloud-agent0b92baf2。下列为同机真实历史样本及源码证据，不是同题配对、浏览器首字或生产SLO。

## 结论

ERP 的主要额外启动等待在模型之前：强制解析工作区触发两个独立冷校验进程，
即使最终只使用远端 ERP 工具，也要先等待这条路径。上一轮 lazy import 只缩短了每次冷启动的一部分，
没有去掉前置资源依赖或重复创建校验进程，因此不能称为首次回复根治。

另一个已确认缺口是工具清单发布：应用层新schema已部署，但新Task仍复用profile revision1的
旧冻结清单，模型实际没有得到该修复。参数错误又增加取证/恢复往返。

最新ERP样本并未完成回答；Native随后因execution_authority_unavailable暂停。
不能把没有完整结果统一解释成模型思考慢。该次授权异常的底层HTTP/传输/解析原因尚未证实。

## 实测对照

ERP会话5uktl70svi，Task4de5e78e-783e-444e-8c46-0fa53afd1f68，
创建2026-11-02 17:58:08.288565 UTC，使用本轮已更新服务。
Trench取最近已执行样本Task d268ce53-7c1b-4027-b36f-2fcaf4606bac，
创建2026-11-02 15:19:59.208263 UTC。均schema117、deepseek-flash、高思考；题目/工具与服务镜像不同。

| 后端指标，从Task创建计时 | ERP | Trench |
| --- | ---: | ---: |
| 原RUN命令接受 |0.575s|0.458s|
| 首轮model_request_started事件 |13.078s|6.453s|
| 首轮Provider报告耗时 |2.321s|1.202s|
| 首条公开commentary事件 |15.625s|7.904s|
| 额外逐次Host authority probe |启用|未启用该额外机制|
| 自定义每工作区物理卷operator钩子 |full_worker:compose|default工厂，没有ERP钩子|

Trench仍有签名Grant、scope/namespace、Host工具授权；额外probe未启用不代表没有授权。
两者都启用gVisor、require_workspace_quota、defer_provision与独立执行器工厂。
不能为追齐数值关闭ERP的当前身份、配额、租约或取消检查。

ERP operator真实阶段日志（同一请求窗口）：

| 阶段 | 耗时 |
| --- | ---: |
| 第一独立fresh_proof |2594.4ms|
| fallocate |3.5ms|
| mkfs.ext4 |13.6ms|
| mount |10.8ms|
| 初次blkid/findmnt/losetup/blkid合计 |8.5ms|
| 第二独立fresh_proof |2669.9ms|

两个proof合计5.264s，是本样本ERP相对Trench6.625s差距中可直接计量的大头。
不是格式化256MiB慢。其余前置等待包含执行器冷导入、恢复/上下文/新鲜校验；
现有日志不足以把剩余全部精确归因。第一proof开始约Task+6.004s，不能把这一段全部归为Python导入。

这是两个逐次独立proof，不是误报为一次缓存命中。各proof含隔离进程启动、Python导入、
只读Native事实读取、当前Host身份检查及前后事实复核。上一轮导入基准的60%不是完整proof或整轮提速。

## 源码链路

1. execution_recovery.py:252-257在进入模型前直接apply_workspace_resolver。
2. workspace_runtime_resolver.py:37-50按prepare_volume→provision_existing→verify_volume串行执行。
3. ERP full_worker.compose给prepare与verify分别接入PrivateWorkspaceClient.require。
4. operator.ensure对两种请求均调用NativeProof；NativeProof每次docker run独立helper。
5. full_workspace_proof中每次新建只读DB及httpx client，并执行当前HostAuthorityProbe和前后事实复核。
6. execution_runtime.can_defer_runtime延迟的是执行沙箱provision，工作区解析已在此前发生。
   所以defer_provision=true不能取消以上物理卷/校验等待。

独立执行器及subreaper都已有轻量脚本启动入口，实际ERP/Trench镜像均使用。
没有证据支持再修一次“监督进程双重完整模块导入”，也不应关闭进程隔离换速度。

## 清单修复为何未到达模型

实际ERP应用gateway.py含read_operations=CHAT_READS if readonly_chat else READS，且没有源码挂载覆盖。
Caddy /manifest仍正常转发到该函数，不是静态Caddy清单。
但是apps/api/host_manifest_freeze.py:61-74按Host/connector/profile_revision读取原冻结记录，存在即返回；
host_manifest_revisions的主键也绑定profile_revision。Worker按Task冻结digest加载，行为符合历史一致性。

最近Task的冻结erpnext.read仍为：

```json
{"arguments":{"type":"object"},"operation":{"type":"string","enum":["aggregate","download_file","export","files","get","print","query","query_page","report","report_describe","workflow_transitions"]}}
```

修复前aea4fc91与修复后4de5e78e的model_response_received均记录：
- tool_schema_bytes=28984
- tool_schema_hash=7893d0fe1938fc15ea4c94b2322b9009ce2ff01a22e54e1831516af320a75c8b

实际第四次工具调用仍发送aggregate而非metric字段，Host返回417。
这是发布/准入契约没有贯通；不能靠继续追加提示词解决，也不能只用应用函数单测声称模型已获得新清单。

## 最新失败与可见性边界

- 共记录2次模型响应、4次工具调用；首轮公开内容只有commentary，不是答案。
- 第4次工具调用ERP read aggregate参数错误，23.744s得到417。
- 第3次model_request_started事件后，25.135s暂停execution_authority_unavailable。
- 该异常统一隐藏了细分原因；没有access日志能进一步证明是超时、HTTP错误还是响应校验。
  不能将该事件数当作3次已成功发出的Provider HTTP请求。
- ERP持久会话行仍running，但实际api.snapshot返回suspended/paused、1条用户消息且无可用动作。
  Native权威状态已经暂停；没有完成答案。未取得实际浏览器DOM，不能断言页面具体spinner表现。

## 根本方案与实施顺序

### P0：先让已修复的契约真正生效，并补齐暂停诊断

- 走受控版本化发布：发现/校验新清单→发布→新Task冻结→Worker模型工具组装→Provider序列化。
- 验收比较erpnext.read的标准化parameters指纹，不能直接把整体manifest digest等同全部模型schema hash。
- 保留旧Task/旧Run的冻结清单和原回执，禁止清表、覆盖旧记录或静默改旧绑定。
- 现有profile revision既影响清单又参与Host当前授权一致性判断。直接全局切到rev2可能使旧Task续接被拒绝。
  先用隔离数据验证新旧Task共存；若当前管理流程不能共存，则复用已有manifest digest/freeze，
  增加独立的受控清单发布选择，不改变原transport/credential/authority revision，也不放宽撤销校验。
  是否需要新增迁移由该兼容验证决定，不能直接改账本或绕过冻结保护。
- 模型参数校验复用已有类型合同；完整补齐nested required/额外字段的前置校验与有界结构化错误，
  避免把metric缺失变成远端417后再让模型猜原因。是否已有足够的递归校验器，实施前先复用审计。
- 对authority依赖失败记录阶段、异常类型、安全HTTP状态、耗时及安全request ID，禁止记录token/正文。
  401/403真实拒绝与超时/502/503/协议错误分开；保留失败关闭，不擅自自动重试或新开模型。
- 暂停状态及安全原因/下一步由权威snapshot恢复，不能只依赖ERP本地running标记。

### P1：通用Cloud按资源需要延迟准备，而不是只延迟沙箱

- 复用DeferredRuntime及已有Tool execution_location/能力声明；模型自由选择工具，不按关键词分类。
- 把逻辑workspace身份、授权与物理文件系统准备解耦。Host/Client远端工具、无需本地文件的问答
  不应先创建私有文件系统。新鲜Host授权、scope、租约、取消始终保留。
- 首次本地文件/命令/真实需文件的Skill操作才触发物理卷、配额、身份和执行器检查；不因read风险标签就跳过文件要求。
- Context编译可先提供有界授权快照/引用；只有需要物理文件的上下文再物化。不能制造假的ready handle或卷路径。
- 同次解析prepare已返回签名receipt时，用该次receipt完成本地mount/容量/UUID校验，评审是否可合并冗余verify RPC。
  不跨请求/租约fence复用，不用receipt代替执行边界的新鲜Host授权；状态变更/TOCTOU负例必须验证。
- 所有改动归入通用Cloud接口和组合，ERP/Trench只声明资源需求并调用，不各造一套快路径。

P1直接移出Host-only启动路径的双proof成本约5.3s（本样本），但不是对整体回复的实测承诺。

### P2：文件类场景仍慢时，再消除重复冷控制进程

- 现有隔离proof改成受控、低权限、只读、网络受限的常驻校验服务；复用导入、DB/HTTP连接，
  不缓存正向授权判断。每请求重新读取Native事实和Host身份，检查nonce/时间/fence/绑定。
- Root allocator仍独立拥有格式化/挂载，Worker不获得root、任意路径/命令或写数据库权限。
- 硬并发/请求上限、取消、进程退出、错误隔离、重启后的失效与回收必须是同一个合同。
- 模型执行器冷准备若仍占主导，才增加少量“从未接触任务数据”的预热执行器。
  保持一任务一PID树、subreaper/exit receipt/租约撤销/强停；执行过业务的进程不回池。
  不复用旧用户进程，不在多线程/已连DB的Worker里随意fork。

P2不是第一步就新建大进程池。先用P1证明剩余成本和收益，再决定是否增加常驻组件。

### P3：分层验收，防止再次只验局部

无模型先做：同入口隔离数据库、fake Provider、真实控制/Quota路径；两业务共享合同。
覆盖Host-only零物理准备、首次文件恰好一次、并发/过期/撤销/取消/强停、未知不重发、旧Run续接、
发布新Schema真正进入序列化工具、417本地结构化拒绝、依赖不可用正确暂停与刷新恢复。

以后另经用户授权做真实模型对照：固定模型/高思考/v2，同题冷/热新会话与实际业务题，
分别记录点击→accepted→实际Provider HTTP→公开commentary→首正文→终态/DOM，工具/轮数/SQL独立统计。
小样本只报告观测；足够样本后才认证p50/p95。

目标（非已实现SLA）：Host-only accepted→实际Provider HTTP优先降到2–4s，
暖态进一步以≤2s为验收目标；完整答案另加模型高思考与必要工具时间，不能承诺所有问题3秒完成。

## 交付边界

本轮只产出根因与方案。没有改生产配置、发布清单、修改应用代码、迁移或部署；
没有新增模型/搜索请求，没有重跑这次暂停的Run，未动Search/MCP或其它正在验收的HA资源。

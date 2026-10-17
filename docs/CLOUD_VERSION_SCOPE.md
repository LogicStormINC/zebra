# 版本范围完成契约

CLOUD-VERSION-SCOPE-01；不新增模型、搜索、提示词、工具或引擎路由。

## 契约与保证边界

TaskAcceptanceContract.version_scopes 保存请求的产品/版本字面量。仅对需要证据的
任务从明确的英文产品token+空白+版本中保守提取（最多12个）；不把8自动解释为
8.0或8.x。紧连的编码/数字、复杂名称/范围不做语义推测，可用Host显式
versionScopes数组覆盖；空数组显式关闭。无版本任务及普通回复保持原行为。

交付assessment增加 version_scope：requested_scope、checked_scope、
unresolved_points。checked_scope 的 basis 明确是 cited_fetched_source_version_only，
只证明引用的实际抓取来源的版本范围，不证明所有陈述正确；
semantic_coverage_certified 固定false。

来源必须是成功web.fetch、确实被最终答案引用、URL路径版本与回执前4096字符中
对应产品/版本字面量一致；URL或标题单独出现、搜索摘要、失败/未引用/未知布局
不算核对依据。各来源/版本集合有界，保留原始工具/模型响应及出处。

请求8而来源只支持8.0（或8.0+8.8）时，报告请求范围未建立，不能认证为完整。
这是范围未决，既不要求穷举所有小版本，也不自动指定必须检查8.8/Array。
具体版本完全对应时只标matched，仍不认证语义完整性。

## 执行与发布

保留正常最终答案，不触发额外模型修订、自动搜索或暂停；执行可以结束，但交付
status必须partial、unmet包含version_scope_unresolved，移除笼统
task_acceptance_contract满足标记。保留其余真实成果与原文。

普通正文追加确定性的范围说明；JSON/代码块及严格长度不允许追加时只提供结构化
assessment，避免破坏格式。模型原始响应事件不变；接受的ANSWER_COMMITTED正文
包含允许的范围说明。Provider reasoning/模型调用ID保留，不公开私有推理。

严格ANSWER_COMMITTED事件契约新增有界可选version_scope；旧事件仍有效；
禁止complete与partial范围并存，状态必须与checked/unresolved对应。
API与Worker共享新增事件契约；v2 wire保留assessment与精确正文，不改Trench产品逻辑或SDK，不改数据库schema。

## 无模型验收

64项聚焦回归（新增范围、质量门、事件契约、真实Harness模拟调用链）通过，
严格mypy/Ruff通过。Harness模拟证明一次既有fetch+最终答复后直接部分交付，
不增加第三轮模型，不强迫工具。

保存D/E真实快照与公开模型答案复核：PG18来源对应18；D Redis仅对应8.0/8.8，
E仅8.0；两者请求仍是8，均保守标partial，分别列明范围。原始证据与模型答案
不变；新提交事件完整schema往返通过。新Worker镜像断网重复快照验收后，才做
本地Worker更新与唯一原题页面F。高思考/v2/Yahoo默认/Exa fast与冷却回退保留，
遇限流停止、不替换样本；结果另记。

## 原题页面 F 与兼容修复

本地已启用精确四文件Worker衍生镜像及API的共享事件契约/wire衍生镜像。
Search容器ID、启动时间、镜像、环境和持久冷却内容保持不变；API/Worker环境
与安全选项保持，服务健康。仅本地集成cloud-agent-trench，不推送或远端部署。

唯一F会话为conv_1792261003864_219971，原Run共10轮模型、17次工具
（3search/9fetch/5artifacts.read）；全部high/thinking/auto、transient_v2，
无Provider错误/重试或限流。模型调用区间合计45.436秒，末轮14.905秒。
这些是该样本观测，不能证明性能提升。

提交事件正确列出请求PostgreSQL18/Redis8、已核对来源18/8.0、Redis8范围未决，
交付partial；页面最终显示版本范围说明。原文仍未核对8.8/Array；本契约阻止
局部覆盖被认证完整，不替代缺失的事实核对，不认证语义正确性。

首次页面验收发现两个兼容问题：旧API严格事件契约拒绝新增字段；更新共享契约后，
保存的raw/accepted帧又在真实未修改消费端复现stream_replacement_gap：相同前缀
被去重而新增后缀失去replacement起点。公共提交wire增加一个有界空replacement帧，
再发送原封不动的权威正文；保留原调用/事件配对、游标顺序与授权，不改消费端。
实际消费端对保存帧的无模型往返已通过，页面随后恢复原Run且仍为10轮模型。

恢复过程包含API更新与只读页面重载，原浏览器有界计时也被重复回放覆盖，故F的
正常首正文/整轮页面延迟均不作为有效配对数据。不替换失败样本、不追加模型/搜索。
共享SQL窗口包含背景及恢复流量，不声称单Run查询数或SQL降幅。

64项core聚焦回归与9项API wire回归通过（共73项；兼容阶段16项中包含重复的7项
scope测试）；Ruff和四个core文件strict mypy通过。保存帧实际消费端校验、镜像断网
检查、部署源码摘要/健康/环境与Search进程及冷却核验通过。证据保存在私有
.artifacts/cloud-version-scope-01/，包含page/summary.json、final-page.png及final-seal.log。
下一轮若评估性能，应另行取得干净页面样本；本轮不追加验收请求。

# 同快照上下文去重

任务 CLOUD-SNAPSHOT-CONTEXT-01；只改模型请求临时消息，不修改原始 Artifact、事件或工具执行。

## 最小实现

复用 HarnessModelStep 已有 compact_repeated_records 入口，增加同快照区间处理。
只接受已执行 Tool 消息、内部 metadata 与观察 JSON 一致的规范 artifact://UUID、
有效半开 Unicode 字符区间和已知无歧义文本布局。比较同 URI/总长度/重叠原文，
不比较不同来源的语义。首次 fetch/read 的可见原文作为锚点；后续 read 仅替换
逐字符相同的重复区间，新增部分完整保留。引用仅指向当前请求仍保留原文的工具
回执，禁止引用链；跨用户轮次清空，每次模型请求重新计算，不依赖全局缓存。

原 metadata/消息对象/调用 ID/assistant tool_calls/Provider reasoning 不变。
临时观察 coverage.included_ranges 只描述本次内联原文，referenced_ranges 指向
之前工具调用；receipt_coverage 保留原工具回执区间。候选词警告、literal_match、
candidate_only、next_cursor、总长度等保留；引用不把候选变事实。

校验失败、相同 URI 长度/原文改变、布局未知时保留原观察；不压缩跨快照内容。
只有新观察更短才替换；缓存最多1MiB原文/每URI512区间，超过上限不扩大缓存。
没有新SQL/模型/搜索/依赖/提示词/引擎路由，逐请求授权/DNS/SSRF/取消保持。

## 无模型验证

9项定向回归通过；严格mypy/Ruff通过。两轮保存回执经原 session-authorized/digest
reader读取后，在断网新Worker镜像内重建临时消息，检查每个引用均有保留原文、
区间/字符一致、原消息未改、Provider工具调用配对完整、重复运行稳定。

| 保存样本 | 工具观察字符原值 | 去重后 | 净减少 |
|---|---:|---:|---:|
| C（17工具） |88,779|83,177|5,602（6.31%）|
| D（24工具） |167,328|155,663|11,665（6.97%）|

分别7个read观察被压缩，原文引用区间8,774/15,363字符；净收益已扣除引用和
coverage说明开销。这是工具观察字符收益，不是总输入tokens或页面提速证明。
真实页面验收按同原题、高思考/Flash/research/v2、Yahoo默认/Exa fast可选、
自主工具/引擎进行一次E对照历史D；遇限流停止、不替换样本。结果待记录。


## 本地接入与原题页面 E

完整31项定向回归（新增安全、既有记录去重、Harness模型步、上下文窗口、并发
工具上下文）通过；Ruff/strict mypy通过。新镜像断网快照检查和正常Worker部署后
无模型检查均与保存D一致（167,328→155,663）。初次镜像构建把本地image ID当成
远端镜像名而失败，服务未改；改为校验ID后的本地标签再构建成功。只覆盖2个
core源文件，从原Worker精确镜像派生；有效环境/挂载/命令/安全参数均核对保留，
无活动lease后更新；Search/API未重启且身份/镜像/环境不变，服务全部健康。

| 指标 | 历史 D | 本轮 E |
|---|---:|---:|
| 首答案正文 React commit（排除进度） |101.860s|72.808s|
| 整轮页面结束 |102.134s|73.713s|
| 模型响应轮数 |9|6|
| 工具调用 |24|18|
| search / fetch / artifacts.read |5 / 12 / 7|3 / 10 / 5|
| 最后一轮输入 tokens |56,711|45,795|
| 最后一轮模型请求区间 |43.248s|27.427s|
| 最后一轮推理 tokens |7,301|2,459|

E实际保存回执复核：18回执中2个read被压缩；引用2,381个原文字符，扣除说明后
模型观察131,784→130,534，净减少1,250字符（0.95%）。每个引用均指向保留原文，
范围/原消息/配对检查通过。这是该请求临时工具观察的确定性收益。

页面首正文-28.52%、整轮-27.83%，但不是可归因的稳定提速：两轮自主取证不同，
本轮Redis答案仅覆盖8.0，未像D核对8.8 Array，因此同等覆盖性能验收未通过。
Array文字实际出现在未被压缩的数据类型总览fetch回执中，不能说被去重删除；
也不能排除上下文表达对模型选择的影响。保留该质量边界，不补跑有利样本，
不以减少取证/降低高思考/强制工具引擎换取验收数字。

6模型均high/thinking enabled/tool_choice auto，实际transient_v2；18工具成功，
0provider重试/限流/ExaRPC/子任务/沙箱事件。Yahoo唯一默认、Exa fast可选、
持久冷却文件字节保留。逐请求授权/DNS/SSRF/取消和Trench产品逻辑未改。

SQL仅共享统计窗口：E100.936s顶层55,647/嵌套8,454，D117.271s顶层69,940/
嵌套11,271。背景工作/观察查询混入且窗口不同，不能称为会话SQL数或降幅。
本次去重不新增SQL；没有修改生产监控、重置统计或运行额外模型/搜索探针。

E会话conv_1792259635071_742955；root65a07545-df2a-4956-8c31-9b2e6698090a。
证据 .artifacts/cloud-snapshot-context-01/{regression.log,snapshot-check.json,
image-snapshot-check.log,final-seal.log,after.json,page/summary.json,
page/browser-timing.json,page/snapshot-check.json,page/final-page.png}。
临时浏览器计时器已清除；本地提交/集成，不推送或远端部署。

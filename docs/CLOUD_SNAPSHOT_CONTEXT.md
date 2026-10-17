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

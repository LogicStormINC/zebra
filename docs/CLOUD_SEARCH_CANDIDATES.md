# 同次搜索响应的有界候选 Artifact

CLOUD-SEARCH-CANDIDATES-01。保留已有响应中的有效候选，不增加搜索探针、查询扩展、
抓取、重排、强制读取或引擎选择，不修改Trench产品逻辑。

## 边界与数据流

LocalWebSearchTransport的公共normalizer继续执行原URL规范化/静态安全校验、
标题/摘要截断及URL去重，按原排名保留最多20条、内容合计最多20,000字符。
这些限制以内处理完该次响应才称为有界候选集；超过限制明确candidates_truncated，
不声称上游全部召回。请求的limit仍是正文最多5条，不修改请求参数/工具定义。
原HTTP响应、headers、Cookie等不存入候选Artifact，只保存已规范化的标题/URL/摘要。
实际打开任何候选仍须经过原逐请求授权、DNS/SSRF和取消链路。

WebSearchResponse携带原inline结果及可选候选集，验证数量、字符预算、唯一性及
相同前缀。WebSearchTool正文仍是原前5条；有额外候选时传给既有工具输出投影器，
写入同一个tool-output Artifact（不是额外副本或新工具）。total_count表示有界保留
数量而非搜索引擎总量；result_count表示正文数量，has_more仅表示Artifact里有额外候选。
内部传递字段在投影前移除，不进入持久工具metadata或模型上下文。

复用ToolOutputProjector.small_output，只在它是完整快照的真前缀时允许选择前缀预览。
短预览保持原文，较长预览只在前缀内部做原有预算截断，不能把第6条之后的尾部塞回
正文；总长度、SHA、included_ranges指向完整候选Artifact中的准确区间。未展示内容
通过既有Complete output URI读取；现有会话权限隔离、字面查询及不可信内容标签保留。
没有投影器时不泄露内部完整候选字段，也不声称额外候选已保存。

Gateway原有投影逻辑移入既有runtime/tool_output_projection模块，保留入口与命令/
测试/外部Artifact行为，使harness保持500行以内。无新依赖/数据库schema/安全绕过。

## 已有响应的无模型价值门

使用之前保存的Yahoo Redis响应：原7条中，第7条为
https://download.redis.io/redis-stable/00-RELEASENOTES ，摘要明确含8.10及相比8.8的变化。
该线索不在前5条正文；新候选Artifact可用artifacts.read定位8.8，且正文顺序/内容
不变、跨会话读取失败、上游请求0。它证明多保留的候选具有版本范围线索，不能把
搜索摘要当已核实事实、不能证明Array已取证，也不能声称恢复了G当时未保存的尾部。
其他旧响应也离线验证，失败引擎不作为成功样本，不重试任何失败组合。

仅在确定性安全回归与镜像断网复核通过后允许一次原题页面H，保留高思考/v2、
Yahoo默认/Exa fast/冷却回退，由agent自主决定工具；遇限流立即停止、不替换样本。
历史G为65.835s首正文、66.426s整轮、8轮模型/19工具；单次历史比较不证明稳定因果收益。

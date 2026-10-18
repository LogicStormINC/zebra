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


## 唯一原题H页面验收

会话conv_1792301593520_6f67d7，root0fb571da-4bf5-46af-b50c-764a9dbb3176。

| 指标 | 历史G | H |
|---|---:|---:|
| 首正文React提交（排除进度） |65.835s|71.561s|
| 整轮页面完成 |66.426s|73.611s|
| 模型轮数 |8|10|
| 工具数 |19|20|
| search/fetch/artifacts.read |4/9/6|4/9/7|

保留high/thinking/auto/transient_v2，全部20工具成功，无Provider重试/错误/限流，
无强选Exa/委派。4次搜索各展示5条并保留7条，运行后只读读取原Artifact核对成立；
agent自主读取搜索候选Artifact次数为0。本次Redis额外候选没有8.8线索，不得把
旧Yahoo响应rank7的线索冒充本次响应或事实核对。答案仍锚定8.0，明确说明未逐一
核对后续增量，最终版本范围契约保持partial。候选不再本地丢失得到验证，实际8.8
召回/减少搜索/减少模型/页面性能收益未得到验证。

H首正文比G+8.70%、整轮+10.82%；工具/来源/模型选择不同，不能归因于存储改动，
更不能声称提速。没有可归因单会话SQL统计，不报告SQL降幅。只跑一个H、不替换
样本，不添加补充搜索探针或模型回放。临时浏览器计时器已移除，最终截图已保存。

92项聚焦检查（28候选/投影/快照、9既有网关、55取消）通过；Ruff/strict5文件mypy
通过。旧响应Artifact权限/准确区间/单次transport调用与镜像断网检查通过；镜像
只复制5个相关源码文件，Worker本地更新，API与Search进程/环境/冷却保持。
页面结束后的镜像整理仅移除源码EOF多余空行，不改功能，不增加模型或搜索验收。
私有证据 .artifacts/cloud-search-candidates-01/，page/summary.json与
page/candidate-observations.json区分旧响应价值与本次实际使用情况。

最终本地集成：cloud-agent-trench已快进到f450665c，包含前序version-state源码/报告；
其原合并已由所属任务结束，本任务未中止或覆盖。用户暂存/未暂存补丁逐字节保持。
最终服务健康，Worker五文件摘要匹配；API/Search容器ID/启动/镜像/重启次数/环境及
持久冷却内容与本任务前一致。仅本地提交/集成与服务更新，没有推送或远端部署。

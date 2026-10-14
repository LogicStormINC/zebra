# CLOUD-STREAM-SDK-PERF-01

2026-10-15。通用Cloud Agent Worker/relay/TypeScript/React链路；不修改Trench。

## 审计边界与根因

Worker TextDeltaCoalescer已有首帧立即发出、后续按字符/100ms合并的实现。Redis临时流通知和v2 Reader保持独立canonical recovery/authority；SDK不会等Run终态才observe draft，React直接显示明确Draft标签。没有证据支持盲目降低轮询间隔、跳过授权或整体取消合并。

确认两项累计客户端成本：ConversationStreamReducer.put每次追加都重新UTF-8编码旧prefix与新全文；32KB增量累计编码1MB。React消息行对未变历史内容每次重新渲染；40live更新下每条历史内容41次render。已审计AgentChat和Timeline调用点：消息列表内部缓存历史行，Timeline直接调用的函数/生命周期保持原样。标签对象可每次新建，list row比较标签值而不是只看标签对象引用。

## 实现

- client-core复用TextEncoder，按消息缓存UTF-8字节数，只编码新delta；正确处理跨帧UTF-16 surrogate pair，reset/remove/generation replacement/full canonical replacement更新缓存。保留1Mi字符/8MiB/500message/offset/chunk/replay限制与canonical authority。
- React用native memo缓存列表内部的row，保持原可调用export function与直接Timeline调用行为；比较message/render callback/contentRenderer引用及标签值。消息变化、标签变化、renderer变化继续更新；历史message引用稳定时不重绘媒体/图表等既有内容。
- v2有SSE时不重复执行恢复前pending-effects读取；复用既有恢复完成边界的awaited poll。遗留/v2无SSE轮询仍按原启动顺序执行。
- 新增独立stream-latency example：built npm exports→真实ZebraClientRuntime SSE parser→ConversationStreamReducer→AgentMessageList。录制40delta后人工点击Commit final，验证首字、Draft标签、最终替换与历史render。无backend/模型/Trench依赖。
- 修正一个已在未改动主工作区复现的旧测试期望：private v2 callback必须被抑制，不能进入durable delta。仅test修正，不改Worker安全行为。

## 已完成验证

- 两个负对照旧实现失败：SDK编码工作随prefix增长、React历史重复render；新实现通过。
- SDK录制512frame/131072中文字符，六交替pairs：reduce均值257.137ms→10.756ms（-95.8%）；首帧两版均亚毫秒，没有首字大幅改善承诺。不是模型请求或SQL性能对比。
- 40live updates历史内容每条41→1render（-97.6%），新标签与commit替换仍正确。框架要求消息/callback/renderer按React惯例保持稳定引用，变化时正常render。
- Worker/Transient/v2 API的35聚焦检查GO。client-core29回归，包括字节上限、surrogate/reset/generation、恢复ACK/权限失败GO；完整SDK初轮83tests GO，strictcheck与五包build GO。
- 浏览器独立built exports：first observation6.80ms，firstbody DOM7.50ms，最终commit前有Draft标签；40frame下三历史row累计只3renders；commit同ID替换并清Draft。仅合成已生成正文流的客户端耗时，不是end-to-end TTFT。

## 包验证与工作区

五包：contracts/ui-contracts/client-core/react/react-charts。contracts与charts无已证明的延迟，不做无关修改，但包含build/exports/consumer/browser验证。没有发布npm或推送。

clean worktree旧package-audit遗漏npm自动包含的React README，因此verify在pack阶段失败；主工作区已有对应一行allowlist修正（以及其他未提交UI改动），不重复实现或纳入本切片commit。当前SDK变更将本地集成后，使用主工作区现有审计/消费者脚本做最终五包验证。用户既有React/charts/timeline/contracts改动保持原样。

无全量Python测试或Cloud部署/模型验收声明；这轮生产更改仅npm包的两处共用实现，无Cloud API/Worker行为改变。详细证据.artifacts/stream-sdk-perf-20261015/，最终包gate待完成。

## 启动读取与组件兼容收敛

v2启动负对照旧请求顺序effects→stream→effects，新stream→effects，读次数2→1。100ms合成读取延迟下三组配对首正文观察224.517/203.506/202.497ms→104.667/101.960/101.949ms；这是单次重复Host读取的消除，不冒称真实模型TTFT或PG SQL降幅。

消息列表缓存只包裹内部row；直接AgentMessageItem仍为原函数，避免改变用户现有Timeline的新折叠生命周期。主工作区新增、尚未提交的Timeline测试需要等待原生toggle事件后再触发terminal；本次只补该测试的事件等待，未改其UI实现或其他用户改动，这一测试小修仍留在既有未提交UI修改中。孤立目标测试/同上下文原版本对照与完整包测试的结果分别留存，不掩盖早期失败。

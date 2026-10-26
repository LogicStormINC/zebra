# CA-P3-03C 原消息 Event/Segment 坐标

## 问题与版本

原消息追加已获得实际持久Event，但Task响应会将session_id重写成Task ID；原收据仅有序号无法定位实际Segment。当前header可能已被其他follow-up推进，不能回填原归属。

原POST /tasks/{task}/messages与GET /tasks/{task}/messages/receipt支持显式头 X-Zebra-Task-Message-Receipt-Version:2。缺省/1保持v1默认形状。未知版本400，不执行写入。V2 POST要求原Idempotency-Key去空白后1–128个ASCII33–126字符；原key/action/request_hash和幂等规则不变，不换key重发。

仅显式v2的Task追加调用向Session适配传入include_message_coordinates=True。保存实际event后，原响应body包含message_coordinates={event_id,segment_id,segment_sequence}，取自event.event_id/session_id/sequence。Task包装只改公开Task身份，保留坐标并作为原幂等response保存。无Event payload、表或迁移变化。默认Session与Task调用不增加字段。

V2 GET返回contract_version=2，原request_hash、response.status_code/body原样保留；另有coordinates_status与message_coordinates。完整的canonical UUID、非bool非负int序号及与原body.sequence/current_sequence一致时为recorded；字段不存在为not_recorded；部分/畸形/不一致为invalid且顶层坐标为null。缺失原记录沿用not_observed/noncommit_proved=false。GET1不增加新顶层字段。

## 兼容、权限和未知

旧幂等记录不回填；同key从v1改请求v2只重放原body，不再次追加。V2 GET仍报告not_recorded，不能以当前header或历史扫描补坐标。原响应失败不改成成功；原部分提交未留收据仍unknown。旧API若忽略新版本头，可能返回v1/无坐标，消费者必须拒绝进入恢复后续、保留unknown，不按未提交处理。正式启用前确认API副本均支持合同，不声称混合旧实例滚动发布已验。

当前Host/Task/principal/namespace权限、409投影、503故障和公共GET的grant/2秒预算沿用B。坐标只证明原Event归属，不是权限/当前Run/Worker/UI/取消或非提交证明。新Run/UUID不赋予相同业务效果新执行授权。凭据仍留BFF。

## DDD与并发边界

源Event由核心追加服务持久化；HTTP适配按opt-in翻译已知源坐标，不引入领域聚合、泛化Operation或新的基础设施依赖。合同校验复用专用task_message_contract.py，Task/Session两层都不会重新查询active Segment来生成原坐标。

原GET索引点查、独立副本读取，不写入/修补/扫描。验证先完成本地适配器启动，再比较SQL行/schema快照。真实PG验证namespace、独立进程及原行不变。

当前header与原Segment相等只是一瞬间的观察，不是原子mount/RUN CAS；同Segment序号变大也不能证明还是原Turn。生产BFF后续必须先审计/补齐服务器提交时的原消息锚点条件，再接持久日志和SDK恢复。本片没有提前实现该条件、持久BFF或SDK接线。

## 验收与后续

12项新用例先在旧代码上失败；修复后31项API定向包含v1与原Task回归。覆盖源Event精确定位、同Segment执行推进、后继Segment、legacy重放不回填、非法版本/键在写前拒绝，以及UUID/布尔序号/负序号/不一致拒绝。真实PG与两仓全量门禁/SDK结果见[证据](evidence/ca-p3-03c/validation.json)。

OD-P3-01AB-A固定发布源码做公开v2丢回复/双BFF原GET/中文hash/源坐标/观察比较与实际Worker联合；同源v1/不同目标/旧消费者另验。没有真实产品IdP/模型/生产HA、外部取消或第三方消息与mount间原子竞争通过声明。

原数据、事件、收据、Coverage和mock不变；无部署/生产迁移/main合并/npm。

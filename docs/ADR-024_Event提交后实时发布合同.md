# ADR-024：Event 提交后实时发布合同

状态：Accepted（`CLOUD-LIVE-WIRE-CON-01`）

## 决策

Session Event 仍由 SQLite/PostgreSQL append-only store 作为唯一事实源。实时
发布是提交成功后的 best-effort 传输，不得成为第二套状态源：

1. 先完成 canonical Event 的 durable append/commit；append 抛错时绝不 publish。
2. 只有 append 返回的 canonical Event 才允许交给 publisher；幂等重试返回同一
   Event 时可以再次 publish，consumer 必须按 `event_id`/durable sequence 去重。
3. publisher 失败不回滚已经提交的 Event，也不把 API/Worker 的业务操作改成失败；
   客户端通过 durable replay 收敛，失败应由 adapter 的 metrics/logging 观测。
4. SSE/Redis 使用 replay barrier：先 capture live cursor，再从 durable store 回放；
   live tail 仅接收 barrier 之后且 `sequence > durable_sequence` 的事件。Redis
   丢失或截断时必须重新 durable replay，不能声称“无事件”。

`PostCommitPublishingEventStore` 实现上述 direct `EventStorePort.append` 边界。
它不捕获 `BaseException`，也不吞掉 durable append 错误。

## PostgreSQL 事务边界

PostgreSQL 的 `append_event_in_transaction(...)`、Workspace/Context/Handoff/Effect
等 aggregate transaction 直接使用同一 connection。它们不能在事务尚未 commit
时向 Redis 发布，否则 rollback 后会出现幽灵 live event。本 ADR 只冻结提交后
发布语义；`CLOUD-LIVE-PUBLISH-01` 必须在共享 transaction/outbox composition
上接入 commit-success hook，并覆盖这些 transaction seam。仅给某个 API caller
补 publish 不满足合同。

## 降级与验证

本地默认不启用 live publisher，仍走原有 SQLite。启用 live 时，发布重复是允许
的，顺序和事实以 durable Event stream 为准。Focused contract tests prove：

- durable append 失败不会 publish；
- publisher 失败不会隐藏已提交 Event；
- publisher 收到 append 返回的 canonical Event；
- idempotent retry 可重复 publish 且由 consumer 去重。

## 独立临时文本合同（2026-10-12，CLOUD-STREAM-CONTRACT-01）

本补充冻结 v2 typed contract，不启用任何 Writer/API/Redis/SDK composition。
上述 canonical Event commit-before-publish 规则原样保留。临时帧是未提交展示，
不是 Event；不进入 Event Store，不分配 event_id/sequence，不推进 expected_revision，
不能更新 Task/Session/Workspace/progress 或覆盖预算、PUBLIC_OUTPUT 与证据。
完整 MODEL_RESPONSE_RECEIVED、ANSWER_COMMITTED、工具/Effect、usage 和 coverage
原文仍按原事务提交。无 Redis 历史也必须从这些事实恢复，不重新执行已提交调用。

### 实现合同与公开资格

- `domain/transient_output.py`：`TransientGeneration`、`TransientTextFrame` 和
  `transient_category_allowed`；`domain/stream_admission.py`：`StreamCapabilities`、
  `RunStreamAdmission`、`StreamMode`；`ports/transient_output.py`：独立
  `TransientOutputPort`。均属于 agent-core，不修改 `LiveEventFanoutPort`。
- 唯一临时类别是 `ordinary_public_text` 的 MODEL_RESPONSE_DELTA。分类缺省拒绝；
  用户明确允许普通候选正文作为临时草稿展示；candidate/tool_loop 普通公开正文
  或未知最终阶段的 typed public callback 可分流。private reasoning、coverage、
  public_expression、语义 PUBLIC_OUTPUT、新事件仍拒绝；不改变最终发布门禁。
- 分类函数只限制类别，不授予权限。`TransientWriterAuthorization.gate_context_ref`
  是可信 composition 在实际调用通过既有公开门禁后发出的短期进程内 handle；
  adapter activation 必须解析并核对 exact scope/Attempt/model call/full LeaseFence。不存在新的
  durable gate receipt 表；不增加逐帧 SQL。客户端/模型自报 bool、类别、handle
  或构造 Python 对象均不构成可信证据。WRITER 必须接入真实门禁，否则保持 legacy。
  当前 model_step 的 delta 先于完成阶段，orchestrator/sequential_loop 最后标记
  candidate/tool_loop。后继卡必须在 call admission 由可信 output policy 限定
  普通非coverage调用的 typed on_text_delta；不是从缺省 stage 推断已授权。
  本卡只冻结已授权草稿语义，wiring仍 dormant，不证明实际流路径或 SQL 降幅。
- Wire 是 flat compact UTF-8 JSON：version=2/kind=text_delta，Task、Segment(Session)、
  Turn、Run、Attempt、model call、message、generation、lease_fence、offset、
  content_delta、durable_anchor、presentation=provisional_draft。完整 JSON 计入 16KiB；
  未知字段拒绝；
  数值不接受 bool/字符串强转；UUID 复用 core IDs，message_id 沿用已有
  message:{model_call_id} bounded string（强制对应同一 model call）。内容保留空白/emoji。
  Writer 必须按完整 envelope 预算合法分块，不能只检查正文长度。
- namespace/authority issuer/session allowlist 仅由服务器绑定；帧没有 namespace。
  durable_anchor 只是定位关联事实；offset 从零按帧递增。不同 generation 不拼接。
  相同 generation/offset 的相同内容幂等；不同内容是完整性错误。Redis ID、
  durable sequence、AG-UI durable frame_index、live offset 四者独立。

### Admission、观察与替换

Run admission 持久冻结 mode、能力与 Writer 后续容量策略，不能在重连时变更。
无字段、local、配置关闭、旧能力均 legacy；具备 wire v2 + replace_message +
reset_provisional + scoped_resume + provisional_draft_label，还必须服务器显式启用 v2。
客户端 query 不是执行模式权威。已有 v2 Run 回滚也保留 v2-compatible reader。
不兼容观察者不能续读 v2 live，可升级或只读取不含临时正文的 durable snapshot。

`TransientResumeCursor` 是内部已解码位置，不是直接可相信的 wire token。
API 必须复用认证 opaque cursor 机制绑定 namespace/issuer/session/Task/Run/generation，
并再次校验 fresh read Grant；scope 相等本身不授权。跨 scope 拒绝；generation 变化、
裁剪、Redis 丢失、offset 缺口都明确 resync：清 provisional，补读已提交完整消息。
先 live barrier 再 bounded durable replay，再 tail；接缝提交必须补读或被 live 捕获。
canonical hint 与 checkpoint-ready hint 是独立水位，通知不能证明投影已完成。

完整 durable 消息以同一逻辑 message ID **替换** provisional，不追加整段造成双倍；
内容不一致时完整消息胜出。MODEL_RESPONSE_RECEIVED 仅替换已持久完整正文；
草稿标签直到 ANSWER_COMMITTED 原门禁通过才移除，不能标记最终成功。
AG-UI start/content/end 顺序仍合法；观察问题与 resync
不能伪造 Task FAILED。帧 batch 最多 100 条且累计 UTF-8 frame bytes <=256KiB；
resync batch 不携带旧 provisional。慢读/正文缺口断开续读，不能静默删中间文本。

### 有界授权与分布式撤销

Server-only authorization 复用完整 LeaseFence(control_plane_epoch/fencing_token/
owner_instance_id)，fencing_token 必须等于 wire generation.lease_fence；不只比较整数。
gate handle绑定fullFence；ensure_frame对照current fullFence，adapter append原子核验。
Wire不暴露epoch/owner，复用可信服务器原lease，不新增逐帧SQL。
Writer 资格最多 30 秒且 expires_at <= min(lease deadline, Grant deadline)；
后续配置可收紧。已校验调用发资格，按时间/调用边界续租，不按帧数量重跑 aggregate。
activate fresh-check 原执行授权并注册 generation/fence；publish 必须在 Redis 原子
追加/容量/期限操作里核验当前 active generation/fence 和 offset，不能只调用 Python
ensure_frame。旧/已撤销 fence 不可重新激活；Attempt/模型重试使用新 generation。
持续保留撤销高水位，直到 durable authority 足以拒绝旧 Worker，不能 TTL 后复活。
read 不续 retention；block_ms 必须被当前 Grant 剩余期限截断，并在实际交付前再校验。

PG 与 Redis 不提供共同原子事务。STOP accepted 仅命令 durable accepted。
STOP completed 需要 durable cancellation 边界和 generation 已失效/观察已关闭，
不能在 Redis invalidation 未确认时声称展示已安全停止。Redis 不可用时停止临时交付，
按 durable facts 收敛；不能继续使用未经确认的 authority cache。Grant 到期立即禁止
交付，重新连接重新授权，不能用 cursor/缓存延长 Grant。撤销在短资格窗口内存在
传播时延；若要求立即零延迟，必须逐批 fresh 验证或可靠撤销屏障再做 native 压测。
本合同不虚构 SQL 与 Redis 跨库原子性，不替代原工具/Host I/O/最终提交 fence。

### 可靠性与验收边界

持久执行事实/已提交结果 RPO=0（原存储合同）；保留窗口内临时流可续读。
未完成尾部允许因 kill/Redis 丢失而显式清除，新 Attempt 不与旧文本合并；
不承诺逐 token 永久保存或断点续生成，不因丢临时文本释放预算/重做 Effect。

确定性检查见 `tests/agent_core/test_transient_output_contract.py`，包括 UTF-8/escaping
总预算、未知字段、privacy 分类、能力缺省/部分能力、Grant/lease deadline、scope/
generation 与独立 positions。它们仅证明合同值对象，不证明 adapter 事务、真实门禁、
撤销屏障、SDK replace 或 SQL 降幅。WRITER/CLIENT/RELIABILITY native Gate 仍必需。

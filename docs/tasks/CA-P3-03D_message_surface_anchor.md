# CA-P3-03D 原消息条件挂载合同

## 状态与依赖

承接已发布CA-P3-03C（537bb57952c3d7c1d42da73362a72a44b2aa872f）。本片实现原生条件准入；消费者OD-P3-01AB-A2固定发布源联合验收另记。完整原消息业务BFF日志/SDK恢复仍为AB-B，不把测试私有bridge当作生产接入。验证记录见[evidence](evidence/ca-p3-03d/validation.json)。

## 公开请求

POST /v1/admission-operations/{operation}，沿既有HostGrant、Client Session、当前Task/Profile授权和密钥/摘要头。显式X-Zebra-Admission-Protocol: atomic-message-surface/1；只允许surface_mount。

```json
{
  "kind": "surface_mount",
  "task": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  "run": "new-run",
  "payload": {"mount": {}, "task_capability_scope": [], "controller": true},
  "original_message": {
    "receipt_key": "original-message-operation",
    "request_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "event_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    "segment_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
    "segment_sequence": 42
  }
}
```

示例mount仅标字段位置，实际仍必须通过既有ClientSurfaceRequest和权限校验。键为1..128 ASCII可打印非空白；hash为64位小写hex；Task/Event/Segment为规范小写UUID；sequence为非bool安全整数0..2^53-1。引用来自原v2保护收据，禁止用当前header推测。新protocol和original_message同时参与跨语言摘要；旧Admission DTO/默认hash/封存AAD不增加字段。

## 领域不变量与事务

- 精确原生PG Task/Event/Projection/Client Session/Controller/Capability/idempotency Ports必须同DSN/namespace；替代或混合Port在claim之前拒绝。
- 复用既有dispatch fence和2秒work-unit budget。先以namespace/Task成员约束锁原Segment stream，再锁既有Task advisory seed61，与append/Handoff顺序一致；无进程锁/全局锁/锁内外调。
- canonical Task仍active于原Segment且source-ready；stream tail必须精确等于原消息sequence，任何后续Event先提交就拒绝。
- 精确匹配原Task-message key/hash/201/appended/Task/v2 Event坐标及原响应sequence/current_sequence；再点查原USER_MESSAGE_RECEIVED、人类origin/user actor和content。不扫描历史、不重建或修补旧收据。
- 不得已存在同Task/Run binding；新协议同Task/Event仅消费一次。已有scoped KV action client-message-surface-v1-consumed，不新增表。
- 条件、Surface/Controller变化、消费记录和加密原结果同事务提交；任何异常/权限撤销/预算失败全部回滚。

条件失败不调用surface dispatcher；保存加密409原结果，status=message_anchor_conflict、稳定reason、retry_allowed=false、controller_reclaim_allowed=false、non_commit_proven=false。201结果回显original_message，消费者核对后才使用metadata。

## 恢复与证明边界

原GET /v1/admission-operations/{operation}继续只读原结果，使用原key/hash/current Host/Task授权；既有结果不是当前授权。unknown不重发、不换operation、不重领Controller。

GET/POST /v1/admission-operations/{operation}/message-surface-termination提供contract_version=6，复用同协议STOP/fence。pending仍unknown；terminated仅证明这个Surface原操作未提交；committed包括201成功或封存409拒绝，均不得发非提交证明。其他协议不能被这个入口升级。

原消息已经提交，STOP不能撤销消息；也不证明RUN、Worker、外部业务效果停止。挂载仅在线性化时绑定原消息；随后RUN继续独立使用原Segment/ExpectedRevision和当前权限。本片不把mount与RUN/Worker合并成一个事务，不授予相同业务效果跨Run重复执行权。旧协议继续兼容，因此一消息一消费仅约束新协议参与者，不能宣称混合legacy全局唯一。

## 验证和交付

- 新DTO/旧digest形状/严格输入/混合Ports定向测试；旧代码16红例。
- 真实隔离PostgreSQL：receipt/hash/Event/Segment/tail/active/namespace负例；原stream追加和Task切换竞争；消费唯一；Surface+result+consume回滚/STOP；旧协议与v2收据回归。原收据保持不变。
- 完整make test、make check及TypeScript SDK check/test独立记录；条件跳过不算真实PG证明。
- OD-P3-01AB-A2通过公开HTTPS固定源验证两副本丢回复原GET恢复、实际SDK/Worker和旧消费者，证据由平台仓库保存。

无数据库schema迁移、历史数据删除、Coverage机制修改、生产部署或main合并。生产HA、真实产品IdP/供应商账号及外部取消未验收。

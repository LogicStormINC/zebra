# CA-P3-03B Task-message 原收据查询

## 公开合同

版本 task-message-receipt/1。`GET /tasks/{task}/messages/receipt` 携带原 `Idempotency-Key` 头；按原 POST 规则去首尾空白后，查询支持1–128个可打印 ASCII 字符。未提供、超长或控制字符400。Task必须为合法UUID。查询不需要正文、不接受新的幂等键代替原键。

当前 Host/Task/principal/namespace 授权经过既有公共门禁；拒绝401/403/404、409 projection_not_ready以及依赖503保持原语义，不能变成查无记录。回收当前权限后历史收据不授予读取或执行权限。查询服务不是新的授权来源。

200 recorded：contract_version=1，task_id，request_hash，response={status_code,body}。response为原保存值，不重写状态或正文。外层200只表示成功读到原记录；内层失败必须按原失败处理，不能当成消息提交成功。

200 not_observed：contract_version=1，task_id，noncommit_proved=false。它不是未提交、原消息不存在、可以重试或取消成功的证明；在途、部分提交后未保存收据与未知结果都不得自动再POST或重新领取Controller。依赖异常503 unavailable且不泄露异常正文。

原存储 action 为 task-message:{task}，key是原POST去空白后的原值，namespace由部署存储隔离；不引入新的 scoped_idempotency_key，也不改历史记录。原请求摘要精确为SHA256(json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode("utf-8"))。消费者须使用保存的原正文验证摘要；Go/JS默认编码，特别中文/数值，不能当作相同算法。AA消费者只支持已验证role/content字符串子集；完整数值/附件编码是未来消费者责任，不修改旧摘要。

## 实现归属与故障

HTTP适配校验和翻译响应，现有 IdempotencyStorePort.get 提供原事实；不引入新的聚合/运行状态机。公共Task门禁继续拥有当前权限，Python独占Task/Segment/消息/收据，Go只消费公开合同，凭据留BFF。收据点查复用2秒Task I/O预算，精确复合索引，不扫描/持全局锁/外部网络调用；公共权限查询保留自身原有预算。

GET不调用append/rollover、投影补偿、调度或收据save。SQLite验证先完成本地适配器启动初始化，再快照全部表与schema，重复GET后原行/事件与schema的SQL快照不变（不声称数据库物理文件逐字节一致）；冷启动既有DDL与请求观察不混为一谈。真实PG验证独立进程重读/namespace隔离与原行不变。

本批不改变原POST的事务边界。消息追加、successor Segment与收据保存仍可能存在部分提交窗口；缺失原收据只能unknown。原recorded收据也是历史结果，不证明当前active Segment/Worker/UI或非提交。新Run/UUID不构成新的相同业务执行意图。

## 验证和后续

先以旧代码证明7项新公开GET红例，保留既有4项权限检查；实现后19项API检查通过，含旧Task正向回归。7项真实PG检查通过。双仓库全量make test/check与SDK check/test结果见[机器证据](evidence/ca-p3-03b/validation.json)。固定发布源码、真实签名HTTP、丢follow-up回复后只GET原收据、双BFF/双浏览器/实际Worker验收由OD-P3-01AA独立记录。

下一独立消费者OD-P3-01AB必须在生产BFF持久保存原正文/key/hash/结果与CAS，再接SDK/跨副本unknown恢复。AA的私有夹具不计作这项生产能力。原POST原子化/安全非提交证明、新业务意图执行授权、真实产品IdP/厂商模型/生产HA/外部取消仍开放。不部署、不生产迁移、不合并main，不变schema/Coverage/mocks/历史。

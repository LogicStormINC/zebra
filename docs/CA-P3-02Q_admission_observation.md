# CA-P3-02Q：原准入缺少结果时的只读观察

状态：实现、定向验证及消费者候选联合通过，完整make test11057通过/3032条件跳过、make check1404类型/30eval通过，发布后消费者联合另记。依赖已发布Pce46a7e5；对应Overdoze OD-P3-01N。

## 合同与 DDD 边界

Native仍独占原准入claim/result、Task/Session/Controller/执行事件；业务人工案件与权限属于业务BFF，不写入Native数据库。
复用P公开原操作的相同scope、恢复key/hash、当前签名Host/Task/Profile/Client校验，追加端点：

`GET /v1/admission-operations/{operation}/observation`

无body/query；POST405。X-Zebra-Admission-Key与X-Zebra-Admission-Hash必须是原请求的值，绝不能由浏览器取得。
当前HostGrant绑定完整issuer/subject/Host/workspace/principal/Origin/resource refs；恢复key、原credential和hash冲突409。
SQLite新合同503。旧P GET/POST、原claim/result及历史接口不改变，无新Native schema/迁移，尾仍113。

```json
{
  "contract_version":1,
  "operation":"原UUID",
  "request_hash":"原64位hash",
  "kind":"surface_mount",
  "claim_recorded":true,
  "result_recorded":false,
  "partial_commit_possible":true,
  "retry_allowed":false,
  "controller_reclaim_allowed":false,
  "observed_at":"原生观察时间，RFC3339"
}
```

- 原claim/result均是持久原操作事实，仅按已有有界唯一索引读取；不存在时claim/result=false、kind为空。
- partial_commit_possible = claim_recorded && !result_recorded。它表示无法排除部分提交，不表示已确认具体效果/Task/Controller，更不是已停止执行。
- result_recorded=true仅表示存在该原结果记录，不代表业务成功、2xx、凭据仍有效或收据内容已由BFF验证；完成仍走P原收据GET及AEAD校验。
- 所有状态的retry_allowed/controller_reclaim_allowed永远false。没有claim或result不证明未提交，时间戳不是租约、静默窗口或非提交证明。
- 观察前后重新检查当前授权。失效的Host/Profile/Client拒绝，BFF只能记录unobservable；不能换key、建Session或领取Controller去修复观察权限。
- 响应不含原payload、恢复key、credential、fence、密文结果或内部claim nonce。不查询当前Controller猜测原请求，不扫描事件/历史，不调用准入组合。

## 并发与恢复

沿P的2秒deadline/有界数据库连接，每次GET两个不可变原记录的有限读取，无锁跨网络、无写入、无接管。
“只读”针对原准入/执行事实，已有HostGrant一次消费及安全审计仍执行。
两个读取不是跨服务原子快照；后续原结果可能迟到，故观察始终是as-of事实，不授予解除pending或重新执行的权力。
业务BFF保留原unknown并保存有版本的观察/人工审计；人工升级、确认未知不能更改Native原claim/result、Coverage或执行状态。
Native没有新增“手工成功/失败”“删除claim”“重置UUID”“重建收据”入口。

## 验证和边界

API拒绝观察POST；真实PG在可能产生效果后故障，重复原观察返回claim=true/result=false且不再次dispatch，不写原结果；错误hash拒绝。
消费者隔离联合在真正Native挂载及Controller提交后、原结果落盘前注入存储TimeoutError，保留真实认证和准入；不是伪造事件/收据或绕过权限。
实际SDK/Worker正常联合与独立BFF人工处置/重启/CAS/阻断另见消费者最终发布pin证据。
[本片证据](evidence/ca-p3-02q/validation.json)。未验证真实业务IdP的支持权限、生产存储故障切换、性能或HA；未部署、生产迁移、主线合并。

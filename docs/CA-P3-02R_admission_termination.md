# CA-P3-02R：派发前安全终止与非提交证明

状态：make test 11059 passed/3036 conditional skips; make check1406 types/30eval; API13 and real owned PG7 focused passed. Pre-dispatch candidate Chromium/WebKit passed; published-source consumer joint is separate. 依赖已发布Q880cdadc，消费者OD-P3-01O；用户授权叠加分支，不表示依赖已合并main。

## 先固定证明边界

本合同只证明一个精确原准入在本协议派发点之前被永久阻断。非提交仅指本次Task/Client Session/mount/Controller准入业务效果；HostGrant消费/审计、claim和终止门闩本身已正常提交，不包含在该证明内。它不证明同用户、Task、Client或产品从未有其他效果，不取消Worker、Task、审批或已开始的Controller操作。

| 原事实 | 返回state | non_commit_proven |
| --- | --- | --- |
| 新协议claim，终止先取得原行锁，永久写入terminated | terminated | true |
| 新协议claim，派发先写入started（即使随后崩溃/无收据） | started | false |
| 旧claim无协议标记 | unsupported | false |
| 无claim | not_observed | false |
| 新claim有、尚无门闩且仅GET观察 | unresolved | false |
| 授权失效、超时、丢包、存储不可用 | 错误/unknown | 不签发证明 |

仅新请求POST带`X-Zebra-Admission-Protocol: pre-dispatch/1`可启用；其他非空版本拒绝。
版本写入新claim的元数据，不更新旧claim，不允许为旧部分提交补发证明。
恢复key/hash、issuer/subject、Host/workspace/principal/Origin/resource refs及当前Task/Run/Profile/Client授权，均复用P/Q；不得凭空替换原key或Client credential。

## 公开合同

`POST /v1/admission-operations/{operation}/termination`是独立显式终止命令；无body/query。
`GET`同路径仅观察；不能建立门闩。两者要求原X-Zebra-Admission-Key、Hash、Client凭据及当前签名HostGrant。
返回固定九字段：contract_version=1、operation、request_hash、kind、state、recorded_at、non_commit_proven、retry_allowed=false、controller_reclaim_allowed=false。
started/terminated有持久化数据库时间；其他state时间为空，无claim时kind为空。
证明无凭据、payload、fence；只通过当前授权的可信HTTPS读取，不作为可转让离线凭证。
原P GET/POST及Q十字段观察不变。已终止原准入仍无完成收据，P返回unknown，Q仍保守partial_commit_possible；要读取本独立证明合同，不能篡改旧合同的含义。

## 实现与并发

复用control_plane_idempotency_records的索引、不可变save和已有postgres_transaction_work_unit；无新增Native迁移，schema仍113。
新派发方先提交原claim，再在短事务锁精确claim行，写入唯一client-admission-v1-dispatch-fence记录started，提交后才能调用既有dispatch。
显式终止锁相同claim行，在无门闩时写terminated；记录一经存在永不覆盖。读GET不写门闩。
终止先胜：原处理器随后恢复也读terminated，拒绝dispatch。开始先胜：终止只报告started，绝不撤销started/过期接管/按无Task推断未提交。
事务只含有界PG读写，无外部网络、模型、Task/Controller派发或等待人工操作；复用2秒task IO预算。
BFF不能直接访问Native数据库；Native拥有门闩事实，BFF拥有业务终止意图及权限审计。证明不清除BFFpending、不授权重发/新UUID/重新领取Controller。

## 验收与限制

真实PG覆盖暂停原请求、终止先胜后恢复零派发、跨进程/重启不漂移；竞争第一写者唯一；started后崩溃仍不证明；旧claim/无claim/错误hash/当前拒绝与GET只读。
HTTP与消费者固定已发布源联合另记；测试dispatch stub只证明日志门闩，不声称实际业务或Worker效果验收。
不部署、不生产迁移、不改历史收据/数据/Coverage，不声称生产HA。
后续仍需设计真正进入dispatch之后的停止与原子效果证明；必须覆盖所有部分提交路径，不能以本派发前证明代替。

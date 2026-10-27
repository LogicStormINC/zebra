# CA-P3-02S：已开始的原子 Surface 准入安全终止

状态：make test 11060 passed/3045 conditional skips; make check1408 types/30eval; API14 and real owned PG16 focused passed. Started atomic-surface candidate Chromium/WebKit passed; published-source consumer joint is separate.
依赖已发布R543d8c89/O93c6244；消费者OD-P3-01P。叠加功能分支，未合并main。

## 证明边界（实施前固定）

| 请求/当前事实 | 结论 |
| --- | --- |
| 新atomic-surface/1，surface_open或surface_mount，全部写适配器是精确同PG/namespace原生类型 | 可以使用本合同 |
| 正在执行，执行行锁仍被原事务持有 | pending，non_commit_proven=false，不能把停止意图当作回滚完成 |
| 原业务效果与密封原收据已共同提交 | committed，non_commit_proven=false；只读取原收据，不撤回已提交效果 |
| 终止意图持久化；观察取得原执行行与claim锁；无原子收据 | terminated，non_commit_proven=true；原事务已退出且未来原执行被提交门禁永久阻断 |
| 尚无终止意图，只是无收据/进程退出 | unresolved，不能证明未提交 |
| 旧版、pre-dispatch/1的started、历史部分提交 | unsupported；不升级、不补造证明 |
| Task创建、Worker、脚本、模型/外部HTTP效果 | 不在本协议内；Task创建显式拒绝该协议 |
| 丢包/超时/授权过期或撤销/存储未知 | unknown/不可观察，不签发证明 |

非提交仅指这个精确原UUID/hash的Client Session、mount、Run binding和Controller业务写入；HostGrant消费/审计、原claim/started门闩、STOP与BFF意图已正常提交，不属于业务非提交范围。
证明不是“系统没有任何影响”，不证明其他请求或历史操作未发生，不是可离线转授的证书。

## 显式新合同

原POST新增header `X-Zebra-Admission-Protocol: atomic-surface/1`，仅新请求可选择；协议写入不可变claim元数据，并在新协议规范hash中加入dispatch_protocol。旧P/Q/R hash与JSON保持不变，不能改原请求协议再重发。
API只装配精确PostgresClientSessionRegistry、PostgresClientControlLeaseStore、PostgresClientCapabilityRegistry，要求与原idempotency数据库DSN和namespace相同；包装/自定义/跨数据库写适配器拒绝新协议。
原Session开通、mount和binding/controller沿用既有领域服务；没有新增业务执行状态机或通用Saga。

`POST /v1/admission-operations/{operation}/atomic-termination`：显式持久STOP，一次命令；无body/query。
`GET`同路径：仅观察/短锁探测，不写STOP、不补收据、不重放任何业务效果。
认证与原key/hash/credential/当前Host/Task/Run/Profile/Client权限复用P/Q/R。
返回固定九字段，contract_version=2；operation、request_hash、kind、state、recorded_at、non_commit_proven、retry_allowed=false、controller_reclaim_allowed=false。
terminated时间为持久STOP的数据库时间；committed为原收据记录时间；其他state为空。无claim时kind为空。
原P完成收据与R版本1终止合同保留；R不能给atomic-surface/1请求补发派发前证明。

## 事务及并发线性化

复用现有control_plane_idempotency_records、postgres_transaction_work_unit与原服务，无新增schema迁移（仍113）。

1. 原claim独立提交。新协议start在claim行锁下检查STOP、写不可变started；从不接管已有原操作。
2. 原执行事务锁精确FENCE行；所有Surface写和密封原收据使用同一连接借用事务。错误响应、nested adapter失败、receipt写失败或最终当前授权拒绝均回滚全部业务效果。
3. 提交点再取得claim行锁，检查STOP；STOP先胜则整个事务回滚。提交先胜则业务效果与原收据共同提交。
4. 显式停止先在短claim锁事务中写唯一STOP（原收据已提交则不写），随后独立探测FENCE→claim两个NOWAIT行锁。执行持锁时返回pending，不等待、不伪造回滚成功。
5. GET重复探测同原事实；拿到两锁且有STOP、无同事务原收据，才有正面非提交证明。迟到原处理器即使恢复，也必须先检查STOP并在提交点重查，不能再提交。

新协议事务显式固定READ COMMITTED，提交点必须看到先前已提交的STOP；不依赖数据库默认隔离级别。行锁只围绕本原操作，所有查询有索引；执行事务仅允许本地PG Surface调用，无IdP/HTTP/模型/脚本/Worker派发。沿用2秒task IO预算；终止探测NOWAIT，不持SQL锁等待外部网络或人工审批。异常事务退出时PG锁释放；进程崩溃但尚未确认释放时仍pending，无租约超时推断。
同事务收据意味着“已提交但原收据不存在”的旧部分提交形态不能由新协议制造；不会据此为旧形态签发证明。

## 验收及剩余工作

真实PG：实际Session+mount+binding+Controller适配器SQL回滚、停止在途时pending、退出后证明/跨进程稳定；成功效果与原收据同事务；部分错误/receipt失败回滚；进程os._exit后观察锁释放才证明；旧/缺失claim不升级。
候选公开联合：真实SDK/OIDC/签名HostGrant/同次Worker，在真实mount SQL之后201/result之前施加有界测试暂停。显式STOP只一次POST；执行仍持锁时真实HTTP返回pending。释放后原事务回滚，第二BFF GET取得证明；旧Controller仍有效，原pending/收据不变，重启不派发。
测试暂停与适配器故障注入仅存在于隔离fixture，不进入产品请求路径。发布后消费者必须固定已发布源码重新验收，不能拿候选代替正式证据。
Task创建原子准入、任意外部效果/Worker已派发终止、历史部分提交处置及生产HA仍开放。保留历史/原收据/Coverage/mock，无部署、生产迁移、main合并或npm发布。

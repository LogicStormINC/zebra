# CA-P3-02D — 原生公开摘要与重挂载绑定同步

2026-10-22；Owner Luke Ding；基于a1635a9c独立任务，不部署/迁移或整合主线。
[机器合同](contracts/client-surface-metadata/contract.json) · [验收证据](evidence/ca-p3-02d/validation.json)。

## 原生权威和公开响应

复用现有Profile/Session/RunBinding/Controller与client-bindings、client-surface POST接口。
capabilities/runtime新增client_surface_metadata_contract_version=1（Client Plane不可用为0），
接口成功响应加法包含同名版本字段、profile_digest、ui_revision、mounted_snapshot_digest、
binding_mounted_snapshot_digest、action_contract_digests；既有绑定ID/摘要/revision/allowed_actions/fence字段保持。
action摘要精确复用Worker同一canonical_client_capability_digest(action.model_dump(mode=json))，
仅返回当前binding.allowed_actions的Profile合同，空允许集返回空map，不在Go或浏览器重算。
Profile摘要和绑定引用必须匹配当前mount，map键集合必须等于允许集。
返回前重读当前snapshot/binding/Controller fence；发现竞争变化返回409 client_surface_changed，不返回成功秘密。

这些接口仍是可信Host/BFF的原生准入接口，必须通过已有当前主体、Task/Run/线程/namespace和Session授权。
原生Session credential/HostGrant/controller_fence_token留在业务BFF；公开metadata本身不授予权限。
响应中的ui_revision由实际挂载产生，浏览器初始化不能使用固定fixture值。

## DDD 不变量与提交边界

| 所有者 | 不变量/变更 | 持久一致性 |
| --- | --- | --- |
| Profile版本 | 不可变合同与canonical action摘要 | 原有发布/读取机制，无新聚合 |
| ClientSession挂载快照 | 同Session/Profile，名字只能收窄，UI revision单调；同revision内容一致 | PG短Session行锁内复用域规则复核，快照和Session指针同事务 |
| ClientRunBinding | 同action列表但snapshot变更也推进revision/摘要；原ID/创建时间/任务scope保持，能力只缩小 | 同Session行锁内复核当前snapshot及原有binding revision/CAS；原机制更新当前行，既有Effect/收据中的旧摘要保持 |
| Controller lease | Controller请求按原机制轮换fence；Observer不产生fence | 原有独立lease事务，原生收据事务最终验证 |

重挂载新UI revision即新snapshot，原service按action列表直接返回旧binding的路径已修复。
所有调用者复用域snapshot.ensure_narrows，storage不依赖control-plane包。
锁顺序为Session行→mounted snapshot或RunBinding行；mount不持RunBinding/lease锁，bind的lease申请在事务提交之后。
每个Session局部锁覆盖存储校验/写入，没有全局锁、外部网络或新的排队机制；新增行锁等待至多1秒，保留调用方/运维更短的lock_timeout；
无请求期限的分步调用也有该锁等待界限，冲突转为原生409并回滚事务。连接/DNS等整体期限仍沿用既有机制，不宣称本片收敛所有历史I/O。
低层历史registry-only binding可能没有Session/mount行：保留其既有登记/读取；公开准入始终要求有效Session。
已有Session关闭/失效后拒绝新的mount/binding保存，不删除其历史快照/绑定/收据。

组合mount/bind/lease仍是多个原有提交，不宣称跨聚合原子事务：失败后可能已mount、已binding或已轮换fence。
409/超时/断线不是未写入证明；BFF串行协调所属surface，不能自动重试一次性credential结果。
相同完整snapshot重试不增binding revision，但Controller请求仍轮换fence，之前fence失效。
Observer只表示本次不申请控制权，不会隐式释放同一Session之前的lease；降权须显式release并处理unknown。
最终重读只是当前观察，响应后仍可能发生新mount/接管/撤销；实际Effect与收据继续按原生权威失败关闭。
没有新增schema/migration，不批量重写历史Task、Binding、Profile、Coverage或收据。
显式重挂载/绑定按原机制更新当前Binding行，本片不新增Binding全版本历史存储。

## 验证与后续接入

API回归先在旧代码复现摘要缺失/旧snapshot/混合成功；验证canonical map、同名新revision、精确重试、旧fence拒绝、
Observer/空map、禁止扩权、split接口一致和能力协商。现有云当前权限/历史收据测试继续保留。
真实独享PG覆盖独立adapter重启、并发不相容收窄只能一个提交、stale binding零写入、关闭后保留历史，
同时跑已有Session/Controller/Effect原子收据及当前Task授权回归；完整make test/check另记条件跳过。

本片保持C的SDK源码与机器合同不变，旧SDK mount()仍不应用这些新绑定事实。
下一片须让可信BFF串行调用原生组合准入、保存最新原生fence，并将准确公开事实应用到SDK的挂载生命周期；
完成前不得把本原生前置称为真实产品BFF/Hook/Worker全链路已通。
Readable当前仅名称/revision，值schema/权限/预算/有效期/Context消费仍需独立原生合同。
生产多副本BFF持久映射、HA/立即撤销、npm发布和部署/生产迁移均非本片证明。

## 本片验证结果

最终make test 10914 passed / 3020 条件跳过（1135.58秒），make check通过。
API/兼容专项56 passed / 1条件；真实独享PG62 passed / 零跳过（含新增1秒/100ms锁边界）。
3669冻结输入、414旧SDK/合同/Coverage文件无漂移，280Coverage保持。
前轮严格能力列表期待值遗漏及主动中断结果均在正式证据中单独记录；不等于SDK/BFF/Worker实际联合验收。

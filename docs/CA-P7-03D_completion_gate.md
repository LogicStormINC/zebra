# CA-P7-03D：持久完成gate与跨仓受限验收

2026-11-02，Review功能候选。分支codex/ca-p7-03d-completion-gate，基线56ae352a。
用户明确没有可信counter：模型调用/执行就绪继续严格拒绝，不部署、不生产迁移。

## 03C整合

Native从05778f05正常合并已验证a8b433d6，得到56ae352a并推cloud-agent；
保留期间ERP提交。仅PROGRESS和任务登记发生前置段冲突，两侧内容均保留。
所有03C变更Python字节逐一与333项已验候选hash比较一致；不把旧333项计为本轮新跑。
本地cloud-agent已ff；Overdoze main从e34ecc4 ff至365e843并推送，AGENTS无关修改字节保持。

## 用例、边界与规则

Native拥有Task/Run/原准入/Lease/事件/Artifact；Go只通过已版本化公开HTTPS合同交互。
不把GateInput、模型summary、工具名字符串、旧v27 passed收据作为完成授权。

生产持久gate必须冻结精确namespace/run/revision/parent binding与真实发布Definition/Version快照，
检查每个原node/child/initial admission、当前有效binding/STOP/Grant及真实终态/segment。
读取Worker栅栏提交的实际tool.called与terminal事件；Artifact须关联原事件且finalized/verified/retained。
原模型/工具unknown仍不能释放预约、重发或生成成功证明。

## 最小明确完成政策

复用AgentDefinitionVersion既有evaluation_profile_ref，不新建通用配置域或UI。
仅受信已发布system/orchestrator显式引用evaluation-profile/orchestration-readonly@1时识别。
Native固定版本政策：all_success；每个child至少一次真实files.read成功及一个相关已提交Artifact；
所有实际执行工具限files.read，存在其他tool/effect/unknown即拒绝。多Segment/Attempt不能隐藏先前工具。
这是只读执行/产物证据政策，不声称测试通过、代码质量或自然语言目标已经验证。
该政策明确不要求Reviewer或测试Toolchain；其他需要审核的政策缺真实producer仍拒绝。

创建run的可信工厂在同一短事务冻结policy ref/完整语义hash及原Definition/Version/snapshot摘要。
政策语义不可原地修改；未知ref、旧run无冻结政策或policy摘要不符均失败关闭。
不能让模型参数或任意GateInput决定政策，不能从没有要求推导已审核通过。

## 一致性、恢复与资源

复用parent→run/node→child锁顺序，500ms锁等待与3s statement budget；外部I/O不在事务内。
最终时钟/当前授权/lease/STOP/Definition撤销复检、不可变原事实收据与完成CAS同事务；
失败回滚不能遗留synthesizing。原观察按完整事实摘要幂等、异体冲突。
有界恢复独立于usage IS NULL；已结算预算但gate晚到仍有扫描入口。
v121保留，v122观察与v123政策冻结均为新增显式迁移，只在owned测试库运行。

唯一owner/run清单位于.artifacts/ca-p7-03d/run.json；一个活跃限额PG容器内gate/native/platform
独立库。所有临时API/Worker/签名材料和日志有明确owner；先保存原收据/unknown/全库dump再清理。
不恢复旧环境或操作业务容器。

## 验收计划及不能证明的部分

Native：真实PG原坐标/并发/lease更替/撤销/失败回滚/晚到恢复、持久gate正反例，
明确受信输入fixture与真实Worker工具事件/Artifact的边界；最终源码hash和静态检查。
跨仓：真实Go管理HTTP→Native HTTPS公开发布与Task准入、两个产品、正常Worker领取后
缺counter拒绝、provider零请求、重启再次拒绝与旧Task事件保持；Host JWT/发布凭据越权负例。

跨仓发布eval、TLS/JWKS/业务签发者仍是owned测试输入；真实LocalRuntime为受支持开发模式，
不是OCI/gVisor或生产HA。没有counter时不能验证模型驱动真实编排child成功或完成合成；
不以Native局部fixture正例替代这些跨仓未验证项，也不宣布P7整体完成。

## 实跑结果

主代理最终独立388 passed / 0 failed / 12 conditional skipped（76.17s）；12项需未配置S3/MinIO，
未当作真实对象服务验收。Ruff、14变更源mypy通过；变更Python以及跨仓1542 Native源文件hash前后相同。
[机器证据](evidence/ca-p7-03d/validation.json)保存完整命令/哈希和清理记录。
正常Go→Native HTTPS/Task/Worker受限跨仓13项通过，provider POST=0；没有注入counter或readiness。
政策正例实际FileReadTool→既有projector→CloudArtifactCoordinator→WorkerMutationAuthority/事件/PG→完成CAS，
对象服务仍为内存字节fixture并核验实际捕获内容，不是S3证明；两spawn进程同原事实只写一份收据。

实际跨仓修复两项03C入口缺陷：public Bundle v2 binding沿用definition_digest，B/C child则full snapshot_digest；
consumer仅接受同一已校验Snapshot的这两格式，execution proof仍严格绑定原字段，不改旧准入或v3规则。
JSON Schema的type可为dict/list，shared inspect_request先判字符串再识别media，避免TypeError阻止真实counter拒绝；
有/无fixturecounter两红回归后18 transport通过，随后完整定向388/12skip复跑。

所有诊断保留原Task/库，未回写快照或制造成功。首次聚合384通过/14 setup error未记green：
2个为fixture request转发已修，12个为256MiB PG耗尽；全7库dump后改用512MiB tmpfs、768MiB内存，
WAL64/32与30s checkpoint；一次minWal16不合约初始化失败无业务数据，保留日志后纠正。
最终另5库及Redis RDB均已保存；owned PG/Redis/进程零残留，清理后磁盘131GiB、memory free67%。

功能分支待整合，03D正向模型驱动孩子/预算触顶/丢回复/成功合成跨仓项仍未验证，P7不关闭。

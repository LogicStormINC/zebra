# CA-P4-02 — 产品分发、安装代际与当前撤回

状态 Review，最终完整门禁通过，Owner Luke Ding。前置 CA-P4-01 b88e2b7b；本片为 P4 D 的原生生产者。

## 权威与合同

新公开 `/management/v1/plugin-distribution`，`/contract`；plugin-distribution/1。
复用独立 rtpa_、原完整 BundleScope、当前共享产品批准、plugin.publish/plugin.read 动作，
固定 X-Runtime-Plugin-Distribution-Contract。原 plugin-admission/1 摘要与语义不改。
POST distribute/withdraw，完整 recipient ExtensionScope、package_digest、
publication_operation 原生成功发布原 UUID、operation_id 原 UUID、expected_revision。
recipient issuer/namespace 必须与受信产品scope相同，principal/workspace 由可信管理端显式绑定；
不会从浏览器产品ID或任意 HostGrant 推导产品。管理批准与业务 HostGrant 仍同时必要。
分发不安装、不创建 MCP 凭据、不启用、不授予业务工具权限。
GET 原 x-runtime-operation，originalResult 不可变，currentDistribution 独立返回当前状态。
404/错误/超时不证明未提交；unknown 只 GET，不重发/自动重试/重领 Controller。

## 事务与执行边界

追加 migration114，显式运维执行；启动不迁移，无旧行/Task/收据/覆盖证明重写。
复用 v111 原收据表和当前批准短事务；分发 revision CAS、原 UUID/原字节冲突、原结果一并提交。
包和 recipient 键固定，跨产品不能覆盖另一产品在相同 Native scope 的分发。
公开产品发布的原收据提交同事务即永久标记该包受管，不能利用分发前的空窗从旧目录安装私有包。
迁移仅向新受管索引回填旧公开发布收据摘要，不修改原收据或旧安装。第一份受管注册永久标记 deployment/package；之后缺分发/撤回不能回退旧未受管安装路径。
未受管旧包行为保持；若选择将旧包转受管，旧无代际安装保持历史但停止使用，需显式重新绑定/启用。
同原 UUID 的请求只观察原结果；新授权需显式新 revision，不能复活原安装。

目录在返回页/游标前检查当前分发，隐藏受管包，不返回隐藏摘要游标；扫描超过140条受控失败，较大目录需专门授权索引。
所有API/Worker必须排空旧版本再启用受管目录；不能以旧Worker和新API混跑宣称撤回生效。

安装模型与 PluginSnapshot 增可选 distribution_digest，None 不序列化，旧摘要保持。
服务器在组件准备前读取分发，安装提交再次同事务检查；启用、Turn 准入和 Worker 的原 get_current_batch
共同复用当前数据库检查。撤回后 enabled 的历史声明不改，但有效检查拒绝，旧快照可读而不可再执行。
重新分发产生新代际；旧安装引用不能随当前权限复活，需显式禁用/重新绑定/启用。
受管分发还固定共享原生批准revision/fingerprint；批准到期或更新令旧代际失败关闭，需显式重绑。
MCP 独立当前认证和目录、Skill 内容/来源保护、HostGrant/工具策略继续生效。

包级共享 advisory transaction lock 与管理首次注册的排他锁防止旧路径在首次注册时穿透。
当前分发行/批准行 FOR SHARE；管理更新排他，元数据内无对象 IO。
现有每实例8槽、6秒线程保留和有界存储连接/SQL deadline；每管理产品最多128已批准包；独立当前读取3秒硬预算。
未做生产吞吐或存储HA证明。撤回线性化只覆盖后续检查，不能回滚已经提交的业务写入或正在外部执行的请求。

## 验证

真实独享PG、HTTP、并发双入口、CAS/原收据、新principal拒绝、撤回/再授权不复活、
原安装/快照保持、Turn和实际WorkerGuard拒绝。受信目录及不自动安装沿用前置。
完整make test：11176通过/3067条件跳过，make check：1425类型源文件/30Eval及全部门禁通过。
21项公开API、12项目录/HTTP夹具及19项真实PG/Worker检查通过；[最终证据](evidence/ca-p4-02/validation.json)。
原有目录Mock显式设置可选端口None，保留旧分页断言；迁移目录断言保留113并新增114。无部署或生产迁移。

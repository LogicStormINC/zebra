# CA-P5-08 — P5 生产者退出复核

状态：P5 工程退出验收已通过，Review 待主线整合；无生产部署或迁移。

固定公开源为 `9e91d75ff12634d34f5eedf57da6558cccd274e4`，
源分支 `codex/ca-p5-10-admitted-stop-identity` 保持不动。包含 CA-P5-09 的原 READY
命令发现及 CA-P5-10 的 canonical 已受理控制身份验证；此验证分支只改文档。

`make test`11240 passed/3080 conditional skips，`make check`尺寸0违规、ruff、
mypy1448、Eval30/30。真实隔离 PG legacy8/8，原资源绑定7/7（原断言不改，
历史固定 scratch fixture换为核对 owner/端口的独立 PG，不连接历史地址）。
完整套件内的 `test_runtime_gate_management` 和 `test_runtime_gate_termination`
使用真实拥有的 PG/HTTP；Coverage 证明回归保留。不能据此宣称 Bundle Task
已经执行未支持的 Coverage 准入，也不能替代生产 HA/故障切换验收。

先全量验证生产者再构建源固定镜像，是 S1 的依赖顺序。消费者结束后核对源文件
哈希不变，复用本会话该完整结果；任何生产源码修改或新失败均重新验证。
V21 与更早环境的原请求、unknown、原 Task/Run/Controller/收据和数据保留。
不执行生产部署、生产迁移或主线合并；当前新 S1 的最终结果/资源清理待回写。

## 最终同环境结果

[机器证据](evidence/ca-p5-08/acceptance.json)记录消费者证据摘要。V31 实际固定源
API/Worker/gVisor、Chromium Alpha/WebKit Beta/Chromium回退三个Task完成，
不兼容镜像CLI对原Task拒绝、模型/工具/运行时增量0，然后健康进程续接同一原Task。
旧grant到期后显式审批续期，平台注册与Host绑定由可信BFF的现有合同维护，
原范围和能力上限不扩大；原Task/Run/Controller/原收据不重发或替换。

三处管理/执行器重启后原Root/意图/ACK/观察及三个Task原事件/Effect/快照/绑定
保持。四个负向stop/CAS/权威/门禁读故障与SQL准入fence通过；未知保留而非强行终结。
全量11240/3080条件跳过、check1448/Eval30、独立PG legacy8/resource7均通过，
五组源码哈希与全量验证时完全一致，未重复运行未变的22分钟套件来制造新证据。

消费者临时运行角色/配额已清理，当前数据停机保留。先前24个确认归属、停止的
容器壳已保存inspect/卷名/挂载/重建说明后移除，不带-v；数据/卷/原收据保留。
未放宽完整库存256KiB/128边界，也未按标签过滤绕过无标签别名检查。
本报告只关闭P5受控工程退出；P6生产HA和P7多产品仍未开始。

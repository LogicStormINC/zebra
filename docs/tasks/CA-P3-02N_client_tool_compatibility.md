# CA-P3-02N：Client Action 与审批继续执行兼容

状态：原生兼容修复；最终门禁见 [证据](evidence/ca-p3-02n/validation.json)。
依赖 published F980d4536；Overdoze OD-P3-01K 同次联合暴露问题，本片作为独立原生前置。

## 根因与边界

公开 `ClientActionContract` 允许省略 description/parameters，也允许只有 object 类型、未提供 properties 的参数 schema。
Worker `ClientToolGateway.model_tools` 原先直接传给严格的 `ModelToolDefinition`；后者要求非空 description、object type 和 properties。
合法 Profile 因而能完成发布、签名准入和 SDK 挂载，却在 Worker 构造 orchestrator 时崩溃；此前分离的 SDK/Worker 验收未覆盖这一路径。

修复既有防腐转换，不修改公开 Profile 合同/校验、核心 ModelToolDefinition 不变量，也不让调用方批量填字段或改历史数据：

- description 有非空白内容时保留原文字节；省略/空白时以稳定的 Action name 作为模型展示描述。
- 模型参数展示仅补缺省 object type 和空 properties；明确发布的 type/properties/required/additionalProperties 等优先保留。
- 不原地修改合同、Profile digest、绑定、Effect action contract digest、原事件或收据。
- 明确的非 object 类型不因默认值覆盖而获得可执行权限；模型工具仍受核心 object 不变量约束。
- USER_INTERACTION 的审批集合、当前 Profile/Run/Controller/能力授权、收据继续执行与 Coverage 完全不变。

## 审批到同一 Run 的两个衔接问题

实际 PG/Worker 联合还发现：审批响应调用 `ensure_for_session` 重建已映射 Task，可能把刚提交的 resume 一并投影，令按未投影命令发现的 Worker 漏掉它。
响应现在优先复用受权的现有 Task 映射，仅对未映射的旧本地数据保留原 fallback；不在普通已知 Task 的响应中重建执行投影。

原审批继续执行是 USER actor 的无 run_id resume，被严格 replay header 当成新的空 Run，导致 Worker 拒绝继续；不能放宽该严格检查或改用新 Task/Run。
仅审批成功后的系统 wakeup 使用 HARNESS actor 和保留的 `approval-resume:` 原生前缀。
通用 HTTP 命令仍固定 USER actor；请求体不能提供 actor。USER 伪造前缀或 HARNESS 带明确新 Run 的命令都不能变为内部继续执行。
SQLite、PG增量113标量header和AG-UI窗口一致识别它；PG旧v62索引表达式保持原字节。上述当前读路径只使用已存在的scalar索引，继续原 canonical Run，既有 child/client-effect 内部收据规则保留。

## 增量存储与升级

- PostgreSQL 新增113，原1–112迁移和 checksum 不变。只替换后续 INSERT 的 header 计算函数，不 UPDATE 任一旧事件或已完成 header。
- SQLite 只在检测到旧触发器时用短 IMMEDIATE 事务替换计算/保护触发器；旧源/ready header 不回填、不改写，源不可变和伪造 header 拒绝仍在。
- 应用启动沿用 matching-schema fail-closed；代码准备好不表示生产已迁移。先按运维批准运行增量113，再协调 API/Worker/replay reader 升级、排空旧读者后启用新审批继续执行；不支持盲目旧二进制回退。
- 已有 USER 空 Run 审批历史保留原字节；本片不把未知/已卡住旧任务改成成功。其恢复需单独审计并明确授权，不自动重发或新建 Task 隐藏问题。
- 专项真实临时 PG 从112升级113，旧完整行及旧迁移记录逐项相同；新 trusted wake 保持原 Run，USER 伪造仍作为普通外部命令。

## 验证与依赖顺序

新参数化回归先在原实现产生11失败/5通过；已知Task响应回归2失败；trusted approval Run回归1失败/2通过/3可选PG跳过。修复后本地89专项通过/10条件跳过，独享PG21通过/零跳过，覆盖历史字节、严格来源与Run边界。
修复后运行原工具、Effect 调度/恢复专项以及完整 `make test`、`make check`。
发布本片源提交后，Overdoze 更新独立消费者 pin 并重新进行最终来源固定的 Chromium/WebKit 同次联合验收。
诊断用未发布源码运行单独标记，不替代已发布 pin 或完整门禁。

同次链路要求真实受控业务 Readable 值进入 Worker 实际模型 HTTP 请求，经 Native policy 审批后触发 SDK DOM handler，
原 Effect 持久收据唤醒同一 Task/Run 的 Worker 提交一次答案；unknown 命令在 BFF 重启后只 GET 原收据。
业务凭据始终在 BFF。受控模型/页面不是供应商模型、已有产品、生产 gVisor、容量或 HA 验收。

无新依赖、公开 API 或状态机；仅准备增量113并在自建测试库执行，无生产迁移、部署或 main/cloud-agent 合并。旧合同、历史数据、原收据和 Coverage 保留。

## 门禁中的历史校验回归

首轮扩展曾修改PG旧header模块的表达式常量，该常量被已发v62迁移引用，间接改变了旧checksum；完整测试的既有冻结校验捕获该问题。该模块已整体恢复到F原字节，新规则只由113计算后续scalar元数据。旧v62 checksum固定为8d05945430613d43455b4d47850634d6e46cbdef841be55902b36bef316e5757，未修改旧断言。校验专项12通过/21条件跳过，真实PG21项再次通过，所有修复后完整门禁重新开始；中断轮次不计为最终通过。

最终文件门禁曾发现新增用例使既有 AG-UI 测试达到703行；完整测试11038通过但该检查失败，未计为全绿。新增用例已移到独立 test_approval_resume_binding.py，原测试文件完整恢复；文件边界专项5通过、make check通过后重新执行全部门禁。

最终重跑：make test **11039通过/3026条件跳过**（1269.08秒），make check **1400类型文件/30eval**通过，文件大小检查3410文件/零违规。原4666个文件中4648字节相同；全量跳过不计为已执行PG验收，另以独享PG21通过/零跳过证明升级路径。

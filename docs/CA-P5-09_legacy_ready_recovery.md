# CA-P5-09 — 已重放但尚未执行的 Legacy 原命令发现

状态：聚焦回归通过；全量门禁、固定镜像同次接入验收尚未完成。

OD-P5-08 的 V21 使用固定 ce6d7d19 镜像，先暂停健康 Worker，再让不兼容 CLI
尝试已受理的同一 Task。CLI 明确报告 `INCOMPATIBLE_RUNTIME_BUNDLE` 并跳过原
Task；模型、工具和运行时执行增量均为零。但恢复原健康 Worker 后，Task 一直 READY。

保留数据的只读诊断确认：原 RUN 在 Session Event seq3，投影也在 seq3、状态 READY，
没有后续执行事实。Legacy 模式没有 migrated pending 行；两个 Legacy 读取方法都只查
严格大于投影序号的命令。恢复投影已经重放到 accepted 事件，不能据此认为命令已经执行。
同样的问题会影响其他尚未开始执行的重试型 setup 拒绝；不能只修本次不兼容路径。

## 修复与证明边界

复用 `LegacyCommandCandidates`，统一增加保守的“未开始命令边界”条件：

- 仍然按 deployment namespace、Session、页预算和永久拒绝事实过滤。
- 原有投影之后的发现逻辑保持；仅 READY 且 RUN/RESUME/MESSAGE 序号正好等于投影
  时，允许发现该原事件；该事件还必须是最后一条持久 Session Event。
- 任何后续持久事实、非 READY 或永久拒绝均不允许等号补充路径。
- 重新读取的仍是同一个 event/command/idempotency key，不新增或重发 HTTP/RUN，
  不回退投影、不清除 unknown、不重新领取 Controller。
- 实际领取、当前授权、Worker lease/fence、模型与工具的副作用准入仍由既有执行路径
  负责。发现候选本身不授予执行权。 migrated lane、SQLite/local 行为和公开合同不变。
- 仅补最后边界是有意的保守限制；存在更复杂后续事实时仍由既有恢复/command-cutover
  日志判断，不扩大为全历史回放扫描。

## 验证

真实 PG 红灯：RUN、RESUME、MESSAGE 三种发现和新消费者恢复共4项失败；两个
“已完成/后续执行事实”反例通过。修复后6项通过；增加永久拒绝反例后，与实际 Worker
Bundle 执行、已提交结束事实恢复和消费者基线一起33项通过。事件原文在只读发现及
消费者替换中保持不变。新消费者用实际组合与执行 spy；实际进程/镜像和完整同次任务
恢复由后续 S1 验证，不能用这个 spy 声称实际模型/Worker 接入成功。

V21 原 Task、原事件、收据和 unknown 保留。诊断只重启该环境自己已停的 PG，使用实际
新映射端口、只读事务，结束后再次停止；没有启动 API/Worker 或重发业务操作。
全量 `make test`/`make check`、不可变发布源和消费者验收完成后补充最终证据。

额外启用真实 PG legacy 基线得到7过/1过期 STOP 失败，原始ce6读取器同样失败。该既有取消身份问题独立登记 CA-P5-10；09不扩展授权规则，最终全量门禁待联合树修复后验证。

## 生产者最终验证

固定代码哈希不变：`make test`11240 passed /3080 conditional skips（1344.56s）；
`make check`文件尺寸0违规、ruff、mypy1448源文件、Eval30/30全通过。
显式隔离真实 PG legacy8/8；资源绑定原7项断言7/7，通过临时插件替换历史固定
scratch fixture为校验 owner 标签/实际映射的独立 PG，未修改断言或连接历史地址。
两次独立 PG均删除含其匿名卷；完整门禁新增4个容器属于不同 owner，原样保留，
无新增卷或网络。证据记录组合分支，不宣称09单独快照已通过10的修复。
任务进入 Review；消费者新固定镜像同次 S1 和 P5 总退出尚待完成。

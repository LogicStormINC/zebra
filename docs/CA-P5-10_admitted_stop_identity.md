# CA-P5-10 — 已受理 STOP 与当前执行授权分离

状态：Review；47项聚焦与修订后全量门禁通过，消费者固定镜像 S1 待验证。

显式启用既有真实 PG 过期 STOP 测试后发现：在 grant 有效期内已受理的命令，
消费时再次用当前时钟校验执行 expiry，导致已授权取消被阻断。精确恢复发布 ce6
读取器仍失败，说明它不是 CA-P5-09 的发现条件引起的。

第一版采用 trusted scope 取消，真实 PG 通过，但全量暴露5项旧契约失败：不能省略
Host context 或其身份重验。该版未发布，失败日志保留。修订实现恢复既有
`cancel_session`/`host_scope` 委托、完整上下文传播和事务内重验，未调整原测试来掩盖失败。

## 最终边界

Worker `cancel_command` 保留原类型、canonical accepted event、command ID、
fingerprint/idempotency 比对，将从存储读取的已受理事件作为内部证明传递。
存储通过 canonical event ID 再读取并逐字段比较，仅 STOP/CANCEL 可用，且必须匹配
本次 operation ID。只有该可信事实的不可变 `created_at` 可用于验证当时 Host grant；
不能传入任意旧时钟、伪造事件、RUN 或其他 Session 的事件。

事务仍检查最新 Task binding、Host principal/origin/namespace/workspace/thread/Run、
binding digest、canonical frontier、原取消收据及精确 scope，原子取消并撤销 Worker lease。
没有改写上下文/expiry，也没有 grant 续期、模型/工具执行或 Controller 重新领取。

新增的可选参数只在内部 Python 取消适配链上传递，不进入任何 HTTP 请求 schema。
未携带 canonical 已受理事件时，`host_scope` 与新 API 请求仍使用当前时钟和原严格
`require_task_host_context` 校验。local/SQLite 与无绑定旧兼容路径保持原语义。

真实 PG 必跑用例覆盖：旧 STOP 幂等完成、lease 撤销、原 binding/收据不变、无执行；
新过期 Host 请求拒绝；伪造/非控制事件和不同 operation 拒绝；指纹不符无副作用。
连同旧身份重验、CA-P5-09、Bundle/已提交结束恢复和消费者基线合计47项通过。
尚未声明全量或实际新镜像 S1 通过；最终证据须分别记录。

## 生产者最终验证

固定代码哈希不变：`make test`11240 passed /3080 conditional skips（1344.56s）；
`make check`文件尺寸0违规、ruff、mypy1448源文件、Eval30/30全通过。
显式隔离真实 PG legacy8/8；资源绑定原7项断言7/7，通过临时插件替换历史固定
scratch fixture为校验 owner 标签/实际映射的独立 PG，未修改断言或连接历史地址。
两次独立 PG均删除含其匿名卷；完整门禁新增4个容器属于不同 owner，原样保留，
无新增卷或网络。证据记录组合分支，不宣称09单独快照已通过10的修复。
任务进入 Review；消费者新固定镜像同次 S1 和 P5 总退出尚待完成。

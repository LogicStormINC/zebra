# INPUT-READ-BATCH-01：Cloud 输入恢复初始读取合并

## 结论与范围

本轮仅优化通用 Cloud Worker 的输入恢复入口。初始 Task membership、Task header、
execution input head 从三个独立连接合并为一次原生 PostgreSQL 只读 RR 快照。
现成的连接、Task 解码、成员关系和有界输入头实现全部复用；没有连接池、跨调用缓存、
新依赖、schema 迁移或 Trench 专用逻辑。

恢复完成前的 canonical Task header 仍在独立新连接读取；输入 advance 提交、Context
刷新之间不共享快照。累积 2 秒 deadline、ownership、STOP、lease fence、Host 权限、
输入字节上限与 source frontier 校验均保留。SQLite、自定义 Task 组合、覆盖 read 的
适配器及没有新方法的旧 Port 保持独立读取路径。高思考和 v2 设置未改变。

## 根因与固定工作量证据

此前真实 B1 的模型 HTTP 前 65 次 TaskIO 连接中，首次输入准备 21 次（建立连接约
93.28ms），两次 Context 输入刷新 12 次（约 54.22ms）。它们包含反复执行的连续纯读，
并非全部连接都可跨写入复用。本轮只合并单次调用开头的三项读取。

原生 PostgreSQL 的相同已就绪输入，40 组 AB/BA 配对，逐次建立新连接，并比较完全
相同的 SessionEvent 列表；计时包含连接建立、SQL 和最终新鲜头校验，不调用模型：

| 每次恢复 | 旧实现 | 本轮实现 | 变化 |
| --- | ---: | ---: | ---: |
| 新建连接 | 4 | 2 | -50% |
| 客户端 SQL | 7 | 6 | -14.3% |
| 中位耗时 | 323.778ms | 187.520ms | -42.1% |

这些绝对时间来自本轮负载偏高的本机环境，不能作为正常环境延迟承诺。首次测量因
原有 2 秒 Task I/O deadline 中断，日志保留；边界收紧后的最终测量完成全部 40 对，未放宽 deadline。
本轮不能把上表比例套用到整个 Worker、全部 SQL 或页面首正文。旧 trace 的 65 次
连接尚未通过新的真实页面配对更新，不能声称已实测下降到某个总数。

## 验证与交付边界

- 原生 red：连接断言实际 4，目标 2；实现前方法缺失。实现后最终版本 8 项通过，1 项并发测试在并行构建/测量时触发 2 秒 deadline；
  单独复核该项通过（15.34s，包括隔离数据库准备），9 项行为均有通过证据，未声称单次全绿。
- 并发消息：初始 header 读取后另连接提交新消息；初始输入快照保持一致，最终新鲜
  header 发现消息并恢复后续输入，没有把旧快照作为最终事实。
- 覆盖原生结果等价、未知 membership 拒绝、Task/read override、不同 Task 实例、数据库/namespace 不一致、
  SQLite 和旧 Port 缺失可选方法的兼容路径。
- 源码 Ruff、mypy（1283 文件）、文件长度、30 项确定性 eval 通过。
- 大历史 SQLite 兼容测试出现超过 fixture 自带 60 秒 lease 的失败；不得为了本轮
  性能变更修改该 fixture 或延长生产校验。旧实现也在相同校验处复现 LeaseLostError（70.04s）；另外 28 项定向兼容检查通过（7 项大历史场景未纳入最终定向集），未修复或掩盖过期租约。
- Chrome 控制连接可列标签，但读取页面报 `Debugger unattached`，新建页超时；用户
  重连后仍失败。未发起本轮真实模型 Run，未重放旧 Run，真实页面配对尚未验收。

## 复现入口与后续

新增检查：`uv run pytest -q tests/worker/test_execution_input_read_batch.py`，提供隔离的
`ZEBRA_TEST_POSTGRES_DSN`。私有工作证据位于执行 worktree 的
`.artifacts/input-read-batch-20261015/`：red、batch-green、native-measure、静态检查、
compatibility、baseline-compatibility、targeted 日志和 source-only 镜像身份。
私有证据不含 Provider 凭据；测试 DSN 仅保存在权限 0600 的临时状态文件，收尾删除。

页面连接恢复后，只执行一次新会话 A/B：相同公开搜索提示、相同高思考/v2，记录
首公开正文、带官方引用正文、模型 HTTP 前 SQL/连接数、实际工具和模型轮数。若
模型路径不同，分别报告观察结果和固定工作量归因，不反复调用模型刷结果。
保留正常六文件 Compose 组成、无 trace launcher、既有源码优化和无关工作区改动；
仅本地 cloud-agent-trench 集成，不推送、不发布 npm、不部署远端。

最终正常服务已更新并健康，60 个角色/源码哈希、原六文件 Compose、入口命令、
搜索镜像与配置核对通过；此次未启动临时 trace launcher。

## 2026-10-15 页面连接恢复后的首次尝试

新基线 A1 会话 `conv_1792077750802_3093b7` 在 11.757 秒显示服务不可用。
未建立 Cloud Session 绑定，模型/工具/沙箱调用均为 0；该错误提示不计为有效首正文。
API trace 显示扩展列表准入 Host 校验在约 2.036 秒返回 503：DNS 1.184 秒、
数据库连接合计 1.331 秒、registry SQL 54ms、JWKS 拉取 583ms，耗尽累积预算。
未对故障旧 Run 重放，也未为了配对继续发送候选模型请求。下一步先修复通用
TaskIO 解析子进程启动成本，页面配对仍待完成。子进程实测 JSON 模块加载约 310ms，
实际 DNS 约 47ms；单纯跳过 site 尚不足，不能把全部解析耗时归因于网络。

# QA-DESKTOP-E2E-01 真实浏览器流式恢复验收

## 目标

为 Desktop 建立可重复的真实 Chromium 发布门禁，覆盖长流式响应、页面重载恢复、
停止执行和终态后续问。该门禁验证真实 Vite 页面、FastAPI、Worker 执行、SQLite
事件存储和 replay-plus-tail SSE 链路。

## 测试边界

- 使用 Playwright 驱动真实 Chromium，不拦截或伪造 Zebra HTTP/SSE 请求。
- API 使用独立的 `UI/desktop/test-results/runtime/sessions.sqlite`，每次启动前仅清理
  这一固定测试数据库及其 WAL/SHM 文件。
- 外部模型网络由本地 OpenAI-compatible SSE provider 替换；它只提供确定性的分块
  内容和节奏，不替换 Zebra 的 Session、Worker、存储或流式协议。
- 单 worker 串行执行，避免固定端口和持久状态互相污染。
- 本门禁不覆盖 packaged Tauri/WebView、多浏览器和真实外部模型凭据。

## 回归矩阵

| 场景 | 浏览器断言 | 持久状态断言 |
|---|---|---|
| 长流式会话 | 首段先出现、末段尚未出现，随后 64 段按序完整呈现 | UI 收敛为 completed |
| 重载恢复 | 流式中刷新页面，恢复后 80 段无重复且顺序一致 | 从 durable SSE cursor 继续并 completed |
| 停止执行 | 可见停止按钮可点击，页面进入已停止 | 存在 `session_cancelled`，5 秒后仍无 `session_completed` |
| 终态续问 | 首轮完成后提交第二条消息，显示第二轮真实响应 | 创建不同 session，前后两个 session 均独立 completed |

真实浏览器首次运行同时暴露并锁定了两个 Desktop 回归：

1. 运行中发送槽的禁用样式吞掉停止按钮点击。
2. 终态续问重绑新 session 时未清理旧事件序列，导致新 session 从 sequence 0
   开始的事件被误判为重复事件。

修复分别落在停止按钮可交互条件和终态 session 重绑边界；Playwright 场景即为对应
的端到端回归保护。

## 本地运行

前置要求：Python 3.12、uv、Node 22.17.0、pnpm 10.28.2。

```bash
make sync
cd UI/desktop
pnpm exec playwright install chromium
pnpm e2e
```

定向运行：

```bash
pnpm exec playwright test --grep "stops a running stream"
pnpm exec playwright test --grep "submits a follow-up"
```

## CI 与失败证据

Quality 工作流的 Desktop job 安装锁定的 Python/Node workspace 和 Chromium，依次执行
Desktop checks、production build 和本套 E2E。单次 job 上限 20 分钟，单条 Playwright
用例上限 30 秒，CI 失败最多重试一次。

失败时 Playwright 保留 trace、截图和视频；CI 将 `playwright-report/` 与
`test-results/` 上传为 `desktop-playwright-evidence`，保留 7 天。

## 验收命令

```bash
pnpm install --frozen-lockfile --ignore-scripts
pnpm run "/^check:/"
pnpm build
pnpm e2e
make test
make check
```

验收完成后，结果写回 `PROGRESS.md` 和 `docs/AGENT_TASKS.md`；packaged Tauri、
迁移/备份、容量和故障注入证据继续作为独立后续工作，不由本任务代替。

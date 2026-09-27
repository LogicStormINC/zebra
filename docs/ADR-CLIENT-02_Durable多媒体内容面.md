# ADR-CLIENT-02：Durable 多媒体内容面

| 字段 | 值 |
|---|---|
| 状态 | Accepted for implementation |
| 日期 | 2026-09-27 |
| 任务 | REACT-MEDIA-01 |
| 影响范围 | AG-UI、Artifact、TypeScript contracts、React package、Host BFF |

## 1. 背景

Zebra 当前公开消息合同以 `content: string` 为主，Artifact 在 React 表面仅作为
文件列表出现。后端已经具备 Durable Event、Artifact MIME/字节存储、授权读取与
AG-UI Custom Event，因此多媒体能力不应再建立一套消息事实源，也不应把 Base64、
任意 HTML 或第三方脚本塞入 Markdown。

ADR-015 早期拒绝 Zebra React SDK；后续 ADR-CLIENT-01 和已经交付的
`@zebra-agent/react` 建立了受控 Client Integration Plane 与 Host-neutral React
package。本文只扩展这一现有边界，不恢复被拒绝的浏览器直连、前端状态权威或任意
DOM/JavaScript 执行能力。

## 2. 决策

采用两层内容面：

1. Zebra 原生类型化内容块负责文本、图片、视频、文件和 Vega-Lite 图表；
2. MCP Apps sandbox 只负责需要独立运行时的复杂交互界面。

所有二进制与大数据保存在 Artifact Store。Durable Event 和 AG-UI 只保存稳定的
内容块 ID、类型、状态、MIME、尺寸元数据和不透明 Artifact 引用。React Host 通过
受授权的 BFF preview URL 读取内容。

## 3. 类型化内容块

`AgentMessage.content` 保留以读取旧会话；新消息可携带有序 `parts`：

```text
text | image | video | chart | file | app
```

每个 part 必须有稳定 `id` 和 `state`。相同 ID 的更新执行 reconciliation；刷新和
重连必须从 Durable Event 重建同样的顺序和终态。大型 chart data 使用 Artifact，
不得在事件流中无限内联。

## 4. 传输与存储

- 文本继续使用标准 AG-UI text events。
- 已发布 Artifact 投影为 `zebra.content_part` Custom Event。
- 事件值只包含公开、安全、有界元数据。
- Artifact preview 使用现有 Host/namespace/task 授权；download 与 inline preview
  分离。
- 视频 preview 支持 `HEAD`、单一字节 `Range`、`206`、`Content-Range`、`ETag`
  与私有缓存策略。
- 当前存储 Port 只能整对象读取时，API 可先执行有界整对象读取后切片；该实现上限
  必须明确，后续由 Object Store range-read Port 替换。

## 5. React 包边界

- `@zebra-agent/ui-contracts`：纯类型、状态与 renderer 协议，不依赖 React。
- `@zebra-agent/react`：renderer registry 与 text/image/video/file/app fallback。
- `@zebra-agent/react-charts`：可选 Vega-Lite renderer；Vega 依赖不进入基础包。
- Host 控制 URL 解析、登录、下载鉴权、品牌主题和业务行为。

内置 renderer 必须允许按 part type 覆盖；未知类型显示安全 fallback，不能让整个
消息渲染失败。CSS 使用现有 `--zebra-agent-*` 变量，不注入全局 reset。

## 6. 图表

图表协议固定为受限 Vega-Lite JSON：

- pin schema major version；
- 禁止任意远程 data URL 和表达式执行；
- 限制 spec/data 大小；
- 卸载时 finalize view；
- 必须提供 title/description，并支持表格或静态图 fallback；
- renderer 通过独立 package 和动态边界加载。

模型不直接生成 React JSX、ECharts JavaScript 或任意 HTML。

## 7. MCP Apps

MCP App 只能由 Host 解析已批准的 `ui://` resource。React package 不接受任意
iframe URL。Host 必须提供资源解析器、允许的 origin/CSP 与 capability snapshot。
iframe 使用 sandbox；Bridge 校验 source、origin、版本、消息类型和请求 ID。未协商
的工具、导航、剪贴板、下载和弹窗全部拒绝。没有 MCP Apps 能力时降级为静态预览、
表格或文件卡片。

## 8. 安全与可访问性

- 禁止 `dangerouslySetInnerHTML` 渲染 Agent 内容；Markdown raw HTML 保持转义。
- MIME、文件名和 URL 均视为不可信；inline 仅允许安全 MIME allowlist。
- SVG 不直接执行；默认下载或由受控净化/栅格化链路处理。
- 图片必须有 alt；视频支持字幕/文字稿；图表有描述和表格 fallback。
- 媒体宽度不得越出消息列；移动端、键盘、减少动画和高对比度均需验证。

## 9. 验收

1. 旧 string message 与新 parts 在同一会话可回放。
2. 图片、视频、图表刷新后顺序、状态和 Artifact 绑定不变。
3. 跨 tenant/principal/task 读取被拒绝。
4. 视频 Range/HEAD 合同正确，非法或多范围请求 fail closed。
5. 图表远程数据、超限 spec 和未知 schema 被拒绝并显示 fallback。
6. MCP App 未授权 origin、消息或 capability 被拒绝。
7. React 18/19、Vite、Next SSR/RSC、Chromium/WebKit 和窄屏通过。
8. Trench 只通过打包产物消费，不使用源码 alias 或第二套 renderer。

## 10. 非目标

- 本任务不改变模型或思考强度。
- 不把 Redis、React state、MCP App 或 CopilotKit 作为执行事实源。
- 不发布 npm、不部署生产；发布与部署仍是独立证据门禁。

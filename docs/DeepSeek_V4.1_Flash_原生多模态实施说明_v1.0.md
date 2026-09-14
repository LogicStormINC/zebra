# DeepSeek V4.1 Flash 原生多模态实施说明 v1.0

## 决策

自 2026-09-10 起，DeepSeek V4.1 Flash 通过 `deepseek-flash` 提供原生视觉理解。
旧别名 `deepseek-v4-flash` 与 `deepseek-v4-flash-vision-exp` 仅为临时兼容路由。
Zebra 因此不再建设独立 Vision Agent 或先图转文的双模型通道，图片与文本由同一次
Flash 模型调用共同理解。稳定的 Zebra profile ID 暂不改名，以保持历史 Task、事件
和 Trench 请求兼容；profile 内实际 Provider model 改为 `deepseek-flash`。

官方依据：

- https://www.deepseek.com/en/news/deepseek-v4-1-flash/
- https://api-docs.deepseek.com/guides/responses_api/
- https://api-docs.deepseek.com/updates/

## 当前链路

1. Trench composer 接受 JPEG、PNG、GIF、WebP 和既有文档附件；选择图片时自动切换
   到 V4.1 Flash profile。
2. Trench 只转发文件名、媒体类型和 base64，不解释图片内容。
3. Zebra API 对文件数量、编码、真实格式、尺寸、像素和字节上限做信任边界校验。
4. 原始图片作为会话所属 Artifact 持久化；事件与队列只持久化引用、摘要、尺寸和
   媒体类型，不持久化 data URL。
5. Stateless Worker 按 Session authority 恢复 Artifact 字节并复核长度与 SHA-256。
6. Harness 仅在本次 USER message 上携带瞬态 Provider image data URL；该字段不进入
   事件 JSON、上下文 token 估算、摘要或记忆。
7. Chat Completions 发送 `text + image_url`；Responses 发送
   `input_text + input_image`，均使用 `detail=auto`。

## 安全与容量边界

- 最多 4 个附件；单图 16 MiB，单次图片合计 32 MiB。
- 单边不超过 8192 px，单图不超过 36,000,000 像素。
- 服务端根据文件头识别真实媒体类型，不信任文件扩展名或浏览器 MIME。
- Artifact 读取必须匹配当前 Session，且 payload 长度与 SHA-256 必须和耐久元数据
  一致。
- 图片只能进入 USER message；不会进入 system、assistant、工具参数或 Skill/MCP
  配置。
- 明确选择 Pro 的图片请求在 API admission 拒绝；历史 Pro Task 的追加图片在
  Worker recovery 再次 fail closed。

这些上限比供应商当前最大值更保守，是 Zebra 自身的内存、延迟与滥用保护，不是
对供应商能力的错误描述。

## 思考强度

界面提供 `关闭 / 低 / 高 / 最大`。其中关闭表示非思考模式；开启思考时 Provider
原生 effort 为 `low / high / max`。选择与图片输入相互独立，均由同一个
`deepseek-flash` 请求处理。

## 验收边界

- 单元：格式伪造、图片 profile、Artifact 写入/恢复、摘要校验、两种 Provider
  payload 形状。
- 集成：Trench 浏览器请求把图片、profile、effort 原样交给 Zebra；Worker 恢复后
  Provider 收到原生 image content part。
- 真实 Provider：仅在配置有效 `DEEPSEEK_API_KEY` 时执行，不以 mock 通过替代真实
  网络验收。
- 当前不实现 Files API、图片 URL 抓取、OCR 派生证据、图片编辑或视频输入；这些
  能力需要各自独立的权限、生命周期和成本设计。

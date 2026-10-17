# Exa 匿名 MCP 可选补充：准备与验收边界

日期：2026-10-17。任务：CLOUD-EXA-OPTIONAL-01。

## 结论

已准备原生 SearXNG 可选引擎、显式 Compose overlay 和离线回归。
**Yahoo 仍是唯一默认引擎；正常 API、Worker、搜索服务未更新或重启。**
本轮不修改模型提示词、工具选择策略、Trench 产品逻辑或全局代理。

四组无模型真实检索中，Exa 补回 Redis 官方发布页，但整体检索中位耗时
更高。仅验收“可选补充的实现准备”，不验收稳定性能收益，不启用正常环境，
不进行真实页面或模型配对，不声称减少 SQL 或首正文延迟。

## 接入边界

- 官方匿名入口：[Exa MCP](https://exa.ai/mcp)；
  [官方服务源码与匿名限流说明](https://github.com/exa-labs/exa-mcp-server)。
  匿名 MCP 与需密钥的 REST API 不同；匿名额度及恢复时间不保证。
- 固定 HTTPS 入口 `https://mcp.exa.ai/mcp?tools=web_search_advanced_exa`。
  调用 `web_search_advanced_exa`，不接入任意第三方 MCP 地址。
- 沿用 SearXNG online processor、已有 native HTTP 连接池和请求取消机制。
  不增加依赖、独立网络服务或 Cloud 授权缓存。
- 只有 operator 显式选择 overlay 后才注册 `!exa`；引擎仍为 disabled，
  排除在默认检索中，但允许显式选择。普通查询仍只走 Yahoo。
  当前正常 Worker 工具说明未宣告新能力；尚未扩大到模型自动发现/页面验收。
- 固定 query 原文；fast、最多 5 条、关闭 summary/highlights、正文每条
  最多 1000 字符、livecrawlTimeout=1000ms。不硬编码来源或改写搜索问题。
- 只接受显式的逐结果 URL。现有 Cloud 结果规范化保留 URL/输出边界，
  后续实际抓取继续经过现有 DNS/SSRF 校验。MCP 不负责替代这些校验。
- 新鲜 Cloud 授权及 DNS/SSRF 生产代码未修改。后端隔离检索不等价于
  已认证 Cloud 工具或页面的端到端安全验收。

## 限流、冷却与回退

1. 识别 HTTP 429、RPC 限流错误、MCP isError，以及 HTTP200、没有
   isError 标记但 content.text 为免费额度/限流提示的响应。初始化和通知
   帧的 HTTP429 同样执行冷却。合法结果正文提到 quota/rate limit 不误判。
2. 一次 Exa 阶段最多 2 秒；初始化、通知、检索共享该预算，零 Exa 重试。
   native 总请求预算最多 6 秒。后续 Yahoo 只能使用原始截止时间内的余额，
   不重新计时。已取消或超时直接传播，**不发起迟到的 Yahoo 回退请求**。
3. 明确的限流触发至少 900 秒冷却；较长的 Retry-After（秒数或日期）
   优先。超过 24 小时则关闭自动恢复，保留阻断状态供 operator 处理，
   不把服务器要求缩短成 24 小时后自动探测。
4. 其他明确的协议/结果错误冷却 60 秒，当前请求在剩余预算内回退 Yahoo。
   网络超时/取消不是上述可恢复协议错误，不在同一请求内重试或回退。
5. 冷却或已有在途探测时，直接使用已加载的 Yahoo 引擎及其连接池、
   原有请求/parser，不发 Exa 控制帧或检索帧。回退 snippet 加
   `[Yahoo fallback]` 标记，不能把回退结果当成 Exa 召回收益。
6. 现有持久 TMPDIR 下 `zebra-exa-control.json` 保存截止时间和探测 lease，
   不保存 query、结果、Cloud 授权或密钥。文件权限 0600，拒绝符号链接，
   flock 保护短读写，一次仅允许一个匿名探测。owner 避免旧请求清除新 lease。
   异常/损坏状态禁止新的 Exa 探测；写入失败可显式失败，不伪装成功。
7. 当前只协调**同一共享本地卷**上的进程/容器；不是多主机配额协调器。
   停电导致部分写入后以损坏状态关闭探测；不提供数据库级持久性保证。
   匿名 MCP session 仅进程内复用，不是授权缓存。请求被取消后不重置配额状态。

严禁通过清理状态文件、换 session/出口/身份或反复重启来规避限流。
真实验证继承了前一轮已知限流批次结束时间加 900 秒的截止时间；首次调用前
该时间已过去，没有宣称上游配额确定恢复，也没有删除或重置控制状态。

## 实施文件与准备命令

- `docker/web-search/zebra_exa.py`：原生可选引擎及上述控制。
- `docker/web-search/check_exa.py`：单个可运行、禁网的 assert 检查。
- Dockerfile：保留原有取消、Yahoo 出口与耗时补丁；复制可选引擎，从当前
  base settings 构建 opt-in settings 快照。修改 base settings 后须重建镜像。
- `compose.exa.yml`：仅指定可选镜像与 settings 路径；正常 compose/settings
  与默认镜像选择未变。

在仓库根目录准备镜像：

```sh
docker build -t zebra-searxng:exa-optional-01 docker/web-search
```

运行离线回归（不会调用 Exa/Yahoo/模型）：

```sh
docker run --rm --network none --read-only --tmpfs /tmp \
  -e PYTHONPATH=/usr/local/searxng \
  --entrypoint /usr/local/searxng/.venv/bin/python \
  --mount type=bind,source="$PWD/docker/web-search/check_exa.py",target=/checks/check_exa.py,readonly \
  --mount type=bind,source="$PWD/docker/web-search/zebra_exa.py",target=/checks/zebra_exa.py,readonly \
  --mount type=bind,source="$PWD/docker/web-search/settings.yml",target=/checks/settings.yml,readonly \
  zebra-searxng:exa-optional-01 /checks/check_exa.py
```

**以下为未来 operator 显式启用操作，本轮未执行：**

```sh
docker compose -f docker/web-search/compose.yml \
  -f docker/web-search/compose.exa.yml up -d --no-deps searxng
```

复用现有 `SEARXNG_YAHOO_PROXY` 指定的受控出口；独立 Exa 路线可通过
service env 中 `SEARXNG_EXA_PROXY` 配置，不改变全局代理。无上述变量时
沿用 native outgoing 设置；启用前应核对部署出口符合当前安全要求。
必须保留既有 `search-cache` 卷；回退到正常组合也不删除冷却状态。

## 本轮验证

离线 native 检查通过：原生引擎 loader、默认仅 Yahoo、HTTP/RPC/文本限流、
初始化/通知限流与 Retry-After、跨进程冷却、8 路竞争仅一个 lease、旧 owner
隔离、损坏状态关闭探测、零 Exa 帧回退、取消与原始截止时间。
通知429处理的回归先复现失败，再用最小修改修复；没有依赖真实限流取样。

现有无模型 Cloud 搜索 transport、public DNS、搜索/网关工具检查共 37 项通过。
代码 Ruff/格式通过。新增引擎镜像实际 native 启动和 healthz 通过，配置显示
Yahoo enabled=true、Exa enabled=false。只读检查默认配置与原有取消补丁。

固定四题、固定官方 URL allowset、交错 AB/BA/BA/AB，一格一次：

| 问题 | Yahoo 官方目标 | Exa 官方目标 | Yahoo ms | Exa ms |
| --- | --- | --- | ---: | ---: |
| Redis 8 GA | 未命中 | 命中 | 2196.930 | 1979.627 |
| PostgreSQL 18 发布 | 命中 | 命中 | 947.977 | 1258.668 |
| SQLite WAL | 命中 | 命中 | 772.110 | 1966.734 |
| Python 3.14 发布 | 命中 | 命中 | 830.811 | 1205.365 |
| 合计/中位数 | 3/4 | 4/4 | 889.394 | 1612.701 |

Yahoo SQLite 的 sqlite.org 与 www.sqlite.org 已在调用前同时列入 allowset。
原始探针仅按第一个 URL 计分的 false 保留；现有 Cloud normalizer 与预定
完整 allowset 的离线裁定为命中，没有事后扩大来源标准。

Exa 本组 4 次有效结果、0 错误、0 回退；未真实触发429。真实限流后的
生产回退尚未观测，正确性证据来自禁网注入回归，不能混称已完成真实配额验收。
Exa 中位数多 723.307ms（约81%）；四题样本小、Yahoo 正常服务已热，候选
首个请求包含首次 MCP 初始化，不能据此推导总体或页面耗时分布。
因此不扩展模型/页面批次；匿名容量及稳定收益仍未通过。

第一版隔离候选因 `network` 导入名撞上原生保留字段而未启动，零 Exa 请求。
完整失败日志及当时 4 次 Yahoo 控制保留，未用这批错误做性能比较；修正导入
并加入 loader 检查后，才进行上述独立四组检索。首次启动失败不能从记录中删除。
真实检索后对通知429分支做的修复不改变成功调用参数或默认路由；最终源码
重新构建与离线检查，不追加选择性真实请求。

私有原始协议、构建/启动失败记录、原始/规范化检索结果、测试日志及服务
前后摘要位于 `.artifacts/cloud-exa-optional/`，不把本机证据当成可移植测试夹具。
本轮未调用模型、未改 Run、未更新正常服务，未推送或远端部署。

## 下一步门槛

只有在实际低频工作量中，召回提升可复现且失败/耗时成本可接受，才考虑
宣告可选工具能力并进行高思考、v2 的真实页面配对。沿用同题对照、保留
限流失败、不重置状态；若配额再次限制，遵守冷却并保留 Yahoo，不扩大压测。
当前可选实现准备完成不代表此门槛通过。

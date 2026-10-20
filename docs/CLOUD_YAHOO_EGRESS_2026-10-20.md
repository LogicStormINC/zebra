# Yahoo 独立出口修复与验收 — 2026-10-20

任务：CLOUD-YAHOO-EGRESS-20261020。负责人：Luke Ding / Codex。

正常服务的 `web.search` 已恢复。本轮仅一次 NBOPC 真实工具调用，
3,261.81 ms 返回 5 条结果，官网排名第 2。没有新模型请求、新 Run、
原 Run 重跑或历史事件修补。这是正常 Worker 工具链验收，不是页面／模型
端到端配对，也不据此声称长期稳定性或 Google 等价召回率。

## 根因与耗时边界

服务器全局 Mihomo 的实际运行模式是 DIRECT；配置文件与运行时分别留存
哈希。旧 Yahoo 代理端点 `http://127.0.0.1:7890` 接受 CONNECT 后，
仍通过直连出口建立目标连接。同期代理日志明确记录：

- search.yahoo.com:443 的直连 IPv4 TCP 超时，IPv6 网络不可达。
- 解析地址包括 162.125.32.9、103.252.115.49 和不匹配的 IPv6 地址。
  独立、证书校验通过的 DoH 返回 Yahoo 的 AWS CNAME 链及另一组地址。
  这些证据定位到解析／直连出口，尚未定位异常 DNS 答案的注入来源。
- CONNECT 是代理的提前接受，不代表目标 TCP 已接通。

一次有界、无搜索的分段检查：代理 TCP 2.158 ms，CONNECT 200 在
2.525 ms；目标 TLS 于 5,004.138 ms 报 SSLEOFError，未发送 HTTP HEAD。
因此原来的五秒预算消耗在出口目标连接阶段，不能算作 Yahoo HTTP
处理时间，也不能把失败路径中接近截止时间的 starttransfer 当作响应。

服务器原先选中节点的健康记录停留在 7 月；独立复制该节点仍在 TLS 前失败。
此失败样本保留，没有轮换节点或扩大搜索样本。最终复用当前本机访问
Yahoo 时实际经过的已有节点，单节点配置经 SSH stdin 传入同一运营服务器，
未在仓库、命令参数、日志或报告中保存凭据；没有订阅刷新或全局代理修改。

## 最小修复

不修改产品源码，不新增依赖。复用已有 `SEARXNG_YAHOO_PROXY` 原生配置
入口、现有静态 Mihomo 二进制和已安装 Search 镜像：

- 新增独立 `zebra-yahoo-egress` 服务，监听服务器 127.0.0.1:17890。
- 唯一出口规则为 Yahoo 域名后缀，其余 MATCH,REJECT；不开放控制接口。
- 保留节点与 Yahoo 的证书校验，非 root、只读容器、ALL capabilities drop、
  no-new-privileges，日志轮转；配置只读挂载，凭据文件 0600、父目录 0700。
- 使用 restart-unless-stopped，运行不依赖本机或 SSH 隧道；不修改原代理服务。
- 正常 Search 只有一个环境项变化：
  `SEARXNG_YAHOO_PROXY=http://127.0.0.1:17890`。
  image、命令、配置文件、挂载、预算与其他引擎保持不变。

原生网络配置只在 Search 启动时组装，没有现成热更新接口。用户明确允许
一次搜索服务重建并接受 MCP 会话重新初始化。本轮准确执行一次；没有
主动调用 Exa 初始化、搜索或清除冷却。重建时有效租约与待处理命令均为 0。

Yahoo 默认、Exa 可选 fast、冷却和回退保持原样。Yahoo 5 秒／Search 6 秒
预算未增加。Worker 新鲜授权、固定后端 DNS/SSRF/TLS、请求级取消和公开
结果 URL 校验沿用原链路；未增加答案缓存、权限旁路或强制引擎选择。
高思考和 stream v2 未改变；独立的 web_pipeline_v2 仍为 false。

## 无模型验证与一次真实检索

出口先通过证书校验的 TLS／HEAD 检查，再允许 Search 重建：

| 检查 | 结果 |
| --- | --- |
| 独立出口原始 TLS 诊断 | TLS 421.510 ms；收到响应 568.144 ms |
| 实际 SearXNG 原生客户端 HEAD | TLS 205.775 ms；首响应 382.611 ms；HTTP 200；总计 386.19 ms |
| Yahoo 原生代理配置回归 | 显式配置仅作用于 Yahoo；unset/empty 保留默认 |
| 截止／取消回归 | 取消本请求 future；并发 sibling 正常结束；无真实网络 |
| 原生 0 状态回归 | 仅既有有界恢复；持续 0 失败；403／429／captcha 不重试 |
| 错误计时与脱敏回归 | 原异常／取消／成功身份保留；不输出 URL、查询、正文或认证信息 |

四项脚本均在已安装 Search 解释器的独立进程中执行，未接触服务内 MCP 会话。
复用现有脚本，没有扩大到历史 fixture／测试设施修复。

唯一一次 NBOPC 调用经正常 Worker LocalToolGateway／WorkerToolGateway、
正常 HTTPS Search 后端和默认引擎执行；使用操作员只读授权并执行 73 次
策略／取消检查，没有创建用户 Run。因此不声称已重新验收用户身份准入页面。

| 指标 | 结果 |
| --- | --- |
| 工具耗时 | 3,261.81 ms |
| 状态 | executed；provider=searxng；5 条结果 |
| 官网 hit@5 | 是，第 2 名，https://nbopc.org.cn/ |
| 其他相关来源 | https://nbopc.org.cn/about；https://www.opcquan.com/communities/ningbo-nbopc-opc |
| 新模型请求／新 Run | 0／0 |
| 限流／自动重复／Exa 请求 | 未观察到限流；无自动重复；未调用 Exa |

上一轮 6,049.68 ms 超时失败与本次成功样本分别保留。这是故障恢复证据，
不是成功对成功的统计性能配对。HEAD 分段计时也不替代真实查询分段计时；
本次查询没有达到既有原生慢请求日志阈值，没有虚构其 TLS／上游等待比例。

## 运行状态与后续部署

私有发布目录：`/home/ubuntu/releases/20261020-yahoo-egress/`。

- `egress-compose.json`：独立出口项目；`config.yaml`：私有单节点配置。
- `state/`：出口运行状态；没有在仓库保存节点凭据。
- `search-override.pending.json`：名字来自准备阶段，现已实际生效，必须与
  原 `20261019-zebra-trench/config/search-release.json` 一起使用。
- `search-recreation.once`、`nbopc-acceptance.once`：防止本轮自动重复。
- `rollback.private.json`、`activation.safe.json`：原镜像／挂载／冷却及变更凭据。

后续部署必须保留上述 Search override 和独立出口，不能只用原 base Compose
覆盖配置。出口使用现有运营节点，其账号／网络可用性仍是外部依赖；没有
扩大为节点调度、自动轮换或全局代理管理功能。

Search 新容器 e59d0718，原镜像 sha256:2f4a6b36 未变，健康且无启动 traceback。
独立出口 bf1375ff，健康、重启次数 0。Worker、API、Trench API、TLS、Broker
的容器身份、镜像、环境、启动时间、重启次数和挂载集合保持不变。
Search settings.yml 与 Exa control 字节哈希不变；服务器全局代理文件和
实际运行配置哈希完全相同，本机源配置也未改变。
四个受保护原 Session 的事件数量、内容哈希和模型请求计数完全相同。

若需要回滚，先按相同租约／命令检查确认空闲，再由操作员明确授权额外的
Search 重建，去掉本任务的 override 后仅重建 searxng；原 7890 出口故障会
随之恢复。确认 Search 已不再使用 17890 后，才可停止本任务独立出口。
本轮一次重建额度已使用，不自动执行回滚重建或新搜索验收。

本地证据：`.artifacts/cloud-yahoo-egress-20261020/`，包括分段计时、一次
NBOPC 结果、无模型回归与前后保存凭据；私有原始快照不提交 Git。
原 cloud-agent-trench 归档引用不变；本轮没有 Trench 产品逻辑修改或 GitHub 推送。

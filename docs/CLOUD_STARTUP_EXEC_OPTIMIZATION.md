# CLOUD-STARTUP-EXEC-01

2026-10-15。只优化本地已确认的TLS bridge缓冲。

## 根因

Docker CLI27.5.1 exec的attach使用MobyClient.Dialer TLS直连，普通HTTP代理环境不覆盖hijacked流。原socat OPENSSL-LISTEN缺少TCP_NODELAY，daemon exec_create→exec_start457–671ms，exec_start→exec_die13–17ms。探针本身很快；不能把整次exec1.1s误归为runsc命令处理。

官方源码：
- https://raw.githubusercontent.com/docker/cli/v27.5.1/cli/command/container/exec.go
- https://raw.githubusercontent.com/moby/moby/v27.5.1/client/hijack.go
- https://raw.githubusercontent.com/moby/moby/v27.5.1/client/client.go

## 最小修复

给已有docker/local-gvisor/zebra-docker-tls.service的OPENSSL-LISTEN加入nodelay。端口2376、绑定地址、CA/SAN/client证书verify=1、unix后端、配置身份摘要、每命令新鲜/info检查、完整ID/labels、PG authority/fence和workspace探针均保持。只重启bridge，不重启Docker daemon或复用沙箱。

## 验证

三个交替无模型正规PG/gVisor生命周期对：首次exec均值1071.654→727.978ms（32.1%），provision1667.888→1291.748ms（22.6%）。临时2377 mTLS listener只用于对照，与原相同证书/daemon；六容器destroy并标removed，随机schema删除。

真实旧基线运行：provision2247.365ms；其后persist authority50.254ms、tool gateway13.019ms、harness task2.819ms、continuations0.020ms、orchestrator40.678ms。登记后主要成本仍在runtime命令；不改已很短的模型前构建步骤。

61聚焦runtime/worker回归通过，包括配置负对照旧unit失败、新unit通过。Ruff通过。临时浏览器MutationObserver只记录发送点击和正文DOM时间，不记录正文/凭据；验收后撤。DOM可见时间不等于像素绘制时间或模型首token。旧基线正文12.840s，模型请求前5.396s；真实新样本待完成。

证据主工作区.artifacts/startup-exec-20261015/。只本地集成/bridge激活；不push。

## 本地激活与真实验收完成

正常2376unit与repo一致/active，匿名TLS拒绝，原daemon未重启；临时2377监听停止、六隔离容器与schema清理。Worker正常入口/healthy/preflight ready，浏览器临时计时撤销，无push。

旧基线first model5.396s，新4.789/4.469s均值4.629s（-14.2%）；发送点击→首正文DOM旧12.840s，新12.133/9.426s均值10.779s（-16.0%）。均v2/Flash/high/general，新会话，1主模型round/0tools。小样本观测；页面计时不是像素绘制或模型首token，首显变化还包含Host创建前/UI同步波动。可归因纯bridge收益以三交替无模型生命周期对照为准。

详细证据主工作区.artifacts/startup-exec-20261015/REPORT.md。61聚焦检查/Ruff GO；不改变短而正常的模型前构建步骤。未来定位发送→Run与完成→UI同步，避免把后端优化收益直接当作浏览器TTFT收益。

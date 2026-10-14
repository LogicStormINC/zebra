# CLOUD-STARTUP-DNS-01

2026-10-15。本地cloud-agent-trench后续切片。

## 根因

真实v2 Run d5add20d-be84-4787-8d6a-820b039efa1f：输入恢复654.721ms，上下文准备1077.240ms，其中TaskIO冷解析分别379.945/389.449ms。租约前handoff/header/lease路径也有冷解析。不同adapter或每次tick的临时PostgresDatabase拥有不同connector，30秒实例缓存不能消除这些冷启动。当前简单显式DSN仍在子进程导入完整psycopg，实际等待主要在import，而不是SQL查询。

## 最小实现

只修改task_io.py内既有RESOLVE_SCRIPT。单一显式host+数字port、无service/prefer-standby/random时，子进程使用stdlib socket.getaddrinfo，返回原参数加hostaddr。原host保持TLS hostname和密码查找语义。multi-host、service、环境继承的host、默认port及特殊host ordering仍沿用psycopg路径。

不改Popen/communicate deadline/kill/reap、PG配置签名、30秒地址缓存、地址失败后的失效、连接/SQL/COMMIT预算、每次新连接或mutating重试。既有共享连接器继续复用。不新增全局缓存、IP写死或依赖。

## 聚焦验证

先添加python -S无site-packages回归，旧脚本因导入psycopg失败，优化后通过。八组单/多host、PGHOST、默认port、prefer-standby和random与既有psycopg attempts逐项对照通过。真实本地scratch PostgreSQL包括service文件更新、新连接、cache invalidation、DNS/handshake/COMMIT/query取消与清理：30 passed，零skip。Ruff/mypy针对性验证。

Worker内六组交替冷解析+真实SELECT1：均值385.714→69.870ms，降低81.9%，缓存后的连接查询保持约4.5–7.3ms。仅冷解析微基准，不能直接换算整个Run收益。

证据：.artifacts/startup-dns-20261015/。本地Worker/v2 API正常入口已激活并验收；全量测试/远端发布不在本切片范围。临时诊断launcher记录阶段/耗时/调用函数名，不记录参数或凭据，最终恢复正常entrypoint。

## 本地真实后测完成

- 正常配置最终两次first model等待5.375/4.626s，均值5.001s；上轮三样本7.278s→5.001s，降低31.3%。本轮旧基线7.372s，另两个仅Worker更新5.880/5.762s。
- API与Worker源hash一致/healthy，preflight ready，临时诊断入口已撤，恢复原entrypoint。均1主模型轮/0工具/v2/UI正文显示。没有浏览器精确首字计时，不将first model冒称TTFT。
- 单一源文件衍生镜像，无依赖变化；30真实/确定性聚焦测试零skip，Ruff/mypy GO，无push。报告主工作区.artifacts/startup-dns-20261015/REPORT.md。
- 均值为小样本前后观测对比，不承诺全部任务或p95；登记前仍均值2.419s、登记后2.582s，后续独立切片。SQL调用数没有变化。

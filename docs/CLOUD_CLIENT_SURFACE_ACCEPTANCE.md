# CLIENT-SURFACE-01 本地验收

2026-10-15。基线514151c0，Zebra分支codex/client-surface-01，Trench companion
2731737。授权集成目标cloud-agent-trench；本地启用，无push/npm发布/远端部署。

## 交付内容

新增POST `/v1/tasks/{task}/runs/{run}/client-surface`，组合现有mount和bind。
Client open仍独立，准入3→2次HTTP。`/capabilities/runtime`增加
`client_surface_contract_version`，完整Client存储组合返回1，否则0。

入口保留独立Client credential与每次新鲜HostGrant签名/registry/nonce验证，在
消费nonce之前验证精确Task/Run/principal/issuer；直接路由调用再次验证当前授权。
请求字段严格、能力列表最多128，整个新处理入口受累计2s及Grant到期预算约束。
使用原领域服务与数据库实现，无迁移、bearer缓存或新凭据协议。

相同请求重试复用binding并轮换controller fence，旧fence失效。mount或binding
可能在后续失败前已经保存，错误仍表示未就绪；不自动fallback/reopen/重试，不派发模型。
竞争Client由原数据库唯一控制租约裁决。

npm client-core提供`mountClientSurface`，调用者注入已有授权transport；显式版本1
只发组合请求，否则走旧mount+binding。错误不回退，响应必须满足digest/UI revision/
能力交集/fence约束。Trench仅在现有能力探测结果中传递版本，无额外探测或产品策略。
已广告组合入口的任何失败都不会被原“可选Client降级”路径吞掉。

完整open+mount+bind三合一未实施：原credential和fence仅存hash，open响应丢失后
不能再次取得原secret；本轮不为少一次请求引入secret持久化或更换凭据协议。

## 发现并修复的真实回退

B1组合入口首次使用限时连接，使三个Client数据库适配器各自冷解析；共201.1ms，
Client窗口反而从249.6ms增至430.7ms。该结果保留，不以页面首正文偶然变快掩盖回退。

B2通过API composition向frontend capability/session/control lease三个适配器传递
Cloud现有TaskIoConnections。只复用已有30s地址解析缓存，不复用连接、事务、Grant
或权限结果。传入不同DSN立即拒绝。Worker默认composition不变。新片段没有重复缓存。

## 无模型检查

隔离且已移除的PostgreSQL，真实Task/Run事实和Client存储。按AB/BA交替共10对，
同权限和能力，setup不计入。直接RouteAdapter测量，不冒称真实HTTP/Host耗时：

| Client存储阶段 | 原mount+bind | 组合入口 |
| --- | ---: | ---: |
| SQL execute调用 | 13 | 12 |
| 实际新PG连接 | 10 | 9 |
| 耗时中位数 | 88.09ms | 80.86ms |

此表不含Host HTTP授权/Task持久权限读取/真实profile注册表；这些成本在下面真实
页面阶段统一计入。不是整个Run SQL的减幅。

原生检查证明响应丢失重试同binding、旧fence续租被拒绝、两个Client竞争同Run只有
一个201且另一409、仅一条控制租约。另验证精确Task/Run/issuer/thread在nonce前拒绝，
直接路由未验证Grant/错误principal不产生mount/binding，非法字段/凭据/过期/撤销拒绝。

## 三场真实页面测量，全部保留

相同全新公开搜索问题：核对PostgreSQL18/Redis8正式发布日期、两项新特性和官方链接。
DeepSeek Flash，thinking enabled/high，transient_v2。每场新Task/Run，不重放旧Run。
三场均completed、无模型重试/工具失败、无OCI实例；搜索并发峰值2。

| 指标 | A1原路径 | B1初版 | B2最终 |
| --- | ---: | ---: | ---: |
| Client HTTP次数 | 3 | 2 | 2 |
| Client窗口 | 249.59ms | 430.70ms | 197.96ms |
| Client HTTP内部总计 | 213.95ms | 411.50ms | 184.97ms |
| Client SQL execute调用 | 38 | 36 | 36 |
| Client额外冷解析次数 | 0 | 3 | 0 |
| Client解析耗时总计 | 0.54ms | 201.11ms | 1.29ms |
| 点击→首次模型HTTP | 3348.15ms | 3289.52ms | 2958.44ms |
| Worker→首次模型HTTP | 1190.27ms | 1247.63ms | 1079.71ms |
| 首段可见正文/过程正文 | 4560.80ms | 4323.90ms | 4378.80ms |
| 同时含两站官方链接的正文 | 29952.50ms | 29385.00ms | 24653.20ms |
| canonical完成 | 30931ms | 29387ms | 25675ms |
| 模型轮数 / 工具次数 | 4 / 6 | 4 / 6 | 4 / 5 |
| Worker启动SQL / 连接 | 412 / 65 | 412 / 65 | 412 / 65 |

可直接证明的是少一次Client HTTP/授权交换，实际Client SQL少2次（5.3%），本组
Client窗口缩短51.6ms（20.7%）。点击到模型HTTP少389.7ms（11.6%），但包含其它
阶段调度/网络波动，不能全部归因于Client合并。首段可见正文仅少182.0ms（4.0%）。

B2比A1少一次Redis release索引抓取，网络与模型行为也有波动，最终正文/完成时间
约5秒差值不是本轮纯性能收益。未做多组统计/P95/冷Pod规模验收，不宣称普遍百分比。

A1：[基线页面](http://localhost:3000/dashboard/strategy/conv_1792064405028_7e2709)，
Run16c88c01-af46-44df-b728-105639c9006e。
B1：[保留回退](http://localhost:3000/dashboard/strategy/conv_1792064553460_8d8772)，
Runf2828e2f-3c33-4516-bf95-ed2b30df1b60。
B2：[最终页面](http://localhost:3000/dashboard/strategy/conv_1792064875963_3e1c7a)，
Run5d3f05b9-bc4e-4952-8c07-d6ed91bb61cb。

## 验证与运行状态

- 原生PostgreSQL、API Client/Host/Task权限及platform composition：85 passed，10.61s。
- Trench消费协商及原gateway：18 passed、2 existing integration skips，0.86s。
- SDK Node24.19：pnpm check（5包构建+类型检查）通过，Client相关25项通过。
- 源码Ruff、mypy1283、file-size3082/0violations、deterministic eval30通过。
- 原`make check`被未跟踪私有.artifacts中的trace脚本Ruff错误阻断；未扩大修复。
  单独执行`ruff check --extend-exclude .artifacts .`及其余三个子门确认源码门通过。
  未运行整个make test；focused/native门和全套测试结论不混用。

正常服务恢复原6个Compose文件与入口/命令，撤除trace launcher/页面观察器。
API更新11个本轮源码文件；Worker保留5d086202原镜像与既有43项接受源码身份，搜索
镜像/代理/设置保持，正常页面刷新恢复同一Run结果。未调用历史会话模型。
私有原始计时、canonical、SQL数量和源码hash保存在.artifacts/client-surface-20261015，
不提交凭据/日志。隔离测试数据库容器与私有DSN已移除。

后续若继续优化，应按实际跨度选择下一片段；本轮不再扩修上下文/fixture/检索策略。

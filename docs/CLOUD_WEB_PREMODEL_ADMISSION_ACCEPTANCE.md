# Cloud 搜索首个模型请求前等待拆解

日期：2026-10-15。任务 WEB-PREMODEL-ADMISSION-01，基线35032a07。
本轮为诊断与下一切片方案；没有修改生产源码、配置或依赖，没有新增性能收益主张。

## 新真实页面的完整边界

只发起一次新的真实公开搜索请求，同一PG18/Redis8发布日期/新特性/官方来源问题。
Flash/high；canonical completed、transient_v2，5轮模型，8次成功工具，0工具失败，
0沙箱实例，网络峰值2；模型回执均enabled/high/retry0。保留本次实际检索路径，
没有为了凑配对或更好结果重复模型请求，也没有恢复/重放旧Run。

Run：2dfa06f1-1240-4fb3-a5b6-8046c0468f0a

http://localhost:3000/dashboard/strategy/conv_1792062339500_e7501d

页面点击→实际Provider HTTP为3231.645ms；首段公开过程文字4911.400ms。
后续整轮35.212秒、官方链接34.364秒，不是本轮启动耗时；本次做了更多检索/抓取。
它不是上一轮3轮/4工具请求的性能对照，不用来宣称整轮变快或变慢。

| 互不重叠的启动区间 | 耗时 |
| --- | ---: |
| 点击→首个Cloud HTTP进入 |419.169ms|
| 首个Cloud HTTP进入→command响应 |1418.675ms|
| command响应→Worker执行进入 |243.194ms|
| Worker执行进入→实际Provider HTTP |1150.606ms|
| 合计 |3231.645ms|

四项可直接相加，安全分析脚本逐项对账。点击前页面导航不计入；Provider实际请求
由原read_openai_stream入口记录，不用model_request_started事件替代网络边界。
首次Cloud请求包含/v1/extensions前缀，避免把Skill请求漏到Host外部区间。

页面ResourceTiming确认创建会话约45ms，发Turn约67ms；这些请求、路由、snapshot
与Host后台派发存在间隔/重叠，不能直接相加为419ms的精确内部归因。Trench源码
仅只读；第一段混合页面/Host/传输，尚没有Host内部独立span。

## 准入链路的真实组成

| 必经Cloud HTTP | 时长 |
| --- | ---: |
| GET /v1/extensions/skill-installations |161.043ms|
| GET /capabilities/runtime |41.409ms|
| POST /tasks |317.066ms|
| POST /v1/client-sessions |43.298ms|
| POST /v1/client-sessions/{id}/mount |78.257ms|
| POST /v1/tasks/{task}/runs/{run}/client-bindings |92.474ms|
| POST /agui/commands |219.229ms|
| HTTP方法完成时间合计 |952.776ms|

剩余约465.899ms为请求之间的Host处理、独立Grant交换、网络和调度混合。
Host-binding renewal约119.7ms与Worker启动重叠，未叠加到关键链路。
请求方法计时包含授权/路由嵌套，不能与内部span再相加。

首次Skill请求授权146.4ms，相关Task I/O连接累计132.1ms，JWKS resolve仅0.087ms。
启动公钥热身已生效，不存在这次请求临时抓公钥的证据。后续授权约18–40ms，
每次仍读取当前Host registry、验证Grant/目标、原子消费nonce，不应缓存授权结果。

POST /tasks的api_create_session为238.3ms，整个route275.2ms。主要SQL成本为
首次事件落库、Task源位置分配及索引回填；_assign下14次SQL累计53.1ms。
没有把这些持久事实/兼容索引当作可直接跳过的检查。Worker输入准备247.4ms、
Context340.2ms，其中两次有界输入刷新71.2/122.2ms、身份事实132.0ms，属于嵌套跨度。
Context的两次刷新隔着不同canonical提交和materialization，不能用“看起来相同”
为由直接删去。Worker启动仍为412显式SQL/65Task I/O连接，前轮收益保留。

## 最小下一切片：通用Client组合准入

目前read-only追踪没有找到一个可安全删除、足以解释整段3.23秒的大重复工作。
继续只做数毫秒的读函数微调，收益上限有限。下一实现应优先减少串行网络往返，
保持领域验证，不把Trench产品规则引入Cloud Agent。

建议先组合Client open→mount→bind这三个相邻操作，Task创建和command保持原边界。
本次三步窗口1057.6→1538.3ms，共480.712ms；HTTP内部214.029ms，间隙266.682ms。
三次授权合计约70.4ms。组合后仍需要实际存储与权限校验，不能承诺省掉全部481ms；
基于本样本可验证目标是数百毫秒级，约0.3秒仅为方案估计，不是验收结果。

代码层面复用既有实现：

1. 在apps/api/src/zebra_agent_api/client_runtime_routes.py附近增加一个明确的组合路由，
   例如POST /v1/tasks/{task}/runs/{run}/client-surface；先由独立任务定义完整契约。
2. 复用packages/agent-control-plane/src/agent_control_plane/client_admission.py中
   ClientAdmissionService.open_session/mount与ClientBindingService.bind_run。
   HTTP适配器只顺序组合，保留每个领域操作的校验，不复制领域规则或写通用批处理器。
3. 请求明确携带原Client Grant、frontend profile/mounted能力、ui revision和binding
   范围；任务/run/path/Host namespace必须一致；对body大小/字段/能力数量设置原有边界。
   一次HTTP仍新鲜验证Host签名/目标、消费一次nonce，各操作继续读取当前Client/Profile/
   controller状态；复用的是同一已验证请求上下文，不是跨请求授权缓存。
4. 幂等、部分成功、credential返回丢失及controller fence必须先定义恢复语义。
   既有三个领域调用各自持久化，不得声称天然是跨表原子事务；复用已有事务或显式
   幂等恢复，不能把HTTP重试变成重复开Client/抢controller。任何部分失败都不派发模型。
5. 通过Cloud capability显式声明支持；通用SDK/Host adapter协商后调用组合入口，旧服务
   继续走原三步。SDK/API单独验收，Trench仅是一个消费方；没有Trench专属默认值。
   当前Trench后端仍直接串行调用三条路径，只增加Server API不会自动改善该页面。

验收范围应固定：原三步与组合路径的相同能力/identity/controller结果；过期、撤销、
越权/跨namespace、伪造mount、scope扩大、重复nonce、Run漂移、幂等冲突/响应丢失、
并发controller及部分失败。先无模型固定HTTP计时/SQL对照，再一个新high/v2搜索页面。
不得靠降低思考、缓存registry授权、跳过挂载校验或单纯缩短轮询掩盖耗时。

## 本轮交付和限制

本轮未实现组合路由、SDK或输入快照缓存，亦未运行无关测试修复。下一实现需要独立
Ready任务、明确Owned paths及上述契约，不能混入本次只读诊断。
分析脚本复核四段合计、三个Client窗口与本次high/v2成功事实；文档diff检查通过。
无生产源码改动，不重复运行全量pytest或声称新增测试/性能通过。

正常Worker5d086202、APIc0b8e9dc恢复原六Compose/入口/命令，均healthy；累计43源码
hash及搜索245b675f/配置/环境指纹核对。临时API/Worker trace入口和页面观察器撤除，
普通页面重载同一完成结果，不调用模型。私有证据.artifacts/web-premodel-admission-20261015
保存原服务身份、API/Worker安全trace、阶段对账、浏览器时序和完成事实。

本地仅提交并集成诊断文档到cloud-agent-trench，保留原27条无关脏改动；不推送、
npm发布、远端部署或业务数据修复。首段约5秒与全系统SQL目标仍未完成。

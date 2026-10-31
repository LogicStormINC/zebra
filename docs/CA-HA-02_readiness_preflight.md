# CA-HA-02 任务、依赖与候选实施

日期2026-10-31；当前状态Review候选：用户后续已授权02实施，实际行为和限制见第6节。
以下1–5节保留领取前设计边界；01 revision 2前置已合入cloud-agent 1dd88bfd。
原文档阶段未实施；本轮已先登记Ready后领取02，依然不启动重型/Docker环境。
依赖：[CA-HA-01 revision 2](contracts/cloud-ha-v1/README.md)、[逐卡范围](CA-HA-01_baseline_and_scope.md)。

## 1. 前置结论

- 00已合入cloud-agent d782039c；01复核以7e692719为输入，revision 2已随1dd88bfd合入主线。
- 02不依赖未合入的97463d00a强停实现；只观测现有退出/调度事实，不增加停止控制或接管动作。
- 03连接池/退避、04排空、06依赖HA、08探针部署均尚未实现。02不能声称这些能力已完成。
- 本轮授权只到复核/文档集成与依赖检查，不启动02业务实现；重型验收暂停指令继续有效。

## 2. DDD 与最小范围

复用既有状态/Ports，不新建HA聚合或平行健康权威。
API/Worker健康是技术观测，由apps适配并组合；当前Task授权、lease/fence、收据、
unknown、Coverage仍由原有上下文决定。一个Task等待审批/长工具调用不判整个Worker失活。

| 范围 | 精确候选文件 | 限定职责 |
| --- | --- | --- |
| API接线 | apps/api/src/zebra_agent_api/http.py、http_host_auth.py、routes.py、api_status_mixin.py | lifespan与精确GET路径接线、兼容/health、鉴权负面回归；不修改Task准入语义 |
| API新增 | apps/api/src/zebra_agent_api/health_readiness.py | 有界观测缓存/生命周期/非敏感状态，不查询完整历史，不建立第二全局池 |
| Worker接线 | apps/worker/src/zebra_agent_worker/main.py、loop.py、command_process.py、worker_loop_service.py | 既有控制tick、模式/能力与退出状态的观测，不改变调度/消费/恢复算法 |
| Worker新增 | apps/worker/src/zebra_agent_worker/worker_health.py | 进程本机只读快照与新鲜度；无公网端口/新业务控制面 |
| 回归 | tests/api/test_routes.py、test_host_auth_http.py、test_cloud_ha_health.py；tests/worker/test_loop.py、test_command_process.py、test_cloud_ha_health.py | 旧入口、实际HTTP鉴权链、两种Worker模式及状态新鲜度 |
| 文档证据 | docs/contracts/cloud-ha-v1/、docs/evidence/ca-ha-02/及注册表/进度/本卡 | 记录固定源、状态与未验证边界；有意义的新增测试须随实现提交 |

02禁止写packages/agent-core、agent-storage、业务BFF、Helm或强停候选文件。
需要新增底层Port/查询时先拆所属合同/适配器卡，更新依赖，不能在HTTP层写新领域规则。
03与02共享Worker接线文件，故03必须在02合入后再开始，不使用临时共享所有权。

静态尺寸：http.py/routes.py已500行，http_host_auth.py488、loop.py486、command_process.py488。
不得直接堆接线越过500行：仅抽取与健康组合直接相关的既有职责到上述专用模块，并保留
原测试与保护；不为省行删除鉴权/错误处理。若需更广职责拆分，先新任务，不扩大本卡。

## 3. API设计输入（当前未实现）

- 保持GET /health现有响应与消费者行为。
- 拟增GET /health/live：正常200，响应仅status=alive；不检查数据库/外部服务。
- 拟增GET /health/ready：200/status=ready；启动未完、缓存未知/过期、维护失败或排空时
  503/status=not_ready。公开响应不含依赖名、身份、实例、配置或拓扑；详细原因仅受控观测。
- 仅上述两个精确GET路径可无HostGrant探测。POST/相似前缀/任务路径仍按原鉴权执行，
  未实现方法应拒绝；不能用path.startswith('/health')形成匿名业务入口。
- 1s响应预算、观测最大年龄5s；后台依赖探测必须独立有界，DNS/libpq可能超时不得
  占住请求线程或无限创建后台线程。启动/退出须关闭本卡拥有的探测资源。
- 就绪只声明当前组合的可服务能力；依赖角色由实际配置决定，不要求所有可选插件/模型
  每次探针都在线。任一关键依赖无新鲜证据即不就绪，且服务端准入仍独立做当前门禁。

## 4. Worker与证明

区分进程响应、控制循环进展和可调度能力。快照初始unknown，采样者身份与当前进程绑定，
不能读取旧进程残留快照报ready；读取探针本身不能刷新更新时间。
旧循环和migrated模式均有确定性回归；生产cutover值未知，不能自动切换/启用新队列。
等待审批、空闲或合法长任务不应触发错误重启；控制无进展/能力失效不应靠独立假心跳掩盖。
SIGTERM只立即反映现有退出状态；真正排空/强停与资源证明仍归04，02不能假报resources_released。

## 5. 未来实施验收表

| 场景 | 必须结果 |
| --- | --- |
| 原/health、local/cloud、factory/真实HTTP入口 | 旧响应/认证行为保持；新增路由实际可到达，不仅直接调handler通过 |
| 匿名精确GET与恶意相似路径/方法 | 两个探针可访问，业务路径仍需当前权限，无信息泄露 |
| 启动、关键依赖失联/恢复、缓存过期 | 未知/过期503，恢复后新鲜200；不无限等待或重试业务 |
| 依赖阻塞/DNS慢、并发探针 | HTTP预算与后台队列有界，存活探针不连带失败 |
| 两Worker模式、长任务/HITL/空闲 | 存活/能力区分正确，不改变原Task、Run、Controller或收据 |
| 控制tick停滞、旧快照/进程重启、退出 | 不能假ready；读取不刷新，退出后不遗留本卡探测资源 |
| 文件边界与回退 | source≤500/test≤700；旧客户端不升级仍可用，不改历史证明 |

实施授权后先最小确定性回归，后完整make test/check和必要真实组合验证；禁止将mock健康
测试当生产HA证明。当前仅文档静态校验，不声称任何上述场景已运行/通过。

## 6. CA-HA-02候选实现（2026-10-31，Review）

用户后续“开始实施”授权本卡代码，旧的未授权说明保留作前置历史；本节是当前实施状态。
分支codex/ca-ha-02-readiness从主线e8a4f10b开始，摘取UX文档01530810为559422d7。
实现仅组合/技术观测，无core/storage/Helm/业务BFF变更，前端mock保持。

### API

- 新GET /health/live总是快速返回200/{status:alive}；不执行依赖检查。
- 新GET /health/ready只读缓存，未知/失败/过期/关闭503/{status:not_ready}，新鲜成功200/{status:ready}。
  FastAPI注册精确GET路由，排在原鉴权catch-all前；没有增加任何前缀匿名豁免。
  新健康响应带Cache-Control:no-store避免中间缓存；原GET /health及原HostGrant/本地bearer路径保持。POST/子路径/尾斜线仍进入原鉴权。
- ApiHealth承接原lifespan的HostGrant预热和流读取器/通知器关闭，保留原行为；
  预热失败不启动后台探测。lifespan成功后仅1条本机观测线程，无请求触发的额外线程。
- 默认Cloud观测只覆盖共同控制面：启动factory的原有schema校验后，通过既有
  read_control_plane_epoch及Task I/O deadline进行单次只读epoch查询，预算0.75s，
  完成后间隔1s，无立即重试风暴，结果最大年龄5s。DNS子进程/套接字/查询/退出预算复用原存储实现。
- 不额外创建连接池，不执行DDL/DML/业务工作，不把数据库异常文本传给匿名调用者。
  本地开发组合成功启动后可就绪；Cloud注入的非Postgres stores不能报告就绪。
- 原schema校验依旧发生在factory启动，不将本卡包装成运行期schema漂移检测。
  readiness只说明公共控制面可服务，不证明全部模型/工具/S3/Broker端点均可用；
  各功能仍有原准入检查，依赖角色与全面容错留给06，完整就绪部署留给08。
- 正常退出先关闭本卡探测，再关闭原流资源；探测未在2s内退出会显式报错，不能悄悄假报回收。

### Worker

- WorkerLoopService创建本机WorkerHealth；新CLI参数--health-file为默认关闭的本机只读
  观测文件输出选项，不开端口。每进程须由管理方提供新的文件路径，已有文件以O_EXCL拒绝覆盖，
  避免误配置破坏业务文件或其他实例快照；稳定路径接管不在本卡实现。只允许绝对、受控、本机目录（推荐运行时tmpfs），不支持网络文件系统。
- 文件以临时文件+原子replace更新，权限0600，含PID/独立进程实例ID、观测时间、phase、
  control_fresh、ready和有效截止时间；不含业务身份、token、Task状态或资源释放收据。
- 消费方须从进程管理侧固定当前PID/实例ID后调用read_worker_health；不能仅信任文件自报身份，
  也不能把该观测当执行授权或Task完成证明。格式损坏、超长、实例不匹配、过期均不就绪。
- 命令模式只采样原control/maintenance已完成的进展及实际consumer拥有的能力凭据；
  无新鲜进展、能力缺失/过期或停止即不就绪。缓存截止不越过能力凭据的实际到期时间。
  没有新增数据库探针、伪造心跳或改动领取/恢复/执行算法。
- 旧串行模式：poll前legacy_busy且非就绪，完成后legacy_idle短期就绪；合法长调用期间
  没有独立控制tick，保守表示观测不足，不表示Task失败或建议自动杀进程。
  本卡没有把旧模式改造成并行控制，也不声称补齐了04的独立终止能力。
- 命令模式收到原停止信号时关闭观测，再走既有真实drain；正常/异常run退出也关闭。
  无强停/清理/租约变化，观察文件写失败只使观测不可信，不中断业务执行。

### 验证与未验证

仅运行SQLite/内存/假I/O的定向回归和局部静态检查；没有真实PG、Redis、Broker、Docker、
外部模型、故障集群、全量make test/check或生产验证。真实PG就绪/schema不兼容等联合
场景仍须在后续明确允许环境验收后证明；不能把本地测试当作生产HA或UX容量达标。
旧基础3项先验证；新API/Worker用例有实现前模块缺失RED，能力到期回归另做撤去守卫
失败→恢复通过。具体命令/版本/结果和资源边界见[证据](evidence/ca-ha-02/validation.json)。
02保持Review候选，未合并/部署；03及其后任务仍Locked。重型验证/Docker暂停继续有效。

## 7. 候选复核修复

输入6af4e5dd，本轮内联单人复核，不冒称独立双人审查。

- 命令模式的ready/control_fresh受真实control/maintenance进展限制；valid_until取能力
  截止、真实进展+5s、采样缓存截止的绝对最小值。采样/落盘耗时或反复tick不能续期旧进展。
  私有文件增补control_observed_at以区别采样时刻与原进展时刻，不形成执行凭据。
- 本机读取使用O_NOFOLLOW/O_NONBLOCK并以fstat确认普通文件；符号链接、FIFO、目录
  均按unknown/non-ready处理，不读取替代目标或阻塞控制通路。仍仅支持受控本机目录。
- API生命周期以AsyncExitStack独立尝试探测线程、流读取器与通知器关闭；一项异常
  不跳过后续关闭，错误仍传播，不假报已释放。保留原流资源的关闭预算，不宣称总关闭≤2s。

[新增证据](evidence/ca-ha-02/review-validation.json)：58项定向回归、局部Ruff/mypy7与
产品边界检查；原52项证据保留。仍无真实PG、完整门禁或集群/UX容量验证，02保持Review。

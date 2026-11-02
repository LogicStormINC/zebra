# CA-HA-03 — 轮询和资源预算收口

2026-11-02；Owner Luke Ding；执行Codex；branch `codex/ca-ha-03-budgets`；基线`56ae352a5`。
03A是本批可审查切片；03整体仍In Progress，03B和完整E1容量验收尚未完成。
没有生产部署/迁移、业务Run重放、模型请求或旧环境恢复。

## 已追踪的实际路径

- `main.py`建立普通池后组合`loop.py`；cutover决定旧串行循环或`CommandWorkerProcess`。
- 旧循环只在空队列sleep，有READY但全被跳过可无等待轮询；本地默认行为保留。
- 命令循环的execution/control各有独立DB线程和游标；原固定间隔不能区分持续deferred。
- Consumer的发现/身份解析及`CommandRecoverySweep`复用同两个storage函数。
  这两处原`connect()`没有读取期限；真实表锁可长期占住DB lane。
- 强停、handoff和Task I/O已经有原生有界连接，直接复用；不改身份解析/原意图语义。

## 03A实现

1. Cloud旧循环及命令循环区分progress/idle/blocked/error，每lane独立保留小型退避状态。
   空和阻塞指数退避到1s，错误到5s，80%–100%抖动；最小非进展等待50ms。
   显式较慢操作员间隔保持下界，不能据此承诺所有配置满足SLO；有进展回到原间隔。
2. 控制lane独立退避，执行侧error/blocked不延长其等待；SIGTERM唤醒命令循环Event。
   原Consumer槽、Future drain、cursor公平扫描、canonical control和收据均复用。
   调整的是发现周期，没有新增执行重试或自动补发unknown操作。
3. `discover_command_pickups`与`resolve_command_pickup`统一改用`connect_task_io()`：
   复用原2s总I/O预算和最多50ms锁等待。覆盖正常消费和恢复扫描，不在每个caller打补丁。
   DB错误继续沿原deferred/重排路径传播，不被当成未提交或资源释放证明。
4. 拒绝NaN/Infinity/bool轮询间隔；命令循环原0–30s配置约束保持。
5. 从已500行的command process抽出后台周期与脱敏trace职责；未扩写为第二调度器。

## 已有上限与03B缺口

| 路径 | 当前已有约束 | 尚缺证明/实现 |
| --- | --- | --- |
| 普通PG池 | 每进程max8、等待max32、借用2s | 只在pool scope覆盖路径有效，不能作为全副本总额 |
| Task I/O | 每次2s总期限/锁等待上限 | 短连接绕过普通池，无全副本并发总配额 |
| 命令执行 | execution_slots1–32；信号量先占槽再handoff | 按namespace负载测量及跨Worker/执行器聚合预算 |
| 命令DB lane | admission/control各2线程，非阻塞槽拒绝多余提交 | 独立线程不等于数据库连接容量预留 |
| 维护/清理 | 各单独1线程，不与execution排队 | 各维护源实际SQL/CPU总预算与故障恢复实测 |
| API入口 | server.main包普通池；Helm直接uvicorn factory | 统一实际入口，计入API副本/请求线程与探针 |
| 隔离执行器 | 每个child也进入自己的普通池scope | 必须乘执行器并发/父Worker数，不能只算父池 |

`PostgresDatabase`在构造时捕获ContextVar的池；动态在线程中构造的adapter还需复核
context传播，不能把main线程pool scope推断为所有线程/直连都受限。
本批未引入全局连接注册表/第二执行队列/新商业租户模型或第二套执行事实。

## 验证边界

机器记录见`docs/evidence/ca-ha-03/validation.json`。

- 先红后绿：新轮询回归修复前8失败/2通过；真实PG表锁回归修复前2失败。
- 实际新旧run路径、2000次连续无进展边界、零间隔deferred、独立控制信号/真实drain。
- 独立PG的公平游标/活跃scope插入/执行满槽控制/表锁/普通池回归33通过。
  PG限1CPU/512MiB/PID128，数据tmpfs256MiB；测试创建的精确容器ID均已回收。
  首次资源参数WAL增长导致DiskFull，后用PG原生min/max_wal_size32MiB后整组通过；
  未把资源失败改成skip，未启动或删除旧环境来释放空间。
- 完整Worker首次1325通过/1失败/759条件跳过；唯一失败在干净基线56ae352a5复现：
  原Mock只提供status而已有生产SQL还要求forced列。只补齐Mock的forced=false，
  不把生产读取改成缺列默认放行；最终完整Worker1326通过/759条件跳过，make check全绿；机器记录保留各次边界。
- 本批未进行生产/多节点故障注入、全仓make test或E1-C/E1-O容量验收；不宣称HA达标。

## 下一切片03B

1. 在任务卡冻结精确API/Worker/child/config/storage/Helm路径后，统一现有池入口。
2. 计算API副本、Worker父/子进程、scheduler、cleanup、探针和Task I/O总连接，
   明确部署上限及控制/原GET预留、等待/拒绝策略；不把单池或单角色上限冒充全局预算。
3. 在独立限额环境记录SQL次数、CPU、池等待、线程/队列上限、队列年龄与拒绝率；
   flood scope和低负载scope分别测p95/p99，拒绝/超时纳入分母。
4. 03B完整验收/评审合入后再解锁04；本批不改旧强停证据缺失的人工对账策略。

03A候选已验证，独立/人工评审待完成。生产镜像/schema与当前源码组合需在部署前单独冻结；
本批不直接将cloud-agent镜像替换到现有生产，不通过升级自动重跑旧任务。

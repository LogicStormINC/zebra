# Cloud Task 原子准入 SQL 往返收敛

任务 CLOUD-TASK-ADMISSION-IO-01，基线 cd0f23d6；保留新鲜授权、高思考、Flash、v2 和工具自主决策。

## 定位与最小改动

建任务73条 Driver SQL中，6条新鲜Host授权/nonce/审计、8条幂等预检/Workspace/Manifest、
55条原子准入、1条准入后幂等回执同步、3条响应header/Session读取。原子准入内首次索引构建43条；
bootstrap的3条新Event各自先写坐标、再检查字节上界、再读派生映射、最后插映射，随后有界repair复核。
事务已使用同一连接，不能靠再开池来消除这些语句。

仅修改现存task_event_positions._assign：首次未分配源坐标的UPDATE同时补字节上界；
已有源坐标仍只在字节上界确实变化时UPDATE，避免改写sealed source witness。
索引用已有唯一键ON CONFLICT DO NOTHING仲裁；成功插入直接返回，冲突才回读并严格核对四元组。
其他唯一冲突仍转为原有typed conflict；缺失/异常仲裁结果fail closed。
所有调用仍沿用原连接、原事务、原Task锁、前驱和source/index guards；没有新Port、迁移、缓存或依赖。
repair、handoff、delegation、coverage调用链均核对，原子准入/原生触发器/旧数据修复策略不改。

## 验证边界

独立检查scripts/check_task_position_assignment.py只创建并清除自己的随机schema；
覆盖真实PG新建、相同映射不变、缺失修复、冲突拒绝、幂等重放与调用方回滚。
红灯原因为新映射仍预读；优化后同一检查通过。
无模型Host新鲜授权/execute=false探针A73、B67（减少6条，8.2%）；均不提交command。
带逐SQL栈的总耗时包含探针开销与首次验签，不能用来宣布性能收益。

固定四轮真实页面ABBA：同一官方搜索题、原Worker/Search及相同临时观察器；所有结果保留。
分别报告POST/tasks、事务体/连接/commit、首次索引、模型前启动、DOM首正文、整轮和Driver SQL。
SQL不包含数据库触发器内部PL/pgSQL语句；这不是PostgreSQL总执行语句或CPU下降百分比。
默认干净跟踪源码make check已通过。首个集中回归在30 passed后主动停止：遇到已有
1千/1万/10万Event扫描用例的大批造数，未扩大修改其fixture；其日志保留。其余直接相关
原生坐标/锁/legacy/guard与API检查38 passed、3个大扫描用例deselected（与首轮有重叠），
不是68个不同测试，也不声称完整make test通过。没有修改既有测试文件。

新建任务受益；legacy validating中本就存在的映射会多一次零行INSERT仲裁再回读，
ready repair仍走原批量实现，未增加普通热读的数据库操作。SQL降低不代表磁盘写入次数
同比降低：原单独字节UPDATE对新行通常影响0行，合并减少的是Driver往返；
ON CONFLICT只在仲裁冲突时回读，不改写已存在派生映射。


## 四轮真实页面结果

A为本轮前已验收版本，B仅API共享_assign最小补丁；相同的Worker/Search镜像、观察器。
四轮均completed、高思考/Flash/transient_v2，14个执行模型响应retry0；20个工具调用均成功。
每轮仅一个candidate，一次quality评估通过。模型与工具数由Agent自选，无强制工具或固定规划。

| 样本 | 建任务SQL | POST/tasks ms | 原子准入含连接/提交ms | 索引构建ms | 启动s | 首正文s | Host整轮s | 模型/工具 | Worker+API非空SQL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| A1 | 73 | 296.2 | 165.4 | 82.9 | 3.007 | 17.822 | 21.930 | 3/4 | 3250 |
| B1 | 67 | 220.2 | 101.1 | 58.6 | 2.688 | 19.667 | 22.694 | 4/5 | 3943 |
| B2 | 67 | 272.1 | 144.5 | 79.4 | 2.183 | 15.390 | 18.730 | 3/5 | 3482 |
| A2 | 73 | 454.6 | 261.2 | 69.4 | 3.256 | 20.769 | 24.092 | 4/6 | 4235 |

确定收益：POST/tasks73→67，减少6条（8.2%）；原子事务Driver SQL55→49（10.9%），
首次索引构建43→37（14.0%）。六个前置Cloud请求保持6个，SQL162→156（3.7%）。
Worker首次Provider前448execute/33空探针/5次物理连接打开均未变；启动合计非空577→571（1.0%）。
整轮非空SQL均值3742.5→3712.5（0.8%）为本组原始值，模型/工具工作和轮询窗口不同，
不能按8.2%推算全流程或PostgreSQL触发器内部语句下降。

## 事务内耗时：不要把抖动当优化

| 均值ms | A | B |
| --- | ---: | ---: |
| POST/tasks完整请求 | 375.4 | 246.2 |
| 原子准入段（含连接/commit） | 213.3 | 122.8 |
| 事务体 | 196.1 | 110.2 |
| 其中首次Task索引构建 | 76.1 | 69.0 |
| 其中三条Event分配 | 45.3 | 44.8 |
| 其中索引后的repair | 9.8 | 4.6 |
| 事务体其余（事件/投影/绑定等，未改动） | 120.0 | 41.2 |
| 准入连接建立 | 10.5 | 5.8 |
| 准入commit（包含deferred trigger） | 6.6 | 5.5 |

原子段仍只开一个连接；POST/tasks其他独立事务的普通connect为7次/请求不变，
其总连接均值66.0→46.9ms属于未改动部分的波动，不能算本补丁复用收益。
API旧TaskIo的_resolve计时仅为解析，不计作物理连接打开。原子commit约5–7ms，
并非主要瓶颈；首次索引仍约59–83ms，其中source赋值及其native metadata触发器约37–53ms。
A2事务体非索引部分174.8ms，其他样本32.1–65.2ms：目前只定位到未改动的写入/投影/绑定段，
没有逐条页面SQL时长证据，不能进一步断言是某个触发器或磁盘锁，更不能把这次差值当补丁收益。
_assign均值只少约0.5ms，索引段约少7.1ms（9.4%），样本仅2/组、区间重叠，
无法保证稳定延迟下降。收益确定在6次Driver往返，并未证明原子准入普遍快42%。

启动均值3.131→2.436s、首正文19.295→17.528s、Host整轮23.011→20.712s，均为原始配对值。
首个Cloud请求之前的等待938.7→708.9ms、未改动Worker启动645.4→465.6ms也同时变动；
执行模型总耗时均值11.679→9.774s，输出token1916/1700/1249/1654。
首正文前Provider约8.592/9.258/6.139/9.469s，工具并集约4.473/5.168/5.145/5.338s。
这些秒级差值主要受模型、搜索/抓取和调度影响，不能归因于6条建任务SQL。
B1首正文/整轮比A1更慢的结果完整保留；无第五次模型Run或挑选有利样本。

## 交付与后续边界

本轮正常本地API仅叠加这一份存储源文件，不带入其他HEAD存储模块；
Worker/Search维持原已验收镜像，未热更新Worker的legacy修复路径，也不声称Worker侧SQL收益。
仓库中共享函数适用于所有调用者；相关handoff/delegation/coverage事务边界未变化。
原六Compose、env摘要、entrypoint、command、healthy/0 restart与105项登记源码指纹复核通过。
无模型探针A/B均确认0 accepted command、0 model_request_started。未备份数据库。
本轮剩余主要成本仍是源赋值触发的metadata投影、事务内其他写入波动，以及模型/工具本身；
若继续，应先对未改动写入/投影逐条低开销计时，再决定是否合并，不能绕过授权或迁移guards。

正常API镜像：sha256:b40a23cd3de5ff46606aed4b338821de3df9aed494d88a0222cb4825f5562095。
Worker：sha256:1a2270dfbf0bb4986e526cb309e73fc0a339822d34139a7084f700c4e9abc22d；Search：sha256:245b675ff61b01a0ddace63abc095420c55393a55761a32b15274e25cfcdd1d5。
私有证据.artifacts/cloud-task-admission-io-20261017包含summary/startup/admission-breakdown/
breakdown.safe.json、四轮Driver日志与DOM观察、原生探针、定向检查和正常源指纹。
验收会话B2：conv_1792177108413_2370f8。

正常服务恢复后B2原正文、完成操作和高思考设置可见；page-B2.jpg已保存，DOM监听解除、
回环接收器关闭。任务Review表示本地验收和集成，尚未推送或合入main。

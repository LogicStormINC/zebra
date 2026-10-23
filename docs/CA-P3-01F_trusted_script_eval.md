# CA-P3-01F 可信原生脚本 Eval 生产者

2026-10-23；实现前准入。SE01–07为本片约束，结果以正式证据为准。

Runtime独占评测执行和证据登记。复用A的只读无网络沙箱、B的精确catalog/2与D的可信门禁；
私有评测suite固定Version/Definition摘要、evaluator、policy和全量binding的输入/期望输出。
输出由真实runner观测并确定性评分，失败不能人工改passed。此policy证明无副作用脚本的固定案例，
不是通用业务正确性、LLM质量、Coverage或生产安全认证。

SE01 当前私有配置与共享批准、完整scope、exactVersion/Definition/引用；SE02完整binding覆盖；
SE03案例/输出/总时限有界；SE04执行前持久unknown/唯一原操作；SE05事务外执行、当前授权逐次复核；
SE06证据和收据原子登记；SE07unknown只读不重跑、不换UUID绕过，重启仅读已提交原收据。
旧D/E HTTP合同不扩宽，正常API无runner依赖；独立Worker运维入口执行评测。
数据库只新增可显式初始化的功能表，不改旧任务/Registry数据或Coverage算法。

Overdoze通过独立验收组合根调用Native私有运维入口，只传原操作/版本标识，Go不连接Native DB。
然后仅用原生evidenceId调用公开D；实际Task/Run由独立签名业务准入创建，Worker消费固定快照。
旧任务在新Release后恢复仍需旧字节/catalog精确批准，不能读latest；不兼容Worker必须拒绝且无新模型或脚本派发。
无部署、生产迁移、main合并或npm发布。

## 运维入口与信任边界

`python -m zebra_agent_worker.script_evaluation --suite /absolute/private/suite.json
--operation <canonical-uuid> --namespace <deployment-namespace> --mode initialize|evaluate|read`。
环境沿用load_settings；DB和publisher approval来自Native运维Secret/私有配置，不能由业务或浏览器提交。
显式initialize只建native_script_eval_operations及有界待对账索引；API/Worker启动不自动DDL。
该可选运维命令需要安装现有Worker、Runtime及API publisher配置适配器；正常API/Worker启动不导入它。
无新依赖/HTTP路由，旧publisher及D/E schema、凭据和动作均不自动扩权。
机器入口与私有suite schema在[合同目录](contracts/native-script-evaluation/contract.json)。

suite须为当前操作系统用户持有的私有绝对路径，最多128KiB，严格JSON/禁止重复字段；
固定完整scope、Definition/Version/Definition digest/assembly digest、evaluator、policy和案例。
Actor必须在当前私有批准的evaluator_actors中，policy与publisher policy相同，精确base+script引用仍批准。
至少一个且最多32个案例，名称唯一、所有binding均覆盖，输入/期望输出遵守原ABI封闭标量类型及字节预算。
累计脚本最长执行时间不超过60秒，包含授权/结束的attempt为65秒；超时不会生成通过证据。
每个调用由既有ScopedNativeScriptRunner建立独立只读/无网络挂载，父进程检查原invocation、输入/Manifest及输出摘要。
Verifier期望不能写为passed=false，脚本返回的passed本身也不能代替整个suite评分。

领取前核对当前共享批准与catalog；短事务内按现有批准锁→Definition锁顺序检查唯一operation与容量。
执行在事务外，逐案例以及原子提交前后复核私有批准/suite/catalog/期限和共享批准；
中途撤权或进程终止保留unknown，不能登记成功证据。完成时Registry证据与原收据共用事务。
证据ID等于原operation UUID，summary只保存评分、观测和摘要，不保存源代码/原始输入/输出或凭据。
失败的确定性案例会登记passed=false，D明确拒绝；操作员可以明确发起新案例评测。

重复原operation且suite相同只观察原completed或unknown；不同suite冲突。
同一Version有unknown时，任何新operation都被拒绝；read缺失不等于未执行。
本片没有非提交证明或人工解除未知状态接口；不能删除unknown解锁，也不能自动重新执行。
当前read仍需原suite及当前批准，配置/资产已撤销时拒绝观察；后续授权迁移/人工处置需独立任务。
每Version保留上限1024次，不自动裁剪历史；并发实例预算由外部Job调度限定，不能无限启动进程。
共享PG保证唯一领取，单机沙箱/双进程测试不证明存储HA、生产gVisor清理或容量SLO。

## 本轮验证

14项专项覆盖真实Seatbelt评分与D门禁、严格suite/完整binding/错误类型、当前撤权不登记、
真实独立PG及两个独立解释器竞争、原unknown阻塞与跨进程读取。
完整make test/check及限定提交/推送状态在[任务表](AGENT_TASKS.md)和后续机器证据记录。
Overdoze同次完整联合在独立任务OD-P3-02D维护，不借历史Worker用例充当本轮新链路通过。
实际模型/业务正确性/生产gVisor/真实产品和HA仍未验证；旧历史、任务及Coverage机制保持。

最终门禁：make test11016通过/3022条件跳过，make check1399类型文件/30eval通过；[机器证据](evidence/ca-p3-01f/validation.json)。旧4650个文件保持，修改的五个既有文件仅为规划/日志。

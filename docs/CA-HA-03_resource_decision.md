# CA-HA-03 独立资源决策（2026-11-06）

状态：**容量验收受环境阻塞**。方案已明确，但尚无云账户可分配额度/库存证明，实际落实0台。
停止本地优化开发；不租用、不创建资源、不重签、不部署、不跑E1-A/E1-R。里程碑3不能关闭。

## 冻结点

应用提交f20b56a3098c72135e156cc3e86b4a6486a61cdb，分支codex/ca-ha-03-q1-stop-capacity。
源码覆盖包及摘要：`.artifacts/cloud-ha-e1/force-stop-capacity-1793898506/FROZEN_CANDIDATE.json`。
原签名Version884d50dd-bbc2-47bd-820b-3ec13e02bf76保持原样；它不是含Q1修复的新签名包。
原pending、unknown及旧签名保留，现有生产192.168.101.7不参与资源补足。

## 当前可用环境与阻塞

此前只读实测：Mac10逻辑CPU/32GiB；OrbStack Kube单节点10CPU、约15.66GiB可分配，
两个Linux VM父级各4CPU/8GiB，均来自同一Mac，没有形成新的物理CPU或独立故障边界。
本轮未重新加压。资源原始证据：`test-tool-closeout-1793897286/resource-inventory.json`。

本机未安装aws/hcloud/gcloud CLI；`.aws/config`、`.aws/credentials`不存在，未发现可用
AWS SDK/已连接基础设施工具。只核查文件存在性，没有打印凭据、使用生产身份或登录云账户。
因此账户Running On-Demand Standard配额、已用量、可用区库存、税费/账期与支付权限均未核验。
现阶段不能把公开规格称为实际可用额度，也不能把报价估算称为已预留资源。

## 选定待采购方案

AWS us-east-1、Linux ARM64/Graviton3、On-Demand，48小时总租用预算窗口；不使用Spot或CPU积分机型。
采用独立测试VPC，同一可用区的rack-level spread placement group，三台位于不同底层硬件。
这是测试实例隔离，不是Dedicated Host；同AZ不证明可用区灾难恢复。AZ名需账户核验后固定。

| 节点 | 实例与供应商额度 | 数据盘/系统盘 | 角色 |
|---|---|---|---|
| A | c7g.8xlarge，32 vCPU/64GiB | 500GiB gp3数据盘＋64GiB gp3系统盘 | Worker1、API1、PG主、cleanup |
| B | c7g.8xlarge，32 vCPU/64GiB | 500GiB gp3数据盘＋64GiB gp3系统盘 | Worker2、API2、PG同步备、cleanup |
| C | c7g.xlarge，4 vCPU/8GiB | 64GiB gp3系统/夹具盘 | 独立控制入口、Broker/授权夹具、负载发生器与观察器 |

共68 vCPU/136GiB是租用实例总量，不是应用最低需求。它包含PG备库、独立观察节点及宿主余量；
先前32CPU/32GiB仍只是容量候选。必须先取得账户净剩余额度至少68 vCPU，再证明实际启动成功；
instance-type-offerings只说明产品在AZ提供，dry-run只核权限，二者都不证明实时库存。

ARM64与现有镜像指令集一致，但Graviton3与Apple CPU不可按核等价换算。AMI、内核、Docker、
gVisor架构和原生冷启动方式均须记录并预检；失败时报告环境不兼容，不转为执行架构改造。

### 父子预算

A/B各自：Worker8CPU/8GiB，PG12CPU/16GiB，API2CPU/2GiB，cleanup/TLS等合计2CPU/4GiB。
应用上限合计24CPU/30GiB；每宿主剩8CPU/34GiB，其中至少2CPU/4GiB留OS及中断处理。
API/control parent与Worker parent分开，不能再套在同一个4CPU父级里；根配额必须覆盖子级。
C：控制/授权/Broker约2CPU/4GiB，负载/观察器1CPU/2GiB，至少1CPU/2GiB留宿主。
所有额度为待验证预算；真实cgroup层级、最大配额、节流和宿主杂负载须采样，不以配置代替实测。

E1-A暂按总32执行槽做资源预算候选；必须先用既有连接预算计算器校验fleet＋每执行器连接，
计入双API/双Worker/双cleanup/Scheduler及监控，不能默认沿用README里8执行器的247连接结论。
超限时停止签包，不静默提高PG连接数或删检查。冻结E1-R另有32活跃/24排队/8执行槽的场景，
应明确固定其验收profile，排空后按正式签名配置切换；不得把不同profile的证据拼成同一容量结论。

### 磁盘、网络及实测门槛

两块数据盘各配置6000 IOPS/250MiB/s；系统盘维持gp3默认性能。实例A/B标称网络15Gbps、
EBS通道10Gbps；C网络标称上限12.5Gbps，不能按持续带宽保证引用。
这些是供应商规格和预置性能，尚无本账户实测。资格阶段在新建scratch文件上采集fio、
pg_test_fsync、WAL/IO及真实PG提交延迟；不得对原数据库文件运行写盘测试。

业务/复制/控制均走同VPC私网。控制入口沿用现有Caddy，数据节点TLS28445只接控制节点；
PG25432只对测试数据节点，Broker/授权28444只对测试节点，模型fixture仍在节点loopback443。
不新增公网数据库、NAT Gateway、收费LB或生产VPN依赖。SSH仅限明确管理来源；三公网IPv4
只用于管理/必要出站，计费纳入估算。机间RTT/吞吐、丢包及NTP误差必须记录；没有测量不承诺延迟。
负载发生器放C，不能从中国公网请求时延推导服务内部排队；排队优先采用同源DB时钟。

## 费用决策

币种USD；Linux无商业OS许可，按48小时、Nov30天/720小时折算。税费与账户折扣未知。
EC2数据直接取AWS官方公开价目：2026-11-04T21:03:05Z版本，2026-11-06下载。
A/B各1.16美元/小时；C为0.145美元/小时。原始JSON及rateCode保留，可独立复算。
EBS/快照采用AWS公开价格示例/卷类型页的费率估算；地域实际账单报价仍需账户核对。

| 项目 | 计算 | 48小时估算 |
|---|---|---:|
| EC2三台 | (2×1.16＋0.145)×48 | $118.32 |
| gp3容量 | 1192GiB×$0.08/月×48/720 | $6.36 |
| 数据盘额外IOPS | 2×(6000−3000)×$0.005/月×48/720 | $2.00 |
| 数据盘额外吞吐 | 2×(250−125)×$0.04/月×48/720 | $0.67 |
| IPv4三地址 | 3×$0.005×48 | $0.72 |
| 外网导出预算 | 最多20GB×$0.09，不预扣账户免费量 | $1.80 |
| 小计 | 未含税、快照 | **$129.86** |
| 证据快照保留7天 | 最多1192GiB已写块×$0.05/月×7/30 | 最多$13.91 |
| 总费用估算 | 上述限定范围、税前 | **约$143.77** |

建议预留**$180税前预算**，不是已授权支出或保证账单上限。含税总价待账户税率/正式报价；
额外运行天数约$64.93/天（同配置、不重复计算已有快照），额外快照/出网另计。
假设48小时内终止实例、删除已导出临时卷、释放IPv4；快照7天后按数据保留授权处置，
不能擅删原签名/回执。停机不停止EBS/IPv4计费；不启用Fast Snapshot Restore/跨区副本/付费监控。
报价不包含人工、真实模型供应商请求费或跨AZ演练流量；本次只用可信计数的合成模型夹具。
若完整矩阵需要改变AZ或额外服务，先更新该范围和费用，不能据此宣称现有预算覆盖新增部署。

## 可执行核验与恢复顺序

以下只读命令供具备AWS CLI和专用账户身份后使用；本轮未执行账户API或下单：

```sh
aws sts get-caller-identity
aws service-quotas get-service-quota --region us-east-1 \
  --service-code ec2 --quota-code L-1216C47A
aws ec2 describe-instance-types --region us-east-1 \
  --instance-types c7g.8xlarge c7g.xlarge
aws ec2 describe-instance-type-offerings --region us-east-1 \
  --location-type availability-zone \
  --filters Name=instance-type,Values=c7g.8xlarge,c7g.xlarge
```

实际配额还须减去同区域已有实例/预留占用；得到实例ID、AZ、placement group、CPU架构、
存储/网络实测和精确owner清单后才算资源落实。48小时总计费窗口从首台实例开始计费时算起，包含创建、准备、签包、资格验证、验收和导出；
不能把准备时间另算为免费。未完成时也须在预算窗口内结束并保留失败证据，延长需重新确认资源预算。

资源落实后的顺序：

1. 核验FROZEN_CANDIDATE.json、源覆盖包摘要和原文件preimage；按f20b56a3冻结源码构建
   新不可变ARM64镜像，记录完整镜像digest；不追加性能改动。
2. 为新环境生成独立namespace/授权/证书和原生签名发布。重算实际DB地址/设置的baseline pin，
   发布新Version、保存签名/审批/摘要证据。不得把旧catalog改地址后继续使用旧签名，
   也不能绕过现有prepare_execution对固定namespace/DSN的限制；它不是AWS通用安装器。
3. 先在单个全新合成Task闭合签名准入→模型一次→业务完成→精确ACK→槽位释放；另做新Task
   强停预检，确认未ACK仍占位、满足退出/租约证明后释放。原任务和unknown不重发。
4. 核验CPU父级/PG/控制与GET预算、时钟误差、磁盘/WAL、机间网络及可信模型计数。
   使用已修复的checked preparation entry；准备失败停止，不进入发Task阶段。
5. 通过才运行E1-A：30秒预热＋60秒稳态、持续5/s、正常负载零容量拒绝、排队p95≤2s/p99≤5s；
   提交/接纳/完成分开计数，429/超时/unknown计失败。通过后才逐子项执行合同F-01–F-09完整E1-R，
   包含模型/工具阻塞强停。单AZ结果不得写成多AZ容灾通过。

现成可复验的本地回归命令（需新的专用测试DSN，禁止指向原语料库）：

```sh
ZEBRA_TEST_POSTGRES_DSN="$E1_FRESH_TEST_DSN" .venv/bin/pytest -q \
  tests/agent_storage/test_postgres_force_stop_capacity.py
.venv/bin/python tests/compose/cloud_ha_e1/check_execution_measurement.py \
  --fixture .artifacts/cloud-ha-e1/execution-qualification-1793892399/measure.py
```

完整E1-A历史入口为`e1-a-resource-candidate-1793875018/fault.py`及其time-bill.py；它们固定旧地址/
绑定，仅作冻结口径和证据参考，不能直接运行在新环境。正式签包/环境适配及安装预检尚未完成，
因此目前不存在可诚实标为“直接运行即可验收”的AWS完整命令；不在资源未落实时循环编写安装器。

## 依据与停点

- [AWS C7g规格](https://aws.amazon.com/ec2/instance-types/c7g/)
- [AWS CPU规格](https://docs.aws.amazon.com/ec2/latest/instancetypes/co.html)
- [EC2公开计价](https://aws.amazon.com/ec2/pricing/on-demand/)；下载的官方JSON见本轮artifact。
- [EBS价格](https://aws.amazon.com/ebs/pricing/)与[卷类型](https://aws.amazon.com/ebs/volume-types/)
- [IPv4价格](https://aws.amazon.com/vpc/pricing/)
- [配额](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-resource-limits.html)
- [Spread边界及库存限制](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/placement-strategies.html)

本轮交付是带规格与公开费用依据的待采购方案，以及明确的账户/配额/库存阻塞。
Q1修复线结束追加开发，维持本地Review；RD1文档进入Review。应用冻结未变，里程碑3及整体HA均未完成。

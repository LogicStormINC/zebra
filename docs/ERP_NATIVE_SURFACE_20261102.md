# ERP 原生能力补齐与业务验收

状态：代码与 ERP Host 线上更新完成；代表性无模型业务链通过。不是所有 ERP 模块和业务场景已认证。
部署入口：`https://192.168.101.7:18443/desk`；内部 Frappe 逻辑站点仍为 `192.168.110.42`。

## 根因及最小修复

1. 原目录仅扫描模块顶层白名单函数，遗漏文档控制器方法。安装源码有 284 个非顶层白名单声明，
   其中包含继承/生命周期重叠，不能称为 284 个独立缺失功能。按 DocType 复用原生 controller 白名单发现。
2. Frappe 故意把 `run_doc_method` 排除在普通函数白名单外，由 HTTP dispatcher 特例调用。
   新 `document_method` 操作复用这个入口；保存文档需 name/modified，未保存草稿用 values。
   保留原生最新性、权限、白名单、HTTP 方法与签名校验，不开放任意代码执行入口。
3. 原适配丢弃 `response.docs`，原生只计算按钮可能没有 message，导致明细不回传。
   共享原生调用上下文现在保留经现有字段规则清理的文档，并标明可能尚未保存；不自动保存草稿。
4. 原生 CSV 使用 response.type/result 而非 filecontent。复用原生 response renderer，生成有界私有文件，
   文件 owner 为真实请求人。保留 20 MiB 文件预算和现有工具输出预算。
5. 复用现有操作 SCHEMAS 返回必填/允许参数；Single 不再展示 create/delete；
   动态必填表达式及管理员可写 Password 字段仅返回元数据，不能读取密码值。
6. Unknown 诊断记录 ERROR 级别的操作 ID、异常类型及有限栈位置，不含参数正文/密钥。
   日志故障不能阻断 Unknown 回执；保留旧回执 businessRevision/evidenceDigest，避免破坏历史兼容。

## 验证

- 原生上下文/普通及管理员/撤销/dispatcher 参数模式/旧版本/私有记录/请求人恢复/幂等与 Unknown：
  9 个本地确定性脚本通过。另 1 个既有 full-capability 脚本因本地 Python 缺 requests，
  改在隔离镜像内使用其现有依赖执行并通过，没有安装产品新依赖或隐藏本地环境问题。
- npm test、修改代码及部署脚本 Ruff F 检查通过；Native Host 35 项回归通过。
- 最终固定镜像 4 项真实签名 HTTP 安全检查通过：控制器/Single/元数据、同意图只执行一次、
  旧版本及私有协调记录拒绝、普通 Grant 不继承管理员工具。
- 隔离环境是独立 internal Docker 网络、MariaDB/Redis/站点克隆，没有外网或生产 DB 连接，
  不启动 Cloud Harness Worker。仅为原生 Data Import 执行一次隔离 ERP RQ burst。

## 真实隔离业务证据

业务批次 89 次签名网关工具调用，累计 25 个检查记录：15 项正向通过，10 个先前失败记录原样保留。
失败不替换成成功；补齐真实前置条件后使用新意图，不重做 Unknown 请求或原 Run。

| 范围 | 通过证据 |
| --- | --- |
| 库存 | 原生收料提交，实际库存 20 |
| 制造 | 工单原生 BOM 计算返回明细；领料和制造后成品实际库存 1 |
| 销售 | 发票及银行收款，未结金额 0 |
| 采购 | 发票及银行付款，未结金额 0 |
| 项目 | Project/Task 创建，Task 完成 |
| 客服 | Issue 创建并关闭 |
| HRMS | Salary Slip 原生计算返回草稿，原文档 modified 未改变 |
| 费用 | Expense Claim 提交并生成原生总账分录 |
| 质量 | 原生草稿返回及 Quality Inspection 实际提交 |
| CRM | Lead/Opportunity/Customer 原生转换 |
| 资产 | 按当前 v16 字段创建、提交资产 |
| 导入导出 | CSV 私有文件实际有内容；Data Import 独立队列执行后 Success、成功 1 行且记录存在 |

10 个原失败样本包括旧调用参数、缺银行参考号/日期、费用成本中心/应付科目、质量前置配置、
隔离站点原调度暂停和旧版资产字段。未关闭原生校验，没有把入队或临时草稿当成业务完成。

## 线上更新与边界

- 先确认 full/legacy Native 运行会话及有效租约为 0、ERP RQ 空闲，再备份生产 ERP 数据库、
  site config 和现有 Compose override。无 DB 迁移，短暂暂停新提交。
- 仅 ERP backend/frontend/queue-long/queue-short/scheduler 更新到固定镜像
  `sha256:746563c4aa0f0833d2435fbc2bf186c307161c93765a5ac672b1cbfbaa996069`。
- 真实 HTTP manifest 显示五个工具，包含 document_method 和按 doctype 目录参数；
  用 Native `HostToolManifest` declared policy 实际解析通过。
- 空闲真实管理员会话无 Task/Run；工具 invoke 返回明确的 inactive-delegation 403，符合权限边界。
  初版验收脚本误期望该调用成功，已修正，未放宽生产权限或伪造活动 Run。
  线上另做已安装 controller/Single 原生元数据只读核对，执行证明来自隔离站点，不冒称线上业务执行。
- 所有原配置恢复一致。搜索/出口容器 ID、镜像、环境、启动时间及重启数均未变化；
  Native 各容器 ID/镜像/环境未变化，本次没有重启 Native、搜索或 MCP。
- **独立遗留风险**：Native `erpnext-full-scheduler-1` 在本次更新前已重启 99 次，观察期间到 104 次。
  日志为 `PostgresMigrationError: database schema differs from this application`。
  只读核对进一步确认：Scheduler 镜像只认识 v115；API 与真实数据库均为 v117，
  API 全部迁移名称/校验和匹配。需统一 Scheduler 到同版运行时，不能改账本或关闭启动校验。
  定时任务尚未验收，启动前还须核对待触发任务，避免违反本轮不新增模型的限制。
- 本轮模型/搜索请求均为 0，未重跑或改变原 Run。未做最新管理员模式真实模型端到端、
  全模块/自定义 App/全部报表/外部集成认证；原生异步任务须核对业务状态。
- 私有证据在 `.artifacts/erp-native-surface-20261102/` 及服务器同名 release 目录，不提交凭据、
  数据库 dump、查询正文或站点配置到 Git。

验收结束已按 owner manifest 清理 3 个隔离容器、2 个卷、1 个网络和 2 个未使用自有镜像；
保留生产固定镜像、原回滚镜像、原 QA 来源与私有证据。没有执行全局 prune。

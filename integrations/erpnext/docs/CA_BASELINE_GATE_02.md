# CA-BASELINE-GATE-02

- Status: Review（源候选验证通过；组合验收待父仓库完成）；Owner Luke Ding，执行Codex。
- Base: main 2e8606a603ffe8836fc8a42874b9771f470bc82c；branch codex/ca-baseline-gate-02。
- 规则核对：本仓库无AGENTS.md/CLAUDE.md/Makefile；README提供npm build/test和独立Python检查脚本；遵循用户本轮不降门禁、限额串行、不部署/生产迁移约束。
- Owned paths: zebra_erpnext/、frontend/、tests/、deploy/*.py、cloud-patches/下Python源码及Dockerfile/装配脚本；docs/CA_BASELINE_GATE_02.md、task_plan.md、WORKLOG.md；package.json（仅新增实际Host适配器回归命令）、pyproject.toml及baseline各包的Ruff项目上下文（规则/阈值不变）、历史来源归档与本卡证据；只为本卡拆分职责新增相邻模块，不修改vendor包、发布依赖或业务数据。
- 导出：完成源仓库验证并发布候选提交，再git archive同步cloud-agent的integrations/erpnext及SOURCE记录；不能仅在同步副本隐藏违规。
- 不变量：保留业务认证/当前权限、原请求/原收据/unknown不重发、Coverage、历史和原overlay入口；机械格式优先做AST对照；显式导入与闭包需逐类验证。
- 验证：原锁定工具Ruff/文件尺寸规则不降低；已有本机隔离检查与前端build/test串行。组合树完整make test/check和HA02真实PG由cloud-agent独立记录，非生产验收。

## 实施路径分工（同一卡/同一Owner，避免重叠）

- App子任务（单一实现代理）：zebra_erpnext/；cloud-patches/{chat-recovery/host/,host-overrides/zebra_erpnext/,host-baseline/zebra_erpnext/}；仅因新增App模块需调整的host Dockerfile复制。
- 主执行：其余cloud-patches/{overrides/,tests/,operator/,*.py}及deploy/、frontend/、源规则/证据/装配；不覆盖App子任务文件。
- 子代理只编辑/自审，不启动测试/构建/Docker或提交；主执行统一串行验证，规格审查通过后再独立质量审查。

- Runtime子任务（App规格/质量审查已通过后，另一个新实现代理）：cloud-patches/{overrides/,chat-recovery/{core/,runtime/,tools/,worker/}}中超限Runtime源文件及新增相邻职责模块、必要Dockerfile COPY接线；不改baseline、App、检查脚本、数据转移工具。主执行暂停修改这些文件，验证仍统一串行。

- Transfer子任务（Runtime规格/质量审查通过后新实现代理）：cloud-patches/transfer_erp_database.py、check_transfer_erp_database.py及必要相邻transfer_*.py/对应检查夹具；不运行迁移/容器/网络，保留CLI、协议与原操作处理。若拆分影响原单文件Worker分发，使用标准库可移植打包且固定入口/参数保持，不注入全局命名空间。

- Operator子任务（前项审查及修复完成后新代理）：cloud-patches/operator/private_workspace_operator.py及相邻专职模块、为其新增模块必需的deploy源码复制接线；不运行sudo/mount/容器/服务，不修改测试。主执行串行验证并保持根信任/配额/原证明边界。

## 版本化源码完整性

- 保留原 frozen-manifest.json、provenance.json、deployment-evidence.json，均不改写旧摘要或已部署证据。
- 原 chat-recovery 与 host-baseline 从固定原提交完整归档，逐项校验原始字节与 SHA；归档只作历史证据，不执行或参与部署。
- source_projection.py 与 source-projection.json 为本候选新增完整性检查：同时验证原 manifest/归档和当前源码完整清单，不能将本地候选冒充已部署版本。Owned paths 增补这两个文件及原始归档证据。
- 只依赖引号/排版的源码断言改为等价 AST 断言；保留原权限、审批、原生状态和 unknown 业务断言。

## 源候选验证与证明边界

- Ruff 全规则0诊断；原尺寸门禁411源码文件0违规，无目录排除/规则忽略/阈值放宽。
- 前端build/test通过；真实Host适配器检查同源、CSRF、会话/栅栏、取消与仅一次提交。
- 离线Python检查全部通过，另9个原生组合检查通过；详见evidence/ca-baseline-gate-02/source-validation.json。7项原夹具失败已在原提交复现，修复夹具且保留原断言；过时字符串断言改为AST或实际异步行为验收。
- 新增原始命令拒绝回调延迟执行回归，确保后续扫描不会将早先命令写到后续数据库/命名空间。
- 原生检查基于当前119依赖与IO doubles，不宣称已部署105镜像或真实ERP/Redis/数据库验收。转移工具stdlib含真实隔离Worker归档执行通过；105 SQL/真实数据转移未运行，不放宽版本守卫。
- source_projection检查需完整canonical目录布局（docs/evidence与cloud-patches并存）；若容器内运行源检查，必须只读挂载完整源码根。Runtime Docker目录COPY、工具Worker自包含归档和Operator三个同目录文件分别保持。
- 本卡未创建Docker、调用真实模型/业务API、执行部署或生产迁移。接下来发布源候选后由父仓库精确archive导出，组合原生01与HA02重跑完整门禁。

# Cloud Agent 基线门禁整改

2026-10-31；基线e8a4f10b；Owner Luke Ding，执行Codex。
输入为CA-HA-02独立候选d16645aa发布的完整门禁与干净基线复现，非HA02新引入。
本轮分支codex/ca-baseline-gate-01从主线独立创建，不混入HA02代码或无关脏工作树。

## 1. 原生整改（01 / Review）

- 真实缺陷：两个新增AGUI关闭开关进入asdict，旧默认基线c774漂移为1bc。恢复默认
  canonical编码，并仅以同一配置/私钥精确计算兼容两种已有编码，不改原pin/快照/事件。
  启用AGUI、改变API凭据/Host授权仍拒绝旧任务；不使用忽略字段或只信catalog的宽松回退。
  历史别名仅限这两种编码；后续新配置须先评审版本投影，不能无限追加猜测性别名。
- Coverage HTTP夹具声明纯编排，却缺失新增当前Profile冻结边界，invalid-dsn进入真实
  数据库适配器。使用明确的未绑定Profile与零摘要，并补失败仍503的反例；生产拒绝不改。
- Worker旧夹具要求普通路径调用解析器，与efba8aa2已发布行为冲突。扩展普通路径/URI、
  local/cloud、解析失败及严格模式先拒绝矩阵，保留原普通路径直通与严格Coverage机制。
- 流式夹具使用真实Starlette请求及/v1路径，保留当前授权只执行一次且在准备前的断言。
- 固定SDK已是ag-ui-protocol1.0.0；spike仍断言0.1.19。改为实际锁定版本及明确枚举，
  不更新依赖、不删除历史Domain Events或改变运行期mapper。
- 原生Task facade515行：元数据函数原样移至既有replay-header模块；AST一致、旧导入
  别名和mypy显式导出保持。没有改SQL、权限、索引、Coverage或历史修复算法。

[证据](evidence/ca-baseline-gate-01/validation.json)：新增摘要回归2失败/1通过→通过；
扩展242通过/29条件跳过，另1项真实PG在完整schema上以元数据只读角色通过。原事件
字节保持；镜像复用且限1CPU/512MiB/PID128、数据tmpfs256MiB，inspect校验，finally回收。
mypy1492源、Eval30及局部Ruff/进度风险/产品边界通过；完整门禁尚未通过，不作生产证明。

## 2. ERPNext整改（02 / Ready，未领取）

`integrations/erpnext/SOURCE.md`声明独立仓库zebra-erpnext的同步导出。只读核对GitHub
main仍为2e8606a603ffe8836fc8a42874b9771f470bc82c，与记录一致，无已修复上游可直接同步。
剩余15尺寸/4924Ruff全部在此目录，01不直接格式化这些运行期overlays或排除目录。

下一任务须在canonical仓库领取独立分支/Owner并读取其AGENTS，再逐文件界定Owned paths：

1. 区分实际Frappe App、前端、部署/数据转移工具和各固定Cloud overlays。明确每组生效
   导入/打包路径，保留原入口、导出、副作用和覆盖文件布局。
2. 先修真实未定义/闭包绑定问题及可机械验证的格式，再按职责拆超限文件；不得用整目录
   exclude、per-file全规则忽略、简单删空行或盲目删除import来规避门禁。
3. overlay拆分的新模块必须进入原构建上下文，保留历史变体与固定兼容基线；业务权限、
   原请求持久化、unknown不重发及原收据不弱化。转移工具不得对生产数据执行。
4. canonical的单元/构建验证通过后，以git archive同步本仓库导出并更新SOURCE提交。
   原生01与ERP02组合树再串行完整make test/check、HA02真实PG复验及最后集成。

02候选仍Review，未满足用户条件合并；HA03依赖01已完成，但HA02未合入，继续Locked。
本轮没有部署、生产迁移或真实业务/模型请求。

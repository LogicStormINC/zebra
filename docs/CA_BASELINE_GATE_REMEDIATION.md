# Cloud Agent 基线门禁整改

当前：2026-11-01 原生01/ERP02/HA02完整组合验收通过并快进本地cloud-agent；最终结果见第3节。第1–2节保留当时输入与阻塞记录。

2026-10-31；基线e8a4f10b；Owner Luke Ding，执行Codex。
输入为CA-HA-02独立候选d16645aa发布的完整门禁与干净基线复现，非HA02新引入。
本轮分支codex/ca-baseline-gate-01从主线独立创建，不混入HA02代码或无关脏工作树。

## 1. 原生整改（01 / 历史候选记录）

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

## 2. ERPNext整改（02 / 历史计划，已完成）

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

## 3. CA-BASELINE-GATE-02 完整结果与集成

- canonical独立分支codex/ca-baseline-gate-02：源实现439fb72、证据92b308b已发布；用git archive精确导出541文件，SOURCE固定完整SHA。未在副本排除/隐藏违规。
- Python/Ruff按原E/F/I/UP/B、100列、py312规则执行；冻结native baseline Python字节不改，仅补准确项目isort上下文，无新增忽略/降低阈值。源尺寸411/0，组合4046/0，Ruff0。
- App/Runtime/转移/Operator依职责拆分，显式导出和所有构建源闭包保持；原frozen-manifest/provenance/部署证据不改，原Host/chat源码归档与新候选清单双重验证，不能冒充旧部署。
- Transfer Worker使用标准库确定性自包含ZIP，保留原worker.py路径/argv/独占写入/协议；Operator三个相邻文件均按root:root0644安装；只编辑和离线检查，未执行物理/部署/转移操作。
- 前端build/test、19源离线检查、9当前原生119依赖+doubles检查、延迟拒绝回调的原数据库/命名空间/命令回归通过。105真实镜像/SQL/迁移不宣称通过；原版本守卫仍拒绝119目录。
- 两次完整树验收暴露夹具问题：旧手工摘要仍纳入后加False字段；租约测试假定主线程必先于后台续约。先保留RED和原树字节证据，再修独立投影与实际事件交接证明；没有修改生产实现或改掉旧历史摘要，分别19项、23项/6条件跳过及20重复通过，规格/质量复核通过。
- 最终make test11672通过/0失败/3161条件跳过（1331.53s）；make check全绿：尺寸4046/0、Ruff0、mypy1494、Eval30及产品/进度/unknown风险全部通过。
- HA02真实PG5通过11.30s，原生epoch/角色槽耗尽/锁超时恢复/schema拒绝/Worker能力到期；单容器1CPU/512MiB/PID128/tmpfs256MiB，finally回收。前后仅原overdoze-dev-pg；不是集群/真实IdP/UX负载证明。
- 已验证代码2b908448已快进至本地cloud-agent；本次最终证据提交随主线推送。旧数据、原收据、unknown、Coverage、前端mock和无关工作树保持，无部署/生产迁移。
- [机器收据及全量日志](evidence/ca-baseline-gate-02/validation.json)保留每轮失败与最终成功；01/02/HA02完成，CA-HA-03仅Ready，后续领取后再实施。

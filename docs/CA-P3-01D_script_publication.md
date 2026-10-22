# CA-P3-01D — 脚本 Bundle 的受权物化与发布

日期：2026-10-23。状态：Review；完整门禁通过，源交付以授权功能分支及远端回执为准。
[机器合同](contracts/script-publication/contract.json) · [任务登记](AGENT_TASKS.md)。

## 问题与边界

P3 B 已有 ScriptBundle/ScriptAssembly、Definition3/Snapshot3、Worker 兼容检查与持久执行收据；
C 只有纯包校验；原 P2 公开 runtime-publication/1 接口只接受基础 Bundle。
因此平台封存的资产还不能通过独立、明确的原生公开合同形成脚本 Version/Release。
本片补原生前置，复用现有装配器、Registry、可信 Eval、当前发布者授权和持久收据。
不执行源码、不上传源码、不生成 EvalEvidence、不替代 Coverage 或自动审批 catalog。

Go BC-ASSET 仍拥有私有草稿和不可变资产版本；BC-DESIGN 后续拥有精确配置与发布意图。
Python Registry 拥有 Definition/Release，Worker 拥有任务快照/实际执行与证明。
平台不得把 sealed 直接解释为执行批准，不得访问原生数据库或复制执行状态机。

## 接口与交互

- `POST /management/v1/script-publication`：action 为 materialize 或 publish。
- `GET /management/v1/script-publication`：用 `X-Runtime-Operation` 查询原 UUID 收据，无 body。
- 两者均要求 `X-Runtime-Publication-Contract` 等于机器合同的 contractDigest。
  固定合同从本仓库制品获得；本片不新增匿名合同发现接口。
- 使用原独立 `rtpub_` 服务凭据、精确 deployment/audience/product/environment/trustRevision 头、
  namespace、私有 approval/1 和共享 PostgreSQL 当前批准；不接受业务 HostGrant、管理 Cookie 或包校验 Token。
- 当前 action 必须在批准列表内；旧发布者不会仅凭 materialize/publish 自动获脚本权限。

materialize 的字段与原 P2 用例一致，`bundle` **只能**是显式 `cloud-agent.script-bundle/1`：

```json
{
  "action": "materialize",
  "operationId": "10000000-0000-4000-8000-000000000001",
  "expectedRevision": 0,
  "versionId": "10000000-0000-4000-8000-000000000002",
  "version": 1,
  "bundle": {"schema_version": "cloud-agent.script-bundle/1"}
}
```

operationId/versionId必须是规范UUID字符串，非字符串统一422；共用入口修复同时保护旧渠道。
示例省略实际 Bundle 内容，不能直接通过校验。完整基础 Bundle、脚本计划、Manifest、精确 lock、
runner 和外层摘要遵守 [B 原生合同](contracts/native-script-worker-v1/script-bundle.schema.json)。
原生 catalog/2 必须已由操作员批准完整 plan、原始源码、provider/image/baseline 等资产。
发布者同时需要精确 `runtime-bundle/<base摘要>@1` 和 `script-bundle/<外层摘要>@1`，
以及既有模板引用授权；不接受通配符、latest、仅源码摘要或单包校验回执替代。

流程：先校验外层类型/摘要与本地批准，再通过原 DraftService 创建/更新/校验草稿和物化 Definition3。
全部 Registry 修改、Definition 级 revision 和 operation 收据共用同一个数据库事务，失败整体回滚。
结果保留原 `bundleDigest`（基础 Bundle）、`assemblyDigest`、`definitionDigest`；
另有 `publicationContract=script-publication/1` 和 `scriptBundleDigest`（显式脚本外层）。
不得把 base/outer/assembly/Definition 四种摘要混为一谈；响应不包含源码。

publish 仍只接 action/operationId/expectedRevision/versionId/evidenceId。
必须为该 scope 的 ScriptDefinition3；原生最新 EvalEvidence 必须属于受信 evaluator、指定 policy、
完全一致的 Definition digest、passed，且 evidenceId 相同。重新核对当前 base/script 引用及 catalog 装配。
校验 C 的 accepted、封版 sealed、Verifier 输出都不能生成或替代这个 Eval 证据。
成功创建原生 Release；响应增加 releaseId/releaseRevision/evidenceId。之后 Task 消费仍由独立 HostGrant、
原生当前发布批准、脚本 scopes、固定快照和兼容 Worker 决定。

## CAS、恢复、权限与资源

沿用每 Definition 的 PG advisory transaction lock、原共享批准检查和 revision CAS，
无网络/沙箱执行在事务内。两个入口共用每实例4个发布槽；副本数乘单实例资源预算，
不把这个预算或两个进程测试当成生产吞吐/HA 证明。
请求最多262144字节，body期限500毫秒，响应等待6秒；超时后线程可继续完成，
保留槽直到完成。503/断连/超时可能已提交，不自动重试，不以缺失收据推断未提交。
通过原 operation UUID 查询；如显式回放，必须保持原字节/原ID/原 expectedRevision，
仍核对当前授权。不能换新UUID掩盖 unknown。

两接口共享同一操作命名空间和 Definition revision，避免并行形成两套发布权威。
收据中的 publicationContract 区分渠道；从另一个接口读取返回404，跨接口复用操作提交返回409。
旧 v1 收据无新标记，仍通过旧接口读取且字节不重写；旧接口不能物化或发布脚本 Version。
旧基础 Bundle/1、基础 Definition2、旧合同文件和历史数据保持。

私有文件与共享授权在结束前重核。catalog 是有界本地文件，物化及脚本发布时重新验证；
没有声称文件更新和数据库事务跨资源原子化。Worker仍独立验证当前执行批准，不以历史发布回执绕过。
无新增表、配置项、服务、DDL 或启动补权。使用原 publication-admin 显式提高批准修订，
新增精确 script 引用；更新 catalog/2 属于操作员动作。本轮只在测试自建资源执行初始化。

错误沿用固定安全响应：401凭据错误、403范围/权限或发布门禁不足、409合同或CAS冲突、
422输入/装配拒绝、404原操作不可观察、429槽耗尽、503依赖/配置不可用。
服务不返回私有路径、Token或源码异常正文。

## 验证和剩余实施

针对新公开HTTP接口，隔离 owned PostgreSQL验证脚本物化、精确摘要、不可变版本、可信发布、
原操作读取/重放、跨渠道拒绝、缺失引用、catalog撤销、Scope/Token/合同错误、晚到授权变化回滚、
两个独立进程CAS和同operation回放；旧P2发布回归及既有脚本Worker/恢复测试保持。
现有取消测试接受取消事务先表现为 LeaseLostError 或 ExecutionInterrupted，仍要求只有 started、
无晚到完成收据及会话已取消；不改变生产取消语义。
HTTP用例使用ASGI TestClient；独立进程用例调用同一生产perform/事务入口。它们不代表两个TLS服务进程或公开HTTP到Worker的同次联合验收。
最终门禁及保存摘要见[验证证据](evidence/ca-p3-01d/validation.json)。

平台资产到配置/发布的业务实现、公开HTTP物化版本直接驱动Worker的同次联合、
真实产品、生产gVisor/模型和容量/HA均非本片证据。下一步固定本次已发布生产者合同，
再独立认领Overdoze消费者用例。前端mock、历史数据和Coverage证明机制保持，
不部署、不执行生产迁移、不整合main/cloud-agent、不发布npm。

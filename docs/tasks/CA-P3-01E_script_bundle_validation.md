# CA-P3-01E — 纯 ScriptBundle 校验

日期：2026-10-23；实现与最终门禁状态见[任务](AGENT_TASKS.md)。
[机器合同](contracts/script-bundle-validation/contract.json) · [请求schema](contracts/script-bundle-validation/request.schema.json)。

## 用例和权威

D 的公开物化会创建 Version，不能用它验证尚未提交发布的配置草稿。
C 的 script-validation/1只校验单 Manifest/源码，不能代表完整 ScriptBundle 的闭包和资产批准。
本片补无执行、无持久变更的受权观察，复用 B 的 ScriptBundle/parser/catalog/2/resolve_scripts。
不创建新聚合、配置字段、数据库表、迁移或依赖。
Go仍负责未来资产/配置意图，Python仍独占规则、实际装配和执行事实；平台消费者另片实施。

## 公开接口

| 接口 | 动作 |
| --- | --- |
| GET /management/v1/script-bundle-contract | script-bundle.contract.read |
| POST /management/v1/script-bundle-validation | script-bundle.validate |

复用独立纯Bundle凭据 `rtbv_` 与 `bundle_management_config` 私有文件，**显式**在 actions 中加入所需动作。
旧 `bundle.contract.read/bundle.validate` 不自动获得脚本权限；C 的 `rtsv_`、发布 `rtpub_`、用户及管理员凭据不能替代。
私有 approval/1允许上述四种动作的无重复非空子集；旧文件和旧API的动作/摘要/响应保持原样。
旧服务器不会识别新动作，滚动启用前应核对服务器能力并显式更新文件，不在启动时补权。

每次请求按完整产品/环境/部署/namespace scope、audience、trustRevision和私有凭据/过期时间授权。
POST要求 `Content-Type:application/json` 与 `X-Runtime-Script-Bundle-Contract` 等于当前固定制品摘要。
Body是原始 `cloud-agent.script-bundle/1` JSON，包含 base_bundle、scripts、外层 bundle_digest；
结构、ABI、完整lock/摘要/Manifest校验均由原生模型负责。不能传单基础Bundle或内联source字段。

响应包装包含 contractVersion/contractDigest/scope/trustRevision/observedAt；GET增加原静态contract。
POST结果包含：

- inputDigest：SHA256原请求字节，保留空白和顺序，与原生语义摘要不同。
- scriptBundleDigest：外层脚本Bundle摘要；baseBundleDigest：基础Bundle摘要。
- assemblyDigest：已装配原生事实；approvalDigest：当时私有catalog的非可逆快照摘要，不返回原配置或源码。
- checks：scriptBundle/assetApproval=passed，worker=not_checked，publication=not_performed。
- capabilities：源码执行/持久化/发布未执行；不提供Eval或Coverage权威。

有效输入仍必须匹配本地catalog/2的完整plan、源码、provider/image/baseline/output/build批准。
成功前重读私有catalog和授权，期间变化不提升为成功。文件与响应无法跨资源原子化；
accepted只证明 observedAt 的观察，不是永久执行允许、发布/Eval凭证、当前Worker就绪或Coverage证书。
源码只在操作员私有catalog中，校验仅编译语法不导入/调用它；API不安装依赖或运行沙箱。

## 错误、资源与恢复

401凭据错误；403范围、权限、过期或结束前批准变化；409合同摘要不同；422输入/闭包/未批准资产拒绝；
400传输错误；405方法错误；429资源饱和；503私有配置不可用、期限或内部依赖失败。
固定安全错误不带源码、私有路径或异常正文，不回退mock。

沿用共享有界传输：单协议每实例8个保留线程槽、原始body≤262144字节、读body200ms、响应等待1s。
超时后后台线程仍占槽直到完成；不能因返回503提前释放并发预算。
旧Bundle、单包C及本协议各有独立8槽，三者同时启用最多24个校验槽/实例，集群预算乘副本数；
不以这些数字声称吞吐或生产HA。原生校验不访问数据库、网络、沙箱或创建执行任务。

没有持久操作ID或发布收据；结果丢失为一次观察未知，调用方记录原平台意图并按自身CAS明确处理。
服务不自动重试、不创建替代Version。不得把该只读接口的可重复观察规则套到D发布写入的unknown重发。
共同传输的路径选择改为匹配已路由路径后缀，确保挂载前缀下的GET正确分派，覆盖P2、C和新E三个调用方。

## 验证边界

专项覆盖固定合同/schema/parser向量，Scope/凭据/动作/摘要/lock/计划/源码注入拒绝，结束前授权/catalog变化，
8个超时后台任务占满槽时仍429且最终释放，以及三种协议挂载前缀的兼容行为。
独立真实socket API进程通过GET/POST、原始摘要观察、动态凭据/权限撤销，比较自建SQLite所有表行数前后不变。
私有批准源码包含顶层写标记文件的代码，成功校验后标记仍不存在，证明没有执行或导入源代码。
SQLite由正常API启动初始化，仅为隔离测试容器；校验路径不依赖或写数据库。
该socket验收为本机HTTP，不是TLS/生产云、Go业务消费者、多副本共享存储HA或HTTP→Worker同次执行证明。

schema向量区分 schemaValid 和 nativeParseValid。JS只能验证前者及制品完整性；
外层摘要错误可以通过JSON Schema却被Python拒绝，不能用AJV结果冒充原生语义验证。
最终门禁/来源及旧文件保留见[证据](evidence/ca-p3-01e/validation.json)。
前端mock、历史Task/旧合同与Coverage机制保持，不部署、不生产迁移、不npm发布或主线整合。
下一片先固定发布后的E合同，再实现Overdoze精确资产版本/配置草稿/验证意图消费者；不提前进入P4/P5。

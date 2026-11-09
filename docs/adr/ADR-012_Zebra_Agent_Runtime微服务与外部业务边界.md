# ADR-012：Zebra Agent Runtime 微服务与外部业务边界

- 状态：Accepted
- 日期：2026-07-18
- 决策范围：产品定位、身份接入、外部授权、云端隔离和系统集成

## 1. 决策

Zebra 定位为可独立部署、可被其他产品嵌入的 **Agent Runtime 微服务**。

Zebra 负责把一次 Agent 请求可靠地执行为可流式观察、可停止、可恢复、可审计的
Task、Conversation、Session、Attempt、Event、Artifact 和 Agent Memory；不负责
承载调用方的用户中心、租户业务、订阅或商业化模型。

认证统一由外部身份平面承担。当前选定 Authelia 作为认证、SSO、MFA 和 OIDC
Provider；身份账号、凭证和注册登录流程属于 Authelia 及其外部身份目录的部署范围，
业务用户档案仍属于调用方业务系统。Zebra 不保存密码、MFA、重置令牌，也不开发
注册登录系统。

用户、组织、成员关系、邀请、业务 RBAC、订阅、套餐、计费和业务配额由调用 Zebra
的业务系统负责。Zebra 只验证面向自身的短时执行 authority，并执行 Agent 领域内的
安全 Policy 和技术资源上限。

## 2. 产品定义

```text
Zebra = Agent Runtime + Agent Control/Data Plane + Optional Operator Surface
```

Zebra 的核心价值是：

- durable Task、Conversation、Session、Attempt 和 Event；
- 模型、Context、Tool、Agent Memory、Artifact 与执行证据；
- 流式输出、取消、暂停、恢复、幂等与副作用账本；
- Worker 调度、高并发、高可用和故障恢复；
- Sandbox、Policy、Approval、Credential/Egress 边界；
- Agent 技术用量和审计证据输出。

Desktop、CLI 和 API 是同一 Runtime 的操作入口，不把 Zebra 变成业务 SaaS 平台。

## 3. 唯一责任边界

| 能力 | Authelia / 身份目录 | 外部业务系统 | Zebra |
|---|---|---|---|
| 身份账号、注册、登录、退出、密码、MFA、Passkey、SSO | 负责 | 使用身份结果 | 不实现 |
| 业务用户档案、组织、成员、邀请、加入、退出、禁用 | 不建模 | 负责 | 不建模 |
| 业务角色、资源授权、套餐、订阅、余额、计费 | 不建模 | 负责 | 不建模 |
| 业务配额的计算和购买关系 | 不建模 | 负责 | 不建模 |
| 面向 Zebra 的短时 authority 和技术限制值 | 提供主体身份 | 签发 | 验证并执行 |
| Task、Conversation、Session、Attempt、Event | 不实现 | 不实现 | 负责 |
| Model、Context、Tool、Agent Memory、Artifact | 不实现 | 不实现 | 负责 |
| Agent Policy、Approval、Sandbox 和 Effect Ledger | 不实现 | 提供上界 | 负责且只能收紧 |
| Worker、并发、HA、流式、重试、恢复 | 不实现 | 不实现 | 负责 |
| 技术用量事件 | 不处理 | 消费和解释 | 生成，不计算账单 |

任何新需求先按此表归属。没有明确属于 Agent 执行生命周期的能力，默认不进入 Zebra。

## 4. 身份与授权合同

### 4.1 认证

Authelia 是当前默认身份提供方。新系统通过 OIDC 接入；遗留 Web 入口可由受信反向
代理使用 Forward Auth，但 Zebra API 不能只信任客户端可伪造的身份 Header。

OIDC 主体以 `(issuer, subject)` 唯一标识，邮箱、用户名和显示名只作为展示属性，
不能作为 durable identity key。

### 4.2 外部执行上下文

身份凭据与业务 authority 是两个逻辑凭据。Zebra 先验证 Authelia OIDC token，再验证
业务系统签发的短时、签名、`audience=zebra` 的执行上下文。业务 authority 必须绑定
OIDC 的 `(identity_issuer, subject)`；两者的 subject 不一致、任一凭据过期，或
namespace 被替换时均 fail closed。可信网关可以封装两个凭据，但不能省略该绑定。

业务 authority 的逻辑合同如下：

```json
{
  "identity_issuer": "https://identity.example.com",
  "authority_issuer": "https://business.example.com",
  "subject": "external-principal-id",
  "audience": "zebra",
  "namespace_id": "opaque-business-scope",
  "authority": [
    "agent.task.create",
    "agent.session.read",
    "agent.session.cancel"
  ],
  "limits": {
    "max_concurrent_tasks": 5,
    "max_model_tokens": 200000,
    "max_runtime_seconds": 3600
  },
  "expires_at": "2026-07-18T12:00:00Z",
  "request_id": "req_external"
}
```

字段语义：

- `subject` 是外部主体引用，不创建 Zebra User 领域对象；
- `namespace_id` 是不透明的隔离和路由键，不表达组织、成员或订阅关系；durable
  隔离键是 `(authority_issuer, namespace_id)`；
- `authority` 是调用方授予 Zebra 的 Agent 操作上界；
- `limits` 是本次或当前 Scope 的技术执行上限，不是套餐或账单；
- Zebra Policy、Approval 和 Sandbox 可以继续收紧，绝不能扩大 authority；
- 有效 authority 摘要必须随 Attempt/Event 持久化，保证恢复和审计不漂移。

Zebra 不查询外部业务数据库确认成员关系，不共享用户表，也不根据邮箱猜测身份。

## 5. 隔离不是租户业务

Zebra 云端必须隔离不同 `(authority_issuer, namespace_id)` 的 Event、Projection、Artifact、Memory、
Snapshot、Volume、Cache、Log、Metric 和 Sandbox。这是 Agent Runtime 的数据安全
责任，不等于 Zebra 拥有 Tenant Domain。

必须满足：

- 每个入口都验证签名、identity/authority issuer、subject binding、audience、expiry
  和 Agent scope；
- 每个 durable query 和对象路径都携带 `authority_issuer` 与 `namespace_id`；
- 不允许默认 namespace、裸 `namespace_id` 查询或跨 issuer/namespace 回退；
- Cache key、队列、Artifact URL、日志和指标不得丢失 namespace；
- 跨 namespace 读取、写入、恢复、缓存命中和 Sandbox 复用测试必须 fail closed；
- 外部 authority 过期、撤销或变化后，新 Attempt 使用新快照，旧 Attempt 不获扩权。

`namespace_id` 的创建、成员和删除业务由外部系统决定；Zebra 只提供按该键清理或导出
Agent 数据的技术接口。

## 6. 技术限制与商业配额

Zebra 负责执行安全和稳定所需的硬边界：并发 Task、Token、模型轮次、工具轮次、
运行时间、CPU、内存、磁盘、网络和 Artifact 大小。

外部系统负责决定某个用户或组织购买、获赠或剩余多少额度。它可以把计算后的限制值
传给 Zebra，也可以消费 Zebra 产生的 usage event。Zebra 不包含价格、货币、订单、
账期、套餐、余额、优惠、扣费或退款逻辑。

实际限制按每个维度取最严值：

```text
effective_limits = min(签名外部 limits, Zebra 服务硬上限, 当前 Policy/Sandbox 能力)
```

缺失或非法的必需限制、试图放宽限制的恢复请求一律 fail closed；生效 limits 摘要
随 Attempt 持久化，resume、retry 和 failover 不得隐式扩容。

技术用量事件至少可关联：

```text
external request -> namespace -> task -> session -> attempt
model tokens / runtime seconds / tool calls / storage bytes / network bytes
```

该链路用于审计、容量和外部计费输入；它本身不是账单。

## 7. 微服务集成面

Zebra 对外提供版本化、业务无关的 Agent API：

- 创建和查询 Task；
- Conversation/Session 消息与状态；
- SSE/WebSocket 事件流与 cursor 恢复；
- cancel、suspend、resume 和 approval/clarification continuation；
- Artifact、Diff、Agent Memory 和执行审计；
- webhook、outbox 或 event bus 状态通知；
- usage、health、readiness 和 metrics。

集成规则：

- 不与调用方共享数据库；
- 不从调用方业务表反向读取用户、成员、套餐或权限；
- 外部引用使用 opaque ID，不复制完整业务对象；
- 创建、取消、回调和 usage event 具有 idempotency/request correlation；
- 同步 API 返回接收结果，长执行通过 durable stream/event 观察；
- API、SDK、事件和 authority schema 必须版本化并保持向后兼容策略。

## 8. 云端部署含义

云端 Zebra 仍需要 PostgreSQL Event Store、对象存储、无状态 Worker、调度、
Credential/Egress Broker、Kubernetes Sandbox、高可用、容量、SLO 和灾难恢复。
这些是 Agent Runtime 的运行职责。

下列内容永久位于 Zebra 之外，而不是“以后再补”：

- User、Organization、TenantMembership；
- 邀请、加入、退出、账号禁用；
- 业务 RBAC、业务资源树和管理后台；
- Subscription、Plan、Billing、Invoice、Payment；
- 商业配额计算和权益生命周期。

原 Phase 3 中相应任务必须改写为外部 authority 接入、不透明 namespace 隔离、
Agent 技术限制和 usage evidence，不得重新引入上述业务模型。

## 9. 结果与约束

正向结果：

- Zebra 可以被不同业务系统复用，不绑定一种用户、组织或商业模式；
- 身份和业务变化不会污染 Agent Kernel；
- 本地版、私有云和云端复用同一 Agent 领域合同；
- 外部系统可以独立替换 Authelia 之后的业务平台或授权实现。

代价与约束：

- 集成方必须提供可信 authority 和 namespace；
- Zebra 必须维护严格的边界验证、隔离和审计；
- 单独部署 Zebra 不自动获得完整 SaaS 用户与商业化能力；
- Authelia 不可用时，受保护的新调用 fail closed，运行中任务按持久 authority
  和显式恢复策略处理。

## 10. 架构不变量

1. Zebra 是 Agent Runtime 微服务，不是用户、租户或计费平台。
2. Authelia/外部身份系统负责认证；Zebra 不接触用户凭证。
3. 外部业务系统负责成员、业务授权、订阅和计费。
4. Zebra 验证外部 authority，内部 Agent Policy 只允许保持或收紧。
5. `namespace_id` 只用于 Agent 数据隔离，不形成 Zebra Tenant Domain。
6. Session Event Store 是 Agent 执行事实源；外部身份和业务数据库不是恢复依赖。
7. Zebra 生成技术用量和审计证据，但不生成商业账单。
8. 所有云端扩展必须保持 API、事件、authority 和隔离合同可替换、可版本化。

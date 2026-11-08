# CA-P3-02L / OD-P3-01G-D：业务登录回调与 Runtime 生命周期

状态：Review，完整make test/check、SDK151与双浏览器联合验收通过。依赖已发布 G-C `ec4bb07f` / SDK K `c023fa58`；
[机器合同](contracts/auth-lifecycle/contract.json)。本片没有 Python/数据库迁移或执行状态机改动。

## DDD 边界

业务拥有 IdP 回调验证、Cookie/SSO、登录事实与业务用户到平台 key 的持久绑定。
业务 BFF LoginIntent 记录一个已验证回调的固定引用和签发意图；CredentialSession 继续由 G-B 管理密文/修订和刷新。
平台是身份和 Token Family 权威；原生 Runtime 仍拥有 Profile/Session/Task/Run、Controller、Worker 及 Coverage。
本片 Go 不签 JWT，不进模型/工具循环；SDK lifecycle epoch 只管理本地 UI 取消与资源，不是分布式授权。

| 对象 | 不变量 | 事务/恢复 |
| --- | --- | --- |
| LoginIntent | 原 callback ID、Scope、原 credential Session/key/platform/expectedRevision 不变；无凭据 | 一个共享业务库行；先持久 unknown 再单次 Issue；无租约接管 |
| CredentialSession | 原身份、密文、代际及 CAS 由 G-B 持有 | 与 LoginIntent 分事务；精确原 Install 收据可确认回调完成 |
| 本地 lifecycle | 一个在途 start；认证/epoch/原生停止状态通过才返回实例 | stop 同步取消；异步晚到不能重挂；重启必须显式 |

## 登录回调流程

1. 业务 IdP 适配器完成自身协议验证（OAuth/OIDC 的 code/state/nonce/issuer/audience/PKCE 等按提供方要求），
   从服务端原始验证记录生成并持久绑定 callback UUID。浏览器提供的用户、key、产品或 `Idempotency-Key` 不构成身份。
2. 业务后端从持久映射取得原 identity_key、Scope、CredentialSession 和 CAS，调用 Go `bfflogin.Service.Complete`。
   Authorize 必须确认当前业务用户/资源权限、原绑定及新鲜登录事实，不能永久缓存“已验证”。
3. 共享 LoginIntent 先提交 unknown，再一次调用已有 G-A Issue；新 pair 直接交给 G-B Install 加密，不写入 Intent/浏览器。
   同一原 callback 重复、同 Session/expectedRevision 的不同 callback，以及两个独立进程竞争，均不能重复签发。
4. 断连/响应丢失/崩溃/安装确认丢失均保留原记录。只读 `Inspect` 核对精确原 Install 操作、原 key/platform/Session 和修订。
   原 Install 已完成可以把 Intent 确认为 completed；缺失/不可观察保持 unknown，绝不重发 Issue/Install。
5. completed 是历史回调收据，不能授权 Runtime。BFF bootstrap/操作仍检查当前业务权限、回调状态、G-B Access 与原生准入。
6. 原 Family 确认 closed 后，新鲜业务登录可使用新的已验证 callback UUID、原 key/Session 和新 CAS。
   unknown 不能换 callback ID 偷渡同 Session 代际，也不能据超时、过期或拒绝把它强制关闭。

若 Issue 成功但新 pair 在安装前丢失，现有平台没有读回该秘密或非提交证明的接口；此 Intent 保持 unknown。
人工处置需独立授权并保留原审计；不能把重新签发、批量撤销用户所有会话或另建 Session 当作自动恢复。
业务 IdP 与其持久 key 映射由业务提供；本片参考 Cookie/头只是明确的验证夹具，不是通用生产认证方案。

## SDK 集成和交互

```ts
const auth = createBFFAuth({path: '/auth', storage: sessionStorage});
const life = createAuthenticatedRuntime({
  auth,
  bootstrap: async signal => {
    const response = await fetch('/bootstrap', {
      signal, credentials: 'same-origin', cache: 'no-store', redirect: 'error',
    });
    if (!response.ok) throw new Error('bootstrap rejected');
    return response.json(); // BFF 只返回公开配置与 Profile 元数据
  },
  create: boot => ZebraClientRuntime.fromConfig(boot.config), // mode:'bff'
  mount: async (runtime, boot) => runtime.mount(boot.mount),
});
await life.start(); // 已确认业务回调后，由用户/应用明确调用
```

bootstrap/mount 回调必须尊重 AbortSignal 和自己的网络预算；create 同步构造并返回拥有 `stop/isStopped` 的实例。
BFF 配置不能包含原生凭据/Fence；真实 ZebraRuntime 的 BFF 模式仍执行既有严格校验。
本地 helper 不能替代服务端准入，不能把不受信任的浏览器 metadata 当成身份；SSR 不访问浏览器存储。
同一登录上下文复用一个 lifecycle；业务路由卸载或退出时调用 stop，不在每次 render 重建。

| 用户动作/事件 | SDK 行为 |
| --- | --- |
| 明确开始 | auth.assertActive → 新 bootstrap → 再查认证 → create/mount → 再查认证/epoch/isStopped；从不复用旧实例/Fence |
| 刷新/退出认证 | 先同步 stop，再调用已有 auth.refresh/retire；成功也不自动重启 |
| unknown / closed / refresh_required / 依赖失败 | sync 停止实例；start 拒绝；仅保留原操作定位与现有恢复接口 |
| 原操作对账 | inspect 先停，再 GET；原操作完成仍须显式新 start |
| bootstrap/mount 晚到或取消 | epoch/AbortSignal 围栏，不能创建/恢复已退出实例 |
| 原生自身终止 | 不把停止实例当挂载成功；getter 返回 null，显式 start 才可能新建 |

SDK 不轮询自动刷新、不偷偷登录、不重试未知写入。业务登录回调本身由业务路由完成，SDK 不消费供应商 code 或 Token。
认证变化事件由业务调用 sync；后端每个敏感请求始终当前检查。stop 终止本地执行并使用原有最佳努力 Controller release，
不承诺跨系统即时全局撤权。原命令 unknown 仍走原 Session/Task/Run 收据恢复，不能因登录新建实例而替换历史映射。

## 验收和部署边界

`auth-lifecycle-browser.mjs` 打包实际 SDK，在 Chromium/WebKit 验证：业务回调→真实平台身份 HTTP→独立业务 PG→
既有真实 Python HTTP Profile/Session/mount/Controller；回调确认丢失/重复不重签、unknown 停止/重载不重挂、显式重新登录取得新 Fence、当前撤权停止。
Go 定向检查使用两个独立进程竞争同一回调，以及 Issue 响应丢失、领取后崩溃、Install/Intent 确认丢失、owner/CAS 与不可替换槽位。

Native 使用既有 local compatibility 测试 Profile/凭据；业务验证使用参考 Cookie。它们不是生产 IdP、签名 cloud HostGrant、
完整模型/Worker 或 HA 认证。已有云准入合同保持；产品真实 IdP/Secret 注入、云部署和故障切换仍需要独立验收。
[最终证据](evidence/ca-p3-02l/validation.json)；旧合同/证据、原型 mock、历史/Coverage 保持，不部署、不生产迁移、不 npm 发布。

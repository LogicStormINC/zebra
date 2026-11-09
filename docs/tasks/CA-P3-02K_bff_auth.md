# CA-P3-02K / OD-P3-01G-C：同源业务认证与 SDK

状态：Review，完整门禁/SDK145/双浏览器已通过；SDK 为 opt-in。基线 J `4e629a5a`、Go G-A `94885ce9`、G-B `4b11b8af`。
[版本合同](contracts/bff-auth/contract.json)。Python 执行接口、历史合同、Task 恢复和 Coverage 不变。

## 权威和接入位置

业务拥有 IdP、登录 Cookie、当前权限及业务用户到平台 identity_key 的持久绑定。
Overdoze 平台公开身份接口拥有身份及 Token Family；Go 业务 BFF 的 G-A 防腐客户端调用这些接口，
G-B CredentialSession 拥有业务自有数据库中的密文、代际、CAS 和原操作日志。
认证门面是可选业务 BFF HTTP 适配器，不是管理后台接口，也不替代原生 Broker/HostGrant/Client Session。
SDK 只管理浏览器状态和不具授权力的操作定位符；不能决定业务权限、原生准入或恢复原 Task。

本片不增加 Python HTTP、表或执行状态机。生产 IdP、业务 Cookie 实现、共享 Secret 托管和集群 HA
需要产品集成时单独验收。参考 Cookie/重新认证按钮仅证明实际平台接口与独立业务库的认证流。

## 开发者集成

```ts
import {createBFFAuth, ZebraClientRuntime} from '@zebra-agent/client-core';
const auth = createBFFAuth({path: '/bff/auth', storage: sessionStorage});
const current = await auth.assertActive();
// 此后由业务 BFF 返回已有无秘密的 Runtime browser config。
// BFF bootstrap 自身必须先 Service.Access，再走原生公开准入链路。
const config = await (await fetch('/bff/bootstrap')).json();
const runtime = ZebraClientRuntime.fromConfig(config);
```

同源路径仅允许 ASCII 字母数字、下划线、短横线的普通路径段；拒绝 URL、query、编码、空段和尾斜线。
SSR 阶段不访问 sessionStorage；在业务已登录的浏览器生命周期创建 helper。
同一登录上下文复用 helper；业务登录切换须使用对应 BFF 服务端会话映射，不凭浏览器标识复用旧身份。
退出时业务应用应立即停止/释放已挂载 Runtime；重新登录后取新配置/新挂载，不能恢复旧 Fence。
`assertActive` 是用户体验门禁，后端必须独立验证；它不保证下一请求仍有效，也不会启动 Runtime。

## HTTP 协议

所有调用使用 same-origin Cookie、`X-Overdoze-Auth: 1`、no-store、redirect:error。
写入还要求固定业务 Origin、application/json、非零小写 UUID `Idempotency-Key`。
BFF 拒绝浏览器 Authorization、跨站 Sec-Fetch-Site、Host 不匹配、query 和任何身份/Token 覆盖字段；不启用 CORS。
业务反向代理保留受控 Host，不能以任意浏览器头重写权威 Origin。

| 方法 | 用途 | 输入 |
| --- | --- | --- |
| `GET base` / `auth.state()` | 当前业务认证状态及当前操作 | 无 body/key；只读 |
| `GET base/receipt` / `auth.inspect(id)` | 原操作收据及当前状态 | 原 UUID header；只读，绝不派发 |
| `POST base/refresh` / `auth.refresh(revision)` | 显式刷新一次 | `{revision}` + 新 UUID，G-B CAS |
| `POST base/retire` / `auth.retire(revision)` | 用户显式退出/恢复 | `{revision}` + 新 UUID，撤销原 Family |

成功严格 DTO：`{version:'1', status, revision, currentOperation, receipt:{operation,kind,outcome}}`。
不返回 Token、identity_key、CredentialSession ID、平台地址、主体、输入摘要、代际或密文。
kind 为 install/refresh/retire；未观察到请求时 kind 为空，outcome 为 not_observed。
completed 是原操作历史收据，不能替代当前认证；当前状态来自业务授权后的同一 Session 修订快照。

| 状态 | 行为 |
| --- | --- |
| active | 平台 Current 和当前业务授权通过，可申请受保护 bootstrap；准入仍须后端独立检查 |
| refresh_required | 业务当前授权允许查看 CAS，但当前 Access 已失效/被拒绝；禁止 bootstrap，可显式刷新或退出，不保证刷新有效 |
| unknown | 已持久领取但结果不明；禁止新刷新/准入，只读对账或用户明确退出 |
| closed | 原 Family 撤销已确认；需要新鲜业务重新认证、服务端签发及安装同 identity_key 的新 pair |

400 无效输入、401 当前业务身份不可用、403 来源拒绝、409 CAS/快照变化、413 超量、503 依赖或写入 unknown。
错误只返回 `{version:'1',error}`，不反射 Cookie、外部响应或凭据；SDK 遇到错误保留 marker，不重试。
权限撤销和外部有效性检查跨系统不具分布式线性化承诺；后端敏感操作始终使用当前 Access 与权限。

## 页面交互与恢复

1. 业务已登录 → 可信 BFF 从当前业务会话解析固定 CredentialSession → SDK 查询状态。
2. active → `assertActive` → BFF 独立 Access 门禁 → 原公开 bootstrap/HostGrant/Task 链路 → 挂载 SDK。
3. refresh_required → 显示“需要刷新认证”，用户明确操作 → SDK 先保存并读回 UUID/kind → 一次 POST。
4. 发生断连、超时、503、冲突或恶意/不匹配响应 → 保留 marker。刷新页面重新创建 helper，
   `pending()` 返回原 locator；`inspect(locator.operation)` 仅 GET。not_observed/unknown 均不清除、不重发。
5. 原操作 completed → 清除匹配的本地 marker，重新读取当前状态；当前 unknown/closed 仍阻止 bootstrap。
6. 无 marker 的另一设备通过当前状态得到 unknown 和 currentOperation，亦不能 bootstrap；可只读查询该原操作。
7. 用户明确退出原 Family → `retire(current.revision)`。它可替换本地未知 locator 为新的退出 locator；
   旧 unknown 仍保留在 BFF 审计，绝不改写为 completed。退出也可能 unknown，原退出操作只读查询，不自动再撤销。
8. closed → 业务重新认证 → 可信服务端签发和 G-B Install → SDK 重新查询、重新 bootstrap。
   当前平台 Issue 无恢复新秘密的幂等合同；不得把未知签发当作失败自动重发。

浏览器存储仅包含版本/路径命名空间下的 UUID/kind；不保存 Token、用户身份、业务数据或原生 Fence。
存储失败在网络派发前拒绝；损坏 marker 失败关闭。结果不明时保留定位符，不能通过清空 storage 绕过后端 unknown。
显式退出是单独用户意图，不是自动刷新重试；旧命令的 unknown 对账仍使用原 Native Session 映射，不能替换凭据/Task。

## 资源、兼容与验收

BFF 每副本默认 8、最多 32 个并发，无排队；入口 9 秒，读/写 G-B 5/8 秒；请求 256 字节，SDK 响应 4096 字节、10 秒。
共享库短行事务与 CAS，不持锁调用平台，不添加进程内权威锁/租约接管。每副本预算需乘副本数规划，不构成 QPS/HA 认证。
业务 HTTP 容器另设 header/body/idle/drain 预算；业务数据库和外部 Keyring 按 G-B 显式初始化/部署，门面不运行 DDL。

定向 SDK 检查覆盖 marker-before-dispatch、reload、严格 DTO、失效状态、存储失败、在途重复、错误保留、显式退出。
`sdks/typescript/scripts/bff-auth-browser.mjs` 使用打包 SDK、实际 Go 平台身份 HTTP 与独立业务 PG，Chromium/WebKit。
通过 `OVERDOZE_AUTH_FIXTURE_BIN` 显式传入 Go identity adapter 测试二进制；只创建并清理自有临时资源。
完整结果和来源边界见[本片验证证据](evidence/ca-p3-02k/validation.json)。
前端 mock 保留；未做部署、生产迁移、npm 发布或生产业务 IdP/存储故障切换验收。

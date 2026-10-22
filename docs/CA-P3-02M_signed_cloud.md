# CA-P3-02M / OD-P3-01G-E：业务 OIDC 与签名云准入

状态：联合验收已通过，完整门禁和源固定记录见 [validation](evidence/ca-p3-02m/validation.json)。
依赖已发布 CA-P3-02L `760fcfb9` / G-D `0547c2b1`。本片不修改生产 Python、SDK、原生数据库 schema 或旧合同。
[机器合同](contracts/business-cloud/contract.json) 描述成对接入约束，不新增原生 HTTP API。

## 边界与复用

业务 BFF 验证业务 OIDC，业务持久映射 `(issuer, sub, product/environment)` → 平台生成 identity_key。
Overdoze 继续提供三字段身份及当前授权；业务登录不能替代平台管理员登录。
Python generic Broker 通过既有公开 current-authority HTTP 合同复核当前业务/平台身份，签发短期 HostGrant。
Python Runtime 继续验证 issuer/audience/Host/namespace/Origin/signature/replay，拥有 Task/Run/Session/Profile/Controller。
Go 的 OIDC JWT **验证**不产生原生签名或执行授权；两套密钥、issuer 和 audience 独立。

新增 `tests/acceptance/business_cloud_services.py` 仅是显式隔离验收组合根：

- 独立测试 IdP：真实 TLS、RS256 JWKS、S256 PKCE、nonce、单次 code、客户端认证及受控测试账户。
- Broker：复用现有 generic current-authority → 签名实现，不注入“已验证 grant”。
- Runtime：`profile=cloud`、真实 PostgreSQL stores、原生 HostGrant verifier/replay、产品 Profile/Task/Session/Controller。
- 仅自有临时 DB/进程/证书/密钥；命令 `execute=false`，无 Worker、模型、对象存储、生产资源操作。

## 登录与恢复

1. BFF 持久 pending 原 state、Cookie 绑定 hash、批准配置 hash、加密 PKCE verifier/nonce，返回授权 URL。
2. 业务 IdP 完成授权码协议；BFF 共享 DB 提交 pending→unknown 后仅兑换一次。
3. 验证成功记 verified，取得服务端 subject；业务映射原平台 key，复用 G-D LoginIntent 单次 Issue 和 G-B 密文 Session。
4. BFF 持有所有 IdP/Agent 凭据。浏览器只拿业务 Cookie、原操作定位和安全状态；IdP token 不写业务状态库。
5. 响应不明不再兑换 code；只能读取原记录。proof 已落库但确认丢失可观察 verified；只有 consumed code 响应丢失不能推断成功。
6. 原生请求在 BFF 复核业务权限和平台 Current，再向 generic Broker 换签名 grant，经真实 HTTP 进入 Runtime。

unknown 不是非提交证明，无超时接管；原生 Controller 围栏、当前 Profile、Task/Run 归属不由业务 Cookie 替代。

## 证明与未证明

联合检查覆盖两个独立 BFF 进程/共享业务 PG、重启只读恢复、同 code 单次兑换/单个 Agent family、
错误 Cookie/nonce/changed-code、兑换响应丢失 unknown、不重发；真实签名 Task→Run→Session→Controller heartbeat/release，
错误 user/fence/run、释放后失效、当前业务拒绝、Profile 停用和 IdP token 不能充当 HostGrant。

使用受控 IdP 测试账户和合成非生产产品参数。没有实际供应商 IdP/产品账户/正式域名和信任批准，
因此实际产品验收状态是 `NOT_RUN_MISSING_REAL_PRODUCT_PARAMETERS`。不声称真实浏览器 SDK + 本链路一次联合运行、
模型执行、生产 HA、即时撤销或原生命令跨副本恢复。此前 G-D 双浏览器证据保持为独立证据。
既有 grant 在 TTL 内可能继续有效；测试 TTL8s 是隔离参数，不是生产 SLA。

## 运行

在 Overdoze 消费方执行 `make accept-p3-business-cloud RUNTIME_PYTHON=/absolute/native/.venv/bin/python NATIVE_ROOT=/absolute/native P3_BUSINESS_CLOUD_OUTPUT=/absolute/fresh-output`。
消费方先核对已发布生产者 commit、Git blob、所需源码及合同，再创建隔离服务；拒绝外部 DSN，退出清理自有容器和进程。
真实产品参数清单和安全配置参考消费方 `docs/api/business-cloud.md` 与 `contracts/business-cloud/v1/product-inputs.json`。
不部署、不生产迁移、不发布 npm、不整合主线。

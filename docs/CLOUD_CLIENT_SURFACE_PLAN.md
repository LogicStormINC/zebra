# Client Surface 组合准入实施计划

> For agentic workers: use executing-plans to implement serially. Existing owner Luke Ding,
> branch codex/client-surface-01. User approved continuation of the prior admission plan.

**Goal:** 减少已认证Client的mount/binding串行往返，保留现有凭据、权限与fence。
**Architecture:** 新POST /v1/tasks/{task}/runs/{run}/client-surface组合原mount与bind。
open独立，3→2请求；现有凭据认证、领域服务、存储及nonce消费保持。
**Tech Stack:** 现有Python/Pydantic API、PostgreSQL、TypeScript client-core，无新依赖。

## 冻结契约

上一轮提议3→1；源码确认session credential/fence仅存hash，一次open响应丢失时不能
重新取得原secret。为避免secret明文持久化或新凭据协议，先组合mount+bind。原open
得到现有credential，组合请求使用X-Zebra-Client-Session及每次新的HostGrant。

请求：{mount:原MountedCapabilitySnapshot,task_capability_scope:原能力列表,controller:bool}。
严格拒绝顶层未知字段、非bool角色、非法/过长能力列表、错误Task/Run/Client/Host/namespace。
复用原mount_client_session和bind_client_run，不复制领域状态机。成功返回原mount与
binding字段的并集；credential仍来自独立open，不在响应缓存、Event或日志中存secret。

在新路径HTTP消费nonce前验证当前Task principal/Run目标；route层也用现有
 task_access_response保留直接RouteAdapter边界。原有三路径行为不改。
mount成功但bind失败时返回原错误，已有mount及可能已保存的binding保留；没有执行模型。相同请求/credential
可用新Grant重试：同Session、相同mount revision/digest、同binding key，controller fence
按现有claim_controller轮换。先前响应/旧fence应失效；不保证每次HTTP返回相同bearer。
并发竞争仍由数据库唯一控制租约与精确binding检查裁决，冲突不fallback、不扩大能力。

capabilities/runtime增加client_surface_contract_version，当前Client组合完整可用时1，
否则0。旧consumer忽略新增字段。新SDK接收调用者提供的transport，不持有HostGrant，
显式capability1只发组合请求，否则原mount+binding；已广告的新路径失败不静默重试旧路径。
不添加自动网络重试，不重新open，不在失败后派发模型。

Trench仅作消费适配：复用已有runtime capability探测返回值，在当前请求payload携带版本，
prepare_client_surface传给现有gateway。新Task采用能力1；没有该探测的旧会话保守旧路径。
不增加一次探测、不改产品权限/思考/模型/Run逻辑。Python消费适配与NPM SDK分别验证。

## Chunk 1: API与边界

- [x] tests/api/test_client_surface.py先写组合成功/拒绝/重试与部分失败检查并观察红。
- [x] 新client_surface.py请求边界和组合函数；原route调度复用凭据authorizer。
- [x] api_status_mixin.get_runtime_capabilities复用原响应并加版本；routes.py迁出原内联块
      （当前500行硬限），不为一行新能力扩修其它路由。
- [x] http_host_auth.validate_host_target只扩展精确新路径，复用原Task/Run authority验证。
- [x] 相关Client/Host/HTTP/fence回归；实际PG相同mount+bind和响应丢失/竞争检查。

## Chunk 2: SDK与消费适配

- [x] client-core/src/client_surface.ts实现显式1-vs2调用；index只加export（498→499行）。
- [x] client-surface.test.ts验证协商、响应校验、不安全fallback禁用、原body/credential传递。
- [x] Trench四个已声明文件做最小适配，单个新test覆盖capability/旧路径/错误不fallback。
- [x] 原有SDK构建/类型检查和相关消费测试；仅本地构建/打包，不npm发布。

## Chunk 3: 接入验收

- [x] 同能力无模型原生存储准入计时/SQL检查；真实HTTP配对另计授权/间隙，二者不混用。
- [x] 原正常服务完整保存并只更新API/消费适配；Worker43项已有收益不改。
- [x] 一组新真实公开搜索页面A/B，Flash/high、transient_v2、无旧Run重放，实际API路径确认。
- [x] 撤除trace/页面观察器，正常入口/源码/hash/配置核对；记录所有失败不挑好数据。
- [x] 代码/文档集中审查、明确门限；只本地提交/FF，保留Zebra27与Trench既有无关脏改动。

## 终点与收益边界

本轮只交付mount+binding合并，完整open合一暂不建。直接目标是少1次Host Grant交换、
1次API授权和两条操作间的传输/调度；原业务存储操作不删。上次测量mount→binding间隙
255ms，不能承诺稳定页面收益或把所有3.23s归成可消除开销。首次组合失败仍fail closed。
不扩修旧fixture、签名算法、通用批处理、原Client路由历史权限问题或其它SDK UI变更。

## 验收修正

实际B1发现整个新入口的累计2s预算使三个旧Client适配器首次进入限时连接路径，
各自创建解析器，增加201ms冷解析。B2只在API composition中把现有Cloud
TaskIoConnections向下传给三个Client适配器。复用已有30s地址缓存，连接/事务/权限
仍逐次新建/验证；DSN兼容性由已有require_compatible校验。Worker默认调用不改。
B1回退数据保留，最终结果及单组测量边界见CLOUD_CLIENT_SURFACE_ACCEPTANCE.md。

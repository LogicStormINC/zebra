# CA-P3-02J — 跨设备待对账发现与人工处置

状态：Review；make test 10971通过/3022条件跳过（1220.28s），make check通过（1393类型文件/30eval）；SDK139、React18/19与双浏览器矩阵、新跨设备及旧恢复联合验收通过；3768保护文件未变。
[本片证据](evidence/ca-p3-02j/validation.json)；依赖已发布 I be4b442c / H 公开收据1，业务BFF依赖 E b710e4a。
[公开合同](contracts/request-discovery/contract.json)；本片仅新增可选 SDK 收件箱，Python执行代码、历史与Coverage不变。

## DDD 与不变量

业务BFF原请求日志负责主体/资源内待处理发现；Runtime仍是命令接纳权威。
人工处置审计属于原请求聚合的业务记录，使用独立revision，不能改原坐标、指纹、接纳revision或commandId。
不把人工“已知悉”解释为执行完成、未提交证明或重发许可。原Session不可观察时，只能保留unknown并升级人工跟踪。
只记录白名单动作/原因、服务器认证actor、DB时间与CAS修订；不保存页面原文或自由文本秘密。

## 开发者接入与交互

1. 业务登录确认当前tenant/subject/resource；资源收件箱路由与当前设备Task/mount无关。
2. `createCommandRecoveryInbox({path:"/bff/command-recovery"})`；只访问业务同源BFF，Cookie认证、no-store、禁止重定向，五秒超时。
3. 在调用方bootstrap/新工作之前显式 `await inbox.assertClear()`。失败或unknown显示待对账流程；SDK不会自动启动/停止其他Runtime。
   此检查是工作流门禁，不是跨设备原子提交锁；业务服务若需要“任何unknown期间禁止所有新key”，须另行定义持久准入不变量，不能仅依赖浏览器检查。
4. `inbox.discover(after,limit)`获取本人资源内原请求key/status/handling；没有新设备sessionStorage也能发现。
   页面1–50条，默认20；UUID keyset、无总数；权限先于分页，after必须属于当前主体/资源原日志。
   UUID不是时间顺序，扫描期间新插入可能位于游标之前，刷新从第一页重扫；不声称快照/无限实时发现。
5. 用户选择原请求，`inbox.reconcile(key)`只读原映射收据；不要求给浏览器原Runtime/Session/Segment或旧凭据。
   原Session失效/权限不明/依赖失败保持阻塞；不换新Session、不选latestRuntime，不重发。
6. 具备单独人工权限时，显式 `inbox.handle(key,{revision,action:"escalate",reason:"unobservable"})`；
   或 `acknowledge_unknown`/`support_review`。成功只表示审计已记录；CAS409/超时需要重新发现当前revision，不自动重试写入。
7. 已处理unknown仍在列表且assertClear仍拒绝，旧设备本地标识不清除。原权威恢复后仍可只读对账；
   只有真实原收据accepted才从服务端unknown查询中消失。旧设备单独对账清理本地标识，重新bootstrap/mount；不恢复旧fence。

GET响应只含`items:[{key,status:"unknown",handling:{revision,action,reason}}],next`；
revision0使用空action/reason；人工revision1–32。收据沿用unknown/accepted+commandId，人工请求严格三字段JSON。
SDK拒绝多余字段、乱序/重复key、不一致next/handling、超页、跨域path和异常返回；不把错误当空列表。

## 持久化与授权

Go库显式InitializeRecovery在业务自有schema添加审计表/索引；旧请求不重写、旧实例可共存。
新实例必须先完成显式初始化；缺表失败关闭，回退旧代码保留新增审计，不删除历史。
发现权限明确授予当前主体在该资源内读取本人全部待对账元数据，不以原生Task可执行性代替业务发现权限。
人工操作必须另行提供当前权限回调；只允许处置本人scope内请求，不提供任意用户管理员越权接口。
原生收据仍走旧当前身份与原Target前后复核。人工审计和原生接纳使用不同CAS；单原请求短行锁协调两者，无外呼持锁。
业务授权回调是当前前后观察，不声称跨业务库/IdP撤权线性化；生产集成须证明自己的授权提交边界。

## 验证与限制

具体结果记录到本片validation/preservation证据，不覆盖旧证据。
独享PG、跨进程重启、两个浏览器独立上下文与当前原Session收据均为验收范围；fixture Cookie/local authority不等同生产IdP/cloud/模型/HA。
原生无权威非提交证明，因此本片不提供“强制完成/重试/清除unknown”。不接管理mock、不部署/生产迁移/npm发布/主线整合。

发现范围是业务日志中尚未得到接纳事实的unknown，不是所有设备本地未清理marker的清单。业务日志已记录原生accepted时不会回退unknown；旧设备丢响应保留的本地marker仍通过既有原请求对账清理。

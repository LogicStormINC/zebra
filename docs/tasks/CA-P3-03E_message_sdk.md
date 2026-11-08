# CA-P3-03E 显式业务BFF原消息恢复SDK

依赖已发布D bd348909，配对平台OD-P3-01AB-B。只扩展TypeScript client-core，不修改Python/数据库/Worker/原原生合同。Go BFF通过原Task-message v2和D条件挂载消费；浏览器同源version1 DTO由Overdoze拥有。验证见[evidence](evidence/ca-p3-03e/validation.json)，固定发布源联合由AB-B另存。

## 接入

```ts
import {createBFFMessages} from '@zebra-agent/client-core';
const messages = createBFFMessages({path:'/messages/registered-tab/registered-document',storage:sessionStorage});
const observed = await messages.discover(); // 只GET；不是授权或自动恢复执行
if (messages.pending()) await messages.inspect(messages.pending()!); // 原GET
// 仅显式用户新消息、无pending、业务返回的当前revision时调用：
// await messages.submit('继续分析', observed.revision);
```

每个业务登录/稳定绑定使用独立path与Storage作用域；服务端resolver独立验证真实业务身份、当前注册/Origin、权限和原BFF定位符，浏览器路径/anchor不能充当Native权限。SDK构造只检查路径和已有本地定位符，没有网络请求、bootstrap、mount/RUN或Controller领取。

## 合同与状态

POST path只发送content/revision和Idempotency-Key（显式调用时生成的一次intent UUID）；凭据与原消息Body/Native目标保留BFF共享加密日志。Unicode只支持有效标量字符串，异常代理码点/空文/超过16000-byte序列化请求在本地持久化/网络前拒绝，Go再次校验。此body不是通用任意Python JSON。

GET path发现当前原消息pending；GET path/receipt带原Idempotency-Key恢复，缺失/错误/拒绝保持unknown。version='1'，返回且只返回status(clear/unknown/recorded)、operation、revision、anchor。recorded要求精确receipt_key=operation、小写hash/UUID和安全整数源坐标；unknown/clear anchor必须null，未知字段（含secret）、旧版/不一致响应全部拒绝。

sessionStorage只保存{operation}，正文/凭据从不落浏览器存储。写入/读回失败在POST之前停止；网络/HTTP/非法响应失败不删定位符。重新构造SDK复用原定位符，只显式GET；discover能在本地定位符丢失时找到业务BFF共享pending，但不能覆盖另一个unknown，也不能凭clear自动删除本地unknown。recorded精确确认后才清除此原定位符；并发对象/标签仍依赖业务BFF的共享CAS，浏览器busy不是跨副本锁。

传输固定same-origin、credentials same-origin、cache no-store、redirect error、10秒Abort和4096-byte响应预算、自定义X-Overdoze-Message:1；不发送Native bearer/refresh/fence，不做POST重试、换UUID、自动mount/Run/Controller。

## 证明范围

recorded只证明原消息收据/坐标，非当前挂载/执行授权。后续挂载必须通过D服务器条件事务和当前权限；挂载之后RUN仍独立准入。没有原消息部分提交的非提交证明，不回落旧admission termination/observation；不能把missing当作未写入。无重复业务效果新执行授权、外部取消或生产HA保证。

确定性测试覆盖丢回复/原GET、未知和跨设备发现、Storage失败/损坏、严格DTO/无secret、同源与边界、不同unknown不覆盖、Unicode/大小。既有SDK、mock、历史事件/原收据/Coverage保持；两仓完整门禁与隔离Go/OIDC/实际Worker联合分别记录。不部署、生产迁移、main合并或npm发布。

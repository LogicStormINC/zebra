# ERP Cloud 通用强停接入（2026-11-02）

## 当前交付

已部署到线上 ERP `https://192.168.110.42:18443/`。
运行时仍为原生产 v117 数据库/namespace，API 与 Worker 使用 cloud-agent `97463d00`；
没有迁移、重放原 Run、添加真实模型或搜索请求。

ERP 的“停止会话”只做当前用户/公司权限核对、任务范围新鲜签名与接口调用：
`POST /tasks/{task_id}/cancel {"force":true}`；进度读取 `GET /tasks/{task_id}/stop`。
不携带 Run 窄授权，幂等键固定绑定原 Task。ERP 不实现 PID 终止、租约撤销或容器删除。
Worker 由服务端配置 `ZEBRA_SESSION_PROCESS_FACTORY=full_worker:compose`，保留原配额/工作区组合；
单独运行通用 `zebra_agent_worker.runtime_cleanup_service`，Worker 容器启用 init。

请求发出前保存强停意图到原 Conversation 的 request_options；未知结果保留意图与待处理提交。
只在退出、租约、沙箱与同步四项证明完整后宣称释放、清理 Host pending 状态；已完成/失败结果
按权威 header 保留。通过现有 Redis 提交锁和 Task/Run 坐标复核防止迟到回执覆盖后继操作。
强停后的 Task 不复活，后续工作需新建会话；普通 composer 停止行为保持。
刷新恢复已存进度，只读查询，不重新 POST/执行。观察链路受阻时，明确提示历史暂不可读，
独立显示强停核对；没有强停标记的普通观察故障仍作为错误返回。

## 验收

- 后端自检：真实函数的任务授权/稳定键/未知回执/所有权/完整释放/原终态保留/迟到坐标边界，
  实际 _submit 早期防护与 snapshot 的强停专用观察降级通过；没有模型/网络。
- 纯配置自检：镜像 digest pin、保留 env_file、不把密钥展开进 Compose、保留原 Worker 工厂及
  工作区/配额配置、独立回收器与其他服务不变通过。
- `npm test`、`npm run build` 通过。旧视图刷新期间切到另一会话的竞态先复现失败，
  删除多余 setState 后通过，避免把旧 Task 强停标记写入新视图。
- Native 真 PostgreSQL/Linux/OCI 与 API/恢复检查本轮 22 passed；2795.3 ms 回收卡死/逃逸后代，
  另一 Task 的执行器/租约/沙箱仍运行；过期任务 I/O、被锁终态写入、幂等重入均覆盖。
- 候选 Worker 使用生产组合 --check 通过，composition_ms=294.8，未执行 Run。
- 实际线上浏览器：独立会话 neso37nvme（明确 execute=false，没有 Run 派发）绑定真实租约，
  启动通用 execute_isolated 的受信卡死工厂，持有真实 Session/stream 锁且派生逃逸进程组。
  从菜单点击停止及确认，浏览器真实 POST 一次、只读进度两次；执行器退出0，独立回收器结算1。
  Native state=stopped、resources_released=true，原租约确已撤销，规范取消事件恰好1。
  刷新并重新打开助手后仍显示已停止/资源已释放，输入框禁用，新 force POST=0。
  没有拦截 HTTP 响应、伪造模型输出或自动重跑。
- 切换前后全生产 namespace 模型请求计数同为175；验收 Task 模型事件0。
  原 Search/Yahoo/MCP 服务未重建，搜索容器 ID/image/env hash/StartedAt/restarts 与 before 一致。
- 仅删除本轮精确标记的已退出 canary 容器；保留验收 Task/取消事实用于追溯，原 Run 不变。

## 部署与回滚资料

私有目录：`/home/ubuntu/releases/20261102-erp-force-stop/`。
保存切换前 Native pg_dump、ERP transactional backup、原 site/Compose/Host override、容器/环境哈希、
候选镜像、签名读取与无模型执行证据。备份/配置不进入 Git。
切换前暂停新提交并确认新旧运行时 running=0/有效租约=0；切换后恢复原 admission flags。
API/Worker/Host 环境与原值逐项哈希对照，只增加明确的隔离工厂配置；高思考/v2/权限保持。

最终固定镜像：

- API `sha256:e4faff1bfaf7d9d38bd7a60befcb534fedcc1f4faf753eb335cad288a98bf968`
- Worker/cleanup `sha256:e848b6f2b14852ff589573496ac2f37e421fac969aef95f5a86a5c6b15e1df26`
- ERP backend/frontend `sha256:0bd16e45a3bbb4ea5436bef72799fa990485243c520883ba2aed2f6e7e4075c3`

回滚先暂停准入并确认无活动执行。已有强停记录后不得回到不识别该 tombstone 的旧 Native，
否则会失去禁止复活的边界；优先保留已验收 Native、只回退展示，且暂停旧 Host 对强停 Task 的新提交。
原回滚副本保留，但不能把简单覆盖旧配置当作已证明安全的全面回退。

## 明确边界

这不是全 ERP 模块/真实模型正常对话/多机失联/内核不可杀/SLA 验收。
旧 native105 会话不会假装支持通用强停；无退出证明时继续待核对。
本轮没有修复既有全仓15处 ERP 文件大小门禁，也没有修改原 partial/failed Run。

Canonical ERP source: separate `LogicStormINC/zebra-erpnext` repository, branch
`codex/erp-cloud-force-stop-20261102`; this Cloud repository retains generic runtime ownership.

ERP adapter source commit: `9fc108b88800f325d490280489c54143e4c8aae4`. Native deployed source remains pinned to `97463d00`,
not unvalidated later Cloud orchestration changes.

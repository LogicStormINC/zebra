# CA-HA-03 D6 设计稿：执行子进程复用（Elastic Executor Pool）

2026-11-10；Owner lukeding；状态 **设计稿，待批准后实施**。
前置：docs/CA-HA-03_capacity_decision.md D4/D5 节（6.51s 固定成本 + 靶点勘察）。
代码标记：session_process.py:90-91 "ponytail" 已预留此方向。

## 1. 问题（实测数据）

每任务一个新子进程（subprocess.Popen）= 全套重建成本：

```
Python 解释器启动       ~100ms
包导入（D1 优化后）      ~900ms
check_model（TLS+httpx）~830ms  ← TLS 仅 33ms，其余为 imports+httpx+事件循环
compose                  ~150ms
─────────────────────────────
子进程启动合计           ~2.0s（auth→model 6.51s 的 31%）
```

16/(6.51+1.5) ≈ 2.0/s 结构上限。复用后预估 6.51→4.0s → 16/(4.0+1.5) ≈ **2.9/s**，
叠加靶点 2（-500ms）→ 16/(3.5+1.5) = **3.2/s** ≥ 3/s 目标。

## 2. 现有架构（session_process.py）

```
Worker 进程
  └─ execute_isolated(service, request)
      ├─ 写 request.json 到 tmpdir
      ├─ register_executor(store, sid, fence, incarnation)
      ├─ subprocess.Popen(executor_supervisor, request.json, result.json)
      │    └─ 子进程: 导入 → 组装 → 执行 → 写 result.json → 退出
      ├─ executor_monitor(database, sid) → cancelled 事件
      ├─ supervise(process, cancelled) → 等待/终止
      └─ 读取 result.json → TypeAdapter(ExecutedSession).validate_json
```

关键约束（来自代码审查）：
- 取消所有权：process.kill() 精确到单个子进程（"never kill a shared Worker"）
- 退出证明：exit.json 匹配 session_id+fence → acknowledge_executor
- 执行器化身：PID namespace 绑定 → register_executor
- 隔离：每任务完全独立的 Python 进程（内存状态零泄漏）

## 3. 设计

### 3.1 架构：Pool Supervisor + N Sequential Children

```
Worker 进程
  └─ ExecutorPoolService (新增)
      ├─ pool_size=N (配置 ZEBRA_EXECUTOR_POOL_SIZE, 默认 0=禁用)
      ├─ 启动时: fork N 个 pool_child 进程（各自完成 imports+TLS+事件循环）
      │    └─ pool_child: 等待 stdin 的任务请求 → 执行 → 写 stdout 结果 → 等待下一个
      ├─ submit(request) → 分配给空闲 child → 写入 stdin
      ├─ 超时/取消 → 给 child 发 SIGUSR1（协作取消当前任务）→ child 清理后继续等待
      └─ child 崩溃 → 从 pending 队列恢复任务 → 重启 child
```

### 3.2 IPC（替代临时文件）

- 请求：Worker → child stdin，JSON 行（含 request payload + task_id + fence）
- 结果：child → Worker stdout，JSON 行（ExecutedSession 或错误分类）
- 协议：每行一个完整 JSON，`\n` 分隔；长度前缀帧（`Content-Length: N\n\n{json}`）
- 向后兼容：pool_size=0 时走现有 tmpdir 路径，零行为变更

### 3.3 Job/Ack 边界（"ponytail" 预留的前提）

每任务生命周期：
```
Worker → child: {"op":"assign","task_id":...,"fence":...,"request":{...}}
child → Worker: {"op":"ack","task_id":...}                    ← 在 deadline 内
child → Worker: {"op":"result","task_id":...,"outcome":...}   ← ExecutedSession 或错误
child → Worker: {"op":"ready"}                                ← child 可接下一个任务
```

- ack 超时（>2s）→ Worker 将任务标记为 outcome_unknown，child 由监督者重启
- result 超时（>task_deadline）→ 协作取消 → child 清理当前任务状态 → ready
- child 进程死亡 → 在飞任务走 outcome_unknown 恢复路径（与现有退出码≠0 等价）

### 3.4 取消与强停

- **协作取消**（正常路径）：Worker 向 child 发 SIGUSR1 → child 在下一个安全点
  检查 per-task cancellation flag → 抛出 ExecutionInterrupted → 写 result → ready
- **强制终止**（超时/崩溃）：process.kill() → 整个 child 终止 → 在飞任务走
  outcome_unknown → Worker 重启该 child 槽位
- **强停兼容**（force-stop）：register_executor 逻辑不变——child 在执行期间
  注册 executor monitor；pool 模式下每个 child 同时只有一个 active executor
  注册，与现有 force-stop 接口完全兼容
- **worker 自身强停**：ExecutorPoolService.drain() 在 Worker 退出时向所有 child
  发送 SIGTERM → child 完成当前任务或超时后退出 → 与现有 drain 语义一致

### 3.5 隔离分析（安全评审核心）

| 状态 | 现有模型（每任务新进程） | Pool 模型（跨任务共享） | 风险评估 |
|---|---|---|---|
| Python 包导入 | 每次全新 | 共享（一次导入） | 低——纯代码，无会话状态 |
| TLS/SSL 上下文 | 每次新建 | 共享 | 低——协议对象，无业务数据 |
| httpx 客户端/连接池 | 每次新建 | 共享 | 低——连接复用到模型 fixture |
| PgBouncer 连接 | 每子进程独立池 | 共享 worker 级池 | 低——事务级隔离已由 PG 保证 |
| settings/configuration | 每次加载 | 共享（首次加载） | 低——settings 在任务间不变 |
| 会话/工作区状态 | 进程退出即清除 | **每任务显式重建** | 中——需确保 child 在任务间
  完全重置 per-task 状态（recorder/indexer/projection 全部新建） |
| module-level 缓存 | 无（新进程） | 可能存在 | **高**——需审计所有 module
  级可变状态（`_enabled_cache`、`_notification_retry` 等），确保 per-task 隔离
  或改为 per-instance |

**结论**：代码/协议对象共享安全；per-task 状态需显式重置；module-level 可变缓存
需审计（主要是 agent-storage 的 TTL 缓存和 agent-integrations 的 retry 字典——
两者均为性能缓存而非正确性状态，跨任务共享实际无害但需标记）。

### 3.6 配置与回滚

```bash
# 现有行为（默认）
ZEBRA_EXECUTOR_POOL_SIZE=0

# 启用复用（N 个常驻 child）
ZEBRA_EXECUTOR_POOL_SIZE=2
```

- 设置参与 baseline_digest → 需重新生成执行链（worker.env 变更 → prepare → publish）
- 回滚：改为 0 并重启 worker（走现有 per-task 路径）
- 兼容性：settings_digest 校验在 pool 模式下比较 worker 的 settings（child 不再
  独立 load_settings——由 Worker 在 assign 时传递 digest 已验证的配置快照）

### 3.7 与冻结纪律的关系

原冻结条款："不新建 warm pool"。本设计申请解禁理由：
1. 原禁令针对的是 **OCI 沙箱 warm pool**（预创建容器绕过 defer-provision），
   非子进程复用
2. 子进程复用不改变沙箱语义（零工具任务仍零 OCI；有工具任务仍按需创建）
3. 隔离分析（3.5）已确认跨任务共享面安全
4. 代码中已有 ponytail 标记预留此方向

## 4. 实施切片

| 切片 | 内容 | 工作量 |
|---|---|---|
| S1 | PoolChild 主循环（stdin/stdout IPC + 任务执行 + ready 信号） | 0.5 天 |
| S2 | ExecutorPoolService（N child 管理 + assign/ack/result 协议 + 超时） | 0.5 天 |
| S3 | 取消/强停集成（SIGUSR1 协作取消 + force-stop 注册兼容 + drain） | 0.5 天 |
| S4 | module-level 缓存审计 + per-task 状态重置验证 | 0.5 天 |
| S5 | 回归测试（隔离/取消/恢复/并发/兼容）+ 101.7 实测 | 1 天 |

## 5. 验证门槛

- 单任务 E2E 与现模型完全等价（事件序列逐项比对）
- 取消/强停在 pool 模式下行为一致（强停 ACK、租约释放、沙箱清理）
- 101.7 实测：auth→model ≤4.5s（从 6.51 降低 ≥30%）
- 16 worker 专用机容量 ≥2.7/s（从 2.0 提升 ≥35%）

## 6. 风险

| 风险 | 缓解 |
|---|---|
| 子进程状态泄漏 | S4 审计 + 每任务 recorder/indexer 全新建 |
| 取消边界模糊 | SIGUSR1 + 安全点检查 + 超时强制 kill |
| pool child 崩溃连锁 | 独立重启 + 在飞任务走 outcome_unknown |
| force-stop 兼容破裂 | 保持 register_executor 按任务注册/注销 |
| settings 漂移 | worker 端 digest 校验 + assign 时传配置快照 |

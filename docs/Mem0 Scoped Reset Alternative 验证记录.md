# Mem0 Scoped Reset Alternative 验证记录

状态：`Review`（`MEM-MEM0-RESET-ALT-01`）
日期：2026-08-02

## 1. 目的与边界

本 Spike 验证一个不依赖 Mem0 全量枚举的替代路径：Zebra 使用 PostgreSQL
v11 的 `scope_digest + generation + provider mapping` 做逻辑 reset，并只对
已确认 mapping 执行定向删除。

它不是 Mem0 Adapter、Worker Consumer 或生产 reset 实现。测试只启动隔离的
PostgreSQL Compose 依赖，并用 deterministic in-memory provider stand-in 模拟
“上游已写入、客户端响应丢失”的 unknown publish。禁止调用 Provider HTTP、全局
`/reset`、生产包、Desktop 或本地 SQLite composition。

## 2. 必须证明的边界

1. 当前 generation 的 confirmed mapping 可以通过 ledger 定向删除，不需要先
   枚举 Provider。
2. generation 切换后，旧 generation 的 mapping 即使仍在 ledger 中，也不能
   通过 search admission 返回；新 generation 从空 mapping 开始。
3. unknown publish 没有 provider ref 时，ledger 不能恢复远端对象。若 stand-in
   已保留该对象，结论必须是“逻辑 reset 成立、物理删除未证明”，不得标成完整
   reset 通过。

## 3. 结果分类

- `A / PASS`：逻辑 reset 与旧代物理清理均有有界、可重放证据。
- `B / PARTIAL`：逻辑 reset 和已知 mapping 清理成立，但 unknown orphan 的
  物理删除无法证明；必须保留 deletion-compliance gate。
- `C / FAIL`：连旧代隔离或已知 mapping 定向清理都无法成立。

本任务预期重点验证 `B / PARTIAL` 边界；测试不得把预期的 orphan 发现失败
隐藏成绿色的完整 reset。

实际结果：`B / PARTIAL`。generation fencing 和已知 mapping 定向删除均通过；
模拟 upstream 已写入但客户端响应丢失后，stand-in 仍保留
`provider-orphan-1`，而 ledger 没有 provider ref 或 mapping 可用于恢复。

## 4. 验收与运行

- 独立 Compose project：`zebra-mem0-reset-alt-test`，仅包含 PostgreSQL 17.5。
- 新 Spike runner 输出 `ZEBRA_MEM0_RESET_ALT_VERDICT=A|B|C`，并始终清理
  container、volume 和 network。
- 实际输出：`2 passed`、`ZEBRA_MEM0_RESET_ALT_TEST_RESULT=PASS`、
  `ZEBRA_MEM0_RESET_ALT_VERDICT=B`。
- 既有 v11 focused delivery runner 保持 `24 passed`；完整 storage matrix
  保持 `295 passed, 1 skipped`。
- 本记录必须写明最终 verdict、未知 orphan 是否仍存在于 stand-in，以及
  `MEM-GW-DEL-RUN-01` 是否继续 `Locked`。

## 5. 当前解锁结论

保持 `MEM-MEM0-RESET-SPIKE-01 = Blocked`、`MEM-GW-DEL-RUN-01 = Locked`
和父任务状态不变。`B` 结果要求另行评审 deletion-compliance gate；当前不
能宣称 Mem0 已具备完整 physical reset/rebuild 能力。

# CA-BASELINE-GATE-01 原生门禁整改

- 已领取独立任务/分支/Owner并完成根因追踪与原生修复。
- 摘要2RED/1pass→5pass；242扩展通过/29条件跳过，另1真实PG通过并及时回收。
- mypy1492/Eval30/局部Ruff/风险检查通过；Task元数据AST与旧导出保持，历史不改写。
- 待处理：ERPNext15尺寸/4924Ruff；02独立源仓库任务Ready未领取。
- 当前01Review，尚未主线合入；HA02仍候选，HA03Locked；不得将继承失败计通过。
- 组合树完整门禁及HA02复验通过后才执行条件合并，不部署/生产迁移。

正式方案docs/CA_BASELINE_GATE_REMEDIATION.md；证据docs/evidence/ca-baseline-gate-01/validation.json。

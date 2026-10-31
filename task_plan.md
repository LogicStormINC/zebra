# CA-BASELINE-GATE-02 完成；CA-HA-03 Ready

1. canonical规则/所有权/源修复、职责与装配复核、源验证及GitHub候选92b308b已完成。
2. 精确git archive同步SOURCE；组合原生01/HA02，旧证据保留，两处整树夹具问题稳定复现并修正。
3. 最终完整make test11672通过/0失败/3161条件跳过，make check全部通过，HA02真实PG5通过；owner临时资源已回收。
4. 代码2b908448已快进本地cloud-agent；本次最终文档/证据随主线推送GitHub。不部署/生产迁移。
5. 03只核对并解锁Ready，尚未领取/实施；先复核cutover、预算/退避、公平/入口范围和精确Owned paths。

正式结果docs/CA_BASELINE_GATE_REMEDIATION.md；证据docs/evidence/ca-baseline-gate-02/validation.json。

## 历史执行计划（保留，状态以当前顶部为准）

# 当前：CA-BASELINE-GATE-02 组合验收

canonical源候选整改与验证中；原生01/HA02进入同一组合树，尚未主线合入。
待源提交发布并archive导出后，串行限额完整make test/check和HA02真实PG；全部通过才合并推送。
旧记录如下保留，旧失败/未验状态代表当时证据；不部署/生产迁移，HA03继续Locked。

# 当前 CA-BASELINE-GATE-02

# CA-HA-02 完整门禁与真实PG

- 已完成：限额串行完整make test/check及全部剩余检查；真实PG5项通过并回收。
- 阻塞：test15失败、check16尺寸/Ruff4924违规，已在干净e8a4f10b逐项复现。
- mypy1494/Eval30/postcommit/risk通过，不视作整树通过。
- 条件合并未执行；02Review/03Locked；下一步先拆分基线门禁修复，再复验合入02。
- 保留历史/原收据/unknown/Coverage/前端mock和无关改动，无部署/生产迁移。
- 正式证据：docs/evidence/ca-ha-02/full-validation.json；03范围见02前置文档第8节。

# CA-HA-02 Review续作

- 输入6af4e5dd，沿原Owned paths复核，不启动03/重型验证/Docker。
- 修复真实控制进展绝对截止、符号链接/FIFO、关闭异常后资源遗漏；对应RED→GREEN。
-58项定向/局部Ruff/mypy7/产品边界通过，新证据与原52项分开保存。
-02保持Review，完整make test/check及真实PG/故障/容量未验，不据此合并/部署或解锁03。

# CA-HA-02 当前实现

- 从e8a4f10b独立分支，摘取UX文档01530810为559422d7；Ready/Owned paths先登记。
- 新精确GET与原lifespan组合、有界epoch观测；保留原健康/鉴权/关闭行为。
- Worker健康只读采样、能力到期约束、默认关闭本机原子文件，不改原任务执行。
- 定向pytest、局部Ruff/mypy/边界与尺寸；不运行完整门禁/Docker/故障负载。
- 02候选Review；真实PG/完整门禁未验，03–10仍Locked，无部署/生产迁移。

# CA-HA-UX-00 用户体验性能文档补充

- 从cloud-agent e8a4f10b建独立分支/worktree，登记Ready后领取。
- 补正式方案、合同revision3和机器可读UX-01–10，明确计时/分母/负载/证明边界。
- 原任务03/04/07/08/09/10补验收；不另建执行队列/业务租户/权威状态机。
- 仅diff/JSON/链接/文档尺寸/任务指标一致性验证；不得启动代码/重型测试/Docker。
- 文档完成后Review，02–10仍Locked；未验证目标不作为生产性能承诺。

# CA-HA-01复核与集成 / CA-HA-02前置

1. canonical源规则/Owned paths已核对并领取；拆分和机械整改在独立仓库候选中完成，集中验证中。
2. 保留原生01与HA02历史证据，canonical通过后发布固定提交并git archive同步SOURCE。
3. 整合HA02，串行限额执行组合树make check、make test和真实PostgreSQL5场景；及时回收自有容器。
4. 所有门禁通过后才条件合入cloud-agent并推送；HA03此前Locked；无部署/生产迁移。

# CA-BASELINE-GATE-01 原生门禁整改

- 已领取独立任务/分支/Owner并完成根因追踪与原生修复。
- 摘要2RED/1pass→5pass；242扩展通过/29条件跳过，另1真实PG通过并及时回收。
- mypy1492/Eval30/局部Ruff/风险检查通过；Task元数据AST与旧导出保持，历史不改写。
- 待处理：ERPNext15尺寸/4924Ruff；02独立源仓库任务Ready未领取。
- 当前01Review，尚未主线合入；HA02仍候选，HA03Locked；不得将继承失败计通过。
- 组合树完整门禁及HA02复验通过后才执行条件合并，不部署/生产迁移。

正式方案docs/CA_BASELINE_GATE_REMEDIATION.md；证据docs/evidence/ca-baseline-gate-01/validation.json。

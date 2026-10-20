# Cloud Agent Decoupling Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development
> or superpowers:executing-plans. Steps use checkbox syntax for tracking.

**Goal:** 第一批证明 Runtime 可脱离 Trench 构建、启动并独立校验发布。
**Architecture:** 中立基础 Compose + 显式旧产品 overlay；v2 独立发布，严格保留 v1。
**Tech Stack:** Python 3.12、Docker Compose、PostgreSQL/Redis/S3、TypeScript React。

## Chunk 1: CLOUD-DECOUPLE-01

负责人 Luke Ding；在用户指定 cloud-agent 主工作区实施，不另建分支。
正式设计见 docs/CLOUD_AGENT_DECOUPLING.md；Owned paths 见 docs/AGENT_TASKS.md。

### Task 1: 独立部署

文件：docker/compose.application.yml、compose.trench-compat.yml、
compose.local-gvisor.yml、local-gvisor/recreate-application.sh、
.env.application.example、README.md；tests/compose/application/。

- [x] 添加失败用例：无 Trench CA/URL 和 Scheduler secret 的基础配置可渲染；
  默认服务无 legacy API；显式兼容组合保留旧 namespace/证书、自动启用 Scheduler
  及原 workload identity、API→legacy 依赖；与 local-gvisor 组合保留 mTLS/CA 挂载。
  验证激活脚本显式选取正确组合；Scheduler 仍严格授权。
- [x] 最小修改：移出产品证书/legacy API；Scheduler 可选；中立环境示例。
- [x] 运行 uv run pytest -q tests/compose/application。

### Task 2: 独立发布与 SDK

文件：scripts/validate_rollout_candidate.py、validate_rollout_rehearsal.py、
configs/cloud_rollout_candidate*.json、cloud_release_capabilities.example.json、
Makefile、tests/test_validate_rollout_candidate.py、test_validate_rollout_rehearsal.py、
tests/test_runtime_independence.py；React agent-usage-analytics.tsx。

- [x] 先测试 v2 不需产品镜像、版本、数据库修订；缺摘要/证据/回滚必须失败。
- [x] 保持 v1 联合契约原样严格校验；新增 v2 独立契约与中立浏览器验收场景。
- [x] 默认例子与命令支持独立候选；旧联合例子显式保留；SDK 文案中立化。
- [x] 运行候选/演练/发布清单回归；构造 fixture 仅证明 CLI 合同，不充当真实发布证据。

### Task 3: 原生验证与交接

- [x] 真实 Docker 镜像构建；记录源文件 fingerprint 与镜像 ID。
- [x] 独立临时 PostgreSQL/Redis/S3 环境运行迁移、API/Worker 启动检查；
  没有 Trench endpoint/cookie/CA/业务库；不接触现有 volumes/containers。
- [x] 独立发布 CLI 正例/反例；真实门禁不足时必须保留 FAIL。
- [x] 规格与质量审查通过；make check 已执行，保留 HEAD 基线 eval 失败；
  定向105通过；完整测试10067通过/2931跳过/1继承 eval 失败。
- [x] 更新 README、PROGRESS、WORKLOG 与本清单，记录验证限制。

## 后续批次（按各批验收记录推进）

- [x] CLOUD-DECOUPLE-02：Broker 业务逻辑外移、显式 Manifest、通用 schedule authority。
- [x] CLOUD-DECOUPLE-03：Coverage 业务快照与来源协议外移，保持完整性/恢复/发布约束。
- [x] CLOUD-DECOUPLE-04：业务消息外移、旧任务兼容退出、双产品接入及架构门禁。

不修改历史数据，不执行生产发布，不在用户未请求时提交或推送。

## 第一批验证记录

- 分支：cloud-agent；起点 HEAD 8f67261f；修改留在当前工作区，未提交/推送。
- 设计审查要求增加 Scheduler 自动包含/身份、legacy API 依赖、CA 和 gVisor
  挂载矩阵；已实现。规格审查/质量审查均通过，另补了两个发布绕过回归。
- 最终定向命令：`make test-runtime-independence`；105 passed（3.85s）。
- 三个 linux/amd64 镜像真实 Dockerfile 构建通过；ID 记录于
  `.artifacts/cloud-decouple-01/images.json`，日志 `build-{api,worker,migrate}.log`。
- 原生启动：运行 `tests/compose/application/run-independent-smoke.py`，
  构建后的迁移/API/Worker + 临时 PG/Redis/S3；没有 Trench endpoint、Cookie、
  业务 CA 或业务数据库，外部 issuer 用 `.invalid` 注册记录且不依赖可访问性。
  只读检查真实 gVisor 引擎就绪，不创建沙箱/Task，不调用模型。
- 原生结果：API/Worker health，cloud+gvisor/no fallback；匿名任务请求401；
  API restart 后 S3 对象和 Host registry 保留。临时网络/容器均清理。
- 32个既有运行容器 ID 保持不变；没有重启/迁移任何既有部署或数据。
- SDK：`cd sdks/typescript && pnpm check` 退出0（含包构建和 typecheck）。
- 独立发布命令：`make validate-rollout-candidate` 与
  `make validate-rollout-rehearsal`，用明确标识的合成 fixture 通过；
  没有 Trench 坐标/镜像/数据库修订。此结果只证明 CLI 契约。
- 反例：`make release-evidence EVIDENCE_ROOT=<empty-private-dir>` 退出非0，
  Runtime 核心/依赖门禁仍 FAIL，Trench NOT_ENABLED；绝不伪造生产 PASS。
- `make check`：大小/Ruff/mypy1319通过，eval 0.80/30失败；归档 pristine HEAD
  scripts/packages/apps/evals 并用其源路径重跑，同样0.80；归档中的原始
  test_eval_release_check_passes_baseline_dataset 也复现同一失败。剩余两个 progress
  检查独立运行通过；当前既有基线不能声称全部发布门禁已通过。
- 完整回归：`make test` 为10067 passed / 2931 skipped / 1 failed，1181.70s；
  唯一失败为已在 pristine HEAD 复现的 baseline eval 单测。其启动早于末次
  v2 Trench capability guard，最终守卫
  由末次定向回归覆盖。完整输出 `.artifacts/cloud-decouple-01/make-test.log`。

原始证据在本地 `.artifacts/cloud-decouple-01/`，不包含可用于真实发布的门禁证据。
后续02-04继续 Locked；本批不代表认证、Coverage 或业务消息已全部去耦。

交付状态：第一批本地源码和独立构建/启动/发布契约验证完成，Registry 为 Review。
全量质量门禁仍有上述既有失败，不能宣称生产发布已获准或全部门禁通过。
未提交、推送或切换既有服务。源文件摘要见 source-sha256.json（不包含用户原有改动）。


2026-10-20 batch02 local verification: pre-batch full gates both exit0, then
implementation. Final make test10162pass/2934skip and make check exit0; eval30/30.
Spec/quality approved. Initial catalog max-version failure fixed without changing
production source, complete suite rerun. v106 nullable policy migration only on
scratch PG; historical digests/data preserved. Five local image builds, corrected
worker-engine boot/preflight/restart-retention pass. Existing32container IDs and
user files unchanged, own scratch cleaned. Local Review/uncommitted; production
business/browser E2E and batches03/04 remain outside this delivery.


## 第三批本地验收（2026-10-20）

- [x] v2 冻结数据集修订/源资源/opaque selector 与固定 dataset.snapshot ABI。
- [x] Worker/Effect/恢复/存储/报告读取使用同一冻结契约；旧 v1 身份金样保留。
- [x] 精确报告 GET/HEAD 消费前置与读授权，不借用执行/写权限，不绕过证明。
- [x] 真实临时 PG 证明与恢复217pass、报告51pass；Host/S3/model 为 fixture。
- [x] 独立设计、规格/权限及质量审查通过；Core/source 定向1320pass。
- [x] 最终 make test10222pass/2974skip，1118.77s，exit0；make check exit0，
  含 mypy1324/eval30/30。首次完整测试两项旧替换点修正并保留超时断言后重跑。
- [x] 32个原有容器、用户文件与源码快照保护校验；临时资源清理。
- [x] 正式设计、README、PROGRESS、WORKLOG 与任务表更新，状态 Review。

详细开发者协议及证据边界见 docs/CLOUD_AGENT_DECOUPLING_BATCH3.md；
原始日志与 validation-summary.json 在 .artifacts/cloud-decouple-03/。
未增加迁移、改写历史数据、提交、推送或上线；04仍待实施/集成决策。


## 第四批本地验收（2026-10-20）

- [x] Core/默认 transport 仅 Runtime command；产品 Turn/source 显式适配。
- [x] 原联合 schema/examples 字节金样保留；94项模拟拓扑/权限请求保持一致。
- [x] 默认 Runtime-only 拓扑，旧联合/source/shadow 使用 --trench-compat。
- [x] 离线兼容退出材料检查；精确命名空间/兼容项/时间/摘要/任务集合，要求
  排空或不可变镜像固定及回滚；不授权生产删除/切流，历史 decoder 保留。
- [x] 默认依赖边界加入 make check；中立 conformance Make/CI 不依赖产品凭据。
- [x] 契约145pass/0skip；真实临时 PG87pass/0skip；源码3镜像构建/独立启动通过。
- [x] 规格 GO/质量 APPROVE；make test10342pass/2974skip (1139.10s) exit0，
  make check exit0，含 mypy1326/eval30/30；未放宽证明/门禁。
- [x] 文档/清单/进度/保护检查，32原有容器和用户文件不变，临时资源清理。

详细协议、离线退出材料格式与证据边界见 CLOUD_AGENT_DECOUPLING_BATCH4.md。
本地 Review，未提交/推送/上线。未改现有 DB/消息队列/凭据或历史 Coverage
证明；生产排空、真实 Broker/模型/产品/浏览器联合验收仍是产品运营动作。


## 四批整体复核与修复（CLOUD-DECOUPLE-AUDIT-01）

- [x] 保留145个既有 dirty 文件、32容器与用户原文件摘要，当前 cloud-agent 不切分支。
- [x] 只读审计协议/业务调用与部署/发布，具体问题先登记 Owned paths 再修复。
- [x] 中立且不覆盖的密钥生成；专项必需模块/筛选/中断和辅助证据隔离。
- [x] 联合候选同样要求 Runtime 核心/依赖/恢复门禁及摘要成员。
- [x] admission/Worker/report 统一 profile Gateway 配置；旧 nullable 路由保持。
- [x] v107追加 Host/revision 冻结，两代写入共享事务锁，歧义/冲突拒绝。
- [x] 真实临时 PG87/13/8项及专项契约161项通过；三镜像与独立启动通过。
- [x] 规格/安全与质量复审通过，补齐混合写入与报告调用 sibling。
- [x] 最终 make test10376pass/2987skip（1162.17秒）和 make check退出0；
  mypy1328/eval30/30，文档/任务 Review状态/129源码摘要/32原容器保护检查完成。

v107 必须先于更新 API/Worker 启动；新 Task 放行需要协调消费者版本，不能将只
新表冻结的 Task 交给旧 Worker。没有生产迁移、切流或历史数据改写；真实产品/
模型/Browser/Broker 验收仍与本地 fixture/临时存储证据分开。
详见 docs/CLOUD_AGENT_DECOUPLING_AUDIT.md。

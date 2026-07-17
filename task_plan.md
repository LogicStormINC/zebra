# Task Plan

## Phase 145 - Event-Driven Conversation Stream

1. `completed` - Persist the remediation design, claim `P145-UI-01`, and lock
   the durable-event, UI, API, accessibility, and non-goal boundaries.
2. `completed` - Add a deterministic event-stream projection with focused
   checks for ordering, tool grouping, failure, retry, and message de-duplication.
3. `completed` - Replace the fixed stage timeline with the chronological stream
   while preserving task plan, approval, clarification, inspector, and Composer.
4. `completed` - Complete responsive, keyboard, and visual-design QA at desktop
   and 900px viewports.
5. `completed` - Run repository gates, record acceptance evidence, and close the
   branch for review.

## Phase 144 - Bounded HTML Readable-Text Projection

1. `completed` - Claim the phase and lock HTML projection, output budget, safe
   metadata, compatibility, and non-goal boundaries.
2. `completed` - Add deterministic standard-library HTML readable-text
   projection and UTF-8 output truncation.
3. `completed` - Preserve the existing Web Gateway Policy, HITL, transport, and
   recovery contracts with focused regression coverage.
4. `completed` - Run full repository and real-provider acceptance gates.
5. `completed` - Close the task, commit the branch, and merge it to `main`.

## Goal

为 Zebra Agent 建立一份可持续使用的实施任务拆解与阶段验收基线文档，并让仓库内的长期进度文件与该基线保持一致。

## Phases

| Phase | Status | Notes |
|---|---|---|
| Read current architecture and progress state | completed | `v1.0` 文档和 `PROGRESS.md` 已对齐 |
| Define implementation phases and acceptance criteria | completed | 已形成正式文档草案 |
| Persist planning files for future continuation | completed | `task_plan.md`、`findings.md`、`WORKLOG.md` 已建立 |
| Sync repo-level progress view | completed | `PROGRESS.md` 已恢复为项目级状态摘要，并链接正式实施文档 |

## Key Decisions

- 主规划文档放在 `docs/实施任务拆解与阶段验收.md`
- 规划以 `Phase 0` 到 `Phase 8` 组织，不按文件夹罗列任务
- 验收标准必须同时覆盖代码、运行路径、测试和文档回写

## Risks

- 如果 `PROGRESS.md` 不同步，后续可能出现“正式文档”和“当前状态”分叉
- 如果过早进入 API/Web，会稀释 core/runtime/harness 的实现节奏

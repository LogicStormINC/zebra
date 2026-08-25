import type {
  Artifact,
  Attempt,
  HostEffect,
  ModelCall,
  SubagentLink,
  TaskEvent,
  ToolCall,
  WorkerNode,
  Approval,
  OrchestrationRun
} from '@/lib/platform/types';

/** Task 详情（事件、尝试、模型调用、工具、Effect、Artifact）与运行中心其余 mock 数据。 */

export const mockTaskEvents: Record<string, TaskEvent[]> = {
  tsk_01JK2M4Q8T: [
    {
      sequence: 1,
      eventId: 'evt_000001',
      type: 'task_created',
      actor: 'operator:lukeding',
      timestamp: '2026-08-26T09:12:00+08:00',
      correlationId: 'corr_a91f',
      summary: 'Task 创建：审查 PR #482',
      policyVersion: 'pol_capability_trench_prod/rev3'
    },
    {
      sequence: 2,
      eventId: 'evt_000002',
      type: 'segment_started',
      actor: 'worker:wrk-c-01',
      timestamp: '2026-08-26T09:12:02+08:00',
      causationId: 'evt_000001',
      correlationId: 'corr_a91f',
      summary: '进入 segment：read-context'
    },
    {
      sequence: 3,
      eventId: 'evt_000003',
      type: 'model_call',
      actor: 'worker:wrk-c-01',
      timestamp: '2026-08-26T09:12:05+08:00',
      causationId: 'evt_000002',
      summary: 'planner 调用 deepseek-v4-pro（thinking=max）',
      modelProfile: 'planner-v3',
      policyVersion: 'pol_model_deepseek_roles/rev4'
    },
    {
      sequence: 4,
      eventId: 'evt_000004',
      type: 'tool_call',
      actor: 'agent:trench-code-reviewer',
      timestamp: '2026-08-26T09:20:11+08:00',
      causationId: 'evt_000003',
      summary: '调用 trench.get_risk_report(date=2026-08-25)',
      payload: { tool: 'trench.get_risk_report', argumentsDigest: 'd41d8cd98f00' }
    },
    {
      sequence: 5,
      eventId: 'evt_000005',
      type: 'tool_receipt',
      actor: 'host:trench',
      timestamp: '2026-08-26T09:20:13+08:00',
      causationId: 'evt_000004',
      summary: 'trench.get_risk_report Receipt OK（12.4KB）'
    },
    {
      sequence: 6,
      eventId: 'evt_000006',
      type: 'client_effect_dispatched',
      actor: 'agent:trench-code-reviewer',
      timestamp: '2026-08-26T09:31:40+08:00',
      causationId: 'evt_000003',
      summary: '下发 ui.highlight_ticket(expected_ui_revision=12)',
      payload: { effectId: 'cefx_01HT4', action: 'ui.highlight_ticket' }
    },
    {
      sequence: 7,
      eventId: 'evt_000007',
      type: 'client_effect_receipt',
      actor: 'client:cs_9f21',
      timestamp: '2026-08-26T09:31:44+08:00',
      causationId: 'evt_000006',
      summary: 'ui.highlight_ticket Receipt succeeded'
    },
    {
      sequence: 8,
      eventId: 'evt_000008',
      type: 'artifact_created',
      actor: 'agent:trench-code-reviewer',
      timestamp: '2026-08-26T09:38:02+08:00',
      summary: '生成审查报告 review-pr482.md'
    },
    {
      sequence: 9,
      eventId: 'evt_000009',
      type: 'model_call',
      actor: 'worker:wrk-c-01',
      timestamp: '2026-08-26T09:40:00+08:00',
      summary: 'summarizer 调用 deepseek-v4-flash',
      modelProfile: 'summarizer-v2'
    }
  ],
  tsk_01JK2LR3XA: [
    {
      sequence: 1,
      eventId: 'evt_000101',
      type: 'task_created',
      actor: 'schedule:daily-report',
      timestamp: '2026-08-26T08:00:00+08:00',
      correlationId: 'corr_b33e',
      summary: 'Task 创建：市场异动日报'
    },
    {
      sequence: 2,
      eventId: 'evt_000102',
      type: 'orchestration_planned',
      actor: 'agent:trench-market-research',
      timestamp: '2026-08-26T08:01:00+08:00',
      summary: 'Orchestrator 生成 DAG（plan rev 2）：3 个研究子任务'
    },
    {
      sequence: 3,
      eventId: 'evt_000103',
      type: 'subagent_spawned',
      actor: 'orchestrator',
      timestamp: '2026-08-26T08:05:00+08:00',
      summary: '创建子任务 tsk_01JK2GZ1QL（美股隔夜行情）'
    },
    {
      sequence: 4,
      eventId: 'evt_000104',
      type: 'subagent_spawned',
      actor: 'orchestrator',
      timestamp: '2026-08-26T08:05:01+08:00',
      summary: '创建子任务 tsk_01JK2GY7TP（亚太资金流）'
    },
    {
      sequence: 5,
      eventId: 'evt_000105',
      type: 'clarification_requested',
      actor: 'agent:trench-market-research',
      timestamp: '2026-08-26T07:45:00+08:00',
      summary: '询问日报是否覆盖衍生品持仓（关联子任务暂停中）'
    },
    {
      sequence: 6,
      eventId: 'evt_000106',
      type: 'subagent_completed',
      actor: 'agent:trench-market-research',
      timestamp: '2026-08-26T08:55:00+08:00',
      summary: '子任务 tsk_01JK2GY7TP 完成：亚太资金流汇总 18 条证据'
    }
  ],
  tsk_01JK2LP9ZC: [
    {
      sequence: 1,
      eventId: 'evt_000201',
      type: 'task_created',
      actor: 'operator:runtime-ops',
      timestamp: '2026-08-26T08:40:00+08:00',
      summary: 'Task 创建：更新工单 TR-2291'
    },
    {
      sequence: 2,
      eventId: 'evt_000202',
      type: 'approval_requested',
      actor: 'policy-engine',
      timestamp: '2026-08-26T08:52:00+08:00',
      summary: 'trench.update_ticket_status 风险=high，触发审批 pol_approval_high_risk/rev3',
      policyVersion: 'pol_approval_high_risk/rev3'
    }
  ]
};

export const mockAttempts: Record<string, Attempt[]> = {
  tsk_01JK2M4Q8T: [
    {
      attemptNumber: 1,
      leaseFence: 'fence_018f22a9',
      model: 'deepseek-v4-pro / deepseek-v4-flash',
      inputTokens: 41200,
      outputTokens: 6310,
      reasoningTokens: 2740,
      toolCalls: 5,
      durationSeconds: 1740,
      outcome: 'succeeded'
    }
  ],
  tsk_01JK2FW8VN: [
    {
      attemptNumber: 1,
      leaseFence: 'fence_018e7710',
      model: 'deepseek-v4-flash',
      inputTokens: 9800,
      outputTokens: 4100,
      reasoningTokens: 0,
      toolCalls: 8,
      durationSeconds: 960,
      outcome: 'failed'
    }
  ]
};

export const mockModelCalls: Record<string, ModelCall[]> = {
  tsk_01JK2M4Q8T: [
    {
      id: 'mc_91001',
      role: 'planner',
      provider: 'deepseek',
      requestedModel: 'deepseek-role:planner',
      resolvedModel: 'deepseek-v4-pro',
      thinkingMode: 'max',
      latencyMs: 8400,
      retryCount: 0,
      finishReason: 'stop',
      inputTokens: 18400,
      outputTokens: 2210,
      reasoningTokens: 1540,
      costUsd: 0.121
    },
    {
      id: 'mc_91002',
      role: 'executor',
      provider: 'deepseek',
      requestedModel: 'deepseek-role:executor',
      resolvedModel: 'deepseek-v4-flash',
      thinkingMode: 'disabled',
      latencyMs: 3200,
      retryCount: 0,
      finishReason: 'tool_calls',
      inputTokens: 22100,
      outputTokens: 3100,
      reasoningTokens: 0,
      costUsd: 0.082
    },
    {
      id: 'mc_91003',
      role: 'summarizer',
      provider: 'deepseek',
      requestedModel: 'deepseek-role:summarizer',
      resolvedModel: 'deepseek-v4-flash',
      thinkingMode: 'disabled',
      latencyMs: 1900,
      retryCount: 0,
      finishReason: 'stop',
      inputTokens: 7700,
      outputTokens: 1000,
      reasoningTokens: 1200,
      costUsd: 0.021
    }
  ]
};

export const mockToolCalls: Record<string, ToolCall[]> = {
  tsk_01JK2M4Q8T: [
    {
      id: 'tc_5501',
      toolName: 'trench.get_risk_report',
      executionLocation: 'host',
      risk: 'read',
      scope: 'trench.risk:read',
      argumentsDigest: 'd41d8cd98f00b204e980',
      status: 'succeeded',
      durationMs: 1180,
      receiptDigest: 'rcpt_7742ab'
    },
    {
      id: 'tc_5502',
      toolName: 'trench.get_position',
      executionLocation: 'host',
      risk: 'read',
      scope: 'trench.positions:read',
      argumentsDigest: '0a1b2c3d4e5f60718293',
      status: 'succeeded',
      durationMs: 860,
      receiptDigest: 'rcpt_8853bc'
    },
    {
      id: 'tc_5503',
      toolName: 'sandbox.exec',
      executionLocation: 'sandbox',
      risk: 'medium',
      scope: 'sandbox:exec',
      argumentsDigest: '9f8e7d6c5b4a3021f0e1',
      status: 'succeeded',
      durationMs: 5400,
      receiptDigest: 'rcpt_9964cd'
    },
    {
      id: 'tc_5504',
      toolName: 'ui.highlight_ticket',
      executionLocation: 'client',
      risk: 'presentation',
      scope: 'client-action:ui',
      argumentsDigest: '11223344556677889900',
      status: 'succeeded',
      durationMs: 4100,
      receiptDigest: 'rcpt_1075de'
    }
  ],
  tsk_01JK2LP9ZC: [
    {
      id: 'tc_6601',
      toolName: 'trench.update_ticket_status',
      executionLocation: 'host',
      risk: 'high',
      scope: 'trench.tickets:write',
      argumentsDigest: 'aa11bb22cc33dd44ee55',
      status: 'awaiting_approval',
      durationMs: 0
    }
  ]
};

export const mockHostEffects = [
  {
    dispatchId: 'hfx_01HA7',
    taskId: 'tsk_01JK2LP9ZC',
    tool: 'trench.update_ticket_status',
    operationId: 'op_ticket_update_2291',
    status: 'pending' as const,
    idempotencyKey: 'idem_9f21a8c3',
    claimOwner: 'worker:wrk-c-01',
    attempt: 1,
    evidence: '等待审批后调度',
    reconciliation: 'not_required' as const,
    hostAppId: 'trench',
    createdAt: '2026-08-26T08:52:00+08:00'
  },
  {
    dispatchId: 'hfx_01HA6',
    taskId: 'tsk_01JK2KJ8PC',
    tool: 'fake_b.write_marker',
    operationId: 'op_marker_07',
    status: 'uncertain' as const,
    idempotencyKey: 'idem_4d77b1e0',
    claimOwner: 'worker:wrk-b-03',
    attempt: 2,
    evidence: '调用超时（read 10s）；Host 侧可能已写入',
    reconciliation: 'manual_review' as const,
    hostAppId: 'fake-host-b',
    createdAt: '2026-08-25T13:33:00+08:00'
  },
  {
    dispatchId: 'hfx_01HA5',
    taskId: 'tsk_01JK2M4Q8T',
    tool: 'trench.get_risk_report',
    operationId: 'op_risk_read_0825',
    status: 'succeeded' as const,
    idempotencyKey: 'idem_2b55c9f2',
    claimOwner: 'worker:wrk-c-01',
    attempt: 1,
    evidence: 'Receipt 200 OK',
    reconciliation: 'not_required' as const,
    hostAppId: 'trench',
    createdAt: '2026-08-26T09:20:11+08:00'
  },
  {
    dispatchId: 'hfx_01HA4',
    taskId: 'tsk_01JK2J7WNA',
    tool: 'trench.get_position',
    operationId: 'op_position_export_44',
    status: 'succeeded' as const,
    idempotencyKey: 'idem_8c33d0a1',
    claimOwner: 'worker:wrk-c-02',
    attempt: 1,
    evidence: 'Receipt 200 OK',
    reconciliation: 'succeeded' as const,
    hostAppId: 'trench',
    createdAt: '2026-08-25T10:18:00+08:00'
  }
];

export const mockArtifacts: Artifact[] = [
  {
    id: 'art_7101',
    taskId: 'tsk_01JK2M4Q8T',
    name: 'review-pr482.md',
    kind: 'report',
    bytes: 18432,
    digest: 'f00d3344aabb5566ccdd',
    createdAt: '2026-08-26T09:38:02+08:00'
  },
  {
    id: 'art_7102',
    taskId: 'tsk_01JK2M4Q8T',
    name: 'pr482-trace.json',
    kind: 'export',
    bytes: 512000,
    digest: '11aa22bb33cc44dd55ee',
    createdAt: '2026-08-26T09:38:05+08:00'
  },
  {
    id: 'art_7103',
    taskId: 'tsk_01JK2KQ2RD',
    name: 'uv-upgrade-patch.diff',
    kind: 'patch',
    bytes: 71680,
    digest: '22bb33cc44dd55ee66ff',
    createdAt: '2026-08-25T16:05:00+08:00'
  },
  {
    id: 'art_7104',
    taskId: 'tsk_01JK2J7WNA',
    name: 'position-snapshot.csv',
    kind: 'export',
    bytes: 131072,
    digest: '33cc44dd55ee66ff7700',
    createdAt: '2026-08-25T10:21:00+08:00'
  }
];

export const mockSubagentLinks: SubagentLink[] = [
  {
    parentTaskId: 'tsk_01JK2LR3XA',
    childTaskId: 'tsk_01JK2GZ1QL',
    childTitle: '子任务：检索美股隔夜行情',
    role: 'researcher',
    status: 'running',
    wakeupPolicy: 'on_completion',
    createdAt: '2026-08-26T08:05:00+08:00'
  },
  {
    parentTaskId: 'tsk_01JK2LR3XA',
    childTaskId: 'tsk_01JK2GY7TP',
    childTitle: '子任务：汇总亚太时段资金流',
    role: 'researcher',
    status: 'completed',
    wakeupPolicy: 'on_completion',
    createdAt: '2026-08-26T08:05:00+08:00'
  }
];

export const mockOrchestrationRuns: OrchestrationRun[] = [
  {
    runRef: 'orch_8842f',
    taskId: 'tsk_01JK2LR3XA',
    planRevision: 2,
    strategy: 'dag',
    status: 'waiting_children',
    totalTokens: 112400,
    totalCostUsd: 0.847,
    createdAt: '2026-08-26T08:01:00+08:00',
    nodes: [
      {
        id: 'n_scope',
        label: '确定研究范围',
        role: 'planner',
        status: 'completed',
        dependsOn: [],
        budgetTokens: 20000,
        evidence: '范围澄清后固定'
      },
      {
        id: 'n_us',
        label: '美股隔夜行情',
        role: 'researcher',
        childTaskId: 'tsk_01JK2GZ1QL',
        status: 'running',
        dependsOn: ['n_scope'],
        budgetTokens: 40000
      },
      {
        id: 'n_apac',
        label: '亚太资金流',
        role: 'researcher',
        childTaskId: 'tsk_01JK2GY7TP',
        status: 'completed',
        dependsOn: ['n_scope'],
        budgetTokens: 35000,
        evidence: '18 条证据'
      },
      {
        id: 'n_derivatives',
        label: '衍生品持仓覆盖（待澄清）',
        role: 'researcher',
        status: 'waiting_clarification',
        dependsOn: ['n_scope'],
        budgetTokens: 30000,
        gate: 'clarification'
      },
      {
        id: 'n_review',
        label: '交叉审查',
        role: 'reviewer',
        status: 'blocked',
        dependsOn: ['n_us', 'n_apac', 'n_derivatives'],
        budgetTokens: 25000,
        gate: 'completion'
      },
      {
        id: 'n_report',
        label: '综合日报',
        role: 'presenter',
        status: 'queued',
        dependsOn: ['n_review'],
        budgetTokens: 20000,
        gate: 'completion'
      }
    ]
  },
  {
    runRef: 'orch_7710a',
    taskId: 'tsk_01JK2J7WNA',
    planRevision: 1,
    strategy: 'sequential',
    status: 'completed',
    totalTokens: 23800,
    totalCostUsd: 0.15,
    createdAt: '2026-08-25T10:00:00+08:00',
    nodes: [
      {
        id: 'n_fetch',
        label: '读取持仓',
        role: 'executor',
        status: 'completed',
        dependsOn: [],
        budgetTokens: 10000
      },
      {
        id: 'n_export',
        label: '导出快照',
        role: 'executor',
        status: 'completed',
        dependsOn: ['n_fetch'],
        budgetTokens: 10000,
        evidence: 'position-snapshot.csv'
      }
    ]
  }
];

export const mockApprovals: Approval[] = [
  {
    id: 'apr_0201',
    type: 'approval',
    taskId: 'tsk_01JK2LP9ZC',
    hostAppId: 'trench',
    namespace: 'trench/prod',
    tool: 'trench.update_ticket_status',
    risk: 'high',
    reason: '高风险写操作：将工单 TR-2291 状态改为 escalated',
    requestedBy: 'agent:trench-code-reviewer',
    requestedAt: '2026-08-26T08:52:00+08:00',
    deadline: '2026-08-26T20:52:00+08:00',
    status: 'pending'
  },
  {
    id: 'clr_0181',
    type: 'clarification',
    taskId: 'tsk_01JK2HY4KM',
    hostAppId: 'trench',
    namespace: 'trench/prod',
    reason: '日报覆盖范围不明确',
    question: '本期日报是否需要覆盖衍生品持仓？如需要，请指定品种范围。',
    requestedBy: 'agent:trench-market-research',
    requestedAt: '2026-08-26T07:45:00+08:00',
    deadline: '2026-08-27T07:45:00+08:00',
    status: 'pending'
  },
  {
    id: 'apr_0194',
    type: 'approval',
    taskId: 'tsk_01JK2J7WNA',
    hostAppId: 'trench',
    namespace: 'trench/prod',
    tool: 'trench.get_position',
    risk: 'read',
    reason: '跨 namespace 读取需二次确认（历史样例）',
    requestedBy: 'agent:trench-code-reviewer',
    requestedAt: '2026-08-25T10:05:00+08:00',
    deadline: '2026-08-25T22:05:00+08:00',
    status: 'approved'
  }
];

export const mockWorkers: WorkerNode[] = [
  {
    id: 'wrk-c-01',
    region: 'cn-east-1',
    sandboxClass: 'standard-v3',
    status: 'healthy',
    activeTasks: 6,
    capacity: 12,
    cpuPercent: 41,
    memoryPercent: 55,
    leaseCount: 9,
    version: 'zebra-worker/1.14.2',
    lastHeartbeat: '2026-08-26T09:44:10+08:00'
  },
  {
    id: 'wrk-c-02',
    region: 'cn-east-1',
    sandboxClass: 'standard-v3',
    status: 'healthy',
    activeTasks: 4,
    capacity: 12,
    cpuPercent: 33,
    memoryPercent: 48,
    leaseCount: 7,
    version: 'zebra-worker/1.14.2',
    lastHeartbeat: '2026-08-26T09:44:08+08:00'
  },
  {
    id: 'wrk-b-03',
    region: 'cn-north-2',
    sandboxClass: 'compute-v2',
    status: 'draining',
    activeTasks: 1,
    capacity: 8,
    cpuPercent: 12,
    memoryPercent: 30,
    leaseCount: 2,
    version: 'zebra-worker/1.13.9',
    lastHeartbeat: '2026-08-26T09:43:55+08:00'
  },
  {
    id: 'wrk-b-04',
    region: 'cn-north-2',
    sandboxClass: 'compute-v2',
    status: 'offline',
    activeTasks: 0,
    capacity: 8,
    cpuPercent: 0,
    memoryPercent: 0,
    leaseCount: 0,
    version: 'zebra-worker/1.13.9',
    lastHeartbeat: '2026-08-25T18:02:00+08:00'
  }
];

import type { Approval, OrchestrationRun, WorkerNode } from '@/lib/platform/types';
/** 运行中心 OrchestrationRun / Approval / Worker mock 数据（自 runtime-detail.ts 拆出）。 */

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
    status: 'pending',
    argumentsDigest: 'aa11bb22cc33dd44ee55',
    resourceRefs: ['trench/tickets/TR-2291', 'trench/tickets:write'],
    effectPreview: '工单 TR-2291 状态由 open 变更为 escalated，并通知值班负责人',
    policyId: 'pol_approval_high_risk/rev3'
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
    status: 'pending',
    responseSchema: '{"type":"object","properties":{"includeDerivatives":{"type":"boolean"},"scopes":{"type":"array","items":{"type":"string"}}},"required":["includeDerivatives"]}',
    context: '关联子任务「衍生品持仓覆盖」处于 waiting_clarification，回复后自动解除阻塞',
    relatedTool: 'trench.get_risk_report'
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
    status: 'approved',
    argumentsDigest: '0a1b2c3d4e5f60718293',
    resourceRefs: ['trench/positions/account-44', 'trench.positions:read'],
    effectPreview: '只读导出 position-snapshot.csv，不产生业务写入',
    policyId: 'pol_cross_namespace_read/rev2'
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

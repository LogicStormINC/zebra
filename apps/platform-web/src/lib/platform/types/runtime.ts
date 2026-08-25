/** 运行中心领域模型：Task、Event、Attempt、Model Call、Tool、Effect、Artifact、Orchestration、Worker。 */

export type TaskStatus =
  | 'queued'
  | 'running'
  | 'waiting_approval'
  | 'waiting_clarification'
  | 'waiting_children'
  | 'waiting_client_effect'
  | 'suspended'
  | 'blocked'
  | 'uncertain'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type Task = {
  id: string;
  title: string;
  hostAppId: string;
  namespace: string;
  agentReleaseId: string;
  agentName: string;
  status: TaskStatus;
  currentSegment: string;
  orchestrationRunRef?: string;
  subagentCount: number;
  waitReason?: string;
  modelTokens: number;
  costUsd: number;
  hasClient: boolean;
  hasUncertainEffect: boolean;
  createdAt: string;
  updatedAt: string;
};

export type TaskEventType =
  | 'task_created'
  | 'segment_started'
  | 'model_call'
  | 'tool_call'
  | 'tool_receipt'
  | 'approval_requested'
  | 'approval_resolved'
  | 'clarification_requested'
  | 'clarification_resolved'
  | 'subagent_spawned'
  | 'subagent_completed'
  | 'orchestration_planned'
  | 'host_effect_dispatched'
  | 'host_effect_receipt'
  | 'client_effect_dispatched'
  | 'client_effect_receipt'
  | 'artifact_created'
  | 'memory_written'
  | 'task_completed'
  | 'task_failed'
  | 'task_cancelled';

export type TaskEvent = {
  sequence: number;
  eventId: string;
  type: TaskEventType;
  actor: string;
  timestamp: string;
  causationId?: string;
  correlationId?: string;
  summary: string;
  policyVersion?: string;
  modelProfile?: string;
  payload?: Record<string, unknown>;
};

export type ModelCall = {
  id: string;
  role: 'executor' | 'planner' | 'reviewer' | 'analyst' | 'summarizer' | 'classifier';
  provider: string;
  requestedModel: string;
  resolvedModel: string;
  thinkingMode: 'disabled' | 'medium' | 'max';
  latencyMs: number;
  retryCount: number;
  finishReason: string;
  inputTokens: number;
  outputTokens: number;
  reasoningTokens: number;
  costUsd: number;
};

export type Attempt = {
  attemptNumber: number;
  leaseFence: string;
  model: string;
  inputTokens: number;
  outputTokens: number;
  reasoningTokens: number;
  toolCalls: number;
  durationSeconds: number;
  outcome: 'succeeded' | 'failed' | 'retried';
};

export type ToolCall = {
  id: string;
  toolName: string;
  executionLocation: 'zebra' | 'host' | 'sandbox' | 'client';
  risk: 'read' | 'low' | 'medium' | 'high' | 'presentation' | 'navigation' | 'local_state' | 'user_interaction';
  scope: string;
  argumentsDigest: string;
  status: 'succeeded' | 'failed' | 'running' | 'awaiting_approval';
  durationMs: number;
  receiptDigest?: string;
};

export type HostEffect = {
  dispatchId: string;
  taskId: string;
  tool: string;
  operationId: string;
  status: 'pending' | 'delivered' | 'succeeded' | 'failed' | 'uncertain';
  idempotencyKey: string;
  claimOwner: string;
  attempt: number;
  evidence: string;
  reconciliation: 'not_required' | 'pending' | 'succeeded' | 'failed' | 'manual_review';
  hostAppId: string;
  createdAt: string;
};

export type Artifact = {
  id: string;
  taskId: string;
  name: string;
  kind: 'patch' | 'report' | 'screenshot' | 'log' | 'export' | 'diagnostic_bundle';
  bytes: number;
  digest: string;
  createdAt: string;
};

export type OrchestrationNode = {
  id: string;
  label: string;
  role: string;
  childTaskId?: string;
  status: TaskStatus;
  dependsOn: string[];
  budgetTokens: number;
  evidence?: string;
  gate?: string;
};

export type OrchestrationRun = {
  runRef: string;
  taskId: string;
  planRevision: number;
  strategy: 'sequential' | 'parallel' | 'dag';
  nodes: OrchestrationNode[];
  status: TaskStatus;
  totalTokens: number;
  totalCostUsd: number;
  createdAt: string;
};

export type SubagentLink = {
  parentTaskId: string;
  childTaskId: string;
  childTitle: string;
  role: string;
  status: TaskStatus;
  wakeupPolicy: 'on_completion' | 'on_failure' | 'manual';
  createdAt: string;
};

export type Approval = {
  id: string;
  type: 'approval' | 'clarification';
  taskId: string;
  hostAppId: string;
  namespace: string;
  tool?: string;
  risk?: string;
  reason: string;
  question?: string;
  requestedBy: string;
  requestedAt: string;
  deadline: string;
  status: 'pending' | 'approved' | 'rejected' | 'responded' | 'expired' | 'escalated';
};

export type WorkerNode = {
  id: string;
  region: string;
  sandboxClass: string;
  status: 'healthy' | 'draining' | 'offline';
  activeTasks: number;
  capacity: number;
  cpuPercent: number;
  memoryPercent: number;
  leaseCount: number;
  version: string;
  lastHeartbeat: string;
};

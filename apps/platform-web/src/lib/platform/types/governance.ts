import type { Environment } from './common';

/** 治理与审计领域模型：Quota、Usage、Audit、Security Finding、Reconciliation。 */

export type Quota = {
  id: string;
  scope: string;
  dimension:
    | 'concurrent_tasks'
    | 'model_tokens'
    | 'tool_calls'
    | 'runtime_seconds'
    | 'artifact_bytes'
    | 'client_actions'
    | 'subagents'
    | 'orchestration_nodes';
  softLimit: number;
  hardLimit: number;
  warningThresholdPct: number;
  used: number;
  resetCycle: 'hourly' | 'daily' | 'monthly';
  updatedAt: string;
};

export type UsageRecord = {
  date: string;
  hostAppId: string;
  inputTokens: number;
  outputTokens: number;
  reasoningTokens: number;
  modelCostUsd: number;
  runtimeSeconds: number;
  toolCalls: number;
  clientActions: number;
  taskCount: number;
  successRate: number;
};

export type AuditEntry = {
  id: string;
  actor: string;
  actorType: 'operator' | 'system' | 'agent';
  action: string;
  resourceType: string;
  resourceId: string;
  environment: Environment;
  hostAppId?: string;
  namespace?: string;
  beforeDigest?: string;
  afterDigest?: string;
  reason?: string;
  result: 'succeeded' | 'failed' | 'denied';
  timestamp: string;
  correlationId: string;
};

export type SecurityFinding = {
  id: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
  title: string;
  resource: string;
  description: string;
  recommendation: string;
  status: 'open' | 'acknowledged' | 'mitigated' | 'resolved';
  detectedAt: string;
};

export type ReconciliationEntry = {
  id: string;
  dispatchId: string;
  taskId: string;
  hostAppId: string;
  operation: string;
  status: 'matched' | 'mismatched' | 'missing_receipt' | 'manual_review';
  lastAttempt: string;
  attempts: number;
};

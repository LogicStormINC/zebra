import type { Environment } from './common';

/** 质量与发布领域模型：Conformance、Dry Run、Rollout、Evaluation、Release Gate。 */

export type ConformanceCheck = {
  name: string;
  group: string;
  status: 'passed' | 'failed' | 'skipped';
  durationMs: number;
  reasonCode?: string;
  evidence?: string;
};

export type ConformanceRun = {
  id: string;
  hostAppId: string;
  environment: Environment;
  surface: 'backend' | 'frontend';
  profileRevision: number;
  triggeredBy: string;
  startedAt: string;
  durationMs: number;
  passed: number;
  failed: number;
  skipped: number;
  status: 'running' | 'passed' | 'failed';
  checks: ConformanceCheck[];
};

export type DryRun = {
  id: string;
  taskId: string;
  hostAppId: string;
  agentReleaseId: string;
  namespace: string;
  result: 'passed' | 'failed' | 'running';
  summary: string;
  createdAt: string;
};

export type Rollout = {
  id: string;
  target: 'connector-binding' | 'backend-manifest' | 'frontend-profile' | 'agent-release' | 'policy';
  targetId: string;
  fromRevision: number;
  toRevision: number;
  strategy: 'dry-run' | 'canary-5' | 'canary-25' | 'canary-50' | 'production' | 'rollback';
  gates: { name: string; status: 'passed' | 'failed' | 'pending' | 'not_required' }[];
  status: 'planning' | 'in-progress' | 'blocked' | 'completed' | 'rolled-back';
  updatedAt: string;
};

export type EvaluationRun = {
  id: string;
  name: string;
  agentReleaseId: string;
  dataset: string;
  qualityScore: number;
  toolAccuracy: number;
  structuredOutputPassRate: number;
  latencyP95Ms: number;
  costUsdPerRun: number;
  status: 'passed' | 'failed' | 'running' | 'pending';
  createdAt: string;
};

export type ReleaseGate = {
  id: string;
  releaseId: string;
  gate: string;
  requirement: string;
  status: 'passed' | 'failed' | 'pending' | 'not_required';
  evaluatedAt: string;
};

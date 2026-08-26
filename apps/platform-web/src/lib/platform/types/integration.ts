import type { Environment } from './common';

/** 接入中心领域模型：Host、入站信任、Connector、Backend Manifest、Namespace Binding。 */

export type HostTrustHealth = 'healthy' | 'warning' | 'invalid';

export type Host = {
  id: string;
  appId: string;
  name: string;
  owner: string;
  environment: Environment;
  description: string;
  contact: string;
  tags: string[];
  inboundTrustHealth: HostTrustHealth;
  connectorId?: string;
  connectorRevision?: number;
  manifestId?: string;
  manifestRevision?: number;
  frontendProfileId?: string;
  frontendProfileRevision?: number;
  agentReleaseCount: number;
  lastConformance: 'passed' | 'failed' | 'pending' | 'none';
  status: 'draft' | 'active' | 'suspended' | 'revoked';
  onboardingStep: number; // 1-7，7 表示完成
  updatedAt: string;
};

export type InboundTrust = {
  id: string;
  hostAppId: string;
  issuer: string;
  audience: string;
  jwksUri: string;
  allowedOrigins: string[];
  algorithms: string[];
  policyVersion: string;
  namespaceStrategy: 'fixed' | 'claim-mapped';
  clockSkewSeconds: number;
  health: HostTrustHealth;
  lastVerifiedAt: string;
  revision: number;
  digest: string;
  status: 'draft' | 'published' | 'deprecated' | 'revoked';
};

export type Connector = {
  id: string;
  hostAppId: string;
  baseUri: string;
  manifestPath: string;
  invokePath: string;
  reconcilePath: string;
  protocolVersions: string[];
  credentialRef: string;
  workloadIdentityRef: string;
  networkPolicyRef: string;
  timeoutPolicy: { connectSeconds: number; readSeconds: number };
  retryPolicy: { maxRetries: number; backoff: 'exponential' | 'fixed' };
  latestRevision: number;
  boundRevision: number;
  health: 'healthy' | 'degraded' | 'unreachable';
  status: 'draft' | 'published' | 'deprecated' | 'revoked';
  digest: string;
  updatedAt: string;
};

export type ManifestTool = {
  name: string;
  description: string;
  capability: string;
  grantScopes: string[];
  risk: 'read' | 'low' | 'medium' | 'high';
  /** 是否允许并行调用（编辑器展示字段，可选） */
  parallelSafe?: boolean;
  idempotency: 'none' | 'idempotent' | 'idempotency_key';
  timeoutSeconds: number;
  maxOutputBytes: number;
  reconcileCapable: boolean;
  argumentSchema: Record<string, unknown>;
};

export type BackendManifest = {
  id: string;
  hostAppId: string;
  protocolVersion: string;
  revision: number;
  tools: ManifestTool[];
  readTools: number;
  writeTools: number;
  reconcileTools: number;
  digest: string;
  status: 'draft' | 'published' | 'deprecated' | 'revoked';
  conformance: 'passed' | 'failed' | 'pending' | 'none';
  createdBy: string;
  createdAt: string;
};

export type NamespaceBinding = {
  id: string;
  hostAppId: string;
  namespace: string;
  environment: Environment;
  connectorRevision: number;
  manifestRevision: number;
  agentReleaseId: string;
  expectedRevision: number;
  status: 'active' | 'canary' | 'rolled-back' | 'draft';
  updatedAt: string;
};

/** Agent 资产领域模型：AgentDefinition、Release、Capability Profile、Policy。 */

export type AgentDefinition = {
  id: string;
  name: string;
  description: string;
  latestDraftRevision: number;
  latestVersion: number;
  publishedReleaseId?: string;
  capabilityCeiling: string[];
  modelPolicyId: string;
  toolProfileId: string;
  runtimeProfileId: string;
  memoryPolicyId?: string;
  status: 'draft' | 'published' | 'deprecated' | 'revoked';
  updatedAt: string;
};

export type AgentRelease = {
  id: string;
  definitionId: string;
  definitionName: string;
  version: number;
  channel: 'stable' | 'canary' | 'dry-run';
  boundHosts: number;
  digest: string;
  status: 'published' | 'deprecated' | 'revoked';
  releasedBy: string;
  releasedAt: string;
};

export type CapabilityProfile = {
  id: string;
  name: string;
  backendTools: string[];
  clientActions: string[];
  readables: string[];
  revision: number;
  digest: string;
  status: 'draft' | 'published' | 'deprecated' | 'revoked';
  updatedAt: string;
};

export type PolicyRecord = {
  id: string;
  name: string;
  kind:
    | 'capability'
    | 'model'
    | 'tool'
    | 'runtime'
    | 'network'
    | 'approval'
    | 'client-action'
    | 'memory'
    | 'artifact';
  level:
    | 'platform'
    | 'environment'
    | 'host'
    | 'namespace'
    | 'agent-release'
    | 'task-type'
    | 'frontend-profile';
  scope: string;
  revision: number;
  digest: string;
  status: 'draft' | 'published' | 'deprecated' | 'revoked';
  updatedBy: string;
  updatedAt: string;
};

import type {
  AgentDefinition,
  AgentRelease,
  AuditEntry,
  CapabilityProfile,
  EvaluationRun,
  NamespaceBinding,
  PolicyRecord,
  ReleaseGate
} from '@/lib/platform/types';

/** Definition 详情页的服务器取数结果（可序列化，传给 'use client' 组件）。 */
export type DefinitionDetailData = {
  definition: AgentDefinition;
  releases: AgentRelease[];
  publishedRelease?: AgentRelease;
  capabilityProfile?: CapabilityProfile;
  modelPolicy?: PolicyRecord;
  toolPolicy?: PolicyRecord;
  memoryPolicy?: PolicyRecord;
  runtimePolicy?: PolicyRecord;
  securityPolicy?: PolicyRecord;
  toolProfileName: string;
  evaluations: EvaluationRun[];
  releaseGates: ReleaseGate[];
  bindings: NamespaceBinding[];
  auditEntries: AuditEntry[];
};

/** 发布流程步骤（PRD 14.2 Overview：Draft→…→Promote）。 */
export const PUBLISH_FLOW_STEPS = [
  'Draft',
  'Validate',
  'Materialize Version',
  'Release Gate',
  'Publish',
  'Canary',
  'Promote'
] as const;

/** 按 definition 状态推导发布流程当前位置。 */
export function publishFlowCurrentIndex(data: DefinitionDetailData): number {
  const { definition, publishedRelease } = data;
  if (definition.status === 'draft') return 1; // Validate
  if (publishedRelease?.channel === 'canary') return 5; // Canary
  if (publishedRelease?.channel === 'dry-run') return 3; // Release Gate
  if (definition.status === 'deprecated' || definition.status === 'revoked') return 4;
  return 6; // Promote（stable 已全量）
}

/** 确定性伪 digest（FNV-1a，演示用）：为未发布版本/派生 Ref 生成稳定摘要。 */
export function pseudoDigest(seed: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < seed.length; i += 1) {
    hash ^= seed.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  let hex = hash.toString(16).padStart(8, '0');
  while (hex.length < 40) {
    let inner = hash;
    for (let i = 0; i < seed.length; i += 1) {
      inner = (Math.imul(inner ^ seed.charCodeAt(i), 0x01000193) + 0x9e3779b9) >>> 0;
    }
    hex += inner.toString(16).padStart(8, '0');
    hash = inner >>> 3;
  }
  return hex.slice(0, 40);
}

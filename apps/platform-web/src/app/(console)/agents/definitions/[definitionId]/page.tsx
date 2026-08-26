import { PageHeader } from '@/components/platform/page-header';
import { EmptyState } from '@/components/platform/empty-state';
import { MonoId, DigestTag } from '@/components/platform/mono-id';
import { StatusBadge } from '@/components/platform/status-badge';
import { lifecycleTone, LIFECYCLE_STATUS_LABELS } from '@/lib/platform/status';
import { relativeTime } from '@/lib/platform/format';
import { DefinitionDetail } from '@/features/agents/components/definition-detail';
import type { DefinitionDetailData } from '@/features/agents/components/definition-detail-data';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Agent Definition 详情'
};

export default async function AgentDefinitionDetailPage({
  params
}: {
  params: Promise<{ definitionId: string }>;
}) {
  const { definitionId } = await params;
  const definition = repository.agentDefinition(definitionId);

  if (!definition) {
    return (
      <div className='flex flex-1 flex-col'>
        <PageHeader title='Agent Definition' description='未找到该 Definition' />
        <EmptyState
          icon='agent'
          title='未找到该 Agent Definition'
          description={`Definition ${definitionId} 不存在，可能已被删除或 ID 输入有误`}
        />
      </div>
    );
  }

  const policies = repository.policies();
  const releases = repository
    .agentReleases()
    .filter((release) => release.definitionId === definition.id);
  const publishedRelease = definition.publishedReleaseId
    ? releases.find((release) => release.id === definition.publishedReleaseId)
    : undefined;

  const data: DefinitionDetailData = {
    definition,
    releases,
    publishedRelease,
    capabilityProfile: repository
      .capabilityProfiles()
      .find((profile) => profile.id === definition.toolProfileId),
    modelPolicy: policies.find((policy) => policy.id === definition.modelPolicyId),
    toolPolicy: policies.find((policy) => policy.kind === 'tool'),
    memoryPolicy: definition.memoryPolicyId
      ? policies.find((policy) => policy.id === definition.memoryPolicyId)
      : undefined,
    runtimePolicy: policies.find((policy) => policy.id === definition.runtimeProfileId),
    securityPolicy: policies.find((policy) => policy.kind === 'approval'),
    toolProfileName:
      repository.capabilityProfiles().find((profile) => profile.id === definition.toolProfileId)
        ?.name ?? definition.toolProfileId,
    evaluations: repository
      .evaluations()
      .filter((evaluation) => releases.some((release) => release.id === evaluation.agentReleaseId)),
    releaseGates: repository
      .releaseGates()
      .filter((gate) => releases.some((release) => release.id === gate.releaseId)),
    bindings: repository
      .bindings()
      .filter((binding) => releases.some((release) => release.id === binding.agentReleaseId)),
    auditEntries: repository
      .auditEntries()
      .filter(
        (entry) =>
          entry.resourceId === definition.id ||
          releases.some((release) => release.id === entry.resourceId)
      )
  };

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title={definition.name}
        description={definition.description}
        meta={
          <>
            <span className='flex items-center gap-1'>
              Definition ID <MonoId value={definition.id} />
            </span>
            <span>Latest Draft rev {definition.latestDraftRevision}</span>
            <span>Latest Version v{definition.latestVersion}</span>
            {publishedRelease && (
              <span className='flex items-center gap-1'>
                Published <MonoId value={publishedRelease.id} copyable={false} /> ·{' '}
                <DigestTag value={publishedRelease.digest} />
              </span>
            )}
            <span>
              Status{' '}
              <StatusBadge tone={lifecycleTone(definition.status)}>
                {LIFECYCLE_STATUS_LABELS[definition.status] ?? definition.status}
              </StatusBadge>
            </span>
            <span>更新于 {relativeTime(definition.updatedAt)}</span>
          </>
        }
      />
      <DefinitionDetail data={data} />
    </div>
  );
}

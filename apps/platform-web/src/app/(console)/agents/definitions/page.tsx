import { PageHeader } from '@/components/platform/page-header';
import { DefinitionsTable, type DefinitionRow } from '@/features/agents/components/definitions-table';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Agent Definitions'
};

export default function AgentDefinitionsPage() {
  const releases = repository.agentReleases();
  const policies = repository.policies();

  const rows: DefinitionRow[] = repository.agentDefinitions().map((definition) => {
    const release = definition.publishedReleaseId
      ? releases.find((item) => item.id === definition.publishedReleaseId)
      : undefined;
    return {
      ...definition,
      modelPolicyName:
        policies.find((policy) => policy.id === definition.modelPolicyId)?.name ?? definition.modelPolicyId,
      toolProfileName:
        repository.capabilityProfiles().find((profile) => profile.id === definition.toolProfileId)?.name ??
        definition.toolProfileId,
      runtimeProfileName:
        policies.find((policy) => policy.id === definition.runtimeProfileId)?.name ?? definition.runtimeProfileId,
      publishedReleaseVersion: release?.version,
      publishedReleaseChannel: release?.channel
    };
  });

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Agent Definitions'
        description='Agent 的可版本化定义：Draft → Validate → Materialize Version → Release Gate → Publish → Canary → Promote'
      />
      <div className='p-4 md:px-6'>
        <DefinitionsTable rows={rows} />
      </div>
    </div>
  );
}

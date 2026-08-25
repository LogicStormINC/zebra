import type { Metadata } from 'next';

import { PageHeader } from '@/components/platform/page-header';
import { repository } from '@/lib/platform/repository';
import { OnboardingWizard } from '@/features/integrations/components/onboarding-wizard';

export const metadata: Metadata = {
  title: '接入向导'
};

/** 7 步接入向导页（PRD 10.3）。 */
export default function OnboardingPage() {
  const releases = repository.agentReleases();
  const definitions = repository.agentDefinitions();
  const definitionById = new Map(definitions.map((definition) => [definition.id, definition]));

  const agentReleases = releases.map((release) => ({
    id: release.id,
    label: `${release.definitionName} · v${release.version}（${release.channel}）`
  }));
  const capabilityProfiles = repository.capabilityProfiles().map((profile) => ({
    id: profile.id,
    label: `${profile.name} · rev ${profile.revision}`
  }));
  const policies = repository.policies().map((policy) => ({
    id: policy.id,
    label: `${policy.name} · ${policy.kind}`
  }));
  const quotas = repository.quotas().map((quota) => ({
    id: quota.id,
    label: `${quota.dimension} · ${quota.scope}`
  }));
  const capabilityCeilings = Object.fromEntries(
    releases.map((release) => [
      release.id,
      definitionById.get(release.definitionId)?.capabilityCeiling ?? []
    ])
  );

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='接入向导'
        description='7 步完成业务系统接入：基础信息、入站信任、出站 Connector、Backend Manifest、Frontend Capability Profile、Agent 与策略、验证与发布（PRD 10.3）'
      />
      <div className='flex flex-1 flex-col p-4 md:px-6'>
        <OnboardingWizard
          agentReleases={agentReleases}
          capabilityProfiles={capabilityProfiles}
          policies={policies}
          quotas={quotas}
          capabilityCeilings={capabilityCeilings}
        />
      </div>
    </div>
  );
}

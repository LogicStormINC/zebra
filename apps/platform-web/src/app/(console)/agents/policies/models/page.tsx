import { PageHeader } from '@/components/platform/page-header';
import { PolicyTable } from '@/features/agents/components/policy-table';
import { PolicySimulator } from '@/features/agents/components/policy-simulator';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Model Policies'
};

export default function ModelPoliciesPage() {
  const policies = repository.policies().filter((policy) => policy.kind === 'model');

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Model Policies'
        description='模型策略：按角色（planner / executor / reviewer…）路由模型、thinking 预算与降级链'
      />
      <div className='flex flex-col gap-6 p-4 md:px-6'>
        <PolicyTable policies={policies} kindLabel='Model Policy' />
        <PolicySimulator
          data={{
            hosts: repository.hosts(),
            bindings: repository.bindings(),
            releases: repository.agentReleases(),
            definitions: repository.agentDefinitions(),
            capabilityProfiles: repository.capabilityProfiles(),
            quotas: repository.quotas(),
            policies: repository.policies()
          }}
        />
      </div>
    </div>
  );
}

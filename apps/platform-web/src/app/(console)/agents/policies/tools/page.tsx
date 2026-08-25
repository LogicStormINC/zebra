import { PageHeader } from '@/components/platform/page-header';
import { PolicyTable } from '@/features/agents/components/policy-table';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Tool Policies'
};

export default function ToolPoliciesPage() {
  const policies = repository.policies().filter((policy) => policy.kind === 'tool');

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Tool Policies'
        description='工具策略：backend tools 的允许清单、风险分级、幂等与对账要求'
      />
      <div className='p-4 md:px-6'>
        <PolicyTable policies={policies} kindLabel='Tool Policy' />
      </div>
    </div>
  );
}

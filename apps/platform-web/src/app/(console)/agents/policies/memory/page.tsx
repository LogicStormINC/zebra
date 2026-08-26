import { PageHeader } from '@/components/platform/page-header';
import { PolicyTable } from '@/features/agents/components/policy-table';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Memory Policies'
};

export default function MemoryPoliciesPage() {
  const policies = repository.policies().filter((policy) => policy.kind === 'memory');

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Memory Policies'
        description='记忆策略：跨 Attempt 的 memory 写入范围、保留周期与脱敏要求'
      />
      <div className='p-4 md:px-6'>
        <PolicyTable policies={policies} kindLabel='Memory Policy' />
      </div>
    </div>
  );
}

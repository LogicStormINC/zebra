import { PageHeader } from '@/components/platform/page-header';
import { PolicyTable } from '@/features/agents/components/policy-table';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Runtime Policies'
};

export default function RuntimePoliciesPage() {
  const policies = repository.policies().filter((policy) => policy.kind === 'runtime');

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Runtime Policies'
        description='运行时策略：sandbox 等级、超时、重试与资源配额的默认值'
      />
      <div className='p-4 md:px-6'>
        <PolicyTable policies={policies} kindLabel='Runtime Policy' />
      </div>
    </div>
  );
}

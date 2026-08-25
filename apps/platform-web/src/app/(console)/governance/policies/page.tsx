import { PageHeader } from '@/components/platform/page-header';
import { PolicyTable } from '@/features/governance/components/policy-table';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Policy 治理'
};

export default function GovernancePoliciesPage() {
  const policies = repository.policies();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Policy'
        description='Policy 列表与版本管理（PRD 15.1）：按层级与作用域组织，已发布版本不可变'
      />
      <div className='flex flex-col gap-4 p-4 md:px-6'>
        <PolicyTable policies={policies} />
      </div>
    </div>
  );
}

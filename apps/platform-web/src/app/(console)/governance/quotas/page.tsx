import { PageHeader } from '@/components/platform/page-header';
import { QuotaTable } from '@/features/governance/components/quota-table';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Quota 限额'
};

export default function GovernanceQuotasPage() {
  const quotas = repository.quotas();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Quota'
        description='限额与预算管理（PRD 15.3）：Soft Limit 告警、Hard Limit 拒绝、变更全部审计'
      />
      <div className='flex flex-col gap-4 p-4 md:px-6'>
        <QuotaTable quotas={quotas} />
      </div>
    </div>
  );
}

import { PageHeader } from '@/components/platform/page-header';
import { ReconciliationTable } from '@/features/governance/components/reconciliation-table';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Effect Reconciliation'
};

export default function GovernanceReconciliationPage() {
  const entries = repository.reconciliation();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Effect Reconciliation'
        description='Host Effect 对账（PRD 12）：Dispatch 与回执的匹配状态，未收敛项进入人工核对'
      />
      <div className='flex flex-col gap-4 p-4 md:px-6'>
        <ReconciliationTable entries={entries} />
      </div>
    </div>
  );
}

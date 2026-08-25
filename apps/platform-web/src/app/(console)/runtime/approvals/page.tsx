import { PageHeader } from '@/components/platform/page-header';
import { ApprovalsTable } from '@/features/runtime/components/approvals-table';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Approvals'
};

export default function ApprovalsPage() {
  const approvals = repository.approvals();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Approvals'
        description='审批与澄清队列：高风险工具调用需要操作员决策，澄清类问题需要用户答复'
      />
      <div className='p-4 md:px-6'>
        <ApprovalsTable approvals={approvals} />
      </div>
    </div>
  );
}

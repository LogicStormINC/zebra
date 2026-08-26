import { PageHeader } from '@/components/platform/page-header';
import { OperatorTable } from '@/features/system/components/operator-table';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Operator 与角色'
};

export default function SystemOperatorsPage() {
  const operators = repository.operators();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Operator 与角色'
        description='Operator 角色注册表（PRD 14.2）：平台角色模型与邀请管理'
      />
      <div className='flex flex-col gap-4 p-4 md:px-6'>
        <OperatorTable operators={operators} />
      </div>
    </div>
  );
}

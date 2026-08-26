import { PageHeader } from '@/components/platform/page-header';
import { AuditTable } from '@/features/governance/components/audit-table';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Audit Log'
};

export default function GovernanceAuditPage() {
  const entries = repository.auditEntries();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Audit Log'
        description='平台审计日志（PRD 23）：Actor、Action、Resource 与结果的全量检索，支持权限内导出'
      />
      <div className='flex flex-col gap-4 p-4 md:px-6'>
        <AuditTable entries={entries} />
      </div>
    </div>
  );
}

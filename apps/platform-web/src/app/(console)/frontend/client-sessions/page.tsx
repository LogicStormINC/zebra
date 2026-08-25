import { PageHeader } from '@/components/platform/page-header';
import { ClientSessionsView } from '@/features/frontend/components/client-sessions-view';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Client Session'
};

/** Client Session 列表页（PRD 19.1 / 19.2）。 */
export default function ClientSessionsPage() {
  const sessions = repository.clientSessions();
  const snapshots = repository.mountedSnapshots();
  const effects = repository.clientEffects();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Client Session'
        description='浏览器会话、Controller Lease 与挂载能力视图；点击行查看会话详情并执行治理操作'
      />
      <div className='p-4 md:px-6'>
        <ClientSessionsView sessions={sessions} snapshots={snapshots} effects={effects} />
      </div>
    </div>
  );
}

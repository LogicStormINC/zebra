import Link from 'next/link';
import type { Metadata } from 'next';

import { PageHeader } from '@/components/platform/page-header';
import { EmptyState } from '@/components/platform/empty-state';
import { buttonVariants } from '@/components/ui/button';
import { Icons } from '@/components/icons';
import { repository } from '@/lib/platform/repository';
import { HostsTable } from '@/features/integrations/components/hosts-table';

export const metadata: Metadata = {
  title: 'Host 应用'
};

/** Host 应用列表页（PRD 10.1）。 */
export default function HostsPage() {
  const hosts = repository.hosts();

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Host 应用'
        description='已接入与接入中的业务 Host：信任健康、Connector / Manifest / Frontend Profile 版本、Conformance 与生命周期状态（PRD 10.1）'
        actions={
          <Link href='/integrations/onboarding' className={buttonVariants()}>
            <Icons.add data-icon='inline-start' />
            创建 Host
          </Link>
        }
      />
      {hosts.length === 0 ? (
        <EmptyState
          title='还没有 Host 应用'
          description='从 7 步接入向导开始接入第一个业务系统'
          icon='host'
        />
      ) : (
        <div className='flex flex-1 flex-col p-4 md:px-6'>
          <HostsTable hosts={hosts} />
        </div>
      )}
    </div>
  );
}

import { PageHeader } from '@/components/platform/page-header';
import { ReleasesTable } from '@/features/agents/components/releases-table';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Agent Releases'
};

export default function AgentReleasesPage() {
  const releases = [...repository.agentReleases()].sort((a, b) => b.releasedAt.localeCompare(a.releasedAt));

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Agent Releases'
        description='已发布的不可变 Agent 版本：stable / canary / dry-run 渠道管理与 Revoke / Promote 操作'
      />
      <div className='p-4 md:px-6'>
        <ReleasesTable releases={releases} />
      </div>
    </div>
  );
}

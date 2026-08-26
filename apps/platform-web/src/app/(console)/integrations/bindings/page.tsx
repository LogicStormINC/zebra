import type { Metadata } from 'next';

import { PageHeader } from '@/components/platform/page-header';
import { EmptyState } from '@/components/platform/empty-state';
import { repository } from '@/lib/platform/repository';
import { BindingsTable } from '@/features/integrations/components/bindings-table';

export const metadata: Metadata = {
  title: 'Namespace Binding'
};

/** Namespace Binding 列表页（PRD 15 / 24.4）。 */
export default function BindingsPage() {
  const bindings = repository.bindings();
  const hosts = repository.hosts().map((host) => ({ appId: host.appId, name: host.name }));
  const agentReleases = repository.agentReleases().map((release) => ({
    id: release.id,
    label: `${release.definitionName} · v${release.version}`
  }));

  const runningTasksByHost: Record<string, number> = {};
  for (const task of repository.tasks()) {
    if (task.status === 'running' || task.status === 'queued') {
      runningTasksByHost[task.hostAppId] = (runningTasksByHost[task.hostAppId] ?? 0) + 1;
    }
  }

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title='Namespace Binding'
        description='Namespace 到 Connector / Manifest / Agent Release 的版本化绑定；升级必须声明 expected revision，回滚遵循新 Run 新版本、旧 Task 保快照（PRD 15 / 24.4）'
      />
      {bindings.length === 0 ? (
        <EmptyState title='暂无 Namespace Binding' description='发布 Host 或手动创建 Binding' icon='binding' />
      ) : (
        <div className='flex flex-1 flex-col p-4 md:px-6'>
          <BindingsTable
            bindings={bindings}
            hosts={hosts}
            agentReleases={agentReleases}
            runningTasksByHost={runningTasksByHost}
          />
        </div>
      )}
    </div>
  );
}

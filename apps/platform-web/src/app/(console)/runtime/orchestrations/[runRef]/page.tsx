import { PageHeader } from '@/components/platform/page-header';
import { EmptyState } from '@/components/platform/empty-state';
import { MonoId } from '@/components/platform/mono-id';
import { OrchestrationDetail } from '@/features/runtime/components/orchestration-detail';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Orchestration 详情'
};

export default async function OrchestrationDetailPage({
  params
}: {
  params: Promise<{ runRef: string }>;
}) {
  const { runRef } = await params;
  const run = repository.orchestration(runRef);

  if (!run) {
    return (
      <div className='flex flex-1 flex-col'>
        <PageHeader title='Orchestration' description='未找到该编排运行' />
        <EmptyState
          icon='orchestration'
          title='未找到该 Orchestration Run'
          description={`编排运行 ${runRef} 不存在，可能已被归档或 runRef 输入有误`}
        />
      </div>
    );
  }

  const gates = repository.releaseGates().filter((gate) => gate.releaseId === repository.task(run.taskId)?.agentReleaseId);

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title={`Orchestration ${run.runRef}`}
        description={`编排计划 rev ${run.planRevision} · ${run.nodes.length} 个节点 · ${run.strategy} 策略`}
        meta={
          <>
            <span className='flex items-center gap-1'>
              Run <MonoId value={run.runRef} />
            </span>
            <span>Plan Revision rev {run.planRevision}</span>
            <span>Nodes {run.nodes.length}</span>
          </>
        }
      />
      <OrchestrationDetail run={run} gates={gates} />
    </div>
  );
}

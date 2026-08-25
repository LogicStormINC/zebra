import { PageHeader } from '@/components/platform/page-header';
import { EmptyState } from '@/components/platform/empty-state';
import { MonoId } from '@/components/platform/mono-id';
import { TaskDetail } from '@/features/runtime/components/task-detail';
import type { TaskDetailData } from '@/features/runtime/components/task-detail-data';
import { repository } from '@/lib/platform/repository';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Task 详情'
};

export default async function TaskDetailPage({ params }: { params: Promise<{ taskId: string }> }) {
  const { taskId } = await params;
  const task = repository.task(taskId);

  if (!task) {
    return (
      <div className='flex flex-1 flex-col'>
        <PageHeader title='Task' description='未找到该 Task' />
        <EmptyState
          icon='task'
          title='未找到该 Task'
          description={`Task ${taskId} 不存在，可能已被清理或 ID 输入有误`}
        />
      </div>
    );
  }

  const release = repository.agentReleases().find((item) => item.id === task.agentReleaseId);
  const definition = release ? repository.agentDefinition(release.definitionId) : undefined;
  const orchestration = task.orchestrationRunRef ? repository.orchestration(task.orchestrationRunRef) : undefined;
  const host = repository.host(task.hostAppId);
  const manifest = host?.manifestId ? repository.manifest(host.manifestId) : undefined;
  const frontendProfile = host?.frontendProfileId ? repository.frontendProfile(host.frontendProfileId) : undefined;

  const clientRunBindings = repository.clientRunBindings().filter((binding) => binding.taskId === task.id);
  const runIds = new Set(clientRunBindings.map((binding) => binding.runId));
  const clientSessions = repository.clientSessions().filter((session) => session.runId !== undefined && runIds.has(session.runId));
  const mountedSnapshots = repository
    .mountedSnapshots()
    .filter((snapshot) => clientSessions.some((session) => session.id === snapshot.clientSessionId));

  const correlationIds = new Set(
    repository
      .taskEvents(task.id)
      .map((event) => event.correlationId)
      .filter((id): id is string => Boolean(id))
  );

  const data: TaskDetailData = {
    task,
    release,
    definition,
    events: repository.taskEvents(task.id),
    attempts: repository.attempts(task.id),
    modelCalls: repository.modelCalls(task.id),
    toolCalls: repository.toolCalls(task.id),
    hostEffects: repository.hostEffectsForTask(task.id),
    artifacts: repository.artifacts(task.id),
    orchestration,
    subagents: repository.subagentLinks().filter((link) => link.parentTaskId === task.id),
    approvals: repository.approvals().filter((approval) => approval.taskId === task.id),
    memoryPolicy: definition?.memoryPolicyId
      ? repository.policies().find((policy) => policy.id === definition.memoryPolicyId)
      : undefined,
    host,
    manifest,
    frontendProfile,
    clientRunBindings,
    clientSessions,
    mountedSnapshots,
    clientEffects: repository.clientEffects().filter((effect) => effect.taskId === task.id),
    auditEntries: repository
      .auditEntries()
      .filter(
        (entry) =>
          entry.resourceId === task.id ||
          (entry.resourceType === 'Task' && entry.resourceId === task.id) ||
          correlationIds.has(entry.correlationId)
      )
  };

  return (
    <div className='flex flex-1 flex-col'>
      <PageHeader
        title={task.title}
        meta={
          <>
            <span className='flex items-center gap-1'>
              Task ID <MonoId value={task.id} />
            </span>
            <span className='font-mono'>{task.id}</span>
          </>
        }
      />
      <TaskDetail data={data} />
    </div>
  );
}

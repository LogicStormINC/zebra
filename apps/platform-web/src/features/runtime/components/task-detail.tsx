'use client';
import Link from 'next/link';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { MonoId } from '@/components/platform/mono-id';
import { RiskConfirmDialog } from '@/components/platform/risk-confirm-dialog';
import { StatusBadge } from '@/components/platform/status-badge';
import { TASK_STATUS_LABELS, taskStatusTone } from '@/lib/platform/status';
import { formatDateTime, formatUsd, relativeTime } from '@/lib/platform/format';
import { Icons } from '@/components/icons';
import type { TaskDetailData } from './task-detail-data';
import { TaskOverviewTab, TaskMemoryTab } from './task-tabs-overview';
import { TaskTimelineTab } from './task-tabs-timeline';
import { TaskAttemptsTab, TaskModelCallsTab, TaskToolsTab } from './task-tabs-traces';
import { TaskClientTab, TaskHostEffectsTab } from './task-tabs-effects';
import { TaskArtifactsTab, TaskAuditTab, TaskUsageTab } from './task-tabs-artifacts';
import { TaskBindingTab } from './task-tabs-binding';
import { OrchestrationDag } from './orchestration-dag';
import { EmptyState } from '@/components/platform/empty-state';

/** Task 详情（PRD 18）：Header + 12 个内容 Tab 的旗舰页面。 */
export function TaskDetail({ data }: { data: TaskDetailData }) {
  const { task } = data;
  const hasWaitingApproval = task.status === 'waiting_approval';

  return (
    <div className='flex flex-col gap-4 p-4 md:px-6'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <div className='flex flex-wrap items-center gap-x-4 gap-y-1.5'>
          <StatusBadge tone={taskStatusTone(task.status)}>
            {TASK_STATUS_LABELS[task.status]}
          </StatusBadge>
          <span className='text-muted-foreground text-xs'>
            Host <span className='text-foreground font-medium'>{task.hostAppId}</span>
          </span>
          <span className='text-muted-foreground text-xs'>
            Namespace <span className='text-foreground font-mono font-medium'>{task.namespace}</span>
          </span>
          <span className='text-muted-foreground text-xs'>
            Agent <span className='text-foreground font-medium'>{task.agentName}</span>{' '}
            <MonoId value={task.agentReleaseId} copyable={false} />
          </span>
          <span className='text-muted-foreground text-xs'>
            Segment <span className='text-foreground font-mono font-medium'>{task.currentSegment}</span>
          </span>
          <span className='text-muted-foreground text-xs'>
            Created <span className='text-foreground font-medium'>{formatDateTime(task.createdAt)}</span>
          </span>
          <span className='text-muted-foreground text-xs'>
            Updated <span className='text-foreground font-medium'>{relativeTime(task.updatedAt)}</span>
          </span>
          <span className='text-muted-foreground text-xs'>
            Cost <span className='text-foreground font-medium tabular-nums'>{formatUsd(task.costUsd)}</span>
          </span>
        </div>
        <div className='flex flex-wrap items-center gap-2'>
          <Button
            variant='outline'
            size='sm'
            onClick={() =>
              toast.info(task.status === 'suspended' ? '恢复 Task（演示）' : '挂起 Task（演示）', {
                description: task.status === 'suspended' ? 'Task 将从当前 segment 继续执行' : 'Task 将暂停在当前 segment，保留全部状态'
              })
            }
          >
            {task.status === 'suspended' ? (
              <>
                <Icons.circleCheck className='size-4' />
                Resume
              </>
            ) : (
              <>
                <Icons.clock className='size-4' />
                Suspend
              </>
            )}
          </Button>
          <RiskConfirmDialog
            trigger={
              <Button variant='destructive' size='sm'>
                <Icons.close className='size-4' />
                Cancel
              </Button>
            }
            title={`Cancel Task ${task.id}`}
            impact='中断当前 Attempt、通知所有 Subagent 停止、未完成的 Host Effect 进入对账流程'
            irreversibility='取消后不可恢复，只能重新创建 Task'
            currentRevision={`attempt / segment ${task.currentSegment}`}
            actionLabel='确认取消'
            onConfirm={() => {
              // 演示操作
            }}
          />
          {hasWaitingApproval && (
            <Button size='sm' render={<Link href='/runtime/approvals' aria-label='打开 Approval' />}>
              <Icons.approval className='size-4' />
              Open Approval
            </Button>
          )}
          <Button
            variant='outline'
            size='sm'
            onClick={() =>
              toast.success('Diagnostic Bundle 生成中（演示）', {
                description: '包含事件流、模型调用、工具调用与 Host Effect 证据的打包下载'
              })
            }
          >
            <Icons.fileZip className='size-4' />
            Download Diagnostic Bundle
          </Button>
        </div>
      </div>

      <Alert>
        <Icons.lock />
        <AlertTitle>Binding 不可变</AlertTitle>
        <AlertDescription>
          Task 运行期间不允许修改 Task Binding（Agent Release、Capability、Host Snapshot 等）：更换版本需要取消当前 Task 并以新 Binding 重建（PRD 18.3）。
        </AlertDescription>
      </Alert>

      <Tabs defaultValue='overview'>
        <div className='overflow-x-auto pb-1'>
          <TabsList className='h-auto flex-nowrap'>
            <TabsTrigger value='overview'>Overview</TabsTrigger>
            <TabsTrigger value='timeline'>Timeline</TabsTrigger>
            <TabsTrigger value='orchestration'>Orchestration</TabsTrigger>
            <TabsTrigger value='attempts'>Attempts</TabsTrigger>
            <TabsTrigger value='model-calls'>Model Calls</TabsTrigger>
            <TabsTrigger value='tools'>Tools</TabsTrigger>
            <TabsTrigger value='host-effects'>Host Effects</TabsTrigger>
            <TabsTrigger value='client'>Client</TabsTrigger>
            <TabsTrigger value='artifacts'>Artifacts</TabsTrigger>
            <TabsTrigger value='memory'>Memory</TabsTrigger>
            <TabsTrigger value='binding'>Binding</TabsTrigger>
            <TabsTrigger value='usage'>Usage</TabsTrigger>
            <TabsTrigger value='audit'>Audit</TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value='overview' className='mt-4'>
          <TaskOverviewTab data={data} />
        </TabsContent>
        <TabsContent value='timeline' className='mt-4'>
          <TaskTimelineTab events={data.events} />
        </TabsContent>
        <TabsContent value='orchestration' className='mt-4'>
          {data.orchestration ? (
            <div className='flex flex-col gap-4'>
              <p className='text-muted-foreground text-xs'>
                编排运行 <MonoId value={data.orchestration.runRef} /> · plan rev {data.orchestration.planRevision} ·{' '}
                <Link
                  href={`/runtime/orchestrations/${data.orchestration.runRef}`}
                  className='text-primary hover:underline'
                >
                  查看编排详情
                </Link>
              </p>
              <OrchestrationDag run={data.orchestration} />
            </div>
          ) : (
            <EmptyState
              icon='orchestration'
              title='该 Task 无编排运行'
              description='单 Agent 直接执行的 Task 不产生 Orchestration Run；由 Orchestrator 分解的 Task 才会有 DAG'
            />
          )}
        </TabsContent>
        <TabsContent value='attempts' className='mt-4'>
          <TaskAttemptsTab attempts={data.attempts} />
        </TabsContent>
        <TabsContent value='model-calls' className='mt-4'>
          <TaskModelCallsTab modelCalls={data.modelCalls} />
        </TabsContent>
        <TabsContent value='tools' className='mt-4'>
          <TaskToolsTab toolCalls={data.toolCalls} />
        </TabsContent>
        <TabsContent value='host-effects' className='mt-4'>
          <TaskHostEffectsTab effects={data.hostEffects} />
        </TabsContent>
        <TabsContent value='client' className='mt-4'>
          <TaskClientTab data={data} />
        </TabsContent>
        <TabsContent value='artifacts' className='mt-4'>
          <TaskArtifactsTab artifacts={data.artifacts} />
        </TabsContent>
        <TabsContent value='memory' className='mt-4'>
          <TaskMemoryTab memoryPolicy={data.memoryPolicy} />
        </TabsContent>
        <TabsContent value='binding' className='mt-4'>
          <TaskBindingTab data={data} />
        </TabsContent>
        <TabsContent value='usage' className='mt-4'>
          <TaskUsageTab data={data} />
        </TabsContent>
        <TabsContent value='audit' className='mt-4'>
          <TaskAuditTab entries={data.auditEntries} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

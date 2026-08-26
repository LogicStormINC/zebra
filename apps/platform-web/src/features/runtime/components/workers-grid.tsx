'use client';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { DataList } from '@/components/platform/data-list';
import { EmptyState } from '@/components/platform/empty-state';
import { StatusBadge } from '@/components/platform/status-badge';
import { lifecycleTone } from '@/lib/platform/status';
import { relativeTime } from '@/lib/platform/format';
import { Progress } from '@/components/ui/progress';
import { cn } from '@/lib/utils';
import type { WorkerNode } from '@/lib/platform/types';

/** Workers 卡片网格（PRD 22）：负载 / CPU / Memory / Lease / 心跳；offline 红边。 */
export function WorkersGrid({ workers }: { workers: WorkerNode[] }) {
  if (workers.length === 0) {
    return (
      <EmptyState
        icon='worker'
        title='暂无 Worker 节点'
        description='无状态 harness worker 会向控制平面注册并维持心跳租约'
      />
    );
  }

  return (
    <div className='grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3'>
      {workers.map((worker) => (
        <WorkerCard key={worker.id} worker={worker} />
      ))}
    </div>
  );
}

function WorkerCard({ worker }: { worker: WorkerNode }) {
  const isOffline = worker.status === 'offline';
  const taskPercent = Math.round((worker.activeTasks / worker.capacity) * 100);

  return (
    <Card className={cn('py-0', isOffline && 'border-red-500/60 border-2')}>
      <CardHeader className='flex flex-row items-center justify-between border-b px-4 py-3'>
        <CardTitle className='font-mono text-sm'>{worker.id}</CardTitle>
        <StatusBadge tone={lifecycleTone(worker.status)}>
          {worker.status === 'healthy' ? '健康' : worker.status === 'draining' ? '排水期' : '离线'}
        </StatusBadge>
      </CardHeader>
      <CardContent className='flex flex-col gap-3 p-4'>
        <DataList
          columns={2}
          items={[
            { label: 'Region', value: <Badge variant='outline'>{worker.region}</Badge> },
            { label: 'Sandbox Class', value: worker.sandboxClass },
            { label: 'Lease Count', value: `${worker.leaseCount} 个租约` },
            { label: 'Version', value: <span className='font-mono text-xs'>{worker.version}</span> },
            { label: 'Last Heartbeat', value: relativeTime(worker.lastHeartbeat) }
          ]}
        />

        <div className='space-y-2.5'>
          <div>
            <div className='mb-1 flex items-center justify-between text-xs'>
              <span className='text-muted-foreground'>Active Tasks</span>
              <span className='tabular-nums font-medium'>
                {worker.activeTasks} / {worker.capacity}（{taskPercent}%）
              </span>
            </div>
            <Progress value={taskPercent} aria-label='Active Tasks 占用' />
          </div>
          <div>
            <div className='mb-1 flex items-center justify-between text-xs'>
              <span className='text-muted-foreground'>CPU</span>
              <span className='tabular-nums font-medium'>{worker.cpuPercent}%</span>
            </div>
            <Progress value={worker.cpuPercent} aria-label='CPU 占用' />
          </div>
          <div>
            <div className='mb-1 flex items-center justify-between text-xs'>
              <span className='text-muted-foreground'>Memory</span>
              <span className='tabular-nums font-medium'>{worker.memoryPercent}%</span>
            </div>
            <Progress value={worker.memoryPercent} aria-label='Memory 占用' />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

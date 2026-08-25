'use client';
import Link from 'next/link';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { EmptyState } from '@/components/platform/empty-state';
import { MonoId } from '@/components/platform/mono-id';
import { StatusBadge } from '@/components/platform/status-badge';
import { TASK_STATUS_LABELS, taskStatusTone } from '@/lib/platform/status';
import { formatDateTime, formatNumber, formatUsd } from '@/lib/platform/format';
import type { OrchestrationRun } from '@/lib/platform/types';

/** Orchestration 列表（PRD 18 附表）：runRef / task / strategy / plan / nodes / 状态 / 成本。 */
export function OrchestrationsList({ runs }: { runs: OrchestrationRun[] }) {
  if (runs.length === 0) {
    return (
      <EmptyState
        icon='orchestration'
        title='暂无编排运行'
        description='由 Orchestrator 分解的 Task 会生成带 DAG 计划的 Orchestration Run'
      />
    );
  }

  return (
    <div className='overflow-hidden rounded-lg border'>
      <Table>
        <TableHeader className='bg-muted'>
          <TableRow>
            <TableHead>Run</TableHead>
            <TableHead>Task</TableHead>
            <TableHead>Strategy</TableHead>
            <TableHead>Plan Revision</TableHead>
            <TableHead>Nodes</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Tokens</TableHead>
            <TableHead>Cost</TableHead>
            <TableHead>Created At</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {runs.map((run) => (
            <TableRow key={run.runRef}>
              <TableCell>
                <Link href={`/runtime/orchestrations/${run.runRef}`} className='text-primary hover:underline'>
                  <MonoId value={run.runRef} copyable={false} />
                </Link>
              </TableCell>
              <TableCell>
                <Link href={`/runtime/tasks/${run.taskId}`} className='text-primary hover:underline'>
                  <MonoId value={run.taskId} copyable={false} />
                </Link>
              </TableCell>
              <TableCell>
                <Badge variant='outline'>{run.strategy}</Badge>
              </TableCell>
              <TableCell className='tabular-nums'>rev {run.planRevision}</TableCell>
              <TableCell className='tabular-nums'>{run.nodes.length}</TableCell>
              <TableCell>
                <StatusBadge tone={taskStatusTone(run.status)}>
                  {TASK_STATUS_LABELS[run.status] ?? run.status}
                </StatusBadge>
              </TableCell>
              <TableCell className='tabular-nums'>{formatNumber(run.totalTokens)}</TableCell>
              <TableCell className='tabular-nums'>{formatUsd(run.totalCostUsd)}</TableCell>
              <TableCell className='text-sm whitespace-nowrap'>{formatDateTime(run.createdAt)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

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
import { formatDateTime } from '@/lib/platform/format';
import type { SubagentLink } from '@/lib/platform/types';

const WAKEUP_LABELS: Record<SubagentLink['wakeupPolicy'], string> = {
  on_completion: '完成时唤醒',
  on_failure: '失败时唤醒',
  manual: '手动唤醒'
};

/** Subagent 列表：Durable Subagent 链接关系。 */
export function SubagentsList({ links }: { links: SubagentLink[] }) {
  if (links.length === 0) {
    return (
      <EmptyState
        icon='subagent'
        title='暂无 Subagent 关系'
        description='Orchestrator 派生的 durable subagent 会在这里登记父子 Task 关系与唤醒策略'
      />
    );
  }

  return (
    <div className='flex flex-col gap-3'>
      <div className='overflow-hidden rounded-lg border'>
        <Table>
          <TableHeader className='bg-muted'>
            <TableRow>
              <TableHead>Parent Task</TableHead>
              <TableHead>Child Task</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Wakeup Policy</TableHead>
              <TableHead>Created At</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {links.map((link) => (
              <TableRow key={`${link.parentTaskId}-${link.childTaskId}`}>
                <TableCell>
                  <Link href={`/runtime/tasks/${link.parentTaskId}`} className='text-primary hover:underline'>
                    <MonoId value={link.parentTaskId} copyable={false} />
                  </Link>
                </TableCell>
                <TableCell>
                  <Link href={`/runtime/tasks/${link.childTaskId}`} className='text-primary hover:underline'>
                    <span className='font-medium'>{link.childTitle}</span>
                  </Link>
                  <div className='text-muted-foreground font-mono text-xs'>{link.childTaskId}</div>
                </TableCell>
                <TableCell>
                  <Badge variant='outline'>{link.role}</Badge>
                </TableCell>
                <TableCell>
                  <StatusBadge tone={taskStatusTone(link.status)}>
                    {TASK_STATUS_LABELS[link.status] ?? link.status}
                  </StatusBadge>
                </TableCell>
                <TableCell className='text-sm'>{WAKEUP_LABELS[link.wakeupPolicy]}</TableCell>
                <TableCell className='text-sm whitespace-nowrap'>{formatDateTime(link.createdAt)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

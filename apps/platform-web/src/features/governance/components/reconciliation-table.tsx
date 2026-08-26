'use client';

import Link from 'next/link';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { MonoId } from '@/components/platform/mono-id';
import { RiskConfirmDialog } from '@/components/platform/risk-confirm-dialog';
import { StatusBadge } from '@/components/platform/status-badge';
import { Icons } from '@/components/icons';
import { relativeTime } from '@/lib/platform/format';
import type { ReconciliationEntry } from '@/lib/platform/types';

const STATUS_META: Record<
  ReconciliationEntry['status'],
  { label: string; tone: 'success' | 'failure' | 'uncertain' | 'warning'; hint: string }
> = {
  matched: { label: '已匹配', tone: 'success', hint: '平台 Dispatch 与 Host 回执一致，效果收敛' },
  mismatched: {
    label: '不匹配',
    tone: 'failure',
    hint: '回执内容与 Dispatch 期望不一致，需要回滚或补偿'
  },
  missing_receipt: {
    label: '缺少回执',
    tone: 'uncertain',
    hint: '超时未收到回执，效果停留在 uncertain，等待自动重试对账'
  },
  manual_review: {
    label: '人工核对',
    tone: 'warning',
    hint: '自动对账多次未收敛，需要人工在业务侧核对实际写入状态'
  }
};

export function ReconciliationTable({ entries }: { entries: ReconciliationEntry[] }) {
  return (
    <div className='flex flex-col gap-4'>
      <Alert>
        <Icons.reconciliation />
        <AlertTitle>Effect Reconciliation 对账语义</AlertTitle>
        <AlertDescription>
          <ul className='mt-1 space-y-1'>
            {(Object.keys(STATUS_META) as ReconciliationEntry['status'][]).map((status) => (
              <li key={status} className='flex flex-wrap items-center gap-2 text-xs'>
                <StatusBadge tone={STATUS_META[status].tone}>
                  {STATUS_META[status].label}
                </StatusBadge>
                <span className='text-muted-foreground'>{STATUS_META[status].hint}</span>
              </li>
            ))}
          </ul>
        </AlertDescription>
      </Alert>

      <div className='overflow-hidden rounded-lg border'>
        <Table>
          <TableHeader className='bg-muted sticky top-0'>
            <TableRow>
              <TableHead>Dispatch ID</TableHead>
              <TableHead>Task</TableHead>
              <TableHead>Host</TableHead>
              <TableHead>Operation</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Last Attempt</TableHead>
              <TableHead className='text-right'>Attempts</TableHead>
              <TableHead className='text-right'>操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.map((entry) => (
              <TableRow key={entry.id}>
                <TableCell>
                  <Link
                    href='/runtime/host-effects'
                    className='inline-flex items-center gap-1 text-xs underline-offset-2 hover:underline'
                    onClick={(event) => event.stopPropagation()}
                  >
                    <MonoId value={entry.dispatchId} copyable={false} />
                    <Icons.externalLink className='text-muted-foreground size-3' />
                  </Link>
                </TableCell>
                <TableCell>
                  <Link
                    href={`/runtime/tasks/${entry.taskId}`}
                    className='font-mono text-xs underline-offset-2 hover:underline'
                  >
                    {entry.taskId}
                  </Link>
                </TableCell>
                <TableCell>
                  <span className='font-mono text-xs'>{entry.hostAppId}</span>
                </TableCell>
                <TableCell>
                  <span className='font-mono text-xs'>{entry.operation}</span>
                </TableCell>
                <TableCell>
                  <StatusBadge tone={STATUS_META[entry.status].tone}>
                    {STATUS_META[entry.status].label}
                  </StatusBadge>
                </TableCell>
                <TableCell className='text-muted-foreground text-xs whitespace-nowrap'>
                  {relativeTime(entry.lastAttempt)}
                </TableCell>
                <TableCell className='text-right font-mono text-xs tabular-nums'>
                  {entry.attempts}
                </TableCell>
                <TableCell className='text-right'>
                  {entry.status === 'manual_review' ? (
                    <RiskConfirmDialog
                      trigger={
                        <Button
                          variant='outline'
                          size='sm'
                          onClick={(event) => event.stopPropagation()}
                        >
                          人工核对
                        </Button>
                      }
                      title={`人工核对 ${entry.dispatchId}`}
                      impact={`需要在 ${entry.hostAppId} 业务侧确认 ${entry.operation} 的实际写入状态，并将结论标记为 matched 或 mismatched`}
                      irreversibility='人工结论会覆盖自动对账结果，成为 Effect 的最终收敛状态'
                      actionLabel='确认核对结论'
                      onConfirm={() => undefined}
                    />
                  ) : (
                    <span className='text-muted-foreground text-xs'>—</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
            {entries.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} className='text-muted-foreground h-24 text-center'>
                  没有待对账的 Effect
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

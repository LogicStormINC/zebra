'use client';
import Link from 'next/link';
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
import { lifecycleTone } from '@/lib/platform/status';
import { formatDateTime } from '@/lib/platform/format';
import type { HostEffect } from '@/lib/platform/types';
import { HostEffectRowActions } from './host-effect-row-actions';

const EFFECT_STATUS_LABELS: Record<string, string> = {
  pending: '待调度',
  delivered: '已送达',
  succeeded: '成功',
  failed: '失败',
  uncertain: '不确定'
};

const RECONCILIATION_LABELS: Record<string, string> = {
  not_required: '无需对账',
  pending: '待对账',
  succeeded: '对账成功',
  failed: '对账失败',
  manual_review: '人工审查'
};

/** Host Effect 全局列表（PRD 18.10 延伸）：uncertain 行提供对账与升级操作。 */
export function HostEffectsTable({ effects }: { effects: HostEffect[] }) {
  if (effects.length === 0) {
    return (
      <EmptyState
        icon='effect'
        title='暂无 Host Effect 派发'
        description='对 Host 后端的工具派发、幂等键与 Receipt 对账状态会集中在此展示'
      />
    );
  }

  return (
    <div className='overflow-hidden rounded-lg border'>
      <Table>
        <TableHeader className='bg-muted'>
          <TableRow>
            <TableHead>Dispatch ID</TableHead>
            <TableHead>Task</TableHead>
            <TableHead>Tool</TableHead>
            <TableHead>Operation ID</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Idempotency Key</TableHead>
            <TableHead>Claim Owner</TableHead>
            <TableHead>Attempt</TableHead>
            <TableHead>Evidence</TableHead>
            <TableHead>Reconciliation</TableHead>
            <TableHead>Host</TableHead>
            <TableHead>Created At</TableHead>
            <TableHead className='text-right'>操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {effects.map((effect) => (
            <TableRow key={effect.dispatchId}>
              <TableCell>
                <MonoId value={effect.dispatchId} copyable={false} />
              </TableCell>
              <TableCell>
                <Link href={`/runtime/tasks/${effect.taskId}`} className='text-primary hover:underline'>
                  <MonoId value={effect.taskId} copyable={false} />
                </Link>
              </TableCell>
              <TableCell className='font-mono text-xs'>{effect.tool}</TableCell>
              <TableCell className='font-mono text-xs'>{effect.operationId}</TableCell>
              <TableCell>
                <StatusBadge tone={lifecycleTone(effect.status === 'uncertain' ? 'uncertain' : effect.status)}>
                  {EFFECT_STATUS_LABELS[effect.status] ?? effect.status}
                </StatusBadge>
              </TableCell>
              <TableCell>
                <MonoId value={effect.idempotencyKey} />
              </TableCell>
              <TableCell className='font-mono text-xs'>{effect.claimOwner}</TableCell>
              <TableCell className='tabular-nums'>#{effect.attempt}</TableCell>
              <TableCell className='text-muted-foreground max-w-[180px] truncate text-sm'>
                {effect.evidence}
              </TableCell>
              <TableCell>
                <StatusBadge tone={lifecycleTone(effect.reconciliation)} withDot={effect.reconciliation !== 'not_required'}>
                  {RECONCILIATION_LABELS[effect.reconciliation] ?? effect.reconciliation}
                </StatusBadge>
              </TableCell>
              <TableCell className='text-sm'>{effect.hostAppId}</TableCell>
              <TableCell className='text-sm whitespace-nowrap'>{formatDateTime(effect.createdAt)}</TableCell>
              <TableCell className='text-right'>
                {effect.status === 'uncertain' ? (
                  <HostEffectRowActions effect={effect} showEscalate />
                ) : (
                  <span className='text-muted-foreground text-xs'>—</span>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

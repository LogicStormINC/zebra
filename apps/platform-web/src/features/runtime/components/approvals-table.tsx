'use client';
import { useState } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
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
import { RiskBadge } from '@/components/platform/risk-badge';
import { lifecycleTone } from '@/lib/platform/status';
import { formatDateTime } from '@/lib/platform/format';
import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';
import type { Approval } from '@/lib/platform/types';

const STATUS_LABELS: Record<Approval['status'], string> = {
  pending: '待处理',
  approved: '已批准',
  rejected: '已拒绝',
  responded: '已回复',
  expired: '已过期',
  escalated: '已升级'
};

type ApprovalAction = 'approve' | 'reject' | 'respond' | 'escalate';

const ACTION_META: Record<ApprovalAction, { title: string; submitLabel: string; toast: string }> = {
  approve: { title: '批准审批', submitLabel: '确认批准', toast: '审批已批准' },
  reject: { title: '拒绝审批', submitLabel: '确认拒绝', toast: '审批已拒绝' },
  respond: { title: '回复澄清', submitLabel: '提交回复', toast: '澄清已回复' },
  escalate: { title: '升级处理', submitLabel: '确认升级', toast: '已升级给值班负责人' }
};

/** Approvals 列表（PRD 21.1）：审批 / 澄清双类型 + Approve / Reject / Respond / Escalate。 */
export function ApprovalsTable({ approvals }: { approvals: Approval[] }) {
  const [dialogState, setDialogState] = useState<{ approval: Approval; action: ApprovalAction } | null>(null);
  // 挂载时固定一次当前时间，避免渲染期调用 Date.now() 造成不确定渲染
  const [nowMs] = useState(() => Date.now());

  if (approvals.length === 0) {
    return (
      <EmptyState
        icon='approval'
        title='暂无审批与澄清'
        description='高风险工具调用与需要用户输入的澄清会进入此队列'
      />
    );
  }

  return (
    <div className='flex flex-col gap-3'>
      <div className='overflow-hidden rounded-lg border'>
        <Table>
          <TableHeader className='bg-muted'>
            <TableRow>
              <TableHead>Type</TableHead>
              <TableHead>Task</TableHead>
              <TableHead>Host / Namespace</TableHead>
              <TableHead>Reason / Question</TableHead>
              <TableHead>Risk</TableHead>
              <TableHead>Requested By</TableHead>
              <TableHead>Requested At</TableHead>
              <TableHead>Deadline</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className='text-right'>操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {approvals.map((approval) => {
              const deadlineSoon =
                approval.status === 'pending' &&
                new Date(approval.deadline).getTime() - nowMs < 24 * 60 * 60 * 1000;
              return (
                <TableRow key={approval.id}>
                  <TableCell>
                    <Badge variant={approval.type === 'approval' ? 'default' : 'secondary'}>
                      {approval.type === 'approval' ? 'Approval' : 'Clarification'}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Link href={`/runtime/tasks/${approval.taskId}`} className='text-primary hover:underline'>
                      <MonoId value={approval.taskId} copyable={false} />
                    </Link>
                  </TableCell>
                  <TableCell>
                    <span className='text-sm'>{approval.hostAppId}</span>
                    <div className='text-muted-foreground font-mono text-xs'>{approval.namespace}</div>
                  </TableCell>
                  <TableCell className='max-w-[280px] text-sm'>
                    <p className='truncate'>{approval.reason}</p>
                    {approval.question && (
                      <p className='text-muted-foreground truncate text-xs'>{approval.question}</p>
                    )}
                  </TableCell>
                  <TableCell>
                    {approval.risk ? <RiskBadge risk={approval.risk} /> : <span className='text-muted-foreground text-xs'>—</span>}
                  </TableCell>
                  <TableCell className='font-mono text-xs'>{approval.requestedBy}</TableCell>
                  <TableCell className='text-sm whitespace-nowrap'>{formatDateTime(approval.requestedAt)}</TableCell>
                  <TableCell className={cn('text-sm whitespace-nowrap', deadlineSoon && 'font-medium text-amber-600 dark:text-amber-400')}>
                    {formatDateTime(approval.deadline)}
                    {deadlineSoon && (
                      <span className='ml-1.5 inline-flex items-center gap-1 text-xs'>
                        <Icons.warning className='size-3.5' />
                        即将到期
                      </span>
                    )}
                  </TableCell>
                  <TableCell>
                    <StatusBadge tone={lifecycleTone(approval.status)}>{STATUS_LABELS[approval.status]}</StatusBadge>
                  </TableCell>
                  <TableCell className='text-right'>
                    {approval.status === 'pending' ? (
                      <span className='inline-flex flex-wrap items-center justify-end gap-1.5'>
                        {approval.type === 'approval' ? (
                          <>
                            <Button variant='outline' size='sm' onClick={() => setDialogState({ approval, action: 'approve' })}>
                              Approve
                            </Button>
                            <Button variant='destructive' size='sm' onClick={() => setDialogState({ approval, action: 'reject' })}>
                              Reject
                            </Button>
                          </>
                        ) : (
                          <Button variant='outline' size='sm' onClick={() => setDialogState({ approval, action: 'respond' })}>
                            Respond
                          </Button>
                        )}
                        <Button variant='ghost' size='sm' onClick={() => setDialogState({ approval, action: 'escalate' })}>
                          Escalate
                        </Button>
                      </span>
                    ) : (
                      <span className='text-muted-foreground text-xs'>已处理</span>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
      <ApprovalActionDialog state={dialogState} onClose={() => setDialogState(null)} />
    </div>
  );
}

function ApprovalActionDialog({
  state,
  onClose
}: {
  state: { approval: Approval; action: ApprovalAction } | null;
  onClose: () => void;
}) {
  const [reason, setReason] = useState('');

  if (!state) return null;
  const { approval, action } = state;
  const meta = ACTION_META[action];

  const submit = () => {
    toast.success(`${meta.toast}（演示）`, {
      description: `${approval.id} · 原因：${reason.trim() || '（未填写）'}`
    });
    setReason('');
    onClose();
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle>{meta.title}</DialogTitle>
          <DialogDescription>
            {approval.type === 'approval' ? approval.reason : approval.question ?? approval.reason}
            {approval.tool ? `（工具：${approval.tool}）` : ''}
          </DialogDescription>
        </DialogHeader>
        <div className='space-y-1.5'>
          <Label htmlFor='approval-reason'>
            处理说明<span className='text-destructive'>（必填）</span>
          </Label>
          <Textarea
            id='approval-reason'
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder={
              action === 'respond'
                ? '输入给 Agent 的澄清答复…'
                : '输入批准 / 拒绝 / 升级的理由，将写入 Audit Log…'
            }
            rows={3}
          />
        </div>
        <DialogFooter>
          <Button variant='outline' onClick={onClose}>
            取消
          </Button>
          <Button
            variant={action === 'reject' ? 'destructive' : 'default'}
            disabled={reason.trim().length < 4}
            onClick={submit}
          >
            {meta.submitLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

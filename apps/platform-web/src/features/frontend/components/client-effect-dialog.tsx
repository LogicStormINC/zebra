'use client';

import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { DataList } from '@/components/platform/data-list';
import { MonoId } from '@/components/platform/mono-id';
import { StatusBadge } from '@/components/platform/status-badge';
import { formatDateTime } from '@/lib/platform/format';
import { lifecycleTone } from '@/lib/platform/status';
import type { ClientEffect } from '@/lib/platform/types';
import { CLIENT_EFFECT_STATUS_LABELS } from './labels';
import { cn } from '@/lib/utils';

const ERROR_CODES: Partial<Record<ClientEffect['status'], string>> = {
  failed: 'E_HANDLER_FAILED',
  declined: 'E_CLIENT_DECLINED',
  unavailable: 'E_CLIENT_UNAVAILABLE',
  stale_ui_state: 'E_STALE_UI_REVISION',
  expired: 'E_FENCE_EXPIRED',
  uncertain: 'E_UNCERTAIN_RECEIPT',
  cancelled: 'E_CANCELLED'
};

/** 事件时间线：静态三步 dispatched → delivered → receipt（PRD 20.3 演示基线）。 */
function Timeline({ effect }: { effect: ClientEffect }) {
  const reachedDelivery = effect.status !== 'pending';
  const reachedReceipt = Boolean(effect.receiptDigest);
  const steps = [
    { key: 'dispatched', label: 'dispatched', at: formatDateTime(effect.createdAt), done: true },
    {
      key: 'delivered',
      label: 'delivered',
      at: reachedDelivery ? '已投递至客户端' : '等待投递',
      done: reachedDelivery
    },
    {
      key: 'receipt',
      label: 'receipt',
      at: reachedReceipt ? `Receipt ${effect.receiptDigest}` : '未收到 Receipt',
      done: reachedReceipt
    }
  ];

  return (
    <ol className='space-y-2'>
      {steps.map((step, index) => (
        <li key={step.key} className='flex items-start gap-3'>
          <div className='flex flex-col items-center'>
            <span
              className={cn(
                'mt-1 size-2.5 rounded-full border-2',
                step.done
                  ? 'border-emerald-500 bg-emerald-500'
                  : 'border-muted-foreground/40 bg-transparent'
              )}
            />
            {index < steps.length - 1 && <span className='bg-border w-px flex-1' style={{ minHeight: 16 }} />}
          </div>
          <div>
            <p className={cn('font-mono text-xs font-medium', step.done ? '' : 'text-muted-foreground')}>
              {step.label}
            </p>
            <p className='text-muted-foreground text-xs'>{step.at}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}

/**
 * Client Effect 详情 Dialog（PRD 20.3）。
 * 安全约束：只显示 Fence Hash 摘要，平台不显示原始 Fence Token。
 */
export function ClientEffectDialog({
  effect,
  open,
  onOpenChange,
  bindingSnapshotDigest,
  profileDigest
}: {
  effect: ClientEffect | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  bindingSnapshotDigest?: string;
  profileDigest?: string;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-h-[85vh] max-w-2xl overflow-y-auto'>
        {effect && (
          <>
            <DialogHeader>
              <DialogTitle className='flex items-center gap-2'>
                Client Effect <MonoId value={effect.id} />
              </DialogTitle>
              <DialogDescription>
                {effect.hostAppId} / {effect.frontendAppId} · action{' '}
                <span className='font-mono'>{effect.action}</span>
              </DialogDescription>
            </DialogHeader>

            <section className='space-y-3'>
              <h3 className='text-sm font-semibold'>契约与凭证摘要</h3>
              <DataList
                columns={2}
                items={[
                  {
                    label: 'Action Contract Digest',
                    value: profileDigest ? (
                      <MonoId value={profileDigest} head={16} tail={4} copyable={false} />
                    ) : (
                      '—'
                    )
                  },
                  {
                    label: 'Arguments Digest',
                    value: <MonoId value={`args_${effect.id}`} head={12} tail={0} copyable={false} />
                  },
                  {
                    label: 'Client Binding Digest',
                    value: bindingSnapshotDigest ? (
                      <MonoId value={bindingSnapshotDigest} head={12} tail={0} copyable={false} />
                    ) : (
                      '—'
                    )
                  },
                  {
                    label: 'Fence Hash（摘要）',
                    value: (
                      <span className='flex items-center gap-2'>
                        <MonoId value={effect.fenceHash} head={12} tail={0} copyable={false} />
                        <span className='text-muted-foreground text-xs'>仅摘要</span>
                      </span>
                    )
                  },
                  {
                    label: 'Expected UI Revision',
                    value: `rev ${effect.expectedRevision}`
                  },
                  {
                    label: 'Idempotency Key（摘要）',
                    value: (
                      <MonoId
                        value={`idem_${effect.taskId}_${effect.id}`}
                        head={14}
                        tail={0}
                        copyable={false}
                      />
                    )
                  }
                ]}
              />
              <Alert>
                <span className='text-xs'>安全说明：平台不显示原始 Fence Token，页面只展示 Fence
                Hash 摘要；Fence 一次一效，重放会被拒绝。</span>
              </Alert>
            </section>

            <section className='space-y-3'>
              <h3 className='text-sm font-semibold'>执行结果</h3>
              <DataList
                columns={2}
                items={[
                  {
                    label: 'Receipt',
                    value: effect.receiptDigest ?? '未收到'
                  },
                  {
                    label: 'Result Digest',
                    value:
                      effect.status === 'succeeded' ? (
                        <MonoId
                          value={`res_${effect.id}`}
                          head={12}
                          tail={0}
                          copyable={false}
                        />
                      ) : (
                        '—'
                      )
                  },
                  { label: 'Handler Version', value: 'hook@v1' },
                  { label: 'Error Code', value: ERROR_CODES[effect.status] ?? '—' },
                  {
                    label: 'Status',
                    value: (
                      <StatusBadge tone={lifecycleTone(effect.status)}>
                        {CLIENT_EFFECT_STATUS_LABELS[effect.status]}
                      </StatusBadge>
                    )
                  },
                  { label: 'Expires At', value: formatDateTime(effect.expiresAt) }
                ]}
              />
            </section>

            <section className='space-y-3'>
              <h3 className='text-sm font-semibold'>事件时间线</h3>
              <Timeline effect={effect} />
            </section>

            <AlertDescription className='text-muted-foreground'>
              Task{' '}
              <span className='font-mono text-xs'>{effect.taskId}</span> · Run{' '}
              <span className='font-mono text-xs'>{effect.runId}</span> · Client Session{' '}
              <span className='font-mono text-xs'>{effect.clientSessionId}</span>
            </AlertDescription>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

'use client';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { JsonBlock } from '@/components/platform/json-block';
import { RiskConfirmDialog } from '@/components/platform/risk-confirm-dialog';
import { Icons } from '@/components/icons';
import type { HostEffect } from '@/lib/platform/types';

/** Uncertain Host Effect 的行操作（PRD 18.10）：查看证据 / 执行 Reconcile / 标记已解决 / 升级人工。 */
export function HostEffectRowActions({
  effect,
  showEscalate = false
}: {
  effect: HostEffect;
  showEscalate?: boolean;
}) {
  return (
    <span className='inline-flex items-center gap-1'>
      <Dialog>
        <DialogTrigger render={<Button variant='outline' size='sm' />}>查看证据</DialogTrigger>
        <DialogContent className='sm:max-w-lg'>
          <DialogHeader>
            <DialogTitle className='font-mono text-sm'>{effect.dispatchId}</DialogTitle>
            <DialogDescription>
              {effect.tool} · attempt {effect.attempt} · {effect.evidence}
            </DialogDescription>
          </DialogHeader>
          <JsonBlock
            title={`${effect.dispatchId}-evidence.json`}
            value={{
              dispatchId: effect.dispatchId,
              taskId: effect.taskId,
              tool: effect.tool,
              operationId: effect.operationId,
              status: effect.status,
              idempotencyKey: effect.idempotencyKey,
              claimOwner: effect.claimOwner,
              attempt: effect.attempt,
              evidence: effect.evidence,
              reconciliation: effect.reconciliation,
              hostAppId: effect.hostAppId,
              createdAt: effect.createdAt
            }}
          />
        </DialogContent>
      </Dialog>

      <Button
        variant='outline'
        size='sm'
        onClick={() =>
          toast.info('Reconcile 已触发（演示）', {
            description: `将通过 ${effect.hostAppId} 的 reconcile 端点核对 operation ${effect.operationId} 的实际结果`
          })
        }
      >
        <Icons.reconciliation className='size-4' />
        执行 Reconcile
      </Button>

      <RiskConfirmDialog
        trigger={<Button variant='outline' size='sm'>标记已解决</Button>}
        title={`标记 ${effect.dispatchId} 已解决`}
        impact='该 Host Effect 将从 uncertain 对账队列移除，Task 恢复推进'
        irreversibility='标记后如 Host 侧实际未写入，需要人工补正'
        currentRevision={`reconciliation ${effect.reconciliation}`}
        actionLabel='标记已解决'
        onConfirm={() => {
          // 演示操作
        }}
      />

      {showEscalate && (
        <Button
          variant='destructive'
          size='sm'
          onClick={() =>
            toast.warning('已升级人工处理（演示）', {
              description: `将在值班队列创建人工处理单：${effect.dispatchId}`
            })
          }
        >
          升级人工
        </Button>
      )}
    </span>
  );
}

'use client';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { DataList } from '@/components/platform/data-list';
import { JsonBlock } from '@/components/platform/json-block';
import { MonoId } from '@/components/platform/mono-id';
import { RiskConfirmDialog } from '@/components/platform/risk-confirm-dialog';
import { formatDateTime } from '@/lib/platform/format';
import { Icons } from '@/components/icons';
import type { ClientEffect, ClientSession, FrontendProfile } from '@/lib/platform/types';

const EXECUTION_MODE_LABELS: Record<string, string> = {
  fire_and_receipt: '发送并等 Receipt',
  receipt_required: '必须回执',
  human_confirmed: '需用户确认'
};

/**
 * Client Effects 行操作（PRD 18.11c）：
 * 查看 Contract / 查看 Receipt / 查看 AG-UI Event / 释放 Controller / 取消过期 Effect。
 */
export function ClientEffectRowActions({
  effect,
  clientSessions,
  frontendProfile
}: {
  effect: ClientEffect;
  clientSessions: ClientSession[];
  frontendProfile?: FrontendProfile;
}) {
  const contract = frontendProfile?.actions.find((action) => action.name === effect.action);
  const session = clientSessions.find((item) => item.id === effect.clientSessionId);
  const isController = session?.role === 'controller';
  const canCancel = effect.status === 'pending' || effect.status === 'expired';

  return (
    <span className='inline-flex items-center gap-1 whitespace-nowrap'>
      <ContractDialog effect={effect} contract={contract} />
      <ReceiptDialog effect={effect} />
      <AgUiEventDialog effect={effect} />

      <RiskConfirmDialog
        trigger={
          <Button
            variant='outline'
            size='sm'
            disabled={!isController}
            title={isController ? undefined : '仅持有 Controller 角色的 Client Session 可释放'}
          >
            释放 Controller
          </Button>
        }
        title={`释放 Controller 会话 ${effect.clientSessionId}`}
        impact='该 Client Session 的 Controller 角色将被释放，前端降级为 Observer；后续 client effect 需等待新的 Controller 会话挂载后才能派发'
        irreversibility='本次 Run 内该会话无法重新获得 Controller，需要用户重新进入页面重新挂载'
        currentRevision={`uiRevision ${effect.expectedRevision}`}
        actionLabel='确认释放 Controller'
        onConfirm={() => {
          // 演示操作
        }}
      />

      <RiskConfirmDialog
        trigger={
          <Button
            variant='outline'
            size='sm'
            disabled={!canCancel}
            title={canCancel ? undefined : '仅 pending / expired 状态的 Effect 可取消'}
          >
            取消过期 Effect
          </Button>
        }
        title={`取消 Client Effect ${effect.id}`}
        impact='该 client effect 将被平台标记为 cancelled，前端不再执行、平台不再等待其 Receipt'
        irreversibility='取消后若前端实际已执行，需通过 Receipt 对账流程补偿'
        currentRevision={`status ${effect.status} · uiRevision ${effect.expectedRevision}`}
        actionLabel='确认取消 Effect'
        onConfirm={() => {
          // 演示操作
        }}
      />
    </span>
  );
}

/** 查看 Contract：优先展示该 task Frontend Profile 中此 action 的 ActionContract。 */
function ContractDialog({
  effect,
  contract
}: {
  effect: ClientEffect;
  contract?: FrontendProfile['actions'][number];
}) {
  return (
    <Dialog>
      <DialogTrigger render={<Button variant='outline' size='sm' />}>查看 Contract</DialogTrigger>
      <DialogContent className='sm:max-w-lg'>
        <DialogHeader>
          <DialogTitle className='font-mono text-sm'>{effect.action}</DialogTitle>
          <DialogDescription>
            effect <span className='font-mono'>{effect.id}</span> 的 ActionContract
          </DialogDescription>
        </DialogHeader>
        {contract ? (
          <DataList
            columns={2}
            items={[
              { label: 'Name', value: <span className='font-mono text-xs'>{contract.name}</span> },
              { label: 'Capability', value: contract.capability },
              { label: 'Risk', value: contract.risk },
              {
                label: 'Execution Mode',
                value: EXECUTION_MODE_LABELS[contract.executionMode] ?? contract.executionMode
              },
              { label: 'Timeout', value: `${contract.timeoutMs}ms` },
              { label: 'Requires Controller', value: contract.requiresController ? '是' : '否' },
              {
                label: 'Requires User Confirmation',
                value: contract.requiresUserConfirmation ? '是' : '否'
              },
              { label: 'Description', value: contract.description }
            ]}
          />
        ) : (
          <div className='text-muted-foreground space-y-2 text-sm'>
            <p className='flex items-start gap-2'>
              <Icons.warning className='mt-0.5 size-4 shrink-0' />
              未在该 Task 绑定的 Frontend Profile 中找到 <span className='font-mono'>{effect.action}</span>{' '}
              的 ActionContract（Profile 可能已迭代，或该 action 来自旧 build）。
            </p>
            <DataList
              columns={2}
              items={[
                { label: 'Action', value: <span className='font-mono text-xs'>{effect.action}</span> },
                { label: 'Frontend App', value: effect.frontendAppId },
                { label: 'Client Session', value: <span className='font-mono text-xs'>{effect.clientSessionId}</span> },
                { label: 'Expected UI Revision', value: `rev ${effect.expectedRevision}` }
              ]}
            />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** 查看 Receipt：receiptDigest + dispatched→delivered→receipt 三步时间线（静态）。 */
function ReceiptDialog({ effect }: { effect: ClientEffect }) {
  const deliveredAt = effect.status === 'pending' ? null : effect.createdAt;
  const receiptAt = effect.receiptDigest ? effect.createdAt : null;

  return (
    <Dialog>
      <DialogTrigger render={<Button variant='outline' size='sm' />}>查看 Receipt</DialogTrigger>
      <DialogContent className='sm:max-w-lg'>
        <DialogHeader>
          <DialogTitle className='font-mono text-sm'>{effect.id}</DialogTitle>
          <DialogDescription>Receipt 摘要与三步时间线（dispatched → delivered → receipt）</DialogDescription>
        </DialogHeader>
        <div className='space-y-3'>
          <div className='flex items-center justify-between gap-2 rounded-lg border p-2.5'>
            <span className='text-muted-foreground text-sm'>Receipt Digest</span>
            {effect.receiptDigest ? (
              <MonoId value={effect.receiptDigest} />
            ) : (
              <span className='text-muted-foreground text-xs'>尚未回执</span>
            )}
          </div>
          <ol className='space-y-0'>
            <TimelineStep
              label='Dispatched（平台派发）'
              detail={`派发至 ${effect.clientSessionId} · expected rev ${effect.expectedRevision}`}
              time={formatDateTime(effect.createdAt)}
              state='done'
            />
            <TimelineStep
              label='Delivered（前端送达）'
              detail={
                deliveredAt
                  ? 'Controller 会话已接收该 effect'
                  : '待送达（effect 仍在 pending）'
              }
              time={deliveredAt ? formatDateTime(deliveredAt) : undefined}
              state={deliveredAt ? 'done' : 'waiting'}
            />
            <TimelineStep
              label='Receipt（结果回执）'
              detail={
                receiptAt
                  ? `已回执 ${effect.receiptDigest}`
                  : `状态 ${effect.status}，无 receiptDigest`
              }
              time={receiptAt ? formatDateTime(receiptAt) : undefined}
              state={receiptAt ? 'done' : 'waiting'}
            />
          </ol>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function TimelineStep({
  label,
  detail,
  time,
  state
}: {
  label: string;
  detail: string;
  time?: string;
  state: 'done' | 'waiting';
}) {
  return (
    <li className='relative flex gap-3 pb-4 last:pb-0 last:[&>.step-line]:hidden'>
      <span className='step-line bg-muted absolute top-6 left-[7px] h-full w-px' aria-hidden />
      <span className='mt-0.5 shrink-0'>
        {state === 'done' ? (
          <Icons.circleCheck className='size-4' />
        ) : (
          <Icons.clock className='text-muted-foreground size-4' />
        )}
      </span>
      <div className='min-w-0 flex-1 space-y-0.5'>
        <p className='text-sm font-medium'>
          {label}
          {time && <span className='text-muted-foreground ml-2 text-xs'>{time}</span>}
        </p>
        <p className='text-muted-foreground text-xs'>{detail}</p>
      </div>
    </li>
  );
}

/** 查看 AG-UI Event：JsonBlock 展示由该 effect 合成的 AG-UI 协议事件（演示）。 */
function AgUiEventDialog({ effect }: { effect: ClientEffect }) {
  const agUiEvent = {
    type: 'CUSTOM',
    name: 'zebra.client_effect',
    eventId: `agui_${effect.id}`,
    timestamp: effect.createdAt,
    taskId: effect.taskId,
    runId: effect.runId,
    clientSessionId: effect.clientSessionId,
    payload: {
      effectId: effect.id,
      action: effect.action,
      expectedRevision: effect.expectedRevision,
      fenceHash: effect.fenceHash,
      expiresAt: effect.expiresAt
    }
  };

  return (
    <Dialog>
      <DialogTrigger render={<Button variant='outline' size='sm' />}>AG-UI Event</DialogTrigger>
      <DialogContent className='sm:max-w-xl'>
        <DialogHeader>
          <DialogTitle>AG-UI Event（合成）</DialogTitle>
          <DialogDescription>
            平台向 Controller 会话下发该 effect 时对应的 AG-UI 协议事件，仅用于排查演示
          </DialogDescription>
        </DialogHeader>
        <JsonBlock title={`agui_${effect.id}.json`} value={agUiEvent} maxHeight={320} />
      </DialogContent>
    </Dialog>
  );
}

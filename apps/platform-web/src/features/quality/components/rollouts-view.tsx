'use client';

import { useState } from 'react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardHeader
} from '@/components/ui/card';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger
} from '@/components/ui/collapsible';
import { StatusBadge } from '@/components/platform/status-badge';
import { EmptyState } from '@/components/platform/empty-state';
import { RiskConfirmDialog } from '@/components/platform/risk-confirm-dialog';
import { Icons } from '@/components/icons';
import { formatDateTime } from '@/lib/platform/format';
import { lifecycleTone } from '@/lib/platform/status';
import type { Rollout } from '@/lib/platform/types';

const TARGET_LABELS: Record<Rollout['target'], string> = {
  'connector-binding': 'Connector Binding',
  'backend-manifest': 'Backend Manifest',
  'frontend-profile': 'Frontend Profile',
  'agent-release': 'Agent Release',
  policy: 'Policy'
};

const STRATEGY_TONES: Record<Rollout['strategy'], 'draft' | 'waiting' | 'running' | 'success' | 'failure'> = {
  'dry-run': 'draft',
  'canary-5': 'waiting',
  'canary-25': 'waiting',
  'canary-50': 'running',
  production: 'success',
  rollback: 'failure'
};

const ROLLOUT_STATUS_LABELS: Record<Rollout['status'], string> = {
  planning: '规划中',
  'in-progress': '进行中',
  blocked: '被阻断',
  completed: '已完成',
  'rolled-back': '已回滚'
};

const GATE_STATUS_LABELS: Record<Rollout['gates'][number]['status'], string> = {
  passed: '通过',
  failed: '失败',
  pending: '待评估',
  not_required: '不适用'
};

const GATE_STATUS_TONES: Record<
  Rollout['gates'][number]['status'],
  'success' | 'failure' | 'waiting' | 'draft'
> = {
  passed: 'success',
  failed: 'failure',
  pending: 'waiting',
  not_required: 'draft'
};

/** Rollout 列表（PRD 24）：策略、Gates 与回滚 / 推进操作。 */
export function RolloutsView({ rollouts }: { rollouts: Rollout[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (rollouts.length === 0) {
    return (
      <EmptyState
        title='暂无 Rollout'
        description='发布对象的新版本会通过 Rollout 流程灰度推进'
        icon='rollout'
      />
    );
  }

  return (
    <div className='flex flex-col gap-4'>
      <div className='flex flex-wrap items-center gap-1.5 text-sm'>
        <span className='text-muted-foreground'>发布对象：</span>
        {Object.values(TARGET_LABELS).map((label) => (
          <Badge key={label} variant='secondary'>
            {label}
          </Badge>
        ))}
      </div>

      {rollouts.map((rollout) => {
        const passedGates = rollout.gates.filter((gate) => gate.status === 'passed').length;
        const allPassed = rollout.gates.length > 0 && passedGates === rollout.gates.length;
        const isOpen = expanded === rollout.id;

        return (
          <Card key={rollout.id} className='py-0'>
            <CardHeader className='gap-2 border-b px-4 py-3'>
              <div className='flex flex-wrap items-center justify-between gap-2'>
                <div className='flex flex-wrap items-center gap-2'>
                  <span className='font-mono text-sm font-medium'>{rollout.id}</span>
                  <Badge variant='outline'>{TARGET_LABELS[rollout.target]}</Badge>
                  <span className='font-mono text-xs'>{rollout.targetId}</span>
                </div>
                <StatusBadge tone={lifecycleTone(rollout.status)}>
                  {ROLLOUT_STATUS_LABELS[rollout.status]}
                </StatusBadge>
              </div>
              <div className='text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-xs'>
                <span>
                  版本：rev {rollout.fromRevision} → rev {rollout.toRevision}
                </span>
                <StatusBadge tone={STRATEGY_TONES[rollout.strategy]} withDot={false}>
                  {rollout.strategy}
                </StatusBadge>
                <span>Updated {formatDateTime(rollout.updatedAt)}</span>
              </div>
            </CardHeader>
            <CardContent className='space-y-3 px-4 py-3'>
              <Collapsible open={isOpen} onOpenChange={(open) => setExpanded(open ? rollout.id : null)}>
                <div className='flex flex-wrap items-center gap-2'>
                  <CollapsibleTrigger
                    render={<Button size='xs' variant='outline' />}
                    className='gap-1.5'
                  >
                    Gates 通过 {passedGates}/{rollout.gates.length}
                    <Icons.chevronDown
                      className={isOpen ? 'size-3 rotate-180 transition-transform' : 'size-3 transition-transform'}
                    />
                  </CollapsibleTrigger>
                  {rollout.status !== 'rolled-back' && rollout.status !== 'completed' && (
                    <RiskConfirmDialog
                      trigger={
                        <Button size='xs' variant='destructive'>
                          Rollback
                        </Button>
                      }
                      title={`回滚 ${TARGET_LABELS[rollout.target]} ${rollout.targetId}`}
                      impact={`目标版本：rev ${rollout.fromRevision}（${rollout.targetId}）。影响 namespace：${rollout.target} 绑定的所有 namespace。运行中 Task：继续使用回滚前固定快照直至结束。`}
                      irreversibility='回滚会创建新的 rev 指向旧版本；新 Task 立即使用回滚后版本，旧 Task 不会被打断。'
                      currentRevision={`rev ${rollout.toRevision}`}
                      targetRevision={`rev ${rollout.fromRevision}`}
                      actionLabel='确认回滚'
                      onConfirm={(reason) =>
                        toast.success('回滚已执行', {
                          description: `${rollout.id} → rev ${rollout.fromRevision} · ${reason || '（未填写）'}`
                        })
                      }
                    />
                  )}
                  <Button
                    size='xs'
                    variant='outline'
                    disabled={!allPassed || rollout.status === 'completed' || rollout.status === 'rolled-back'}
                    onClick={() =>
                      toast.success('Canary 继续推进已排队', {
                        description: `${rollout.id} 全部 Gates 通过，推进到下一档流量（演示）`
                      })
                    }
                  >
                    继续推进 Canary
                  </Button>
                  {!allPassed && (
                    <span className='text-muted-foreground text-xs'>
                      Gates 全部通过后才可继续推进（当前 {passedGates}/{rollout.gates.length}）
                    </span>
                  )}
                </div>
                <CollapsibleContent>
                  <ul className='mt-3 space-y-1.5 rounded-lg border p-3'>
                    {rollout.gates.map((gate) => (
                      <li key={gate.name} className='flex items-center justify-between gap-2 text-sm'>
                        <span className='font-mono text-xs'>{gate.name}</span>
                        <StatusBadge tone={GATE_STATUS_TONES[gate.status]} withDot={false}>
                          {GATE_STATUS_LABELS[gate.status]}
                        </StatusBadge>
                      </li>
                    ))}
                  </ul>
                </CollapsibleContent>
              </Collapsible>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

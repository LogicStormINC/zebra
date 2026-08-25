'use client';

import Link from 'next/link';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from '@/components/ui/card';
import { EmptyState } from '@/components/platform/empty-state';
import { StatusBadge } from '@/components/platform/status-badge';
import { Icons } from '@/components/icons';
import { formatDateTime } from '@/lib/platform/format';
import type { AgentRelease, ReleaseGate } from '@/lib/platform/types';

const GATE_STATUS_LABELS: Record<ReleaseGate['status'], string> = {
  passed: '通过',
  failed: '失败',
  pending: '待评估',
  not_required: '不适用'
};

const GATE_STATUS_TONES: Record<ReleaseGate['status'], 'success' | 'failure' | 'waiting' | 'draft'> = {
  passed: 'success',
  failed: 'failure',
  pending: 'waiting',
  not_required: 'draft'
};

/** Release Gate 按 Release 分组卡片：全部通过才满足 Promote 条件。 */
export function ReleaseGatesView({
  gates,
  releases
}: {
  gates: ReleaseGate[];
  releases: AgentRelease[];
}) {
  const groups = gates.reduce<{ releaseId: string; gates: ReleaseGate[] }[]>((acc, gate) => {
    const existing = acc.find((item) => item.releaseId === gate.releaseId);
    if (existing) {
      existing.gates.push(gate);
    } else {
      acc.push({ releaseId: gate.releaseId, gates: [gate] });
    }
    return acc;
  }, []);

  if (groups.length === 0) {
    return (
      <EmptyState
        title='暂无 Release Gate'
        description='发布进入 Rollout 流程后会生成对应的 Gate 评估'
        icon='gate'
      />
    );
  }

  return (
    <div className='grid grid-cols-1 gap-4 xl:grid-cols-2'>
      {groups.map((group) => {
        const release = releases.find((item) => item.id === group.releaseId);
        const effective = group.gates.filter((gate) => gate.status !== 'not_required');
        const allPassed = effective.length > 0 && effective.every((gate) => gate.status === 'passed');
        const hasFailed = effective.some((gate) => gate.status === 'failed');
        const hasPending = !hasFailed && effective.some((gate) => gate.status === 'pending');

        return (
          <Card key={group.releaseId} className='py-0'>
            <CardHeader className='gap-1.5 border-b px-4 py-3'>
              <div className='flex items-center justify-between gap-2'>
                <CardTitle className='text-sm'>
                  {release ? `${release.definitionName} v${release.version}` : group.releaseId}
                </CardTitle>
                <Link href='/agents/releases' className='text-primary hover:underline text-xs'>
                  {group.releaseId} →
                </Link>
              </div>
              <CardDescription>
                {release ? `${release.channel} channel · released by ${release.releasedBy}` : 'Agent Release'}
              </CardDescription>
            </CardHeader>
            <CardContent className='space-y-3 px-4 py-3'>
              <ul className='divide-y rounded-lg border'>
                {group.gates.map((gate) => (
                  <li key={gate.id} className='flex items-start justify-between gap-3 px-3 py-2.5'>
                    <div className='min-w-0'>
                      <p className='font-mono text-xs font-medium'>{gate.gate}</p>
                      <p className='text-muted-foreground mt-0.5 text-xs'>{gate.requirement}</p>
                      <p className='text-muted-foreground mt-0.5 text-[10px]'>
                        evaluated {formatDateTime(gate.evaluatedAt)}
                      </p>
                    </div>
                    <StatusBadge tone={GATE_STATUS_TONES[gate.status]} className='shrink-0'>
                      {GATE_STATUS_LABELS[gate.status]}
                    </StatusBadge>
                  </li>
                ))}
              </ul>

              {allPassed ? (
                <Alert className='border-emerald-500/40 bg-emerald-500/10'>
                  <Icons.badgeCheck className='text-emerald-600' />
                  <AlertTitle className='text-emerald-700 dark:text-emerald-400'>
                    满足 Promote 条件
                  </AlertTitle>
                  <AlertDescription className='text-emerald-700/80 dark:text-emerald-400/80'>
                    全部 Gate 通过：该 Release 可以 Promote 到下一通道（stable / production）。
                  </AlertDescription>
                </Alert>
              ) : hasFailed ? (
                <Alert variant='destructive'>
                  <Icons.circleX />
                  <AlertTitle>存在未通过的 Gate</AlertTitle>
                  <AlertDescription>
                    Promote 被阻断：需修复失败项并重新评估后才能推进。
                  </AlertDescription>
                </Alert>
              ) : hasPending ? (
                <Alert className='border-amber-500/40 bg-amber-500/10'>
                  <Icons.clock className='text-amber-600' />
                  <AlertTitle className='text-amber-700 dark:text-amber-400'>
                    等待 Gate 评估完成
                  </AlertTitle>
                  <AlertDescription className='text-amber-700/80 dark:text-amber-400/80'>
                    部分Gate仍在评估（如 Canary 24h 指标），全部通过前不可 Promote。
                  </AlertDescription>
                </Alert>
              ) : (
                <Alert>
                  <Icons.info />
                  <AlertTitle>暂无生效 Gate</AlertTitle>
                  <AlertDescription>该 Release 当前只有不适用（not_required）的 Gate。</AlertDescription>
                </Alert>
              )}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

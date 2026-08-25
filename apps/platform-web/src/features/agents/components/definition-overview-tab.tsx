'use client';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { DataList } from '@/components/platform/data-list';
import { StatusBadge } from '@/components/platform/status-badge';
import { lifecycleTone } from '@/lib/platform/status';
import { formatDateTime, relativeTime } from '@/lib/platform/format';
import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';
import type { AgentRelease } from '@/lib/platform/types';
import {
  PUBLISH_FLOW_STEPS,
  publishFlowCurrentIndex,
  type DefinitionDetailData
} from './definition-detail-data';

const LIFECYCLE_LABELS: Record<string, string> = {
  draft: '草稿',
  published: '已发布',
  deprecated: '已废弃',
  revoked: '已撤销'
};

/** Definition 详情 Overview Tab（PRD 14.2）：基本信息 + 发布流程可视化 + Capability Ceiling。 */
export function DefinitionOverviewTab({ data }: { data: DefinitionDetailData }) {
  const { definition, publishedRelease } = data;
  const currentIndex = publishFlowCurrentIndex(data);

  return (
    <div className='flex flex-col gap-4'>
      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='text-sm'>基本信息</CardTitle>
        </CardHeader>
        <CardContent className='p-4'>
          <DataList
            columns={2}
            items={[
              { label: 'Name', value: definition.name },
              { label: 'Definition ID', value: definition.id },
              { label: '描述', value: definition.description },
              { label: 'Status', value: <StatusBadge tone={lifecycleTone(definition.status)}>{LIFECYCLE_LABELS[definition.status] ?? definition.status}</StatusBadge> },
              { label: 'Latest Draft Revision', value: `rev ${definition.latestDraftRevision}` },
              { label: 'Latest Version', value: definition.latestVersion > 0 ? `v${definition.latestVersion}` : '尚未物化版本' },
              { label: 'Updated At', value: `${formatDateTime(definition.updatedAt)}（${relativeTime(definition.updatedAt)}）` }
            ]}
          />
        </CardContent>
      </Card>

      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='text-sm'>发布流程</CardTitle>
        </CardHeader>
        <CardContent className='p-4'>
          <ol className='flex flex-wrap items-center gap-y-4'>
            {PUBLISH_FLOW_STEPS.map((step, index) => {
              const isDone = index < currentIndex;
              const isCurrent = index === currentIndex;
              return (
                <li key={step} className='flex items-center'>
                  <div
                    className={cn(
                      'flex w-40 flex-col items-center gap-1.5 rounded-lg border px-2 py-2.5 text-center',
                      isCurrent && 'border-sky-500/50 bg-sky-500/10',
                      isDone && 'border-emerald-500/40 bg-emerald-500/5',
                      !isDone && !isCurrent && 'border-muted bg-muted/30'
                    )}
                  >
                    <span
                      className={cn(
                        'flex size-6 items-center justify-center rounded-full border text-xs font-semibold',
                        isCurrent && 'border-sky-500 text-sky-600 dark:text-sky-400',
                        isDone && 'border-emerald-500 text-emerald-600 dark:text-emerald-400',
                        !isDone && !isCurrent && 'text-muted-foreground'
                      )}
                    >
                      {isDone ? <Icons.check className='size-3.5' /> : index + 1}
                    </span>
                    <span className={cn('text-xs font-medium', isCurrent && 'text-sky-700 dark:text-sky-400')}>
                      {step}
                    </span>
                  </div>
                  {index < PUBLISH_FLOW_STEPS.length - 1 && (
                    <Icons.arrowRight className='text-muted-foreground mx-1.5 size-4 shrink-0' />
                  )}
                </li>
              );
            })}
          </ol>
          <p className='text-muted-foreground mt-3 text-xs'>
            当前位置：
            <span className='text-foreground font-medium'>{PUBLISH_FLOW_STEPS[currentIndex]}</span>
            {publishedRelease ? releasePositionHint(publishedRelease) : '（尚无已发布 Release，仍在 Draft 阶段迭代）'}
          </p>
        </CardContent>
      </Card>

      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='text-sm'>Capability Ceiling</CardTitle>
        </CardHeader>
        <CardContent className='p-4'>
          <div className='flex flex-wrap gap-1.5'>
            {definition.capabilityCeiling.map((capability) => (
              <Badge key={capability} variant='secondary' className='font-mono text-xs'>
                {capability}
              </Badge>
            ))}
          </div>
          <p className='text-muted-foreground mt-2 text-xs'>
            Ceiling 是该 Agent 的能力上限：Task Binding 时与 Host/Namespace 策略取交集，超出上限的调用会被 Policy Engine 拒绝。
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

function releasePositionHint(release: AgentRelease): string {
  const channelText = release.channel === 'canary' ? 'Canary 渠道' : release.channel === 'dry-run' ? 'Dry Run 渠道' : 'Stable 渠道';
  return `（最新 Release ${release.id} · v${release.version} · ${channelText}）`;
}

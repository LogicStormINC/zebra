'use client';
import Link from 'next/link';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusBadge } from '@/components/platform/status-badge';
import { lifecycleTone } from '@/lib/platform/status';
import { relativeTime } from '@/lib/platform/format';
import {
  overviewAlerts,
  overviewPendingApprovals,
  overviewRecentHosts,
  overviewRecentReleases
} from '@/lib/platform/mock/overview';
import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';

/** 第三行（PRD 9.2）：高优先级告警、最近发布、最近接入、待处理审批。 */
export function OverviewLists({ pendingApprovalCount }: { pendingApprovalCount: number }) {
  return (
    <div className='grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-4'>
      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='flex items-center gap-2 text-sm'>
            <Icons.warning className='text-amber-500 size-4' />
            高优先级告警
          </CardTitle>
        </CardHeader>
        <CardContent className='divide-y p-0'>
          {overviewAlerts.map((alert) => (
            <Link
              key={alert.id}
              href={alert.href}
              className='hover:bg-muted/50 flex flex-col gap-1 px-4 py-3 transition-colors'
            >
              <div className='flex items-center justify-between gap-2'>
                <span className='truncate text-sm font-medium'>{alert.title}</span>
                <StatusBadge tone={alert.severity === 'high' ? 'failure' : alert.severity === 'medium' ? 'warning' : 'draft'}>
                  {alert.severity === 'high' ? '高' : alert.severity === 'medium' ? '中' : '低'}
                </StatusBadge>
              </div>
              <p className='text-muted-foreground truncate text-xs'>{alert.detail}</p>
            </Link>
          ))}
        </CardContent>
      </Card>

      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='flex items-center gap-2 text-sm'>
            <Icons.agentRelease className='size-4' />
            最近发布
          </CardTitle>
        </CardHeader>
        <CardContent className='divide-y p-0'>
          {overviewRecentReleases.map((release) => (
            <div key={release.id} className='flex items-center justify-between gap-2 px-4 py-3'>
              <div className='min-w-0'>
                <p className='truncate text-sm font-medium'>{release.name}</p>
                <p className='text-muted-foreground text-xs'>{relativeTime(release.at)}</p>
              </div>
              <StatusBadge tone={lifecycleTone(release.status === 'published' ? 'published' : release.status)}>
                {release.status === 'canary'
                  ? 'Canary'
                  : release.status === 'blocked'
                    ? '被阻断'
                    : '已发布'}
              </StatusBadge>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='flex items-center gap-2 text-sm'>
            <Icons.host className='size-4' />
            最近接入
          </CardTitle>
        </CardHeader>
        <CardContent className='divide-y p-0'>
          {overviewRecentHosts.map((host) => (
            <Link
              key={host.id}
              href={`/integrations/hosts/${host.id}`}
              className='hover:bg-muted/50 flex items-center justify-between gap-2 px-4 py-3 transition-colors'
            >
              <div className='min-w-0'>
                <p className='truncate text-sm font-medium'>{host.name}</p>
                <p className='text-muted-foreground text-xs'>{relativeTime(host.at)}</p>
              </div>
              <span
                className={cn(
                  'text-xs font-medium',
                  host.step === 7 ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'
                )}
              >
                {host.step === 7 ? '接入完成' : `向导 ${host.step}/7`}
              </span>
            </Link>
          ))}
        </CardContent>
      </Card>

      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='flex items-center gap-2 text-sm'>
            <Icons.approval className='size-4' />
            待处理审批
          </CardTitle>
        </CardHeader>
        <CardContent className='divide-y p-0'>
          {pendingApprovalCount === 0 && overviewPendingApprovals.length === 0 ? (
            <p className='text-muted-foreground px-4 py-3 text-sm'>暂无待处理项</p>
          ) : (
            overviewPendingApprovals.map((item) => (
              <Link
                key={item.id}
                href='/runtime/approvals'
                className='hover:bg-muted/50 flex items-center justify-between gap-2 px-4 py-3 transition-colors'
              >
                <div className='min-w-0'>
                  <p className='truncate text-sm font-medium'>{item.title}</p>
                  <p className='text-muted-foreground text-xs'>{relativeTime(item.at)}</p>
                </div>
                <StatusBadge tone='waiting'>
                  {item.type === 'approval' ? '待审批' : '待澄清'}
                </StatusBadge>
              </Link>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}

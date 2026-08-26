'use client';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusBadge } from '@/components/platform/status-badge';
import { Icons } from '@/components/icons';
import { formatDuration, relativeTime } from '@/lib/platform/format';
import { cn } from '@/lib/utils';
import type { PlatformHealthCheck } from '@/lib/platform/types';

const STATUS_META: Record<PlatformHealthCheck['status'], { label: string; tone: 'success' | 'warning' | 'failure' }> = {
  healthy: { label: '健康', tone: 'success' },
  degraded: { label: '降级', tone: 'warning' },
  down: { label: '不可用', tone: 'failure' }
};

const GROUP_LABELS: Record<string, string> = {
  storage: 'Storage 存储',
  acceleration: 'Acceleration 加速层',
  runtime: 'Runtime 运行时',
  'model-provider': 'Model Provider 模型提供方',
  integration: 'Integration 集成'
};

const GROUP_ORDER = ['storage', 'acceleration', 'runtime', 'model-provider', 'integration'];

/** 平台健康页（PRD 14.6 / 30）：总状态 + 组件分组检查 + 依赖说明。 */
export function HealthView({ checks }: { checks: PlatformHealthCheck[] }) {
  const counts = {
    healthy: checks.filter((check) => check.status === 'healthy').length,
    degraded: checks.filter((check) => check.status === 'degraded').length,
    down: checks.filter((check) => check.status === 'down').length
  };
  const downChecks = checks.filter((check) => check.status === 'down');
  const overallDegraded = counts.down > 0 || counts.degraded > 0;

  const groups = GROUP_ORDER.map((component) => ({
    component,
    items: checks.filter((check) => check.component === component)
  })).filter((group) => group.items.length > 0);

  return (
    <div className='flex flex-col gap-4'>
      <Card
        className={cn(
          'gap-3 py-0',
          overallDegraded
            ? counts.down > 0
              ? 'border-red-500/50'
              : 'border-amber-500/50'
            : 'border-emerald-500/50'
        )}
      >
        <CardHeader className='flex flex-row items-center justify-between space-y-0 border-b px-4 py-3'>
          <CardTitle className='flex items-center gap-2 text-sm'>
            <Icons.heartbeat className={cn('size-4', counts.down > 0 && 'text-red-500')} />
            平台整体状态
          </CardTitle>
          <StatusBadge tone={overallDegraded ? (counts.down > 0 ? 'failure' : 'warning') : 'success'}>
            {overallDegraded ? (counts.down > 0 ? 'Degraded 降级运行' : 'Degraded 部分降级') : 'Healthy 正常'}
          </StatusBadge>
        </CardHeader>
        <CardContent className='flex flex-col gap-2 px-4 py-3 text-sm'>
          <p>
            {counts.down > 0 ? (
              <>
                整体 <span className='text-red-600 font-medium dark:text-red-400'>degraded</span>：
                {downChecks.map((check) => check.name).join('、')} 不可用
                {downChecks[0] && `（${downChecks[0].detail}）`}；其余组件正常提供服务，相关 Host
                的新 Task 已被阻断。
              </>
            ) : (
              <>全部组件健康，无降级项。</>
            )}
          </p>
          <p className='text-muted-foreground text-xs'>
            组件统计：健康 {counts.healthy} · 降级 {counts.degraded} · 不可用 {counts.down} · 共{' '}
            {checks.length} 项
          </p>
        </CardContent>
      </Card>

      <div className='grid grid-cols-1 gap-4 lg:grid-cols-2'>
        {groups.map((group) => {
          const hasDown = group.items.some((check) => check.status === 'down');
          const hasDegraded = group.items.some((check) => check.status === 'degraded');
          return (
            <Card
              key={group.component}
              className={cn(
                'gap-0 py-0',
                hasDown ? 'border-red-500/50' : hasDegraded ? 'border-amber-500/50' : undefined
              )}
            >
              <CardHeader className='border-b px-4 py-3'>
                <CardTitle className='text-sm'>{GROUP_LABELS[group.component] ?? group.component}</CardTitle>
              </CardHeader>
              <CardContent className='divide-y p-0'>
                {group.items.map((check) => (
                  <div key={check.name} className='flex flex-col gap-1 px-4 py-3'>
                    <div className='flex flex-wrap items-center justify-between gap-2'>
                      <p className='text-sm font-medium'>{check.name}</p>
                      <div className='flex items-center gap-2'>
                        <span className='text-muted-foreground font-mono text-xs tabular-nums'>
                          {formatDuration(check.latencyMs)}
                        </span>
                        <StatusBadge tone={STATUS_META[check.status].tone}>
                          {STATUS_META[check.status].label}
                        </StatusBadge>
                      </div>
                    </div>
                    <div className='text-muted-foreground flex flex-wrap items-center justify-between gap-2 text-xs'>
                      <span>{check.detail}</span>
                      <span>检查于 {relativeTime(check.checkedAt)}</span>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          );
        })}
      </div>

      <Alert>
        <Icons.info />
        <AlertTitle>依赖说明</AlertTitle>
        <AlertDescription>
          平台依赖：PostgreSQL（事件存储，durable source of truth）、Redis（加速层 / Live
          Stream）、Worker Fleet 与 Sandbox 供给池（运行时）、DeepSeek Provider（模型）与各业务 Host
          Connector（集成）。健康检查每 30 秒刷新；不可用组件按 fail closed 语义阻断相关流量。
        </AlertDescription>
      </Alert>
    </div>
  );
}

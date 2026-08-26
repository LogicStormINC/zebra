'use client';

import Link from 'next/link';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Separator } from '@/components/ui/separator';
import { Icons } from '@/components/icons';
import { KpiCard } from '@/components/platform/kpi-card';
import { StatusBadge } from '@/components/platform/status-badge';
import { EmptyState } from '@/components/platform/empty-state';
import { formatDateTime, formatNumber, relativeTime } from '@/lib/platform/format';
import { lifecycleTone } from '@/lib/platform/status';
import type {
  AuditEntry,
  ClientSession,
  Connector,
  FrontendProfile,
  Host,
  InboundTrust,
  Task
} from '@/lib/platform/types';
import { CONFORMANCE_LABELS, TRUST_HEALTH_LABELS } from '../lib/labels';

const DEPENDENCIES = [
  { key: 'trust', label: 'Inbound Trust', icon: 'trust' as const },
  { key: 'connector', label: 'Outbound Connector', icon: 'connector' as const },
  { key: 'manifest', label: 'Backend Manifest', icon: 'manifest' as const },
  { key: 'frontend', label: 'Frontend Profile', icon: 'frontend' as const }
];

/** Host 详情 Overview（PRD 10.2）：完成度、依赖健康、24h 运行统计、版本漂移、最近操作。 */
export function HostOverviewTab({
  host,
  trust,
  connector,
  frontendProfile,
  tasks,
  clientSessions,
  recentAudit
}: {
  host: Host;
  trust?: InboundTrust;
  connector?: Connector;
  frontendProfile?: FrontendProfile;
  tasks: Task[];
  clientSessions: ClientSession[];
  recentAudit: AuditEntry[];
}) {
  const completed = tasks.filter((task) => task.status === 'completed').length;
  const failed = tasks.filter((task) => task.status === 'failed').length;
  const finished = completed + failed;
  const successRate = finished === 0 ? null : Math.round((completed / finished) * 100);
  const uncertainEffects = tasks.filter((task) => task.hasUncertainEffect).length;
  const activeSessions = clientSessions.filter(
    (session) => session.status === 'active' || session.status === 'connecting'
  ).length;

  const dependencyHealth: Record<string, { tone: string; label: string }> = {
    trust: trust
      ? { tone: trust.health, label: TRUST_HEALTH_LABELS[trust.health] }
      : { tone: 'draft', label: '未配置' },
    connector: connector
      ? { tone: connector.health, label: connector.health === 'healthy' ? '健康' : connector.health === 'degraded' ? '降级' : '不可达' }
      : { tone: 'draft', label: '未配置' },
    manifest: host.manifestId
      ? { tone: host.lastConformance === 'failed' ? 'warning' : 'published', label: host.manifestId ? `rev ${host.manifestRevision}` : '未配置' }
      : { tone: 'draft', label: '未配置' },
    frontend: frontendProfile
      ? { tone: frontendProfile.conformance === 'failed' ? 'warning' : 'published', label: `rev ${frontendProfile.revision}` }
      : { tone: 'draft', label: '未配置' }
  };

  const drift =
    connector && host.connectorRevision !== undefined && host.connectorRevision !== connector.latestRevision;

  return (
    <div className='flex flex-col gap-4'>
      <div className='grid grid-cols-1 gap-4 lg:grid-cols-2'>
        <Card className='py-0'>
          <CardHeader className='border-b px-4 py-3'>
            <CardTitle className='text-sm'>接入完成度</CardTitle>
          </CardHeader>
          <CardContent className='space-y-3 p-4'>
            <Progress value={Math.round((host.onboardingStep / 7) * 100)}>
              <div className='flex w-full items-center justify-between'>
                <span className='text-muted-foreground text-xs'>7 步接入向导</span>
                <span className='text-xs font-medium tabular-nums'>
                  {host.onboardingStep}/7 · {Math.round((host.onboardingStep / 7) * 100)}%
                </span>
              </div>
            </Progress>
            <p className='text-muted-foreground text-xs'>
              {host.onboardingStep === 7
                ? '接入已完成，Host 处于可运营状态'
                : '接入未完成，可从页头「继续接入」回到向导'}
            </p>
          </CardContent>
        </Card>

        <Card className='py-0'>
          <CardHeader className='border-b px-4 py-3'>
            <CardTitle className='text-sm'>依赖健康</CardTitle>
          </CardHeader>
          <CardContent className='grid grid-cols-2 gap-3 p-4'>
            {DEPENDENCIES.map((dep) => {
              const health = dependencyHealth[dep.key];
              const Icon = Icons[dep.icon];
              return (
                <div key={dep.key} className='bg-muted/40 flex items-center justify-between gap-2 rounded-lg border px-3 py-2'>
                  <span className='flex min-w-0 items-center gap-2 text-sm font-medium'>
                    <Icon className='text-muted-foreground size-4 shrink-0' />
                    <span className='truncate'>{dep.label}</span>
                  </span>
                  <StatusBadge tone={lifecycleTone(health.tone)} withDot={false}>
                    {health.label}
                  </StatusBadge>
                </div>
              );
            })}
          </CardContent>
        </Card>
      </div>

      <div className='grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4'>
        <KpiCard label='24h Task 总数' value={formatNumber(tasks.length)} icon='task' href='/runtime/tasks' />
        <KpiCard
          label='成功率'
          value={successRate === null ? '—' : `${successRate}%`}
          tone={successRate !== null && successRate < 90 ? 'warning' : 'success'}
          icon='circleCheck'
          hint={`完成 ${completed} / 失败 ${failed}`}
        />
        <KpiCard
          label='异常 Effect Task'
          value={uncertainEffects}
          tone={uncertainEffects > 0 ? 'failure' : 'success'}
          icon='effect'
          href='/runtime/host-effects'
        />
        <KpiCard
          label='活跃 Client Session'
          value={activeSessions}
          icon='clientSession'
          href='/frontend/client-sessions'
        />
      </div>

      {drift && (
        <Alert>
          <Icons.warning className='text-amber-500' />
          <AlertTitle>Connector 版本漂移</AlertTitle>
          <AlertDescription>
            Host 绑定 rev {host.connectorRevision}，Connector 当前最新为 rev {connector?.latestRevision}。
            请评估后通过{' '}
            <Link href={`/integrations/connectors/${connector?.id}`} className='underline underline-offset-2'>
              绑定升级
            </Link>{' '}
            更新 expected revision。
          </AlertDescription>
        </Alert>
      )}

      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='flex items-center justify-between text-sm'>
            <span>最近操作</span>
            <Link href='/governance/audit' className='text-primary text-xs hover:underline'>
              查看全部审计
            </Link>
          </CardTitle>
        </CardHeader>
        <CardContent className='divide-y p-0'>
          {recentAudit.length === 0 ? (
            <p className='text-muted-foreground px-4 py-3 text-sm'>暂无操作记录</p>
          ) : (
            recentAudit.slice(0, 5).map((entry) => (
              <div key={entry.id} className='flex items-center justify-between gap-3 px-4 py-2.5'>
                <div className='min-w-0'>
                  <p className='truncate text-sm font-medium'>
                    <span className='font-mono text-xs'>{entry.action}</span>
                  </p>
                  <p className='text-muted-foreground truncate text-xs'>
                    {entry.actor} · {formatDateTime(entry.timestamp)}
                  </p>
                </div>
                <StatusBadge tone={lifecycleTone(entry.result)} withDot={false}>
                  {entry.result === 'succeeded' ? '成功' : entry.result === 'failed' ? '失败' : '拒绝'}
                </StatusBadge>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      {host.lastConformance !== 'none' && (
        <>
          <Separator />
          <p className='text-muted-foreground text-xs'>
            最近 Conformance：{CONFORMANCE_LABELS[host.lastConformance]} · 数据更新于 {relativeTime(host.updatedAt)}
          </p>
        </>
      )}
    </div>
  );
}

/** 未找到 Host 时的空态（PRD 10.2）。 */
export function HostNotFound({ hostId }: { hostId: string }) {
  return (
    <div className='flex flex-1 flex-col'>
      <EmptyState
        title='未找到该 Host'
        description={`Host ${hostId} 不存在或已被删除，请从列表重新进入`}
        icon='host'
      />
    </div>
  );
}

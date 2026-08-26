'use client';

import Link from 'next/link';

import { Badge } from '@/components/ui/badge';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from '@/components/ui/card';
import { StatusBadge } from '@/components/platform/status-badge';
import { MonoId } from '@/components/platform/mono-id';
import { EmptyState } from '@/components/platform/empty-state';
import { formatDateTime, formatDuration, relativeTime } from '@/lib/platform/format';
import { lifecycleTone } from '@/lib/platform/status';
import type {
  AuditEntry,
  ConformanceRun,
  FrontendProfile,
  MountedCapabilitySnapshot
} from '@/lib/platform/types';
import { DRIFT_LABELS, driftTone } from './labels';

/** Mounted Snapshot Tab：按 Profile Digest 前缀匹配的挂载快照卡片（PRD 13.8 摘要视图）。 */
export function ProfileMountedSnapshotTab({
  profile,
  snapshots
}: {
  profile: FrontendProfile;
  snapshots: MountedCapabilitySnapshot[];
}) {
  if (snapshots.length === 0) {
    return (
      <EmptyState
        title='当前没有挂载该 Profile 的客户端'
        description={`按 Digest 前缀 ${profile.digest.slice(0, 8)} 匹配，未发现 Mounted Snapshot`}
        icon='clientSession'
      />
    );
  }

  return (
    <div className='grid grid-cols-1 gap-4 lg:grid-cols-2'>
      {snapshots.map((snapshot) => (
        <Card key={snapshot.mountedSnapshotDigest} className='py-0'>
          <CardHeader className='gap-1.5 border-b px-4 py-3'>
            <div className='flex items-center justify-between gap-2'>
              <CardTitle className='flex items-center gap-2 text-sm'>
                <MonoId value={snapshot.clientSessionId} head={12} tail={0} copyable={false} />
              </CardTitle>
              <StatusBadge tone={driftTone(snapshot.driftStatus)}>
                {DRIFT_LABELS[snapshot.driftStatus]}
              </StatusBadge>
            </div>
            <CardDescription className='font-mono text-xs'>{snapshot.route}</CardDescription>
          </CardHeader>
          <CardContent className='grid grid-cols-2 gap-x-6 gap-y-2 px-4 py-3 text-sm'>
            <div>
              <p className='text-muted-foreground text-xs'>Frontend Build</p>
              <p className='font-mono text-xs'>{snapshot.frontendBuild}</p>
            </div>
            <div>
              <p className='text-muted-foreground text-xs'>UI Revision</p>
              <p className='tabular-nums'>rev {snapshot.uiRevision}</p>
            </div>
            <div>
              <p className='text-muted-foreground text-xs'>Role</p>
              <p>{snapshot.role === 'controller' ? 'Controller' : 'Observer'}</p>
            </div>
            <div>
              <p className='text-muted-foreground text-xs'>Heartbeat</p>
              <p>{relativeTime(snapshot.heartbeatAt)}</p>
            </div>
            <div className='col-span-2 space-y-1'>
              <p className='text-muted-foreground text-xs'>Mounted Readables</p>
              <div className='flex flex-wrap gap-1'>
                {snapshot.mountedReadables.length === 0 ? (
                  <span className='text-muted-foreground text-xs'>—</span>
                ) : (
                  snapshot.mountedReadables.map((name) => (
                    <Badge key={name} variant='secondary' className='font-mono text-[10px]'>
                      {name}
                    </Badge>
                  ))
                )}
              </div>
            </div>
            <div className='col-span-2 space-y-1'>
              <p className='text-muted-foreground text-xs'>Mounted Actions</p>
              <div className='flex flex-wrap gap-1'>
                {snapshot.mountedActions.length === 0 ? (
                  <span className='text-muted-foreground text-xs'>—</span>
                ) : (
                  snapshot.mountedActions.map((name) => (
                    <Badge key={name} variant='secondary' className='font-mono text-[10px]'>
                      {name}
                    </Badge>
                  ))
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

/** Conformance Tab：该 Host 前端面 Conformance 运行列表。 */
export function ProfileConformanceTab({ runs }: { runs: ConformanceRun[] }) {
  if (runs.length === 0) {
    return (
      <EmptyState
        title='暂无 Frontend Conformance 运行'
        description='该 Host 尚未运行 surface=frontend 的 Conformance'
        icon='conformance'
      />
    );
  }

  return (
    <div className='overflow-x-auto rounded-lg border'>
      <table className='w-full text-sm'>
        <thead className='bg-muted text-muted-foreground'>
          <tr className='border-b'>
            <th className='px-3 py-2 text-left font-medium'>Run ID</th>
            <th className='px-3 py-2 text-left font-medium'>Environment</th>
            <th className='px-3 py-2 text-left font-medium'>Profile Revision</th>
            <th className='px-3 py-2 text-left font-medium'>Triggered By</th>
            <th className='px-3 py-2 text-left font-medium'>Started At</th>
            <th className='px-3 py-2 text-left font-medium'>Duration</th>
            <th className='px-3 py-2 text-left font-medium'>Passed / Failed / Skipped</th>
            <th className='px-3 py-2 text-left font-medium'>Status</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id} className='border-b last:border-0'>
              <td className='px-3 py-2'>
                <Link href={`/quality/conformance/${run.id}`} className='text-primary hover:underline font-mono text-xs'>
                  {run.id}
                </Link>
              </td>
              <td className='px-3 py-2'>{run.environment}</td>
              <td className='px-3 py-2 font-mono text-xs'>rev {run.profileRevision}</td>
              <td className='px-3 py-2 font-mono text-xs'>{run.triggeredBy}</td>
              <td className='px-3 py-2 text-xs'>{formatDateTime(run.startedAt)}</td>
              <td className='px-3 py-2 tabular-nums'>{formatDuration(run.durationMs)}</td>
              <td className='px-3 py-2 tabular-nums'>
                <span className='text-emerald-600 dark:text-emerald-400'>{run.passed}</span> /{' '}
                <span className='text-red-600 dark:text-red-400'>{run.failed}</span> /{' '}
                <span className='text-muted-foreground'>{run.skipped}</span>
              </td>
              <td className='px-3 py-2'>
                <StatusBadge tone={lifecycleTone(run.status)}>
                  {run.status === 'passed' ? '通过' : run.status === 'failed' ? '失败' : '运行中'}
                </StatusBadge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Audit Tab：该 Profile 的审计记录。 */
export function ProfileAuditTab({ entries }: { entries: AuditEntry[] }) {
  if (entries.length === 0) {
    return (
      <EmptyState
        title='暂无该 Profile 的审计记录'
        description='发布、回滚等操作会写入 Audit Log'
        icon='audit'
      />
    );
  }

  return (
    <div className='overflow-x-auto rounded-lg border'>
      <table className='w-full text-sm'>
        <thead className='bg-muted text-muted-foreground'>
          <tr className='border-b'>
            <th className='px-3 py-2 text-left font-medium'>Time</th>
            <th className='px-3 py-2 text-left font-medium'>Actor</th>
            <th className='px-3 py-2 text-left font-medium'>Action</th>
            <th className='px-3 py-2 text-left font-medium'>Digest 变更</th>
            <th className='px-3 py-2 text-left font-medium'>Reason</th>
            <th className='px-3 py-2 text-left font-medium'>Result</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={entry.id} className='border-b last:border-0'>
              <td className='px-3 py-2 text-xs whitespace-nowrap'>
                {formatDateTime(entry.timestamp)}
              </td>
              <td className='px-3 py-2 font-mono text-xs'>{entry.actor}</td>
              <td className='px-3 py-2 font-mono text-xs'>{entry.action}</td>
              <td className='px-3 py-2'>
                {entry.beforeDigest || entry.afterDigest ? (
                  <span className='font-mono text-xs'>
                    {entry.beforeDigest ? `${entry.beforeDigest} → ` : ''}
                    {entry.afterDigest ?? '—'}
                  </span>
                ) : (
                  <span className='text-muted-foreground'>—</span>
                )}
              </td>
              <td className='px-3 py-2 max-w-64 truncate text-xs'>{entry.reason ?? '—'}</td>
              <td className='px-3 py-2'>
                <StatusBadge tone={lifecycleTone(entry.result === 'succeeded' ? 'passed' : entry.result)}>
                  {entry.result === 'succeeded' ? '成功' : entry.result === 'failed' ? '失败' : '拒绝'}
                </StatusBadge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

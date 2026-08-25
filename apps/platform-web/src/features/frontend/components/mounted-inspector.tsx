'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardHeader
} from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { EmptyState } from '@/components/platform/empty-state';
import { MonoId } from '@/components/platform/mono-id';
import { RiskConfirmDialog } from '@/components/platform/risk-confirm-dialog';
import { StatusBadge } from '@/components/platform/status-badge';
import { relativeTime } from '@/lib/platform/format';
import type {
  ClientEffect,
  FrontendProfile,
  MountedCapabilitySnapshot
} from '@/lib/platform/types';
import { DRIFT_LABELS, ROLE_LABELS, driftTone } from './labels';
import { SnapshotDiffDialog, SnapshotJsonDialog } from './snapshot-dialogs';

/**
 * Mounted Capability Inspector（PRD 13.8）：
 * 挂载快照卡片网格 + 漂移检测与治理操作。
 */
export function MountedInspector({
  snapshots,
  profiles,
  effects
}: {
  snapshots: MountedCapabilitySnapshot[];
  profiles: FrontendProfile[];
  effects: ClientEffect[];
}) {
  const [driftFilter, setDriftFilter] = useState('all');
  const [jsonSnapshot, setJsonSnapshot] = useState<MountedCapabilitySnapshot | null>(null);
  const [diffSnapshot, setDiffSnapshot] = useState<MountedCapabilitySnapshot | null>(null);

  const driftOptions = useMemo(
    () => ['all', ...Array.from(new Set(snapshots.map((snapshot) => snapshot.driftStatus)))],
    [snapshots]
  );

  const filtered = useMemo(
    () =>
      snapshots.filter(
        (snapshot) => driftFilter === 'all' || snapshot.driftStatus === driftFilter
      ),
    [snapshots, driftFilter]
  );

  const profileOf = (snapshot: MountedCapabilitySnapshot) =>
    profiles.find((profile) => profile.digest.slice(0, 8) === snapshot.profileDigest.slice(0, 8)) ??
    null;

  const pendingEffectCount = (sessionId: string) =>
    effects.filter((effect) => effect.clientSessionId === sessionId && effect.status === 'pending')
      .length;

  return (
    <div className='flex flex-col gap-4'>
      <div className='flex flex-wrap items-center gap-2'>
        <span className='text-sm font-medium'>Drift 状态</span>
        <Select value={driftFilter} onValueChange={(value) => value && setDriftFilter(value)}>
          <SelectTrigger className='w-56' aria-label='按 Drift 状态筛选'>
            <SelectValue placeholder='全部' />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {driftOptions.map((option) => (
                <SelectItem key={option} value={option}>
                  {option === 'all'
                    ? '全部'
                    : DRIFT_LABELS[option as MountedCapabilitySnapshot['driftStatus']]}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          title='没有匹配的 Mounted Snapshot'
          description='调整 Drift 筛选条件后重试'
          icon='inspector'
        />
      ) : (
        <div className='grid grid-cols-1 gap-4 xl:grid-cols-2'>
          {filtered.map((snapshot) => {
            const pending = pendingEffectCount(snapshot.clientSessionId);
            return (
              <Card key={snapshot.mountedSnapshotDigest} className='py-0'>
                <CardHeader className='gap-2 border-b px-4 py-3'>
                  <div className='flex flex-wrap items-center justify-between gap-2'>
                    <div className='flex items-center gap-2'>
                      <MonoId value={snapshot.clientSessionId} head={12} tail={0} copyable={false} />
                      <StatusBadge tone={snapshot.role === 'controller' ? 'running' : 'draft'} withDot={false}>
                        {ROLE_LABELS[snapshot.role]}
                      </StatusBadge>
                    </div>
                    <StatusBadge tone={driftTone(snapshot.driftStatus)}>
                      {DRIFT_LABELS[snapshot.driftStatus]}
                    </StatusBadge>
                  </div>
                  <div className='text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-xs'>
                    <span>
                      Task:{' '}
                      {snapshot.taskId ? (
                        <Link
                          href={`/runtime/tasks/${snapshot.taskId}`}
                          className='text-primary hover:underline font-mono'
                        >
                          {snapshot.taskId}
                        </Link>
                      ) : (
                        '—'
                      )}
                    </span>
                    <span>
                      Run: <span className='font-mono'>{snapshot.runId ?? '—'}</span>
                    </span>
                    <span>
                      Route: <span className='font-mono'>{snapshot.route}</span>
                    </span>
                  </div>
                </CardHeader>
                <CardContent className='space-y-3 px-4 py-3'>
                  <div className='grid grid-cols-2 gap-x-6 gap-y-2 text-sm md:grid-cols-3'>
                    <div>
                      <p className='text-muted-foreground text-xs'>Frontend Build</p>
                      <p className='font-mono text-xs'>{snapshot.frontendBuild}</p>
                    </div>
                    <div>
                      <p className='text-muted-foreground text-xs'>Profile Digest</p>
                      <p className='font-mono text-xs'>{snapshot.profileDigest.slice(0, 16)}…</p>
                    </div>
                    <div>
                      <p className='text-muted-foreground text-xs'>Snapshot Digest</p>
                      <p className='font-mono text-xs'>{snapshot.mountedSnapshotDigest}</p>
                    </div>
                    <div>
                      <p className='text-muted-foreground text-xs'>UI Revision</p>
                      <p className='tabular-nums'>rev {snapshot.uiRevision}</p>
                    </div>
                    <div>
                      <p className='text-muted-foreground text-xs'>Heartbeat</p>
                      <p>{relativeTime(snapshot.heartbeatAt)}</p>
                    </div>
                    <div>
                      <p className='text-muted-foreground text-xs'>Pending Effect</p>
                      <p className='tabular-nums'>{pending}</p>
                    </div>
                  </div>

                  <div className='space-y-1'>
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
                  <div className='space-y-1'>
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

                  <div className='flex flex-wrap gap-2 border-t pt-3'>
                    <Button size='xs' variant='outline' onClick={() => setJsonSnapshot(snapshot)}>
                      查看 Snapshot
                    </Button>
                    <Button size='xs' variant='outline' onClick={() => setDiffSnapshot(snapshot)}>
                      比较 Published Profile
                    </Button>
                    {snapshot.role === 'controller' && (
                      <RiskConfirmDialog
                        trigger={
                          <Button size='xs' variant='outline'>
                            释放 Controller
                          </Button>
                        }
                        title='Release Controller Lease'
                        impact={`释放会话 ${snapshot.clientSessionId} 的 Controller Lease，等待中的 Client Effect 将失效。`}
                        currentRevision={`ui rev ${snapshot.uiRevision}`}
                        onConfirm={(reason) =>
                          toast.success('Controller Lease 已释放', {
                            description: `${snapshot.clientSessionId} · ${reason || '（未填写）'}`
                          })
                        }
                      />
                    )}
                    <RiskConfirmDialog
                      trigger={
                        <Button size='xs' variant='destructive'>
                          强制断开
                        </Button>
                      }
                      title='强制断开 Client Session'
                      impact={`会话 ${snapshot.clientSessionId} 将被强制断开，运行中的 Client Effect 标记为 unavailable。`}
                      irreversibility='断开后客户端必须重新建立会话并重新上报 Snapshot。'
                      onConfirm={(reason) =>
                        toast.success('会话已强制断开', {
                          description: `${snapshot.clientSessionId} · ${reason || '（未填写）'}`
                        })
                      }
                    />
                    <Button size='xs' variant='ghost' render={<Link href='/frontend/client-effects' aria-label='查看 Pending Client Effect' />}>
                      查看 Pending Client Effect{pending > 0 ? `（${pending}）` : ''}
                    </Button>
                    <Button
                      size='xs'
                      variant='ghost'
                      onClick={() =>
                        toast.success('诊断包已复制', {
                          description: `包含 ${snapshot.clientSessionId} 的 Snapshot 与 Drift 信息（演示）`
                        })
                      }
                    >
                      复制诊断包
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      <SnapshotJsonDialog
        snapshot={jsonSnapshot}
        open={jsonSnapshot !== null}
        onOpenChange={(open) => !open && setJsonSnapshot(null)}
      />
      <SnapshotDiffDialog
        snapshot={diffSnapshot}
        profile={diffSnapshot ? profileOf(diffSnapshot) : null}
        open={diffSnapshot !== null}
        onOpenChange={(open) => !open && setDiffSnapshot(null)}
      />
    </div>
  );
}

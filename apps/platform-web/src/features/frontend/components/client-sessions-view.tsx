'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { DataList } from '@/components/platform/data-list';
import { EmptyState } from '@/components/platform/empty-state';
import { MonoId } from '@/components/platform/mono-id';
import { RiskConfirmDialog } from '@/components/platform/risk-confirm-dialog';
import { StatusBadge } from '@/components/platform/status-badge';
import { formatDateTime, relativeTime } from '@/lib/platform/format';
import { lifecycleTone } from '@/lib/platform/status';
import type {
  ClientEffect,
  ClientSession,
  MountedCapabilitySnapshot
} from '@/lib/platform/types';
import {
  CLIENT_EFFECT_STATUS_LABELS,
  DRIFT_LABELS,
  ROLE_LABELS,
  SESSION_STATUS_LABELS,
  driftTone
} from './labels';

/**
 * Client Session 列表（PRD 19.1）+ 详情 Dialog（PRD 19.2，Tabs 简化为分区）。
 */
export function ClientSessionsView({
  sessions,
  snapshots,
  effects
}: {
  sessions: ClientSession[];
  snapshots: MountedCapabilitySnapshot[];
  effects: ClientEffect[];
}) {
  const [selected, setSelected] = useState<ClientSession | null>(null);
  const [promoteOpen, setPromoteOpen] = useState(false);
  const [expectedRevision, setExpectedRevision] = useState('');

  const roleBadge = (role: ClientSession['role']) => (
    <StatusBadge tone={role === 'controller' ? 'running' : 'draft'} withDot={false}>
      {ROLE_LABELS[role]}
    </StatusBadge>
  );

  const sessionSnapshots = useMemo(
    () => (selected ? snapshots.filter((s) => s.clientSessionId === selected.id) : []),
    [snapshots, selected]
  );
  const sessionEffects = useMemo(
    () => (selected ? effects.filter((effect) => effect.clientSessionId === selected.id) : []),
    [effects, selected]
  );

  return (
    <div className='flex flex-col gap-4'>
      <div className='overflow-x-auto rounded-lg border'>
        <Table>
          <TableHeader className='bg-muted'>
            <TableRow>
              <TableHead>Client Session</TableHead>
              <TableHead>Host</TableHead>
              <TableHead>Namespace</TableHead>
              <TableHead>Frontend App</TableHead>
              <TableHead>Build</TableHead>
              <TableHead>Origin</TableHead>
              <TableHead>User Subject</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Task</TableHead>
              <TableHead>Run</TableHead>
              <TableHead>Route</TableHead>
              <TableHead>UI Revision</TableHead>
              <TableHead>Heartbeat</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sessions.length === 0 ? (
              <TableRow>
                <TableCell colSpan={14} className='h-20 text-center'>
                  <EmptyState title='暂无 Client Session' description='浏览器建立会话后会出现在这里' />
                </TableCell>
              </TableRow>
            ) : (
              sessions.map((session) => (
                <TableRow
                  key={session.id}
                  className='cursor-pointer'
                  onClick={() => setSelected(session)}
                >
                  <TableCell>
                    <MonoId value={session.id} copyable={false} />
                  </TableCell>
                  <TableCell className='text-sm'>{session.hostAppId}</TableCell>
                  <TableCell className='font-mono text-xs'>{session.namespace}</TableCell>
                  <TableCell className='text-sm'>{session.frontendAppId}</TableCell>
                  <TableCell className='font-mono text-xs'>{session.buildId}</TableCell>
                  <TableCell className='max-w-48 truncate font-mono text-xs'>
                    {session.origin}
                  </TableCell>
                  <TableCell className='font-mono text-xs'>{session.userSubjectHash}</TableCell>
                  <TableCell>{roleBadge(session.role)}</TableCell>
                  <TableCell>
                    {session.taskId ? (
                      <Link
                        href={`/runtime/tasks/${session.taskId}`}
                        className='text-primary hover:underline font-mono text-xs'
                        onClick={(event) => event.stopPropagation()}
                      >
                        {session.taskId}
                      </Link>
                    ) : (
                      <span className='text-muted-foreground'>—</span>
                    )}
                  </TableCell>
                  <TableCell className='font-mono text-xs'>
                    {session.runId ?? '—'}
                  </TableCell>
                  <TableCell className='max-w-44 truncate font-mono text-xs'>
                    {session.route}
                  </TableCell>
                  <TableCell className='tabular-nums'>rev {session.uiRevision}</TableCell>
                  <TableCell className='text-muted-foreground text-xs'>
                    {relativeTime(session.lastHeartbeatAt)}
                  </TableCell>
                  <TableCell>
                    <StatusBadge tone={lifecycleTone(session.status)}>
                      {SESSION_STATUS_LABELS[session.status]}
                    </StatusBadge>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog open={selected !== null} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent className='max-h-[85vh] max-w-3xl overflow-y-auto'>
          {selected && (
            <>
              <DialogHeader>
                <DialogTitle className='flex items-center gap-2'>
                  Client Session <MonoId value={selected.id} />
                </DialogTitle>
                <DialogDescription>
                  {selected.hostAppId} / {selected.frontendAppId} · {selected.route}
                </DialogDescription>
              </DialogHeader>

              <section className='space-y-3'>
                <h3 className='text-sm font-semibold'>Overview</h3>
                <DataList
                  columns={3}
                  items={[
                    { label: 'Host', value: selected.hostAppId },
                    { label: 'Namespace', value: <span className='font-mono text-xs'>{selected.namespace}</span> },
                    { label: 'Frontend App', value: selected.frontendAppId },
                    { label: 'Build', value: <span className='font-mono text-xs'>{selected.buildId}</span> },
                    { label: 'Origin', value: <span className='font-mono text-xs'>{selected.origin}</span> },
                    { label: 'User Subject Hash', value: <span className='font-mono text-xs'>{selected.userSubjectHash}</span> },
                    { label: 'Role', value: roleBadge(selected.role) },
                    { label: 'UI Revision', value: `rev ${selected.uiRevision}` },
                    { label: 'Route', value: <span className='font-mono text-xs'>{selected.route}</span> },
                    { label: 'Last Heartbeat', value: `${formatDateTime(selected.lastHeartbeatAt)}（${relativeTime(selected.lastHeartbeatAt)}）` },
                    {
                      label: 'Status',
                      value: (
                        <StatusBadge tone={lifecycleTone(selected.status)}>
                          {SESSION_STATUS_LABELS[selected.status]}
                        </StatusBadge>
                      )
                    },
                    { label: 'Run', value: selected.runId ?? '—' }
                  ]}
                />
              </section>

              <section className='space-y-2'>
                <h3 className='text-sm font-semibold'>Mounted Capabilities</h3>
                {sessionSnapshots.length === 0 ? (
                  <p className='text-muted-foreground text-sm'>该会话没有上报 Mounted Snapshot。</p>
                ) : (
                  sessionSnapshots.map((snapshot) => (
                    <div
                      key={snapshot.mountedSnapshotDigest}
                      className='space-y-2 rounded-lg border p-3'
                    >
                      <div className='flex flex-wrap items-center gap-2 text-xs'>
                        <span className='font-mono'>{snapshot.mountedSnapshotDigest}</span>
                        <StatusBadge tone={driftTone(snapshot.driftStatus)}>
                          {DRIFT_LABELS[snapshot.driftStatus]}
                        </StatusBadge>
                        <span className='text-muted-foreground'>UI rev {snapshot.uiRevision}</span>
                      </div>
                      <div className='space-y-1'>
                        <p className='text-muted-foreground text-xs'>Mounted Readables</p>
                        <div className='flex flex-wrap gap-1'>
                          {snapshot.mountedReadables.map((name) => (
                            <Badge key={name} variant='secondary' className='font-mono text-[10px]'>
                              {name}
                            </Badge>
                          ))}
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
                    </div>
                  ))
                )}
              </section>

              <section className='space-y-2'>
                <h3 className='text-sm font-semibold'>Controller Lease</h3>
                <div className='rounded-lg border p-3 text-sm'>
                  {selected.role === 'controller' ? (
                    <DataList
                      columns={2}
                      items={[
                        { label: 'Lease 持有', value: <StatusBadge tone='success' withDot={false}>是（当前 Controller）</StatusBadge> },
                        { label: 'Task', value: selected.taskId ?? '—' },
                        { label: 'Run', value: selected.runId ?? '—' },
                        { label: 'UI Revision', value: `rev ${selected.uiRevision}` },
                        { label: '规则', value: '同一 Run 同时只有一个 Controller；Client Effect 一次一效（Fence）' }
                      ]}
                    />
                  ) : (
                    <p className='text-muted-foreground'>
                      该会话为 Observer，未持有 Controller Lease；如需升级需经 Promote 流程。
                    </p>
                  )}
                </div>
              </section>

              <section className='space-y-2'>
                <h3 className='text-sm font-semibold'>Client Effects</h3>
                {sessionEffects.length === 0 ? (
                  <p className='text-muted-foreground text-sm'>该会话没有 Client Effect 记录。</p>
                ) : (
                  <div className='overflow-x-auto rounded-lg border'>
                    <Table>
                      <TableHeader className='bg-muted'>
                        <TableRow>
                          <TableHead>Effect</TableHead>
                          <TableHead>Action</TableHead>
                          <TableHead>Expected Revision</TableHead>
                          <TableHead>Created</TableHead>
                          <TableHead>Status</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {sessionEffects.map((effect) => (
                          <TableRow key={effect.id}>
                            <TableCell>
                              <MonoId value={effect.id} copyable={false} />
                            </TableCell>
                            <TableCell className='font-mono text-xs'>{effect.action}</TableCell>
                            <TableCell className='tabular-nums'>rev {effect.expectedRevision}</TableCell>
                            <TableCell className='text-xs'>
                              {formatDateTime(effect.createdAt)}
                            </TableCell>
                            <TableCell>
                              <StatusBadge tone={lifecycleTone(effect.status)} withDot={false}>
                                {CLIENT_EFFECT_STATUS_LABELS[effect.status]}
                              </StatusBadge>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </section>

              <DialogFooter className='flex-wrap sm:justify-start'>
                <RiskConfirmDialog
                  trigger={
                    <Button variant='destructive' size='sm'>
                      Revoke Session
                    </Button>
                  }
                  title='Revoke Client Session'
                  impact={`会话 ${selected.id} 将立即失效，进行中的 Client Effect 会被标记为 unavailable。`}
                  irreversibility='撤销后不可恢复，客户端需重新建立会话并通过 Origin / Build 校验。'
                  onConfirm={(reason) =>
                    toast.success('会话已撤销', {
                      description: `${selected.id} · 审计原因：${reason || '（未填写）'}`
                    })
                  }
                />
                <RiskConfirmDialog
                  trigger={
                    <Button variant='outline' size='sm'>
                      Release Controller
                    </Button>
                  }
                  title='Release Controller Lease'
                  impact={`释放 ${selected.id} 的 Controller Lease；等待中的 Client Effect 将按 Fence 规则失效。`}
                  irreversibility='Lease 释放后，新 Controller 需通过 Promote 流程接管。'
                  currentRevision={`ui rev ${selected.uiRevision}`}
                  onConfirm={(reason) =>
                    toast.success('Controller Lease 已释放', {
                      description: `${selected.id} · 审计原因：${reason || '（未填写）'}`
                    })
                  }
                />
                <Button
                  variant='outline'
                  size='sm'
                  onClick={() => {
                    setExpectedRevision(String(selected.uiRevision));
                    setPromoteOpen(true);
                  }}
                >
                  Promote Observer
                </Button>
                <Button
                  variant='outline'
                  size='sm'
                  onClick={() =>
                    toast.success('诊断包已生成', {
                      description: `包含会话 ${selected.id} 的 Snapshot、心跳与 Effect 摘要（演示）`
                    })
                  }
                >
                  Download Diagnostic Bundle
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={promoteOpen} onOpenChange={setPromoteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Promote Observer 为 Controller</DialogTitle>
            <DialogDescription>
              提升前需确认客户端当前 UI Revision，与平台记录一致才会授予 Lease。
            </DialogDescription>
          </DialogHeader>
          <div className='space-y-1.5'>
            <Label htmlFor='promote-revision'>Expected UI Revision</Label>
            <Input
              id='promote-revision'
              type='number'
              min={1}
              value={expectedRevision}
              onChange={(event) => setExpectedRevision(event.target.value)}
              placeholder='例如 12'
            />
            <p className='text-muted-foreground text-xs'>
              {selected
                ? `会话 ${selected.id} 当前上报 rev ${selected.uiRevision}；不匹配时 Promote 会被拒绝（fail closed）。`
                : ''}
            </p>
          </div>
          <DialogFooter>
            <Button variant='outline' size='sm' onClick={() => setPromoteOpen(false)}>
              取消
            </Button>
            <Button
              size='sm'
              disabled={!expectedRevision || Number(expectedRevision) < 1}
              onClick={() => {
                setPromoteOpen(false);
                toast.success('Promote 已提交', {
                  description: `expected revision = ${expectedRevision}（演示）`
                });
              }}
            >
              确认 Promote
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

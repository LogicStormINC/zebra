'use client';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
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
import { StatusBadge } from '@/components/platform/status-badge';
import { CLIENT_BINDING_STATUS_LABELS, lifecycleTone } from '@/lib/platform/status';
import { formatDateTime } from '@/lib/platform/format';
import { Icons } from '@/components/icons';
import type { HostEffect } from '@/lib/platform/types';
import type { TaskDetailData } from './task-detail-data';
import { HostEffectRowActions } from './host-effect-row-actions';

const EFFECT_STATUS_LABELS: Record<string, string> = {
  pending: '待调度',
  delivered: '已送达',
  succeeded: '成功',
  failed: '失败',
  uncertain: '不确定'
};

const RECONCILIATION_LABELS: Record<string, string> = {
  not_required: '无需对账',
  pending: '待对账',
  succeeded: '对账成功',
  failed: '对账失败',
  manual_review: '人工审查'
};

/** Host Effects Tab（PRD 18.10）：Dispatch / 幂等键 / Claim / Evidence / 对账状态。 */
export function TaskHostEffectsTab({ effects }: { effects: HostEffect[] }) {
  if (effects.length === 0) {
    return (
      <EmptyState
        icon='effect'
        title='该 Task 无 Host Effect'
        description='对 Host 后端的每次写/读派发都会记录 Dispatch、幂等键与 Receipt 证据'
      />
    );
  }

  return (
    <div className='overflow-hidden rounded-lg border'>
      <Table>
        <TableHeader className='bg-muted'>
          <TableRow>
            <TableHead>Dispatch ID</TableHead>
            <TableHead>Tool</TableHead>
            <TableHead>Operation ID</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Idempotency Key</TableHead>
            <TableHead>Claim Owner</TableHead>
            <TableHead>Attempt</TableHead>
            <TableHead>Evidence</TableHead>
            <TableHead>Reconciliation</TableHead>
            <TableHead className='text-right'>操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {effects.map((effect) => (
            <TableRow key={effect.dispatchId}>
              <TableCell>
                <MonoId value={effect.dispatchId} copyable={false} />
              </TableCell>
              <TableCell className='font-mono text-xs'>{effect.tool}</TableCell>
              <TableCell className='font-mono text-xs'>{effect.operationId}</TableCell>
              <TableCell>
                <StatusBadge
                  tone={lifecycleTone(effect.status === 'uncertain' ? 'uncertain' : effect.status)}
                >
                  {EFFECT_STATUS_LABELS[effect.status] ?? effect.status}
                </StatusBadge>
              </TableCell>
              <TableCell>
                <MonoId value={effect.idempotencyKey} />
              </TableCell>
              <TableCell className='font-mono text-xs'>{effect.claimOwner}</TableCell>
              <TableCell className='tabular-nums'>#{effect.attempt}</TableCell>
              <TableCell className='text-muted-foreground max-w-[200px] truncate text-sm'>
                {effect.evidence}
              </TableCell>
              <TableCell>
                <StatusBadge
                  tone={lifecycleTone(effect.reconciliation)}
                  withDot={effect.reconciliation !== 'not_required'}
                >
                  {RECONCILIATION_LABELS[effect.reconciliation] ?? effect.reconciliation}
                </StatusBadge>
              </TableCell>
              <TableCell className='text-right'>
                {effect.status === 'uncertain' ? (
                  <HostEffectRowActions effect={effect} />
                ) : (
                  <span className='text-muted-foreground text-xs'>—</span>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

const CLIENT_EFFECT_STATUS_LABELS: Record<string, string> = {
  pending: '待执行',
  delivered: '已送达',
  succeeded: '成功',
  failed: '失败',
  declined: '已拒绝',
  unavailable: '前端不可用',
  stale_ui_state: 'UI 状态过期',
  expired: '已过期',
  uncertain: '不确定',
  cancelled: '已取消'
};

const DRIFT_LABELS: Record<string, string> = {
  aligned: '一致',
  profile_digest_mismatch: 'Profile Digest 不一致',
  unknown_action: '未知动作',
  action_not_mounted: '动作未挂载',
  schema_mismatch: 'Schema 不一致',
  origin_mismatch: 'Origin 不一致',
  build_mismatch: 'Build 不一致',
  stale_ui_revision: 'UI Revision 过期',
  stale_fence: 'Fence 过期'
};

/** Client Tab（PRD 18.11）：Binding / Controller / Mounted / Effects 四个子区。 */
export function TaskClientTab({ data }: { data: TaskDetailData }) {
  const { clientRunBindings, clientSessions, mountedSnapshots, clientEffects } = data;

  if (clientRunBindings.length === 0 && clientEffects.length === 0) {
    return (
      <EmptyState
        icon='frontend'
        title='该 Task 无前端绑定'
        description='只有绑定了 Client Run 的 Task 才能下发 client effect 与读取 readables'
      />
    );
  }

  return (
    <div className='flex flex-col gap-4'>
      <AlertNoBrowserHook />

      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='text-sm'>Client Run Binding</CardTitle>
        </CardHeader>
        <CardContent className='p-0'>
          {clientRunBindings.length === 0 ? (
            <p className='text-muted-foreground p-4 text-sm'>无</p>
          ) : (
            <Table>
              <TableHeader className='bg-muted'>
                <TableRow>
                  <TableHead>Binding</TableHead>
                  <TableHead>Run</TableHead>
                  <TableHead>Client Session</TableHead>
                  <TableHead>Frontend Profile Digest</TableHead>
                  <TableHead>Snapshot Digest</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Created At</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {clientRunBindings.map((binding) => (
                  <TableRow key={binding.id}>
                    <TableCell>
                      <MonoId value={binding.id} copyable={false} />
                    </TableCell>
                    <TableCell className='font-mono text-xs'>{binding.runId}</TableCell>
                    <TableCell className='font-mono text-xs'>{binding.clientSessionId}</TableCell>
                    <TableCell>
                      <MonoId value={binding.frontendProfileDigest} copyable={false} />
                    </TableCell>
                    <TableCell>
                      <MonoId value={binding.snapshotDigest} copyable={false} />
                    </TableCell>
                    <TableCell>
                      <StatusBadge tone={lifecycleTone(binding.status)}>
                        {CLIENT_BINDING_STATUS_LABELS[binding.status] ?? binding.status}
                      </StatusBadge>
                    </TableCell>
                    <TableCell className='text-sm'>{formatDateTime(binding.createdAt)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='text-sm'>Active Controller / Observer</CardTitle>
        </CardHeader>
        <CardContent className='p-0'>
          {clientSessions.length === 0 ? (
            <p className='text-muted-foreground p-4 text-sm'>无活跃会话</p>
          ) : (
            <Table>
              <TableHeader className='bg-muted'>
                <TableRow>
                  <TableHead>Session</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Route</TableHead>
                  <TableHead>UI Revision</TableHead>
                  <TableHead>Last Heartbeat</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {clientSessions.map((session) => (
                  <TableRow key={session.id}>
                    <TableCell>
                      <MonoId value={session.id} copyable={false} />
                    </TableCell>
                    <TableCell>
                      <Badge variant={session.role === 'controller' ? 'default' : 'outline'}>
                        {session.role === 'controller' ? 'Controller' : 'Observer'}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <StatusBadge tone={lifecycleTone(session.status)}>
                        {session.status}
                      </StatusBadge>
                    </TableCell>
                    <TableCell className='font-mono text-xs'>{session.route}</TableCell>
                    <TableCell className='tabular-nums'>{session.uiRevision}</TableCell>
                    <TableCell className='text-sm'>
                      {formatDateTime(session.lastHeartbeatAt)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='text-sm'>Mounted Capabilities</CardTitle>
        </CardHeader>
        <CardContent className='flex flex-col gap-4 p-4'>
          {mountedSnapshots.length === 0 ? (
            <p className='text-muted-foreground text-sm'>无挂载快照</p>
          ) : (
            mountedSnapshots.map((snapshot) => (
              <div key={snapshot.clientSessionId} className='space-y-2 rounded-lg border p-3'>
                <div className='flex flex-wrap items-center justify-between gap-2'>
                  <span className='flex items-center gap-2 text-sm font-medium'>
                    <MonoId value={snapshot.clientSessionId} copyable={false} />
                    <Badge variant='outline'>{snapshot.role}</Badge>
                  </span>
                  <StatusBadge
                    tone={lifecycleTone(
                      snapshot.driftStatus === 'aligned' ? 'aligned' : snapshot.driftStatus
                    )}
                  >
                    {DRIFT_LABELS[snapshot.driftStatus] ?? snapshot.driftStatus}
                  </StatusBadge>
                </div>
                <DataList
                  columns={3}
                  items={[
                    {
                      label: 'Route',
                      value: <span className='font-mono text-xs'>{snapshot.route}</span>
                    },
                    { label: 'Frontend Build', value: snapshot.frontendBuild },
                    { label: 'UI Revision', value: `rev ${snapshot.uiRevision}` },
                    {
                      label: 'Mounted Readables',
                      value: snapshot.mountedReadables.join('、') || '无'
                    },
                    {
                      label: 'Mounted Actions',
                      value: snapshot.mountedActions.join('、') || '无'
                    },
                    { label: 'Heartbeat', value: formatDateTime(snapshot.heartbeatAt) }
                  ]}
                />
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <Card className='py-0'>
        <CardHeader className='border-b px-4 py-3'>
          <CardTitle className='text-sm'>Client Effects</CardTitle>
        </CardHeader>
        <CardContent className='p-0'>
          {clientEffects.length === 0 ? (
            <p className='text-muted-foreground p-4 text-sm'>无</p>
          ) : (
            <Table>
              <TableHeader className='bg-muted'>
                <TableRow>
                  <TableHead>Effect ID</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Expected UI Rev</TableHead>
                  <TableHead>Client Session</TableHead>
                  <TableHead>Fence</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Scheduled</TableHead>
                  <TableHead>Delivered</TableHead>
                  <TableHead>Receipt</TableHead>
                  <TableHead>Result Digest</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {clientEffects.map((effect) => (
                  <TableRow key={effect.id}>
                    <TableCell>
                      <MonoId value={effect.id} copyable={false} />
                    </TableCell>
                    <TableCell className='font-mono text-xs'>{effect.action}</TableCell>
                    <TableCell className='tabular-nums'>{effect.expectedRevision}</TableCell>
                    <TableCell className='font-mono text-xs'>{effect.clientSessionId}</TableCell>
                    <TableCell>
                      <MonoId value={effect.fenceHash} copyable={false} />
                    </TableCell>
                    <TableCell>
                      <StatusBadge tone={lifecycleTone(effect.status)}>
                        {CLIENT_EFFECT_STATUS_LABELS[effect.status] ?? effect.status}
                      </StatusBadge>
                    </TableCell>
                    <TableCell className='text-sm whitespace-nowrap'>
                      {formatDateTime(effect.createdAt)}
                    </TableCell>
                    <TableCell className='text-sm whitespace-nowrap'>
                      {effect.status === 'pending' ? '—' : formatDateTime(effect.createdAt)}
                    </TableCell>
                    <TableCell>
                      {effect.receiptDigest ? (
                        <MonoId value={effect.receiptDigest} />
                      ) : (
                        <span className='text-muted-foreground text-xs'>无</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {effect.receiptDigest ? (
                        <MonoId value={`res_${effect.receiptDigest}`} copyable={false} />
                      ) : (
                        <span className='text-muted-foreground text-xs'>—</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function AlertNoBrowserHook() {
  return (
    <div className='border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-400 flex items-start gap-2 rounded-lg border p-3 text-sm'>
      <Icons.warning className='mt-0.5 size-4 shrink-0' />
      <p>
        后台不允许代执行浏览器 Hook：client effect 只能由持有 Controller 会话的前端执行并回传
        Receipt；平台侧仅做派发、Fence 校验与对账。
      </p>
    </div>
  );
}

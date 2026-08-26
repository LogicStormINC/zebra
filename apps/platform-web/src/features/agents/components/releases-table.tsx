'use client';
import Link from 'next/link';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { EmptyState } from '@/components/platform/empty-state';
import { DigestTag, MonoId } from '@/components/platform/mono-id';
import { RiskConfirmDialog } from '@/components/platform/risk-confirm-dialog';
import { StatusBadge } from '@/components/platform/status-badge';
import { lifecycleTone } from '@/lib/platform/status';
import { formatDateTime } from '@/lib/platform/format';
import type { AgentRelease } from '@/lib/platform/types';

const LIFECYCLE_LABELS: Record<string, string> = {
  draft: '草稿',
  published: '已发布',
  deprecated: '已废弃',
  revoked: '已撤销'
};

const CHANNEL_LABELS: Record<string, string> = {
  stable: 'Stable',
  canary: 'Canary',
  'dry-run': 'Dry Run'
};

/** Agent Release 列表（PRD 14.3）：Revoke / Promote 行操作。 */
export function ReleasesTable({ releases }: { releases: AgentRelease[] }) {
  if (releases.length === 0) {
    return <EmptyState icon='agentRelease' title='暂无 Agent Release' description='从 Definition 详情的 Release Tab 发布版本' />;
  }

  return (
    <div className='overflow-hidden rounded-lg border'>
      <Table>
        <TableHeader className='bg-muted'>
          <TableRow>
            <TableHead>Release ID</TableHead>
            <TableHead>Definition</TableHead>
            <TableHead>Version</TableHead>
            <TableHead>Channel</TableHead>
            <TableHead>Bound Hosts</TableHead>
            <TableHead>Digest</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Released By</TableHead>
            <TableHead>Released At</TableHead>
            <TableHead className='text-right'>操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {releases.map((release) => (
            <TableRow key={release.id}>
              <TableCell>
                <MonoId value={release.id} copyable={false} />
              </TableCell>
              <TableCell>
                <Link
                  href={`/agents/definitions/${release.definitionId}`}
                  className='text-primary text-sm hover:underline'
                >
                  {release.definitionName}
                </Link>
              </TableCell>
              <TableCell className='font-medium tabular-nums'>v{release.version}</TableCell>
              <TableCell>
                <Badge variant='outline' className='text-xs'>
                  {CHANNEL_LABELS[release.channel] ?? release.channel}
                </Badge>
              </TableCell>
              <TableCell className='tabular-nums'>{release.boundHosts}</TableCell>
              <TableCell>
                <DigestTag value={release.digest} />
              </TableCell>
              <TableCell>
                <StatusBadge tone={lifecycleTone(release.status)}>
                  {LIFECYCLE_LABELS[release.status] ?? release.status}
                </StatusBadge>
              </TableCell>
              <TableCell className='text-sm'>{release.releasedBy}</TableCell>
              <TableCell className='text-sm whitespace-nowrap'>{formatDateTime(release.releasedAt)}</TableCell>
              <TableCell className='text-right'>
                <span className='inline-flex items-center gap-1.5'>
                  <RiskConfirmDialog
                    trigger={<Button variant='destructive' size='sm'>Revoke</Button>}
                    title={`Revoke ${release.id}`}
                    impact={`影响 ${release.boundHosts} 个 Host Binding；使用 v${release.version} 的 Task 将拒绝新建`}
                    irreversibility='撤销后不可恢复'
                    currentRevision={`v${release.version} · ${release.channel}`}
                    actionLabel='确认撤销'
                    onConfirm={() => {
                      // 演示操作
                    }}
                  />
                  <RiskConfirmDialog
                    trigger={<Button variant='outline' size='sm'>Promote</Button>}
                    title={`Promote ${release.id}`}
                    impact={`将 v${release.version} 提升为 stable 渠道并全量生效`}
                    currentRevision={`v${release.version} · ${release.channel}`}
                    targetRevision='stable'
                    actionLabel='确认提升'
                    onConfirm={() => {
                      // 演示操作
                    }}
                  />
                </span>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

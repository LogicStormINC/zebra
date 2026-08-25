'use client';
import { toast } from 'sonner';
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
import { StatusBadge } from '@/components/platform/status-badge';
import { lifecycleTone } from '@/lib/platform/status';
import { formatDateTime } from '@/lib/platform/format';
import type { PolicyRecord } from '@/lib/platform/types';

const LIFECYCLE_LABELS: Record<string, string> = {
  draft: '草稿',
  published: '已发布',
  deprecated: '已废弃',
  revoked: '已撤销'
};

/** 层级徽标（PRD 15.1）：platform → frontend-profile 的七层叠加。 */
export const POLICY_LEVEL_LABELS: Record<PolicyRecord['level'], string> = {
  platform: 'Platform',
  environment: 'Environment',
  host: 'Host',
  namespace: 'Namespace',
  'agent-release': 'Agent Release',
  'task-type': 'Task Type',
  'frontend-profile': 'Frontend Profile'
};

/** 按类型过滤的 Policy 列表（model / tool / memory / runtime 页面共用）。 */
export function PolicyTable({ policies, kindLabel }: { policies: PolicyRecord[]; kindLabel: string }) {
  if (policies.length === 0) {
    return (
      <EmptyState
        icon='policy'
        title={`暂无 ${kindLabel} 记录`}
        description='点击「新建 Draft」创建策略草稿，验证后发布生效'
      />
    );
  }

  return (
    <div className='flex flex-col gap-3'>
      <div className='flex items-center justify-end gap-2'>
        <Button
          size='sm'
          onClick={() =>
            toast.info('新建 Draft（演示）', {
              description: `将为 ${kindLabel} 创建 revision 0 的策略草稿`
            })
          }
        >
          新建 Draft
        </Button>
      </div>
      <div className='overflow-hidden rounded-lg border'>
        <Table>
          <TableHeader className='bg-muted'>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Policy ID</TableHead>
              <TableHead>Level</TableHead>
              <TableHead>Scope</TableHead>
              <TableHead>Revision</TableHead>
              <TableHead>Digest</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Updated By</TableHead>
              <TableHead>Updated At</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {policies.map((policy) => (
              <TableRow key={policy.id}>
                <TableCell className='font-medium'>{policy.name}</TableCell>
                <TableCell>
                  <MonoId value={policy.id} copyable={false} />
                </TableCell>
                <TableCell>
                  <Badge variant='outline' className='text-xs'>
                    {POLICY_LEVEL_LABELS[policy.level] ?? policy.level}
                  </Badge>
                </TableCell>
                <TableCell className='font-mono text-xs'>{policy.scope}</TableCell>
                <TableCell className='tabular-nums'>rev {policy.revision}</TableCell>
                <TableCell>
                  <DigestTag value={policy.digest} />
                </TableCell>
                <TableCell>
                  <StatusBadge tone={lifecycleTone(policy.status)}>
                    {LIFECYCLE_LABELS[policy.status] ?? policy.status}
                  </StatusBadge>
                </TableCell>
                <TableCell className='text-sm'>{policy.updatedBy}</TableCell>
                <TableCell className='text-sm whitespace-nowrap'>{formatDateTime(policy.updatedAt)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

'use client';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
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
import type { CapabilityProfile } from '@/lib/platform/types';

const LIFECYCLE_LABELS: Record<string, string> = {
  draft: '草稿',
  published: '已发布',
  deprecated: '已废弃',
  revoked: '已撤销'
};

/** Capability Profile 列表（PRD 14.4）：行内 Dialog 展示三组能力徽标。 */
export function CapabilityProfilesList({ profiles }: { profiles: CapabilityProfile[] }) {
  if (profiles.length === 0) {
    return <EmptyState icon='agent' title='暂无 Capability Profile' description='Capability Profile 定义 backend tools / client actions / readables 三组能力' />;
  }

  return (
    <div className='overflow-hidden rounded-lg border'>
      <Table>
        <TableHeader className='bg-muted'>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Profile ID</TableHead>
            <TableHead>Backend Tools</TableHead>
            <TableHead>Client Actions</TableHead>
            <TableHead>Readables</TableHead>
            <TableHead>Revision</TableHead>
            <TableHead>Digest</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Updated At</TableHead>
            <TableHead className='text-right'>操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {profiles.map((profile) => (
            <TableRow key={profile.id}>
              <TableCell className='font-medium'>{profile.name}</TableCell>
              <TableCell>
                <MonoId value={profile.id} copyable={false} />
              </TableCell>
              <TableCell className='tabular-nums'>{profile.backendTools.length}</TableCell>
              <TableCell className='tabular-nums'>{profile.clientActions.length}</TableCell>
              <TableCell className='tabular-nums'>{profile.readables.length}</TableCell>
              <TableCell className='tabular-nums'>rev {profile.revision}</TableCell>
              <TableCell>
                <DigestTag value={profile.digest} />
              </TableCell>
              <TableCell>
                <StatusBadge tone={lifecycleTone(profile.status)}>
                  {LIFECYCLE_LABELS[profile.status] ?? profile.status}
                </StatusBadge>
              </TableCell>
              <TableCell className='text-sm whitespace-nowrap'>{formatDateTime(profile.updatedAt)}</TableCell>
              <TableCell className='text-right'>
                <CapabilityProfileDialog profile={profile} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function CapabilityProfileDialog({ profile }: { profile: CapabilityProfile }) {
  return (
    <Dialog>
      <DialogTrigger render={<Button variant='outline' size='sm' />}>查看详情</DialogTrigger>
      <DialogContent className='sm:max-w-xl'>
        <DialogHeader>
          <DialogTitle>{profile.name}</DialogTitle>
          <DialogDescription>
            rev {profile.revision} · {LIFECYCLE_LABELS[profile.status] ?? profile.status} · 更新于{' '}
            {formatDateTime(profile.updatedAt)}
          </DialogDescription>
        </DialogHeader>
        <div className='space-y-3'>
          <div className='flex items-center justify-between gap-2 text-sm'>
            <span className='text-muted-foreground'>Digest</span>
            <DigestTag value={profile.digest} />
          </div>
          <CapabilityGroup title='Backend Tools' items={profile.backendTools} />
          <CapabilityGroup title='Client Actions' items={profile.clientActions} />
          <CapabilityGroup title='Readables' items={profile.readables} />
        </div>
      </DialogContent>
    </Dialog>
  );
}

function CapabilityGroup({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <p className='text-muted-foreground mb-1.5 text-xs font-medium'>{title}</p>
      {items.length === 0 ? (
        <p className='text-muted-foreground text-sm'>无</p>
      ) : (
        <div className='flex flex-wrap gap-1.5'>
          {items.map((item) => (
            <Badge key={item} variant='secondary' className='font-mono text-xs'>
              {item}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

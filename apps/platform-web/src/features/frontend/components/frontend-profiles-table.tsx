'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { DigestTag } from '@/components/platform/mono-id';
import { StatusBadge } from '@/components/platform/status-badge';
import { EmptyState } from '@/components/platform/empty-state';
import { formatDateTime } from '@/lib/platform/format';
import type { FrontendProfile } from '@/lib/platform/types';
import {
  CONFORMANCE_LABELS,
  CONFORMANCE_TONES,
  PROFILE_STATUS_LABELS,
  lifecycleTone
} from './labels';

/**
 * Frontend Profile 列表（PRD 13.2）：
 * Host / Frontend App / Revision / Build / Origins / 能力数量 / 挂载客户端 / Digest / 状态 / Conformance。
 */
export function FrontendProfilesTable({ profiles }: { profiles: FrontendProfile[] }) {
  const [keyword, setKeyword] = useState('');
  const [status, setStatus] = useState<string>('all');

  const statusOptions = useMemo(
    () => ['all', ...Array.from(new Set(profiles.map((profile) => profile.status)))],
    [profiles]
  );

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return profiles.filter((profile) => {
      if (status !== 'all' && profile.status !== status) return false;
      if (!kw) return true;
      return (
        profile.hostAppId.toLowerCase().includes(kw) ||
        profile.frontendAppId.toLowerCase().includes(kw) ||
        profile.id.toLowerCase().includes(kw) ||
        profile.buildId.toLowerCase().includes(kw)
      );
    });
  }, [profiles, keyword, status]);

  return (
    <div className='flex flex-col gap-4'>
      <div className='flex flex-wrap items-center gap-2'>
        <Input
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          placeholder='搜索 Host App / Frontend App / Build ID'
          className='h-8 w-64'
          aria-label='搜索 Frontend Profile'
        />
        <Select value={status} onValueChange={(value) => value && setStatus(value)}>
          <SelectTrigger className='w-32' aria-label='按状态筛选'>
            <SelectValue placeholder='全部状态' />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {statusOptions.map((option) => (
                <SelectItem key={option} value={option}>
                  {option === 'all' ? '全部状态' : PROFILE_STATUS_LABELS[option as FrontendProfile['status']]}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Button
          size='sm'
          variant='outline'
          className='ml-auto'
          onClick={() =>
            toast.info('演示环境：新建 Frontend Profile 请前往对应 Host 的接入向导', {
              description: 'Profile 与 Host App、Origin 校验和 Build 绑定一起创建'
            })
          }
        >
          导出 Profile 清单
        </Button>
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          title='没有匹配的 Frontend Profile'
          description='调整搜索关键字或状态筛选后重试'
        />
      ) : (
        <div className='overflow-x-auto rounded-lg border'>
          <Table>
            <TableHeader className='bg-muted'>
              <TableRow>
                <TableHead>Host App</TableHead>
                <TableHead>Frontend App</TableHead>
                <TableHead>Revision</TableHead>
                <TableHead>Build ID</TableHead>
                <TableHead>Allowed Origins</TableHead>
                <TableHead className='text-center'>Readables</TableHead>
                <TableHead className='text-center'>Actions</TableHead>
                <TableHead className='text-center'>Components</TableHead>
                <TableHead className='text-center'>Mounted Clients</TableHead>
                <TableHead>Digest</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Conformance</TableHead>
                <TableHead>更新时间</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((profile) => (
                <TableRow key={profile.id}>
                  <TableCell>
                    <Link
                      href={`/frontend/profiles/${profile.id}`}
                      className='text-primary hover:underline font-medium'
                    >
                      {profile.hostAppId}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <Link
                      href={`/frontend/profiles/${profile.id}`}
                      className='hover:underline'
                    >
                      {profile.frontendAppId}
                    </Link>
                  </TableCell>
                  <TableCell className='font-mono text-xs'>rev {profile.revision}</TableCell>
                  <TableCell className='font-mono text-xs'>{profile.buildId}</TableCell>
                  <TableCell className='max-w-56 truncate text-xs'>
                    {profile.allowedOrigins.join(', ') || '—'}
                  </TableCell>
                  <TableCell className='text-center tabular-nums'>
                    {profile.readables.length}
                  </TableCell>
                  <TableCell className='text-center tabular-nums'>
                    {profile.actions.length}
                  </TableCell>
                  <TableCell className='text-center tabular-nums'>
                    {profile.components.length}
                  </TableCell>
                  <TableCell className='text-center tabular-nums'>
                    {profile.mountedClients}
                  </TableCell>
                  <TableCell>
                    <DigestTag value={profile.digest} />
                  </TableCell>
                  <TableCell>
                    <StatusBadge tone={lifecycleTone(profile.status)}>
                      {PROFILE_STATUS_LABELS[profile.status]}
                    </StatusBadge>
                  </TableCell>
                  <TableCell>
                    <StatusBadge tone={CONFORMANCE_TONES[profile.conformance]} withDot={false}>
                      {CONFORMANCE_LABELS[profile.conformance]}
                    </StatusBadge>
                  </TableCell>
                  <TableCell className='text-muted-foreground text-xs'>
                    {formatDateTime(profile.updatedAt)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';

import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { EmptyState } from '@/components/platform/empty-state';
import { MonoId } from '@/components/platform/mono-id';
import { StatusBadge } from '@/components/platform/status-badge';
import { formatDateTime } from '@/lib/platform/format';
import { lifecycleTone } from '@/lib/platform/status';
import type { ClientRunBinding } from '@/lib/platform/types';

const BINDING_STATUS_LABELS: Record<ClientRunBinding['status'], string> = {
  active: '生效中',
  released: '已释放',
  expired: '已过期'
};

/** Client Run Binding 列表：Task / Run 与 Client Session 的绑定关系。 */
export function ClientBindingsTable({ bindings }: { bindings: ClientRunBinding[] }) {
  const [keyword, setKeyword] = useState('');

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    if (!kw) return bindings;
    return bindings.filter(
      (binding) =>
        binding.id.toLowerCase().includes(kw) ||
        binding.taskId.toLowerCase().includes(kw) ||
        binding.runId.toLowerCase().includes(kw) ||
        binding.clientSessionId.toLowerCase().includes(kw)
    );
  }, [bindings, keyword]);

  return (
    <div className='flex flex-col gap-4'>
      <Input
        value={keyword}
        onChange={(event) => setKeyword(event.target.value)}
        placeholder='搜索 Binding ID / Task / Run / Client Session'
        className='h-8 w-72'
        aria-label='搜索 Client Run Binding'
      />
      {filtered.length === 0 ? (
        <EmptyState title='没有匹配的 Client Run Binding' description='调整关键字后重试' />
      ) : (
        <div className='overflow-x-auto rounded-lg border'>
          <Table>
            <TableHeader className='bg-muted'>
              <TableRow>
                <TableHead>Binding ID</TableHead>
                <TableHead>Task</TableHead>
                <TableHead>Run</TableHead>
                <TableHead>Client Session</TableHead>
                <TableHead>Frontend Profile Digest</TableHead>
                <TableHead>Snapshot Digest</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((binding) => (
                <TableRow key={binding.id}>
                  <TableCell>
                    <MonoId value={binding.id} copyable={false} />
                  </TableCell>
                  <TableCell>
                    <Link
                      href={`/runtime/tasks/${binding.taskId}`}
                      className='text-primary hover:underline font-mono text-xs'
                    >
                      {binding.taskId}
                    </Link>
                  </TableCell>
                  <TableCell className='font-mono text-xs'>{binding.runId}</TableCell>
                  <TableCell>
                    <MonoId value={binding.clientSessionId} copyable={false} />
                  </TableCell>
                  <TableCell className='font-mono text-xs'>
                    {binding.frontendProfileDigest}
                  </TableCell>
                  <TableCell className='font-mono text-xs'>{binding.snapshotDigest}</TableCell>
                  <TableCell>
                    <StatusBadge tone={lifecycleTone(binding.status)}>
                      {BINDING_STATUS_LABELS[binding.status]}
                    </StatusBadge>
                  </TableCell>
                  <TableCell className='text-muted-foreground text-xs'>
                    {formatDateTime(binding.createdAt)}
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
